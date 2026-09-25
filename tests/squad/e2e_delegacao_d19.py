#!/usr/bin/env python3
"""D19 (402e76f187f9) — CA-1 ponta a ponta SIMULADO (QA).

pending (UNKNOWN) → pending (CONFLICTING) → pr-conflict → B6 no /api/live → GET /api/conversas/pedido → conversa
(runner simulado) → cartão → confirmação → `delegation` → pending lista a delegação → server.py --delegation-check 0
→ gitflow demand-worktree → feature-sync (3) → dono resolve → feature-sync (commit do merge) → QA handoff
--delegation → G3 APPROVE --delegation → gitflow review-update (mesmo PR) → delegation-result ok → pending vê
MERGEABLE → pr-conflict-cleared → B6 fecha; `gh pr list --head` com 1 PR; nenhuma chamada `gh pr merge`/`pr create`.

Tudo em diretório temporário: repositório git com `origin` bare local (cópia principal em `develop` + worktree da
demanda), `gh` simulado no PATH (1ª consulta `UNKNOWN`; depois `mergeable` calculado no origin: a develop está contida
na branch? MERGEABLE : CONFLICTING), servidor deste repositório numa porta livre com `SQUAD_ROOT_DATA`/`SQUAD_LOG` da
cópia principal temporária e `SQUAD_CHAT_RUNNER=fake`. Nenhum POST ao :7070, nenhum push/PR/merge real, log real
intocado (checado no fim, de verdade).

Uso: python3 tests/squad/e2e_delegacao_d19.py [--base DIR] [--serve-ui PORT]
  --serve-ui PORT: depois do fluxo, abre um 2º conflito (D2, PR #172, B6 aberto) e deixa o servidor no ar nessa
  porta para o roteiro de navegador tests/ui/d19-delegacao.js (Ctrl+C/TERM derruba tudo).
Código 0 = todos os passos passaram.
"""
import argparse
import hashlib
import http.client
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

REPO = pathlib.Path(__file__).resolve().parents[2]
FAKE = REPO / "tests/squad/delegacao_fake_runner.py"
MARK = f"qa-d19-e2e-{uuid.uuid4().hex[:8]}"
D1, D2 = "d1e2e0000001", "d2e2e0000002"
BR1, BR2 = "feature/D1-cupom", "feature/D2-frete"
STEPS: list[tuple[str, bool, str]] = []

GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
base = os.environ["QA_GH_BASE"]
a = sys.argv[1:]
open(os.path.join(base, "gh_calls"), "a").write(" ".join(a) + "\n")
origin = os.path.join(base, "origin.git")
BR = {"171": "%s", "172": "%s"}
if a[:2] == ["pr", "view"]:
    n = a[2].rstrip("/").rsplit("/", 1)[-1]
    cnt = os.path.join(base, "gh_count_" + n)
    k = int(open(cnt).read()) if os.path.exists(cnt) else 0
    open(cnt, "w").write(str(k + 1))
    if k == 0:
        m = "UNKNOWN"
    else:
        ok = subprocess.run(["git", "-C", origin, "merge-base", "--is-ancestor", "develop", BR[n]]).returncode == 0
        clean = subprocess.run(["git", "-C", origin, "merge-tree", "--write-tree", "develop", BR[n]],
                               capture_output=True).returncode == 0
        m = "MERGEABLE" if ok or clean else "CONFLICTING"
    print(json.dumps({"state": "OPEN", "mergeable": m}))
elif a[:2] == ["pr", "list"]:
    head = a[a.index("--head") + 1]
    print("\n".join(n for n, b in BR.items() if b == head))
else:
    print("gh simulado: comando não permitido", file=sys.stderr)
    sys.exit(1)
