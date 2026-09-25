#!/usr/bin/env python3
"""Git Flow da squad (independe do fornecedor de IA: qualquer agente ou humano usa os mesmos comandos).

  feature-start <código> <slug>        develop → feature/<código>-<slug>
  feature-finish --demand <id>         G3 APPROVE → push + PR para develop PARA REVISÃO HUMANA (sem merge)
  review-sync --demand <id>            PR integrado → delivered; fechado sem merge → review-rejected
  release-start <x.y.z>                develop → release/<x.y.z>; versão do pom = x.y.z; CHANGELOG
  release-finish <x.y.z>               PR para main PARA REVISÃO HUMANA (sem merge)
  release-publish <x.y.z>              após o merge humano: tag no merge commit, GitHub Release e PR de back-merge
  hotfix-start <x.y.z> <slug>          main → hotfix/<x.y.z>-<slug>
  hotfix-finish <x.y.z>                igual ao release-finish, a partir do hotfix
  demand-worktree --demand <id>        D19: worktree da demanda (<pai>/<cópia principal>-d<n>) na branch dela
  feature-sync --demand <id>           D19: merge de origin/develop na branch, NO WORKTREE (sai 3 com conflitos)
  feature-sync --demand <id> --abort   D19: `git merge --abort` no worktree (antes de delegation-result falhou)
  review-update --demand <id> --delegation <id>   D19: push na MESMA branch do PR (nunca PR novo nem `review` novo)

Regras (CLAUDE.md / AGENTS.md → "Fluxo de branches"): ninguém commita direto em main; features entram em develop
por PR; o Auditor aprova o G3 antes do merge; releases e hotfixes são do Orquestrador, com aprovação humana.

D19 (ADR-022 §3, contrato §9): os comandos da delegação rodam SEMPRE do gitflow.py da cópia principal (pelo caminho
absoluto), mas todo `git` deles usa cwd = worktree da demanda (`--worktree`); nunca fazem switch, merge ou commit na
cópia principal; só leem o log dela e gravam eventos nela. Sem rebase e sem --force.
"""
import argparse
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = ROOT / "docs/squad/memory/decisions.jsonl"
if (pathlib.Path(__file__).resolve().parent / "product.py").exists():
    # D23 (F2a §5.1): log e código da demanda pelo resolvedor ($SQUAD_LOG > $SQUAD_ROOT_DATA > repositório). Sem
    # product.py ao lado (cópia isolada do script, testes antigos), o comportamento de antes.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import product
    try:
        PRODUCT = product.resolve()
    except product.ProductError as _e:
        sys.exit(f"gitflow.py: {_e}")
    LOG = PRODUCT.log
else:
    product = PRODUCT = None
CHANGELOG = ROOT / "CHANGELOG.md"
REPO = "jcrouzillard/checkout-saga-squad"
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"


def sh(*cmd: str, check=True, capture=True, cwd=None) -> str:
    out = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=capture, text=True)
    if check and out.returncode != 0:
        sys.exit(f"falhou: {' '.join(cmd)}\n{(out.stderr or out.stdout).strip()}")
    return (out.stdout or "").rstrip()  # rstrip: o porcelain do git começa com espaço significativo


def log_env() -> dict:
    """D23 (F2a §5.1): o filho log.py grava SEMPRE no log resolvido (SQUAD_LOG explícito). Sem product.py ao lado,
    o ambiente herdado (comportamento de antes)."""
    return {**os.environ, "SQUAD_LOG": str(LOG)} if product is not None else dict(os.environ)


def log_py(*args: str):
    out = subprocess.run(["python3", "tools/squad/log.py", *args], cwd=ROOT, capture_output=True, text=True,
                         env=log_env())
    if out.returncode != 0:
        sys.exit(f"falhou: log.py {' '.join(args[:4])}\n{(out.stderr or out.stdout).strip()}")
    return (out.stdout or "").rstrip()


def log(title: str, detail: str = "", demand: str | None = None, ref: str | None = None, branch: str | None = None):
    args = ["--agent", "orquestrador", "--type", "decision", "--title", title]
    if detail:
        args += ["--detail", detail]
    if demand:
        args += ["--demand", demand]
    if ref:
        args += ["--ref", ref]
    if branch:
        args += ["--branch", branch]
    log_py(*args)


def memory_in_repo() -> bool:
    """D23 (F2a §5.1): só com o log DENTRO do repositório (o caso de hoje) as operações de memória no git agem."""
    try:
        return LOG.resolve() == (ROOT / "docs/squad/memory/decisions.jsonl").resolve()
    except OSError:
        return False


