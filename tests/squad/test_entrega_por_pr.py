#!/usr/bin/env python3
"""QA D8 (`349e5b1bf818`) — Entrega por PR com revisão humana (ADR-011).

Reproduz o fluxo de `tools/squad/gitflow.py` (feature-finish, review-sync, release-finish,
release-publish) e `tools/squad/pending.py` num repositório git TEMPORÁRIO com um remote bare
LOCAL e um `gh` FALSO no PATH — nenhum efeito no GitHub real. Cobre CA1, CA2, CA3, CA4, CA5, CA6, CA7
do contrato `docs/contracts/entrega-por-pr.md`.

Uso: python3 tests/squad/test_entrega_por_pr.py
Código de saída: 0 se todas as verificações passaram; 1 caso contrário (lista os defeitos no fim).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # .../plankton-d8
FAILURES: list[str] = []


def check(label: str, cond: bool, extra: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(f"{label}" + (f" — {extra}" if extra else ""))
    return cond


FAKE_GH = textwrap.dedent('''\
    #!/usr/bin/env python3
    import sys, os, json, subprocess

    STATE_FILE = os.environ["GH_FAKE_STATE"]
    CALLS_FILE = os.environ.get("GH_FAKE_CALLS")


    def load():
        try:
            return json.loads(open(STATE_FILE, encoding="utf-8").read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"prs": {}, "next_pr": 1}


    def save(state):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)


    def record(argv):
        if CALLS_FILE:
            with open(CALLS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(argv) + "\\n")


    def flag(args, name):
        return args[args.index(name) + 1] if name in args else None


    def main():
        argv = sys.argv[1:]
        record(argv)
        state = load()
        if argv[:2] == ["pr", "list"]:
            head, base = flag(argv, "--head"), flag(argv, "--base")
            match = next((p for p in state["prs"].values()
                          if p["head"] == head and p["base"] == base and p["state"] == "OPEN"), None)
            sys.stdout.write(match["url"] if match else "")
            return 0
        if argv[:2] == ["pr", "create"]:
            base, head = flag(argv, "--base"), flag(argv, "--head")
            title, body = flag(argv, "--title"), flag(argv, "--body")
            pid = str(state["next_pr"]); state["next_pr"] += 1
            url = f"https://github.com/jcrouzillard/checkout-saga-squad/pull/{pid}"
            state["prs"][pid] = {"id": pid, "url": url, "base": base, "head": head, "title": title,
                                  "body": body, "state": "OPEN", "mergeCommit": None, "mergedBy": None,
                                  "closedAt": None, "comments": [], "reviews": []}
            save(state)
            print(url)
            return 0
        if argv[:2] == ["pr", "view"]:
            url = argv[2]
            pid = url.rstrip("/").split("/")[-1]
            pr = state["prs"].get(pid)
            if pr is None:
                print("no such pr", file=sys.stderr)
                return 1
            if "-q" in argv and flag(argv, "-q") == ".state":
                print(pr["state"])
                return 0
            out = {
                "state": pr["state"],
                "mergeCommit": {"oid": pr["mergeCommit"]} if pr["mergeCommit"] else None,
                "mergedBy": {"login": pr["mergedBy"]} if pr["mergedBy"] else None,
                "closedAt": pr["closedAt"],
                "comments": [{"body": c} for c in pr["comments"]],
                "reviews": [{"body": r} for r in pr["reviews"]],
            }
            print(json.dumps(out))
            return 0
        if argv[:2] == ["release", "create"]:
            tag, target = argv[2], flag(argv, "--target")
            # no GitHub real o commit já está no servidor (o humano acabou de mergear); aqui o fake roda com
            # cwd = ROOT do checkout local do orquestrador, que pode não ter esse objeto ainda — busca primeiro.
            subprocess.run(["git", "fetch", "-q", "origin"], check=False)
            subprocess.run(["git", "tag", tag, target], check=True)
            print(f"https://github.com/jcrouzillard/checkout-saga-squad/releases/tag/{tag}")
            return 0
        print(f"fake gh: comando nao suportado: {argv}", file=sys.stderr)
        return 1


    if __name__ == "__main__":
        sys.exit(main())
    ''')

FAKE_MVN = textwrap.dedent('''\
    #!/usr/bin/env python3
    import re, sys
    ver = None
    for a in sys.argv[1:]:
        m = re.match(r"-DnewVersion=(.+)", a)
        if m:
            ver = m.group(1)
    if ver:
        with open("VERSION", "w", encoding="utf-8") as f:
            f.write(ver + "\\n")
    sys.exit(0)
    ''')


class Harness:
    def __init__(self, base: Path):
        self.base = base
        self.remote = base / "remote.git"
        self.work = base / "work"
        self.bin = base / "bin"
        self.state_file = base / "gh-state.json"
        self.calls_file = base / "gh-calls.jsonl"
        self.env = dict(os.environ)

    def sh(self, *cmd, cwd=None, check=True):
        out = subprocess.run(cmd, cwd=cwd or self.work, capture_output=True, text=True, env=self.env)
        if check and out.returncode != 0:
            raise RuntimeError(f"falhou: {' '.join(cmd)}\n{out.stdout}\n{out.stderr}")
        return out

    def run_gitflow(self, *args, check=True):
        return self.sh("python3", str(self.work / "tools/squad/gitflow.py"), *args, check=check)

    def run_log(self, *args, check=True):
        return self.sh("python3", str(self.work / "tools/squad/log.py"), *args, check=check)

    def run_pending(self, check=False):
        return self.sh("python3", str(self.work / "tools/squad/pending.py"), check=check)

    def current_branch(self):
        return self.sh("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def gh_state(self):
        return json.loads(self.state_file.read_text())

    def gh_calls(self):
        return [json.loads(l) for l in self.calls_file.read_text().splitlines() if l.strip()] \
            if self.calls_file.exists() else []

    def decisions(self):
        p = self.work / "docs/squad/memory/decisions.jsonl"
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def decisions_on(self, branch: str):
        out = self.sh("git", "show", f"{branch}:docs/squad/memory/decisions.jsonl")
        return [json.loads(l) for l in out.stdout.splitlines() if l.strip()]

    def commit_all(self, message: str):
        self.sh("git", "add", "-A")
        self.sh("git", "commit", "-q", "-m", message)

    def snapshot(self, message: str = "Sincronização da memória da squad (fixture QA)"):
        """Espelha snapshot_state() do gitflow.py: comita só docs/squad/memory|inbox antes de trocar de branch,
        para que escritas diretas de log.py/pending.py (fora do fluxo do gitflow.py) nunca deixem a árvore suja."""
        status = self.sh("git", "status", "--porcelain").stdout.splitlines()
        changed = [l[3:] for l in status if l[3:].startswith(("docs/squad/memory/", "docs/squad/inbox/"))]
        if changed:
            self.sh("git", "add", "--", *changed)
            self.sh("git", "commit", "-q", "-m", message)

    def setup(self):
        self.bin.mkdir(parents=True)
        gh_path = self.bin / "gh"
        gh_path.write_text(FAKE_GH)
        gh_path.chmod(0o755)
        mvn_path = self.bin / "mvn"
        mvn_path.write_text(FAKE_MVN)
        mvn_path.chmod(0o755)
        self.env["PATH"] = f"{self.bin}:{self.env['PATH']}"
        self.env["GH_FAKE_STATE"] = str(self.state_file)
        self.env["GH_FAKE_CALLS"] = str(self.calls_file)
        self.state_file.write_text(json.dumps({"prs": {}, "next_pr": 1}))

        self.sh("git", "init", "-q", "-b", "main", str(self.remote), "--bare", cwd=self.base)
        self.work.mkdir()
        self.sh("git", "init", "-q", "-b", "main", cwd=self.work)
        self.sh("git", "config", "user.email", "qa@squad.local")
        self.sh("git", "config", "user.name", "QA Squad")
        self.sh("git", "config", "commit.gpgsign", "false")

        shutil.copytree(REPO_ROOT / "tools" / "squad", self.work / "tools" / "squad")
        (self.work / "docs/squad/memory").mkdir(parents=True)
        (self.work / "docs/squad/memory/decisions.jsonl").write_text("")
        (self.work / "docs/squad/inbox").mkdir(parents=True)
        (self.work / "docs/squad/inbox/.gitkeep").write_text("")
        (self.work / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n")
        (self.work / ".gitignore").write_text(".squad/\n")
        self.commit_all("chore: bootstrap do ambiente de teste QA D8")

        self.sh("git", "remote", "add", "origin", str(self.remote))
        self.sh("git", "push", "-q", "-u", "origin", "main")
        self.sh("git", "switch", "-q", "-c", "develop")
        self.sh("git", "push", "-q", "-u", "origin", "develop")

    def new_demand(self, title: str) -> str:
        out = self.run_log("--agent", "humano", "--type", "task", "--title", f"Demanda: {title}",
                            "--detail", "cenario de teste QA D8", "--kind", "operacao")
        m = re.search(r"logged (\S+)", out.stdout)
        assert m, out.stdout
        return m.group(1)

    def approve_g3(self, demand: str, detail: str):
        self.run_log("--agent", "auditor", "--type", "gate", "--gate", "G3", "--recommendation", "APPROVE",
                      "--confidence", "0.95", "--risk", "baixo", "--demand", demand,
                      "--title", "G3 aprovado (fixture QA D8)", "--detail", detail)

    def human_merge(self, base: str, head: str, message: str, clone_name: str) -> str:
        """Simula o merge humano NO GITHUB: opera num clone À PARTE do remote bare (nunca no checkout local
        do 'orquestrador'), exatamente como o GitHub faria server-side. Retorna o SHA do merge commit."""
        clone = self.base / clone_name
        self.sh("git", "clone", "-q", str(self.remote), str(clone), cwd=self.base)
        self.sh("git", "config", "user.email", "humano@github.local", cwd=clone)
        self.sh("git", "config", "user.name", "Humano (revisor)", cwd=clone)
        self.sh("git", "switch", "-q", base, cwd=clone)
        self.sh("git", "merge", "-q", "--no-ff", f"origin/{head}", "-m", message, cwd=clone)
        sha = self.sh("git", "rev-parse", "HEAD", cwd=clone).stdout.strip()
        self.sh("git", "push", "-q", "origin", base, cwd=clone)
        return sha

    def sync_develop(self):
        """Espelha sync_develop() do gitflow.py (chamada por feature-start): develop local = develop remota
        + memória da squad, e local vira remota de novo (senão a develop local diverge da origin e o próximo
        merge/rebase humano pode conflitar por causa só do decisions.jsonl — não é isso que queremos exercitar
        aqui, que é o fluxo de revisão em si)."""
        self.sh("git", "fetch", "-q", "origin")
        if self.current_branch() != "develop":
            self.sh("git", "switch", "-q", "develop")
        self.sh("git", "pull", "-q", "--rebase", "--autostash", "origin", "develop")
        self.snapshot()
        self.sh("git", "push", "-q", "origin", "develop")

    def make_feature_branch(self, branch: str, filename: str, content: str):
        self.sync_develop()
        self.sh("git", "switch", "-q", "-c", branch, "develop")
        f = self.work / filename
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        self.commit_all(f"feat: {filename}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="qa-d8-"))
    h = Harness(tmp)
    print(f"ambiente de teste: {tmp}")
    try:
        h.setup()

        # ------------------------------------------------------------------ CA1
        d1 = h.new_demand("Teste D8 - fluxo de revisao")
        h.make_feature_branch("feature/T1-teste", "tests/squad/tmp/a.txt", "linha 1\n")

        out = h.run_gitflow("feature-finish", "--demand", d1, check=False)
        check("CA1: feature-finish sem G3 falha (código != 0)", out.returncode != 0)
        check("CA1: mensagem cita G3 não aprovado", "G3" in out.stderr and "não" in out.stderr, out.stderr)

        out = h.run_gitflow("feature-finish", check=False)  # sem --demand
        check("CA1: --demand é obrigatório (argparse recusa)", out.returncode != 0)

        out = h.run_gitflow("feature-finish", "--demand", d1, "--force", check=False)
        check("CA1: --force não existe (argparse recusa)", out.returncode != 0 and "unrecognized" in out.stderr)

        # validação com pergunta + resposta (para o corpo do PR, CA3) e evidência
        out = h.run_log("--agent", "arquiteto", "--type", "validation", "--demand", d1, "--status", "perguntas",
                         "--title", "Validação da demanda",
                         "--question", "escopo::Qual o escopo exato da mudança?")
        val_id = re.search(r"logged (\S+)", out.stdout).group(1)
        h.run_log("--agent", "humano", "--type", "clarification", "--demand", d1, "--title", "Respostas",
                   "--detail", f"validation={val_id}")
        # clarification real precisa do campo "answers"; log.py não tem --answer, então gravamos via edição
        # direta do jsonl (fixture) mantendo o formato usado por gitflow.py (amap por id de pergunta).
        lines = (h.work / "docs/squad/memory/decisions.jsonl").read_text().splitlines()
        clar = json.loads(lines[-1])
        clar["answers"] = [{"id": "q1", "text": "Só o painel de revisão, sem tocar no backend"}]
        lines[-1] = json.dumps(clar, ensure_ascii=False)
        (h.work / "docs/squad/memory/decisions.jsonl").write_text("\n".join(lines) + "\n")

        h.run_log("--agent", "qa", "--type", "evidence", "--demand", d1, "--title", "Evidências enviadas",
                   "--evidence", "Testes unitários=pass", "--evidence", "Cobertura de branch=validate")

        h.approve_g3(d1, "aprovado para o teste D8 (fixture QA)")

        # ------------------------------------------------------------------ CA2 / CA3
        out = h.run_gitflow("feature-finish", "--demand", d1)
        pr1_url = out.stdout.strip()
        check("CA2: feature-finish com G3 aprovado abre o PR (stdout = url)", pr1_url.startswith("https://"))
        check("CA2: volta para a develop depois de abrir o PR", h.current_branch() == "develop")

        calls = h.gh_calls()
        creates = [c for c in calls if c[:2] == ["pr", "create"]]
        check("CA2: exatamente 1 'gh pr create' na 1ª execução", len(creates) == 1, str(creates))

        dev_events = h.decisions_on("develop")
        reviews_d1 = [e for e in dev_events if e.get("type") == "review" and e.get("demand") == d1]
        check("CA2: o evento 'review' está commitado NA DEVELOP (defeito do ciclo 1 do G2-D8 corrigido)",
              len(reviews_d1) == 1, str(reviews_d1))
        check("CA2: review referencia a mesma PR url", reviews_d1 and reviews_d1[0].get("url") == pr1_url)

        state = h.gh_state()
        body1 = state["prs"]["1"]["body"]
        for section, needle in [
            ("Pareceres do Auditor", "## Pareceres do Auditor"),
            ("G3 no corpo", "**G3:**"),
            ("Evidências", "Testes unitários: pass"),
            ("Perguntas e respostas", "Qual o escopo exato da mudança?"),
            ("Resposta do humano", "Só o painel de revisão"),
            ("Artefatos alterados", "## Artefatos alterados"),
            ("Nome do arquivo do diff", "a.txt"),
            ("Checklist do revisor", "## Checklist do revisor"),
            ("Revisão humana", "revisão humana"),
        ]:
            check(f"CA3: corpo do PR contém {section}", needle in body1, body1[:400])
        check("CA3: sem 'Refs #' quando a demanda não tem issue (github-sync.json ausente)",
              "Refs #" not in body1)

        # idempotência: reexecuta na feature — não deve duplicar PR nem review
        h.sh("git", "switch", "-q", "feature/T1-teste")
        out2 = h.run_gitflow("feature-finish", "--demand", d1)
        check("CA2: reexecução reutiliza o PR (mesma url)", out2.stdout.strip() == pr1_url)
        calls2 = h.gh_calls()
        creates2 = [c for c in calls2 if c[:2] == ["pr", "create"]]
        check("CA2: reexecução não chama 'gh pr create' de novo", len(creates2) == 1, str(creates2))
        dev_events2 = h.decisions_on("develop")
        reviews_d1_b = [e for e in dev_events2 if e.get("type") == "review" and e.get("demand") == d1]
        check("CA2: reexecução não duplica o evento 'review'", len(reviews_d1_b) == 1, str(reviews_d1_b))

        # ------------------------------------------------------------------ CA4
        grep = subprocess.run(["grep", "-rnE", r'"pr",\s*"merge"|pr merge', str(REPO_ROOT / "tools/squad")],
                               capture_output=True, text=True)
        check("CA4: 'grep pr merge' em tools/squad (fonte real) está vazio", grep.stdout.strip() == "",
              grep.stdout)
        merge_calls = [c for c in h.gh_calls() if c[:2] == ["pr", "merge"]]
        check("CA4: nenhuma chamada 'gh pr merge' foi registrada pelo gh falso", merge_calls == [],
              str(merge_calls))

        # ------------------------------------------------------------------ CA5 (PR fechado sem merge)
        state = h.gh_state()
        state["prs"]["1"]["state"] = "CLOSED"
        state["prs"]["1"]["closedAt"] = "2026-09-23T12:00:00Z"
        state["prs"]["1"]["comments"] = ["Ajustar a mensagem de erro antes de mergear."]
        state["prs"]["1"]["reviews"] = ["Solicitando mudanças: cobrir o caso de PR já fechado."]
        h.state_file.write_text(json.dumps(state))

        pend = h.run_pending()
        check("CA5: pending.py lista 'revisão recusada' para o PR fechado",
              f"revisão recusada: demanda {d1} (PR #1)" in pend.stdout, pend.stdout)

        out = h.run_gitflow("review-sync", "--demand", d1)
        check("CA5: review-sync imprime 'devolvida pelo revisor'", out.stdout.strip() == "devolvida pelo revisor",
              out.stdout)
        rejected = [e for e in h.decisions() if e.get("type") == "review-rejected" and e.get("demand") == d1]
        check("CA5: evento review-rejected registrado", len(rejected) == 1, str(rejected))
        check("CA5: review-rejected inclui os comentários do revisor",
              rejected and "Ajustar a mensagem de erro" in rejected[0].get("detail", ""),
              str(rejected))

        out = h.run_gitflow("review-sync", "--demand", d1)
        check("CA5: review-sync é idempotente (já tratado)", "já tratado: review-rejected" in out.stdout,
              out.stdout)

        # ------------------------------------------------------------------ CA6 (PR integrado)
        d2 = h.new_demand("Teste D8 - fluxo de entrega")
        h.make_feature_branch("feature/T2-teste2", "tests/squad/tmp/b.txt", "linha 1\n")
        h.approve_g3(d2, "aprovado para o teste D8 (fluxo de entrega)")
        out = h.run_gitflow("feature-finish", "--demand", d2)
        pr2_url = out.stdout.strip()
        pr2_id = pr2_url.rstrip("/").split("/")[-1]

        # simula o humano integrando o PR #2 no GitHub: merge feito num clone À PARTE (server-side),
        # nunca no checkout local do orquestrador — é o review-sync que precisa buscar essa mudança.
        merge_sha = h.human_merge("develop", "feature/T2-teste2", f"Merge pull request #{pr2_id}", "humanclone-1")
        state = h.gh_state()
        state["prs"][pr2_id]["state"] = "MERGED"
        state["prs"][pr2_id]["mergeCommit"] = merge_sha
        state["prs"][pr2_id]["mergedBy"] = "jcrouzillard"
        state["prs"][pr2_id]["closedAt"] = "2026-09-23T12:30:00Z"
        h.state_file.write_text(json.dumps(state))

        pend = h.run_pending()
        check("CA6: pending.py lista 'revisão integrada' para o PR merged",
              f"revisão integrada: demanda {d2} (PR #{pr2_id})" in pend.stdout, pend.stdout)

        out = h.run_gitflow("review-sync", "--demand", d2, check=False)
        rebase_conflict = out.returncode != 0 and "could not apply" in (out.stderr or "") and \
            "decisions.jsonl" in h.sh("git", "status", "--porcelain", check=False).stdout
        if check("CA6 [DEFEITO]: review-sync (MERGED) não quebra com conflito de git ao sincronizar a develop",
                 out.returncode == 0, out.stderr if not rebase_conflict else
                 "git pull --rebase --autostash origin develop entra em CONFLITO em decisions.jsonl: o evento "
                 "'review' fica commitado só na develop LOCAL (nunca é empurrado para origin/develop — só o "
                 "próximo sync_develop/feature-start faria isso); se o humano integra o PR antes disso (o caso "
                 "normal, já que nada empurra a develop entre o feature-finish e o merge humano), o rebase do "
                 "review-sync tenta reaplicar o commit local 'Sincronização da memória da squad' sobre a nova "
                 "ponta da develop (que já trouxe outra mudança no fim do mesmo arquivo pelo merge do PR) e "
                 "conflita. O comando termina com git em rebase pendente (repositório sujo) e SEM o evento "
                 f"'delivered'. stderr: {out.stderr.strip()}"):
            delivered = [e for e in h.decisions() if e.get("type") == "delivered" and e.get("demand") == d2]
            check("CA6: evento delivered registrado com mergeCommit",
                  delivered and delivered[0].get("mergeCommit") == merge_sha[:12], str(delivered))
            branches = h.sh("git", "branch", "--list", "feature/T2-teste2").stdout.strip()
            check("CA6: branch local da feature foi removida", branches == "", branches)
            out = h.run_gitflow("review-sync", "--demand", d2)
            check("CA6: review-sync é idempotente para delivered", "já tratado: delivered" in out.stdout, out.stdout)
        elif rebase_conflict:
            # recupera o repositório de teste (git rebase --abort + reset para a origin) só para continuar
            # exercitando CA7 a seguir; isto NÃO faz parte do comportamento do gitflow.py, é limpeza do teste.
            h.sh("git", "rebase", "--abort", check=False)
            h.sh("git", "fetch", "-q", "origin")
            h.sh("git", "reset", "-q", "--hard", "origin/develop")

        # ------------------------------------------------------------------ CA7 (release)
        h.sh("git", "fetch", "-q", "origin")
        h.sh("git", "switch", "-q", "-c", "release/9.9.9", "origin/develop")
        changelog = h.work / "CHANGELOG.md"
        text = changelog.read_text()
        changelog.write_text(text.replace("## [Unreleased]", "## [Unreleased]\n\n## [9.9.9] - 2026-09-23\n\n- Teste QA D8 (fixture)."))
        h.commit_all("Release 9.9.9: versão e CHANGELOG (fixture QA)")

        out = h.run_gitflow("release-finish", "9.9.9")
        rel_pr_url = out.stdout.strip()
        check("CA7: release-finish abre PR (não faz merge)", rel_pr_url.startswith("https://"))
        rel_creates = [c for c in h.gh_calls() if c[:2] == ["pr", "create"]]
        check("CA7: release-finish criou 1 novo PR (para main)", len(rel_creates) == 3, str(rel_creates))  # 2 anteriores (d1, d2) + este
        rel_state = h.gh_state()
        rel_pr_id = rel_pr_url.rstrip("/").split("/")[-1]
        check("CA7: PR da release tem base=main", rel_state["prs"][rel_pr_id]["base"] == "main",
              rel_state["prs"][rel_pr_id]["base"])

        out = h.run_gitflow("release-publish", "9.9.9", check=False)
        check("CA7: release-publish recusa sem MERGED", out.returncode != 0 and "ainda não foi integrado" in out.stderr,
              out.stderr)

        # simula o humano integrando o PR da release em main (de novo, num clone à parte)
        main_merge_sha = h.human_merge("main", "release/9.9.9", f"Merge pull request #{rel_pr_id}", "humanclone-2")
        rel_state = h.gh_state()
        rel_state["prs"][rel_pr_id]["state"] = "MERGED"
        rel_state["prs"][rel_pr_id]["mergeCommit"] = main_merge_sha
        h.state_file.write_text(json.dumps(rel_state))

        out = h.run_gitflow("release-publish", "9.9.9")
        check("CA7: release-publish com MERGED conclui", out.returncode == 0, out.stderr)
        tag_sha = h.sh("git", "rev-parse", "v9.9.9", check=False).stdout.strip()
        check("CA7: tag v9.9.9 aponta para o merge commit da release", tag_sha == main_merge_sha,
              f"tag={tag_sha} merge={main_merge_sha}")
        rel_release_calls = [c for c in h.gh_calls() if c[:2] == ["release", "create"]]
        check("CA7: 'gh release create' chamado com --target o merge commit",
              rel_release_calls and "--target" in rel_release_calls[-1] and
              rel_release_calls[-1][rel_release_calls[-1].index("--target") + 1] == main_merge_sha,
              str(rel_release_calls))
        delivered_release = [e for e in h.decisions() if e.get("type") == "delivered" and e.get("release") == "9.9.9"]
        check("CA7: evento delivered da release registrado", len(delivered_release) == 1, str(delivered_release))
        rel_creates_final = [c for c in h.gh_calls() if c[:2] == ["pr", "create"]]
        check("CA7: back-merge aberto como PR (mais 1 'pr create', total 4)", len(rel_creates_final) == 4,
              str(rel_creates_final))
        merge_calls_final = [c for c in h.gh_calls() if c[:2] == ["pr", "merge"]]
        check("CA4/CA7: em nenhum momento do release 'gh pr merge' foi chamado", merge_calls_final == [],
              str(merge_calls_final))
        back_branch = h.sh("git", "branch", "--list", "chore/back-merge-9.9.9").stdout.strip()
        check("CA7: branch de back-merge foi criada e empurrada", back_branch != "")

    finally:
        server_msg = "(sem servidor HTTP nesta suíte; nada a encerrar)"
        print(server_msg)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} verificação(ões) FALHARAM:")
        for f in FAILURES:
            print(f" - {f}")
        return 1
    print("Todas as verificações passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