''' % (BR1, BR2)


def step(name, ok, info=""):
    STEPS.append((name, bool(ok), str(info)[:300]))
    print(f"[{'ok' if ok else 'FALHOU'}] {name}" + (f" — {str(info)[:300]}" if info and not ok else ""), flush=True)
    if not ok:
        raise SystemExit(1)


def worktrees(repo: pathlib.Path) -> list[pathlib.Path]:
    """Todas as cópias do repositório (cópia principal `plankton`, worktrees de demanda, clone de origem)."""
    out = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True).stdout
    return [pathlib.Path(l[9:]) for l in out.splitlines() if l.startswith("worktree ")] + [repo]


REAL_LOGS = sorted({w / "docs/squad/memory/decisions.jsonl" for w in worktrees(REPO)})
REAL_BEFORE = {p: p.read_bytes().count(b"\n") for p in REAL_LOGS if p.exists()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--serve-ui", type=int)
    a = ap.parse_args()
    base = pathlib.Path(a.base or tempfile.mkdtemp(prefix="qa-d19-e2e-")).resolve()
    if base.exists() and any(base.iterdir()):
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    # `python3` chamado pelos scripts (gitflow → log.py) = este intérprete: o /usr/bin/python3 do macOS é 3.9, sem
    # tomllib (product.py, D23)
    (base / "pybin").mkdir()
    (base / "pybin/python3").symlink_to(sys.executable)
    main_ = base / "plankton"
    origin = base / "origin.git"
    wt = base / "plankton-d1"
    log = main_ / "docs/squad/memory/decisions.jsonl"
    genv = {k: v for k, v in os.environ.items() if not k.startswith(("SQUAD_", "GIT_"))}
    genv.update(GIT_AUTHOR_NAME="qa", GIT_AUTHOR_EMAIL="qa@t", GIT_COMMITTER_NAME="qa", GIT_COMMITTER_EMAIL="qa@t",
                GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", QA_GH_BASE=str(base),
                # D26: `claude`/`codex` FALSOS antes do /opt/homebrew/bin (a checagem de executores nunca toca o login real)
                PATH=f"{base / 'bin'}:{base / 'pybin'}:{REPO / 'tests/squad/fixtures/d26/bin'}:/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin",
                CODEX_HOME=str(base / "codexhome"), CLAUDE_CONFIG_DIR=str(base / "claudecfg"))
    env = {**genv, "SQUAD_ROOT_DATA": str(main_), "SQUAD_LOG": str(log), "SQUAD_TRANSCRIPTS": str(base / "tr"),
           "SQUAD_TESTENV_PROBE": "0", "SQUAD_TESTENV_SPAWN": "0", "SQUAD_CHAT_RUNNER": "fake",
           "SQUAD_CHAT_FAKE": str(FAKE), "SQUAD_CHAT_TIMEOUT_S": "10"}
    (base / "tr").mkdir()
    proc = None

    def git(*args, cwd=main_, check=True):
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=genv)
        if check and r.returncode:
            raise SystemExit(f"git {args}: {r.stderr}")
        return r.stdout.strip()

    def py(script, *args, root=main_):
        return subprocess.run([sys.executable, str(root / "tools/squad" / script), *args], cwd=main_, env=env,
                              capture_output=True, text=True)

    def LOG(*args):   # log.py da CÓPIA PRINCIPAL pelo caminho absoluto (§8.3)
        args = list(args) + ([] if "--title" in args else ["--title", MARK])
        r = py("log.py", *args)
        if r.returncode:
            raise SystemExit(f"log.py {args}: {r.stderr}")
        return rows()[-1]

    def rows():
        return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]

    def pending(reset=True):
        if reset:
            (main_ / ".squad/pr-state.json").unlink(missing_ok=True)
        return py("pending.py", root=REPO).stdout

    def sha():
        return hashlib.sha256(log.read_bytes()).hexdigest()

    try:
        # ---------------------------------------------------------------- repositório temporário
        (base / "bin").mkdir()
        (base / "bin/gh").write_text(GH)
        (base / "bin/gh").chmod(0o755)
        git("init", "-q", "--bare", str(origin), cwd=base)
        subprocess.run(["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/develop"], env=genv)
        main_.mkdir()
        git("init", "-q", "-b", "develop")
        shutil.copytree(REPO / "tools/squad", main_ / "tools/squad", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "docs/squad/prompts", main_ / "docs/squad/prompts")
        (main_ / "services/order-service").mkdir(parents=True)
        (main_ / "services/order-service/Cupom.java").write_text("class Cupom { int desconto = 0; }\n")
        (main_ / ".gitignore").write_text(".squad/\n__pycache__/\n")
        log.parent.mkdir(parents=True)
        log.write_text("")
        for did, code, title in ((D1, "D1", "cupom de desconto"), (D2, "D2", "frete grátis")):
            with log.open("a") as f:
                f.write(json.dumps({"id": did, "ts": "2026-09-25T10:00:00+00:00", "agent": "humano", "type": "task",
                                    "title": f"{code}: {title} {MARK}", "kind": "produto"}) + "\n")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("remote", "add", "origin", str(origin))
        git("push", "-q", "origin", "develop")
        for br, content in ((BR1, "class Cupom { int desconto = 10; }\n"), (BR2, None)):
            git("switch", "-q", "-c", br)
            if content:
                (main_ / "services/order-service/Cupom.java").write_text(content)
            else:
                (main_ / "services/order-service/Frete.java").write_text("class Frete {}\n")
                git("add", "-A")
            git("commit", "-q", "-am", f"feature {br}")
            git("push", "-q", "origin", br)
            git("switch", "-q", "develop")
            git("branch", "-q", "-D", br)
        other = base / "other"
        git("clone", "-q", "-b", "develop", str(origin), str(other), cwd=base)
        (other / "services/order-service/Cupom.java").write_text("class Cupom { int desconto = 0; boolean ativo; }\n")
        git("commit", "-q", "-am", "develop: cupom ativo", cwd=other)
        git("push", "-q", "origin", "develop", cwd=other)
        for did, br, pr in ((D1, BR1, 171), (D2, BR2, 172)):
            LOG("--agent", "orquestrador", "--type", "decision", "--demand", did, "--branch", br, "--title", f"Branch {br} criada")
            LOG("--agent", "orquestrador", "--type", "review", "--demand", did, "--pr", str(pr), "--url",
                f"https://github.com/x/y/pull/{pr}", "--branch", br, "--title", f"PR #{pr} aberto para revisão")
        main_before = (git("rev-parse", "HEAD"), git("status", "--porcelain", "--", ".", ":!docs/squad/memory"),
                       git("rev-parse", "--abbrev-ref", "HEAD"))

        # ---------------------------------------------------------------- 1. detecção (CA-2)
        out = pending()
        step("pending 1ª consulta: UNKNOWN não gera item", "conflito" not in out, out)
        out = pending()
        step("pending 2ª consulta: CONFLICTING → 'conflito de PR' do PR #171",
             f"conflito de PR: demanda {D1} (PR #171)" in out and "PR #172" not in out, out)
        calls = (base / "gh_calls").read_text().splitlines()
        step("gh pr view com --json state,mergeable (uma chamada por PR por ciclo)",
             all("--json state,mergeable" in c for c in calls if c.startswith("pr view")), calls)
        pc = LOG("--agent", "orquestrador", "--type", "pr-conflict", "--demand", D1, "--pr", "171", "--url",
                 "https://github.com/x/y/pull/171", "--branch", BR1, "--mergeable", "CONFLICTING",
                 "--title", "PR #171 em conflito com a develop")

        # ---------------------------------------------------------------- 2. servidor: B6, pedido, conversa, cartão
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = a.serve_ui or s.getsockname()[1]
        proc = subprocess.Popen([sys.executable, str(REPO / "tools/squad/server.py"), "--port", str(port)], env=env,
                                stdout=subprocess.DEVNULL, stderr=open(base / "server.err", "w"), start_new_session=True)

        def req(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                      headers={"Host": f"localhost:{port}", "Content-Type": "application/json"})
            r = c.getresponse()
            d = r.read()
            try:
                return r.status, json.loads(d)
            except json.JSONDecodeError:
                return r.status, d.decode()
        for _ in range(150):
            try:
                req("GET", "/api/conversas")
                break
            except OSError:
                time.sleep(0.1)
        _, live = req("GET", "/api/live")
        b6 = next((x for x in live["alerts"] if x["id"] == f"pr-conflict:{pc['id']}"), None)
        step("B6 no /api/live com 'Delegar correção' e delegável",
             b6 and b6["action"]["label"] == "Delegar correção" and b6["delegable"] and b6["severity"] == "bloqueio", b6)
        before = sha()
        s_, ped = req("GET", f"/api/conversas/pedido?ref=pr-conflict:{pc['id']}")
        step("GET /api/conversas/pedido → texto pré-preenchido, nada gravado",
             s_ == 200 and ped["demand"] == "D1" and "PR #171" in ped["text"] and sha() == before, ped)
        s_, conv = req("POST", "/api/conversas", {})
        cid = conv["id"]
        req("POST", f"/api/conversas/{cid}/mensagens", {"text": ped["text"]})
        msg = None
        for _ in range(200):
            _, v = req("GET", f"/api/conversas/{cid}")
            ms = [m for m in v["messages"] if m.get("role") == "orquestrador"]
            if ms:
                msg = ms[-1]
                break
            time.sleep(0.1)
        p = (msg or {}).get("proposal") or {}
        step("conversa → cartão de delegação válido (agente e risco do servidor), sem gravar no log",
             p.get("kind") == "delegar" and p.get("valid") and p.get("category") == "conflito-develop"
             and p.get("owner") == "orquestrador" and p.get("risk") == "moderado" and p.get("target") == f"pr-conflict:{pc['id']}"
             and "```delegar" not in msg["text"] and sha() == before, p)
        task = ped["text"] + f" Rodar os testes do order-service. {MARK}"
        s_, r = req("POST", f"/api/conversas/{cid}/propostas/{p['id']}/confirmar", {"task": task})
        ev = r.get("event") or {}
        step("confirmar → 201 e evento `delegation` (agent humano, via conversa, tarefa editada)",
             s_ == 201 and ev.get("type") == "delegation" and ev.get("agent") == "humano" and ev.get("via") == "conversa"
             and ev.get("detail") == task and ev.get("pr") == 171 and rows()[-1]["id"] == ev["id"], r)
        did = ev["id"]
        s_, r2 = req("POST", f"/api/conversas/{cid}/propostas/{p['id']}/confirmar", {})
        step("2ª confirmação → 409 ja_decidida", s_ == 409 and r2.get("code") == "ja_decidida", r2)

        # ---------------------------------------------------------------- 3. plantão (simulado, seção D)
        out = pending()
        step("pending lista a delegação", f"delegação: {did} · conflito-develop · D1" in out, out)
        chk = py("server.py", "--delegation-check", did, root=REPO)
        step("server.py --delegation-check → 0 (autêntica e válida)", chk.returncode == 0, chk.stdout + chk.stderr)
        r = py("gitflow.py", "demand-worktree", "--demand", D1)
        step("gitflow demand-worktree cria o worktree na branch da demanda",
             r.returncode == 0 and r.stdout.strip() == str(wt) and git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt) == BR1,
             r.stdout + r.stderr)
        pr_head = git("rev-parse", "HEAD", cwd=wt)
        wt_log_before = (wt / "docs/squad/memory/decisions.jsonl").read_text()
        LOG("--agent", "orquestrador", "--type", "delegation-start", "--demand", D1, "--delegation", did, "--branch", BR1,
            "--to", "backend", "--detail", str(wt), "--title", "Delegação iniciada: conflito do PR #171")
        r = py("gitflow.py", "feature-sync", "--demand", D1, "--delegation", did)
        step("feature-sync → código 3 com o arquivo em conflito e o dono",
             r.returncode == 3 and "services/order-service/Cupom.java → backend" in r.stdout, r.stdout + r.stderr)
        # o dono (backend) resolve preservando as duas intenções
        (wt / "services/order-service/Cupom.java").write_text("class Cupom { int desconto = 10; boolean ativo; }\n")
        git("add", "services/order-service/Cupom.java", cwd=wt)
        LOG("--agent", "backend", "--type", "handoff", "--to", "qa", "--demand", D1, "--delegation", did,
            "--title", "Conflito resolvido no Cupom.java (desconto + ativo)")
        r = py("gitflow.py", "feature-sync", "--demand", D1, "--delegation", did)
        parents = git("log", "-1", "--format=%P", cwd=wt).split()
        step("feature-sync conclui o merge (commit com 2 pais, histórico do PR preservado)",
             r.returncode == 0 and len(parents) == 2
             and subprocess.run(["git", "merge-base", "--is-ancestor", pr_head, "HEAD"], cwd=wt).returncode == 0,
             r.stdout + r.stderr)
        LOG("--agent", "qa", "--type", "handoff", "--to", "auditor", "--demand", D1, "--delegation", did,
            "--evidence", "order-service-testes=pass", "--title", "QA: testes do order-service verdes após o merge")
        r = py("gitflow.py", "review-update", "--demand", D1, "--delegation", did)
        step("review-update sem G3 APPROVE → recusado", r.returncode != 0 and "G3 APPROVE" in r.stderr, r.stderr)
        LOG("--agent", "auditor", "--type", "gate", "--gate", "G3", "--recommendation", "APPROVE", "--confidence", "0.9",
            "--risk", "moderado", "--demand", D1, "--delegation", did, "--title", "G3 (delegação): APPROVE")
        remote_before = git("rev-parse", f"refs/heads/{BR1}", cwd=origin)
        r = py("gitflow.py", "review-update", "--demand", D1, "--delegation", did)
        head = git("rev-parse", "HEAD", cwd=wt)
        ru = [e for e in rows() if e.get("type") == "review-updated"]
        step("review-update → push sem --force (fast-forward) e `review-updated` no MESMO PR #171",
             r.returncode == 0 and git("rev-parse", f"refs/heads/{BR1}", cwd=origin) == head
             and subprocess.run(["git", "-C", str(origin), "merge-base", "--is-ancestor", remote_before, head]).returncode == 0
             and len(ru) == 1 and ru[0]["pr"] == 171 and ru[0]["sha"] == head and ru[0]["delegation"] == did
             and sum(e.get("type") == "review" and e.get("demand") == D1 for e in rows()) == 1, r.stdout + r.stderr)
        LOG("--agent", "orquestrador", "--type", "delegation-result", "--demand", D1, "--delegation", did, "--status", "ok",
            "--pr", "171", "--sha", head, "--ref", "services/order-service/Cupom.java",
            "--detail", "Merge da develop integrado; QA e G3 aprovados; PR #171 atualizado.",
            "--title", "Delegação concluída: PR #171 sem conflito")
        out = pending()
        step("pending vê MERGEABLE → 'conflito resolvido'", f"conflito resolvido: demanda {D1} (PR #171)" in out, out)
        LOG("--agent", "orquestrador", "--type", "pr-conflict-cleared", "--demand", D1, "--pr", "171", "--url",
            "https://github.com/x/y/pull/171", "--mergeable", "MERGEABLE", "--sha", head, "--title", "PR #171 sem conflito")
        time.sleep(1.2)
        _, live = req("GET", "/api/live")
        step("B6 fecha no /api/live", not any(x["id"] == f"pr-conflict:{pc['id']}" for x in live["alerts"]),
             [x["id"] for x in live["alerts"]])
        _, dl = req("GET", "/api/delegacoes?demand=D1")
        it = dl["items"][0]
        kinds = {e["type"] for e in it["events"]}
        step("GET /api/delegacoes coerente: concluida, resultado ok com PR/sha, eventos vinculados",
             it["id"] == did and it["state"] == "concluida" and it["result"]["status"] == "ok" and it["result"]["sha"] == head
             and {"delegation-start", "handoff", "gate", "review-updated", "delegation-result"} <= kinds, it)
        prl = subprocess.run(["gh", "pr", "list", "--head", BR1, "--json", "number", "-q", ".[].number"], env=genv,
                             capture_output=True, text=True).stdout.split()
        calls = (base / "gh_calls").read_text()
        step("gh pr list --head com 1 PR; nenhum 'gh pr merge' nem 'pr create'",
             prl == ["171"] and "pr merge" not in calls and "pr create" not in calls, calls)
        step("CA-29: cópia principal em develop com HEAD/status iguais; log do worktree intacto",
             (git("rev-parse", "HEAD"), git("status", "--porcelain", "--", ".", ":!docs/squad/memory"),
              git("rev-parse", "--abbrev-ref", "HEAD")) == main_before
             and (wt / "docs/squad/memory/decisions.jsonl").read_text() == wt_log_before
             and not git("diff", "--name-only", f"origin/develop...{BR1}", "--", "docs/squad/memory/", cwd=wt))
        step("nenhum control/test-env-*/merge gravado pela squad",
             not any(e.get("type") in ("control", "test-env-request", "test-env-publishing", "test-env-reset",
                                       "test-env-released", "delivered") for e in rows()))

        if a.serve_ui:
            # 2º conflito (D2) com B6 aberto para o roteiro de navegador
            other2 = base / "other2"
            git("clone", "-q", "-b", "develop", str(origin), str(other2), cwd=base)
            (other2 / "services/order-service/Frete.java").write_text("class Frete { int gratis; }\n")
            git("add", "-A", cwd=other2)
            git("commit", "-q", "-m", "develop: frete", cwd=other2)
            git("push", "-q", "origin", "develop", cwd=other2)
            LOG("--agent", "orquestrador", "--type", "pr-conflict", "--demand", D2, "--pr", "172", "--url",
                "https://github.com/x/y/pull/172", "--branch", BR2, "--mergeable", "CONFLICTING",
                "--title", "PR #172 em conflito com a develop")
            (base / "ui-ready.json").write_text(json.dumps({"port": port, "base": str(base), "d1": did, "log": str(log)}))
            print(f"UI PRONTA na porta {port} (base {base})", flush=True)
            signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        # log real intocado (checagem real): nada desta execução foi parar no log da cópia principal nem no do worktree
        ids = {r.get("id") for r in (rows() if log.exists() else []) if r.get("id")}
        bad = []
        for pth, n in REAL_BEFORE.items():
            for line in pth.read_bytes().splitlines()[n:]:
                s = line.decode("utf-8", "replace")
                try:
                    rr = json.loads(s)
                except json.JSONDecodeError:
                    continue
                if MARK in s or rr.get("id") in ids or rr.get("type") == "delegation":
                    bad.append(s[:160])
        STEPS.append(("log real intocado", not bad, "; ".join(bad)[:300]))
        print(f"[{'ok' if not bad else 'FALHOU'}] log real intocado ({len(REAL_BEFORE)} arquivo(s), {len(ids)} ids de teste ausentes)")
        (base / "e2e-result.json").write_text(json.dumps([{"passo": n, "ok": o, "info": i} for n, o, i in STEPS],
                                                         ensure_ascii=False, indent=1))
        if not a.base:
            shutil.rmtree(base, ignore_errors=True)
    return 0 if all(o for _, o, _ in STEPS) else 1


if __name__ == "__main__":
    sys.exit(main())