def skip_memory(step: str) -> bool:
    """True (e avisa) quando a memória está fora do repositório: a etapa é pulada e nunca toca o log do repositório."""
    if memory_in_repo():
        return False
    print(f"memória fora do repositório (SQUAD_LOG={LOG}): {step} ignorada")
    return True


def current() -> str:
    return sh("git", "rev-parse", "--abbrev-ref", "HEAD")


# memória viva da squad (log, sync e — D16/ADR-019 — as pastas de bugs): muda o tempo todo e é commitada automaticamente
STATE = ("docs/squad/memory/", "docs/squad/inbox/", "docs/squad/produto/bugs/", "docs/squad/operacao/bugs/")


def porcelain() -> list[str]:
    """`-uall`: arquivos novos aparecem um a um (sem isso uma pasta nova vem colapsada como `?? docs/squad/produto/`
    e não casa com o prefixo de STATE — ressalva 3 do G1 da D16)."""
    return sh("git", "status", "--porcelain", "-uall").splitlines()


def snapshot_state():
    if skip_memory("snapshot_state"):
        return
    changed = [l[3:] for l in porcelain() if l[3:].startswith(STATE)]
    if changed:
        sh("git", "add", "--", *changed)
        sh("git", "commit", "-q", "-m", f"Sincronização da memória da squad{TRAILER}")


def clean_tree():
    snapshot_state()
    dirty = [l for l in porcelain() if not l[3:].startswith(STATE)]
    if dirty:
        sys.exit("há alterações não commitadas; faça commit antes de trocar de branch:\n" + "\n".join(dirty))


def switch(*args: str):
    """Troca de branch à prova da memória viva (log/sync escrevem a qualquer momento)."""
    for _ in range(3):
        snapshot_state()
        out = subprocess.run(["git", "switch", "-q", *args], cwd=ROOT, capture_output=True, text=True)
        if out.returncode == 0:
            return
    sys.exit(f"falhou: git switch {' '.join(args)}\n{out.stderr.strip()}")


def sync_develop():
    """develop local = develop remota + memória da squad commitada."""
    sh("git", "fetch", "-q", "origin")
    if current() != "develop":
        switch("develop")
    sh("git", "pull", "-q", "--rebase", "--autostash", "origin", "develop")
    snapshot_state()
    sh("git", "push", "-q", "origin", "develop")


def events() -> list[dict]:
    return [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]


def g3_approved(demand: str) -> dict | None:
    gates = [e for e in events() if e.get("type") == "gate" and e.get("gate") == "G3" and e.get("demand") == demand]
    return gates[-1] if gates and gates[-1].get("recommendation") == "APPROVE" else None


def set_version(version: str):
    sh("mvn", "-q", "-B", "versions:set", f"-DnewVersion={version}", "-DgenerateBackupPoms=false",
       "-DprocessAllModules=true")


def pr(base: str, head: str, title: str, body: str) -> str:
    existing = sh("gh", "pr", "list", "-R", REPO, "--head", head, "--base", base, "--json", "url", "-q", ".[0].url")
    return existing or sh("gh", "pr", "create", "-R", REPO, "--base", base, "--head", head, "--title", title, "--body", body)


# ---------------------------------------------------------------- feature
def feature_start(a):
    if a.demand and product is not None:   # D23 (F2a §5.1): o código da branch = o resolvido para a demanda
        expected = demand_code(a.demand)
        if a.code != expected:
            print(f"código {a.code} ≠ {expected} da demanda {a.demand}", file=sys.stderr)
            sys.exit(2)
    clean_tree()
    slug = re.sub(r"[^a-z0-9]+", "-", a.slug.lower()).strip("-")
    branch = f"feature/{a.code}-{slug}"
    sync_develop()
    switch("-c", branch)
    log(f"Branch {branch} criada a partir de develop", demand=a.demand, branch=branch)
    print(branch)


def event(kind: str, title: str, **fields):
    args = ["--agent", "orquestrador", "--type", kind, "--title", title]
    for k, v in fields.items():
        if v is not None:
            args += [f"--{k.replace('_', '-')}", str(v)]
    log_py(*args)


def pr_number(url: str) -> int:
    return int(url.rstrip("/").split("/")[-1])


def import_memory(branch: str):
    """Na develop: acrescenta ao log os eventos que só existem na branch (append-only, deduplicado por id)."""
    if skip_memory("import_memory"):
        return
    theirs = sh("git", "show", f"{branch}:{LOG.relative_to(ROOT).as_posix()}", check=False)
    have = {e.get("id") for e in events()}
    new = [l for l in theirs.splitlines() if l.strip() and json.loads(l).get("id") not in have]
    if new:
        with LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(new) + "\n")


def align_memory(branch: str):
    """Leva a develop para dentro da branch em revisão com a memória IGUAL à da develop. Assim o PR não mexe no
    log e o merge humano no GitHub não conflita com o que a squad segue registrando na develop (defeito a66b91c8a0d6)."""
    if skip_memory("align_memory"):
        return
    switch(branch)
    out = subprocess.run(["git", "merge", "-q", "--no-ff", "--no-commit", "develop"], cwd=ROOT, capture_output=True, text=True)
    for path in STATE:  # um por vez: um caminho ausente não pode impedir os outros
        sh("git", "checkout", "develop", "--", path, check=False)
    unmerged = [f for f in sh("git", "diff", "--name-only", "--diff-filter=U").splitlines() if not f.startswith(STATE)]
    if unmerged:
        sh("git", "merge", "--abort", check=False)
        switch("develop")
        sys.exit("conflito de código entre a feature e a develop; resolva antes de revisar:\n" + "\n".join(unmerged))
    if out.returncode == 0 or sh("git", "status", "--porcelain"):
        for path in STATE:  # um por vez: pasta de bugs ainda inexistente não pode falhar o add (D16)
            sh("git", "add", "-A", "--", path, check=False)
        sh("git", "commit", "-q", "--no-edit", "-m", f"Sincroniza a develop e a memória da squad antes da revisão{TRAILER}", check=False)
    sh("git", "push", "-q", "origin", branch)
    switch("develop")


def open_review(base: str, head: str, title: str, body: str, demand: str | None = None, release: str | None = None) -> str:
    """Abre (ou reutiliza) o PR, VOLTA para a develop e só então registra UM `review` — no log que o plantão lê
    (devolução do G2-D8: gravado na feature branch, o evento sumia ao voltar para a develop). Ninguém da squad faz merge."""
    url = pr(base, head, title, body)
    switch("develop")
    sh("git", "pull", "-q", "--rebase", "--autostash", "origin", "develop", check=False)
    if head.startswith("feature/"):
        import_memory(head)
    already = [e for e in events() if e.get("type") == "review" and e.get("url") == url]
    if not already:
        event("review", f"PR #{pr_number(url)} aberto para revisão humana: {title}", demand=demand, release=release,
              pr=pr_number(url), url=url, branch=head)
    snapshot_state()
    # Defeito a66b91c8a0d6 (D8): a develop com o `review` precisa chegar à origin já, senão o merge humano no
    # GitHub diverge dela e o próximo pull entra em conflito no log.
    sh("git", "push", "-q", "origin", "develop", check=False)
    if head.startswith("feature/"):
        align_memory(head)
    return url


def feature_finish(a):
    if not a.demand:
        sys.exit("--demand é obrigatório: a entrega de uma feature é sempre de uma demanda")
    clean_tree()
    branch = current()
    if not branch.startswith("feature/"):
        sys.exit(f"não está numa feature branch ({branch})")
    gate = g3_approved(a.demand)
    if not gate:
        sys.exit("G3 da demanda ainda não aprovado pelo Auditor: o PR não é aberto")
    evs = events()
    demand = next((e for e in evs if e.get("id") == a.demand and e.get("type") == "task"), {})
    gates = [e for e in evs if e.get("type") == "gate" and e.get("demand") == a.demand]
    evid = [f"- {v['name']}: {v['status']}" for e in evs if e.get("demand") == a.demand and e.get("type") in ("evidence", "handoff")
            for v in e.get("evidences", [])]
    sh("git", "push", "-q", "-u", "origin", branch)
    val = [e for e in evs if e.get("type") == "validation" and e.get("demand") == a.demand]
    ans = [e for e in evs if e.get("type") == "clarification" and e.get("demand") == a.demand]
    amap = {x["id"]: x["text"] for x in (ans[-1].get("answers", []) if ans else [])}
    qa = [f"- **{q['text']}**\n  → {amap.get(q['id'], '(sem resposta)')}" for q in (val[-1].get("questions", []) if val else [])]
    try:
        issue = json.loads((LOG.parent / "github-sync.json").read_text())["issues"].get(a.demand, {}).get("number")
    except (OSError, json.JSONDecodeError, KeyError):
        issue = None
    stat = sh("git", "diff", "--stat", "origin/develop...HEAD", check=False).splitlines()[-12:]
    body = "\n".join([
        *([f"Refs #{issue}", ""] if issue else []),
        f"## Demanda `{a.demand}` — {demand.get('title', '').replace('Demanda: ', '')}",
        "", (demand.get("detail") or "").strip(), "",
        "## Pareceres do Auditor",
        *[f"- {g['gate']} · {g.get('recommendation')} · {round((g.get('confidence') or 0) * 100)}% · risco {g.get('risk')}" for g in gates],
        "", f"**G3:** {gate.get('detail', '')}", "",
        "## Evidências", *(evid or ["- (ver log da squad)"]), "",
        *(["## Perguntas da validação e respostas do humano", *qa, ""] if qa else []),
        "## Artefatos alterados", "```", *stat, "```", "",
        "## Checklist do revisor",
        "- [ ] O diff corresponde aos critérios de aceite da demanda",
        "- [ ] Nenhum contrato de evento/API mudou sem ADR",
        "- [ ] Evidências (testes, capturas) conferidas", "",
        "> Pronta para **revisão humana**. O merge é do revisor; ao integrar, a demanda vira *Entregue* no Squad Control.",
        "", "🤖 Generated with [Claude Code](https://claude.com/claude-code)"])
    url = open_review("develop", branch, a.title or demand.get("title", branch).replace("Demanda: ", ""), body, demand=a.demand)
    print(url)


def after_review(delivered: bool):
    """D15 (ADR-018): após o merge, primeiro atualiza o produtivo só nos serviços alterados (desligável com
    SQUAD_PROD_AUTOUPDATE=0) e só depois libera o ambiente de teste e publica o próximo da fila (reconcile). Roda em
    segundo plano (log em .squad/after-review.log) para o review-sync não ficar preso a builds longos. Só age onde o
    ambiente existe (cópias sem compose/teste.env são ignoradas)."""
    steps = []
    if (delivered and current() == "develop" and os.environ.get("SQUAD_PROD_AUTOUPDATE", "1") != "0"
            and (ROOT / "docker-compose.yml").exists() and (ROOT / "tools/squad/prod.py").exists()):
        steps.append(["python3", "tools/squad/prod.py", "update", "--auto"])
    if (ROOT / "infra/teste/teste.env").exists() and (ROOT / "tools/squad/testenv.py").exists():
        steps.append(["python3", "tools/squad/testenv.py", "reconcile"])
    if not steps:
        return
    (ROOT / ".squad").mkdir(exist_ok=True)
    script = " ; ".join(" ".join(shlex.quote(x) for x in cmd) for cmd in steps)
    with (ROOT / ".squad/after-review.log").open("a", encoding="utf-8") as log_file:
        subprocess.Popen(["sh", "-c", script], cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    print("pós-revisão em segundo plano: " + " → ".join(" ".join(c[2:]) for c in steps) + " (log em .squad/after-review.log)")


def review_sync(a):
    """Consulta o PR em revisão e registra o desfecho (merge humano ou fechamento)."""
    key = "release" if a.release else "demand"
    val = a.release or a.demand
    reviews = [e for e in events() if e.get("type") == "review" and e.get(key) == val]
    if not reviews:
        sys.exit("nenhum PR em revisão para esse item")
    rv = reviews[-1]
    done = [e for e in events() if e.get("type") in ("delivered", "review-rejected") and e.get("url") == rv["url"]]
    if done:
        print(f"já tratado: {done[-1]['type']}")
        return
    info = json.loads(sh("gh", "pr", "view", rv["url"], "--json", "state,mergeCommit,mergedBy,closedAt,comments,reviews"))
    if info["state"] == "MERGED":
        commit = (info.get("mergeCommit") or {}).get("oid", "")[:12]
        who = (info.get("mergedBy") or {}).get("login", "humano")
        # Primeiro traz o merge humano, depois registra `delivered` e publica (defeito a66b91c8a0d6).
        if current() == "develop":
            sync_develop()
        event("delivered", f"Entregue: PR #{rv['pr']} integrado por {who}", demand=a.demand, release=a.release,
              pr=rv["pr"], url=rv["url"], merge_commit=commit)
        if current() == "develop":
            snapshot_state()
            sh("git", "push", "-q", "origin", "develop", check=False)
        else:
            sh("git", "fetch", "-q", "origin")
        if rv.get("branch", "").startswith("feature/"):
            sh("git", "branch", "-q", "-D", rv["branch"], check=False)
        print(f"entregue ({commit})")
        if a.demand:
            after_review(delivered=True)
    elif info["state"] == "CLOSED":
        notes = [c.get("body", "") for c in info.get("comments", [])] + [r.get("body", "") for r in info.get("reviews", [])]
        event("review-rejected", f"Devolvida pelo revisor: PR #{rv['pr']} fechado sem merge", demand=a.demand,
              release=a.release, pr=rv["pr"], url=rv["url"], detail=" | ".join(n for n in notes if n)[:1500])
        print("devolvida pelo revisor")
        if a.demand:
            after_review(delivered=False)
    else:
        print("ainda em revisão")


# ---------------------------------------------------------------- release / hotfix
def changelog_section(version: str) -> str:
    evs = events()
    demands = {e["id"]: e for e in evs if e.get("type") == "task" and e.get("agent") == "humano"}
    last_tag = sh("git", "describe", "--tags", "--abbrev=0", "origin/main", check=False)
    since = ""
    if last_tag:
        since = sh("git", "log", "-1", "--format=%cI", last_tag, check=False)
    lines = [f"## [{version}] - {date.today().isoformat()}", ""]
    done = [(d, g) for d_id, d in demands.items() if (g := g3_approved(d_id)) and (not since or g["ts"] > since)]
    if done:
        lines.append("### Demandas entregues pela squad")
        for i, (d, g) in enumerate(done, 1):
            lines.append(f"- {d['title'].replace('Demanda: ', '')} — G3 aprovado pelo Auditor "
                         f"({round((g.get('confidence') or 0) * 100)}%)")
        lines.append("")
    return "\n".join(lines)


def release_start(a, source="develop", kind="release"):
    clean_tree()
    branch = f"{kind}/{a.version}" + (f"-{a.slug}" if getattr(a, "slug", None) else "")
    if source == "develop":
        sync_develop()
        switch("-c", branch)
    else:
        sh("git", "fetch", "-q", "origin")
        switch("-c", branch, f"origin/{source}")
    set_version(a.version)
    if CHANGELOG.exists() and f"## [{a.version}]" not in CHANGELOG.read_text():
        text = CHANGELOG.read_text()
        head, _, rest = text.partition("\n## ")
        CHANGELOG.write_text(f"{head}\n{changelog_section(a.version)}\n## {rest}" if rest else f"{text}\n{changelog_section(a.version)}")
    sh("git", "add", "-A")
    sh("git", "commit", "-q", "-m", f"{kind.capitalize()} {a.version}: versão e CHANGELOG{TRAILER}")
    log(f"Branch {branch} criada a partir de {source} (versão {a.version})", branch=branch)
    print(branch)


def release_finish(a, kind="release"):
    clean_tree()
    branch = current()
    if not branch.startswith(f"{kind}/"):
        sys.exit(f"não está numa branch {kind}/ ({branch})")
    sh("git", "push", "-q", "-u", "origin", branch)
    notes = CHANGELOG.read_text().split(f"## [{a.version}]", 1)[-1].split("\n## [", 1)[0] if CHANGELOG.exists() else ""
    url = open_review("main", branch, f"{kind.capitalize()} {a.version}",
                      f"{kind.capitalize()} {a.version} — pronta para **revisão humana**. Após o merge, "
                      f"`gitflow.py {kind}-publish {a.version}` cria a tag e abre o PR de back-merge.\n\n## [{a.version}]{notes}"
                      f"\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)", release=a.version)
    print(url)


def release_publish(a, kind="release"):
    """Depois do merge HUMANO do PR da release: tag no merge commit, GitHub Release e PR de back-merge para develop."""
    reviews = [e for e in events() if e.get("type") == "review" and e.get("release") == a.version]
    if not reviews:
        sys.exit("release sem PR em revisão")
    info = json.loads(sh("gh", "pr", "view", reviews[-1]["url"], "--json", "state,mergeCommit"))
    if info["state"] != "MERGED":
        sys.exit(f"o PR da release ainda não foi integrado pelo humano (estado: {info['state']})")
    commit = info["mergeCommit"]["oid"]
    tag = f"v{a.version}"
    notes = CHANGELOG.read_text().split(f"## [{a.version}]", 1)[-1].split("\n## [", 1)[0] if CHANGELOG.exists() else ""
    sh("gh", "release", "create", tag, "-R", REPO, "--target", commit, "--title", tag, "--notes", f"## [{a.version}]{notes}")
    event("delivered", f"{kind.capitalize()} {a.version} publicada: {tag} no merge commit", release=a.version,
          pr=reviews[-1]["pr"], url=reviews[-1]["url"], merge_commit=commit[:12])
    # back-merge também passa por revisão humana (ressalva 1 do G1-D8)
    clean_tree()
    sh("git", "fetch", "-q", "origin")
    back = f"chore/back-merge-{a.version}"
    switch("-c", back, "origin/develop")
    sh("git", "merge", "-q", "--no-ff", "origin/main", "-m", f"Back-merge de main ({tag}) em develop{TRAILER}")
    major, minor, _ = (int(x) for x in a.version.split("."))
    nxt = f"{major}.{minor + 1}.0-SNAPSHOT"
    set_version(nxt)
    sh("git", "add", "-A")
    sh("git", "commit", "-q", "-m", f"Próxima versão de desenvolvimento: {nxt}{TRAILER}")
    sh("git", "push", "-q", "-u", "origin", back)
    url = open_review("develop", back, f"Back-merge {tag} em develop e {nxt}",
                      f"Back-merge da {kind} {a.version} e próxima versão {nxt}. Revisão humana.\n\n"
                      "🤖 Generated with [Claude Code](https://claude.com/claude-code)", release=f"{a.version}-back-merge")
    print(url)


# ---------------------------------------------------------------- D19: delegação (worktree da demanda)
# Dono de cada caminho (AGENTS.md, single-writer): o mais específico primeiro.
OWNERS = [(("services/", "/src/test/"), "qa"), (("tests/",), "qa"), (("services/",), "backend"), (("pom.xml",), "backend"),
          (("infra/observability/",), "observabilidade"), (("docs/observability.md",), "observabilidade"),
          (("Dockerfile",), "devops"), (("docker-compose",), "devops"), (("infra/",), "devops"),
          ((".github/",), "devops"), (("Makefile",), "devops"), (("checkout-console/",), "frontend"),
          (("squad-control/",), "frontend"), (("docs/architecture/",), "arquiteto"), (("docs/adr/",), "arquiteto"),
          (("docs/contracts/",), "arquiteto"), (("docs/squad/gates/",), "auditor")]


def owner_of(path: str) -> str:
    for keys, owner in OWNERS:
        if len(keys) == 2:
            if path.startswith(keys[0]) and keys[1] in path:
                return owner
        elif path.startswith(keys[0]) or path == keys[0]:
            return owner
    return "orquestrador"   # AGENTS.md, CLAUDE.md, docs/squad/**, tools/squad/** e o que não tem dono explícito


def demand_code(demand: str) -> str:
    """D23 (F2a §5.1): código resolvido (congelado > gravado > posicional) = product.demand_codes(events())[id]."""
    if product is not None:
        code = product.demand_codes(events(), PRODUCT.with_log(LOG)).get(demand)
        if code:
            return code
        sys.exit(f"demanda {demand} não encontrada no log")
    n = 0
    for e in events():
        if e.get("type") == "task" and e.get("agent") == "humano" and e.get("id"):
            n += 1
            if e["id"] == demand:
                return f"D{n}"
    sys.exit(f"demanda {demand} não encontrada no log")


def demand_branch(demand: str) -> str:
    evs = events()
    rv = [e for e in evs if e.get("type") == "review" and e.get("demand") == demand and e.get("branch")]
    dec = [e for e in evs if e.get("type") == "decision" and e.get("demand") == demand
           and str(e.get("branch", "")).startswith("feature/")]
    branch = (rv or dec or [{}])[-1].get("branch")
    if not branch:
        sys.exit(f"demanda {demand} sem branch registrada (review ou decision \"Branch … criada\")")
    return branch


def default_worktree(demand: str) -> pathlib.Path:
    return ROOT.parent / f"{ROOT.name}-{demand_code(demand).lower()}"


def worktree_of(a) -> pathlib.Path:
    wt = pathlib.Path(a.worktree).resolve() if getattr(a, "worktree", None) else default_worktree(a.demand)
    if wt == ROOT.resolve() or wt.name.endswith("-teste"):
        sys.exit(f"worktree proibido: {wt} (cópia principal/ambiente de teste — ADR-018)")
    return wt


def wt_dirty(wt: pathlib.Path) -> list[str]:
    return [l for l in sh("git", "status", "--porcelain", "-uall", cwd=wt).splitlines() if not l[3:].startswith(STATE)]


def discard_state(wt: pathlib.Path):
    """O worktree da demanda não commita a memória da squad (§8.3): alterações locais em STATE são descartadas."""
    if skip_memory("discard_state"):
        return
    for path in STATE:
        sh("git", "checkout", "--", path, cwd=wt, check=False)
    for l in sh("git", "status", "--porcelain", "-uall", cwd=wt).splitlines():
        if l.startswith("??") and l[3:].startswith(STATE):
            (wt / l[3:]).unlink(missing_ok=True)


def demand_worktree(a):
    branch = demand_branch(a.demand)
    wt = worktree_of(a)
    if wt.exists():
        head = sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=wt, check=False)
        if head != branch:
            print(f"worktree ocupado: {wt} está em {head or '(não é um repositório git)'}, não em {branch}",
                  file=sys.stderr)
            sys.exit(5)
        dirty = wt_dirty(wt)
        if dirty or (wt / ".git").exists() and sh("git", "rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=wt, check=False):
            print("worktree ocupado: alterações alheias no worktree da demanda:\n" + "\n".join(dirty or ["merge em andamento"]),
                  file=sys.stderr)
            sys.exit(5)
        print(wt)
        return
    sh("git", "worktree", "prune")                      # metadado de worktree removido à mão
    sh("git", "fetch", "-q", "origin")
    local = sh("git", "rev-parse", "-q", "--verify", f"refs/heads/{branch}", check=False)
    if local:
        sh("git", "worktree", "add", "-q", str(wt), branch)
    elif sh("git", "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}", check=False):
        sh("git", "worktree", "add", "-q", "-b", branch, str(wt), f"origin/{branch}")
    else:
        sys.exit(f"branch {branch} não existe localmente nem na origin")
    print(wt)


def feature_sync(a):
    """§9.2: `git merge --no-ff --no-commit origin/develop` no worktree; STATE fica com a versão da develop; conflitos de
    código → lista com o dono de cada arquivo e sai 3 (merge em andamento). Rodar de novo após a resolução conclui o
    merge (commit). `--abort` desfaz o merge em andamento (falha/recusa/cancelamento da delegação)."""
    wt = worktree_of(a)
    if not wt.exists():
        sys.exit(f"worktree {wt} não existe: rode demand-worktree")
    in_merge = bool(sh("git", "rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=wt, check=False))
    if a.abort:
        if in_merge:
            sh("git", "merge", "--abort", cwd=wt)
        discard_state(wt)
        print("merge abortado; worktree limpo" if in_merge else "nenhum merge em andamento")
        return
    branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=wt)
    if branch != demand_branch(a.demand):
        sys.exit(f"worktree em {branch}, não na branch da demanda")
    if not in_merge:
        discard_state(wt)
        dirty = wt_dirty(wt)
        if dirty:
            sys.exit("worktree com alterações não commitadas; commit antes de sincronizar:\n" + "\n".join(dirty))
        sh("git", "fetch", "-q", "origin", cwd=wt)
        res = subprocess.run(["git", "merge", "-q", "--no-ff", "--no-commit", "origin/develop"], cwd=wt,
                             capture_output=True, text=True)
        in_merge = bool(sh("git", "rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=wt, check=False))
        if not in_merge:
            # G2-D19 (ressalva 1): só é "nada a integrar" se a develop já estiver na branch; senão o merge falhou.
            contains = subprocess.run(["git", "merge-base", "--is-ancestor", "origin/develop", "HEAD"], cwd=wt,
                                      capture_output=True).returncode == 0
            if contains:
                print(f"{branch} já contém a origin/develop (nada a integrar)")
                return
            sys.exit("merge da origin/develop falhou sem deixar merge em andamento:\n"
                     + (res.stderr or res.stdout).strip())
    # memória da squad = versão da develop (mesma regra do align_memory), inclusive arquivos só da branch
    if not skip_memory("feature_sync (STATE)"):
        for path in STATE:
            sh("git", "checkout", "origin/develop", "--", path, cwd=wt, check=False)
        for f in sh("git", "diff", "--cached", "--name-only", "origin/develop", "--", *STATE, cwd=wt,
                    check=False).splitlines():
            if subprocess.run(["git", "cat-file", "-e", f"origin/develop:{f}"], cwd=wt, capture_output=True).returncode:
                sh("git", "rm", "-q", "-f", "--", f, cwd=wt, check=False)
    unmerged = sorted(set(sh("git", "diff", "--name-only", "--diff-filter=U", cwd=wt).splitlines()) - {""})
    unmerged = [f for f in unmerged if not f.startswith(STATE)]
    if unmerged:
        print("conflitos a resolver (arquivo → dono):")
        for f in unmerged:
            print(f"  {f} → {owner_of(f)}")
        print(f"merge em andamento em {wt}; após resolver (git add), rode de novo feature-sync para concluir, "
              "ou feature-sync --abort")
        sys.exit(3)
    msg = f"Integra a develop na {branch}" + (f" (delegação {a.delegation})" if a.delegation else "")
    sh("git", "commit", "-q", "--no-edit", "-m", msg + TRAILER, cwd=wt)
    print(f"merge de origin/develop commitado em {branch}: {sh('git', 'rev-parse', '--short=12', 'HEAD', cwd=wt)}")


def review_update(a):
    """§9.4: push da branch (sem --force) para o MESMO PR do último `review`; grava `review-updated`. Recusa (código 4)
    se o diff da branch contra a origin/develop tocar a memória/estado da squad (STATE inteiro: memória, inbox, bugs)."""
    evs = events()
    dl = next((e for e in evs if e.get("id") == a.delegation and e.get("type") == "delegation"), None)
    if dl is None or dl.get("demand") != a.demand:
        sys.exit("delegação não encontrada para esta demanda")
    idx = {e.get("id"): i for i, e in enumerate(evs)}
    starts = [i for i, e in enumerate(evs) if e.get("type") == "delegation-start" and e.get("delegation") == a.delegation]
    if not starts:
        sys.exit("delegação sem delegation-start: nada a atualizar")
    if any(e.get("type") == "delegation-result" and e.get("delegation") == a.delegation for e in evs):
        sys.exit("delegação já encerrada")
    reviews = [e for e in evs if e.get("type") == "review" and e.get("demand") == a.demand]
    closed = {e.get("url") for e in evs if e.get("type") in ("delivered", "review-rejected")}
    rv = reviews[-1] if reviews and reviews[-1].get("url") not in closed else None
    if rv is None:
        sys.exit("demanda sem PR em revisão: review-update nunca cria PR")
    gates = [e for i, e in enumerate(evs) if e.get("type") == "gate" and e.get("demand") == a.demand and i > starts[0]]
    ok = gates and gates[-1].get("recommendation") == "APPROVE" and gates[-1].get("gate") == "G3" \
        and gates[-1].get("delegation") == a.delegation
    if not ok:
        sys.exit("sem G3 APPROVE do Auditor com --delegation posterior ao delegation-start: push recusado")
    wt = worktree_of(a)
    branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=wt)
    if branch != rv.get("branch"):
        sys.exit(f"worktree em {branch}, mas o PR #{rv.get('pr')} é da branch {rv.get('branch')}")
    if sh("git", "rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=wt, check=False):
        sys.exit("merge em andamento no worktree: conclua (feature-sync) ou aborte antes do push")
    discard_state(wt)
    dirty = wt_dirty(wt)
    if dirty:
        sys.exit("alterações não commitadas no worktree:\n" + "\n".join(dirty))
    sh("git", "fetch", "-q", "origin", cwd=wt)
    touched = sh("git", "diff", "--name-only", "origin/develop...HEAD", "--", *STATE, cwd=wt).splitlines()
    if touched:
        print("a branch altera a memória da squad (push recusado; ADR-022 §3):\n" + "\n".join(touched), file=sys.stderr)
        sys.exit(4)
    nums = sh("gh", "pr", "list", "-R", REPO, "--head", branch, "--json", "number", "-q", ".[].number").split()
    if str(rv.get("pr")) not in nums or len(nums) != 1:
        sys.exit(f"PR da branch ({', '.join(nums) or 'nenhum'}) difere do PR #{rv.get('pr')} do último review: "
                 "nada é criado")
    sh("git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=wt)
    sha = sh("git", "rev-parse", "HEAD", cwd=wt)
    event("review-updated", f"PR #{rv['pr']} atualizado pela delegação {a.delegation}", demand=a.demand,
          pr=rv["pr"], url=rv["url"], branch=branch, sha=sha, delegation=a.delegation)
    print(f"PR #{rv['pr']} atualizado ({sha[:12]})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("feature-start"); s.add_argument("code"); s.add_argument("slug"); s.add_argument("--demand")
    s = sub.add_parser("feature-finish"); s.add_argument("--demand", required=True); s.add_argument("--title")
    s = sub.add_parser("review-sync"); s.add_argument("--demand"); s.add_argument("--release")
    s = sub.add_parser("release-start"); s.add_argument("version")
    s = sub.add_parser("release-finish"); s.add_argument("version")
    s = sub.add_parser("hotfix-start"); s.add_argument("version"); s.add_argument("slug")
    s = sub.add_parser("hotfix-finish"); s.add_argument("version")
    s = sub.add_parser("release-publish"); s.add_argument("version")
    s = sub.add_parser("hotfix-publish"); s.add_argument("version")
    s = sub.add_parser("demand-worktree"); s.add_argument("--demand", required=True); s.add_argument("--worktree")
    s = sub.add_parser("feature-sync"); s.add_argument("--demand", required=True); s.add_argument("--worktree")
    s.add_argument("--delegation"); s.add_argument("--abort", action="store_true")
    s = sub.add_parser("review-update"); s.add_argument("--demand", required=True)
    s.add_argument("--delegation", required=True); s.add_argument("--worktree")
    a = p.parse_args()
    {"feature-start": feature_start, "feature-finish": feature_finish,
     "release-start": release_start, "release-finish": release_finish,
     "hotfix-start": lambda x: release_start(x, source="main", kind="hotfix"),
     "hotfix-finish": lambda x: release_finish(x, kind="hotfix"),
     "review-sync": review_sync, "release-publish": release_publish,
     "hotfix-publish": lambda x: release_publish(x, kind="hotfix"),
     "demand-worktree": demand_worktree, "feature-sync": feature_sync, "review-update": review_update}[a.cmd](a)


if __name__ == "__main__":
    main()
