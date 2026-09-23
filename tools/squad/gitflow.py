#!/usr/bin/env python3
"""Git Flow da squad (independe do fornecedor de IA: qualquer agente ou humano usa os mesmos comandos).

  feature-start <código> <slug>        develop → feature/<código>-<slug>
  feature-finish [--demand <id>]       push + PR para develop; merge só com G3 APPROVE da demanda
  release-start <x.y.z>                develop → release/<x.y.z>; versão do pom = x.y.z; CHANGELOG
  release-finish <x.y.z>               PR para main + merge, tag vX.Y.Z + GitHub Release,
                                       back-merge em develop e próxima versão -SNAPSHOT
  hotfix-start <x.y.z> <slug>          main → hotfix/<x.y.z>-<slug>
  hotfix-finish <x.y.z>                igual ao release-finish, a partir do hotfix

Regras (CLAUDE.md / AGENTS.md → "Fluxo de branches"): ninguém commita direto em main; features entram em develop
por PR; o Auditor aprova o G3 antes do merge; releases e hotfixes são do Orquestrador, com aprovação humana.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = ROOT / "docs/squad/memory/decisions.jsonl"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO = "jcrouzillard/checkout-saga-squad"
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"


def sh(*cmd: str, check=True, capture=True) -> str:
    out = subprocess.run(cmd, cwd=ROOT, capture_output=capture, text=True)
    if check and out.returncode != 0:
        sys.exit(f"falhou: {' '.join(cmd)}\n{(out.stderr or out.stdout).strip()}")
    return (out.stdout or "").strip()


def log(title: str, detail: str = "", demand: str | None = None, ref: str | None = None, branch: str | None = None):
    args = ["python3", "tools/squad/log.py", "--agent", "orquestrador", "--type", "decision", "--title", title]
    if detail:
        args += ["--detail", detail]
    if demand:
        args += ["--demand", demand]
    if ref:
        args += ["--ref", ref]
    if branch:
        args += ["--branch", branch]
    sh(*args)


def current() -> str:
    return sh("git", "rev-parse", "--abbrev-ref", "HEAD")


STATE = ("docs/squad/memory/",)  # memória viva da squad (log, sync): muda o tempo todo e é commitada automaticamente


def snapshot_state():
    changed = [l[3:] for l in sh("git", "status", "--porcelain").splitlines() if l[3:].startswith(STATE)]
    if changed:
        sh("git", "add", "--", *changed)
        sh("git", "commit", "-q", "-m", f"Sincronização da memória da squad{TRAILER}")


def clean_tree():
    snapshot_state()
    dirty = [l for l in sh("git", "status", "--porcelain").splitlines() if not l[3:].startswith(STATE)]
    if dirty:
        sys.exit("há alterações não commitadas; faça commit antes de trocar de branch:\n" + "\n".join(dirty))


def sync_develop():
    """develop local = develop remota + memória da squad commitada."""
    sh("git", "fetch", "-q", "origin")
    if current() != "develop":
        sh("git", "switch", "-q", "develop")
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
    clean_tree()
    slug = re.sub(r"[^a-z0-9]+", "-", a.slug.lower()).strip("-")
    branch = f"feature/{a.code}-{slug}"
    sync_develop()
    sh("git", "switch", "-q", "-c", branch)
    log(f"Branch {branch} criada a partir de develop", demand=a.demand, branch=branch)
    print(branch)


def feature_finish(a):
    clean_tree()
    branch = current()
    if not branch.startswith("feature/"):
        sys.exit(f"não está numa feature branch ({branch})")
    gate = None
    if a.demand:
        gate = g3_approved(a.demand)
        if not gate and not a.force:
            sys.exit("G3 da demanda ainda não aprovado pelo Auditor: o merge em develop fica bloqueado (use --force só "
                     "com decisão humana registrada)")
    sh("git", "push", "-q", "-u", "origin", branch)
    body = (f"Demanda `{a.demand}`.\n\n" if a.demand else "") + (
        f"Auditor · G3 {gate['recommendation']} · {round((gate.get('confidence') or 0) * 100)}% · risco {gate.get('risk')}\n\n"
        f"{gate.get('detail', '')}\n\n" if gate else "") + "Gerado por `tools/squad/gitflow.py`.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"
    url = pr("develop", branch, a.title or branch.replace("feature/", "").replace("-", " "), body)
    sh("gh", "pr", "merge", url, "--merge", "--delete-branch")
    sh("git", "switch", "-q", "develop")
    sh("git", "pull", "-q", "--rebase", "--autostash", "origin", "develop")
    log(f"{branch} integrada em develop via PR", demand=a.demand, ref=url, branch="develop")
    snapshot_state()
    sh("git", "push", "-q", "origin", "develop")
    print(url)


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
        sh("git", "switch", "-q", "-c", branch)
    else:
        sh("git", "fetch", "-q", "origin")
        sh("git", "switch", "-q", "-c", branch, f"origin/{source}")
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
    tag = f"v{a.version}"
    sh("git", "push", "-q", "-u", "origin", branch)
    notes = CHANGELOG.read_text().split(f"## [{a.version}]", 1)[-1].split("\n## [", 1)[0] if CHANGELOG.exists() else ""
    url = pr("main", branch, f"{kind.capitalize()} {a.version}",
             f"{kind.capitalize()} {a.version}.\n\n## [{a.version}]{notes}\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")
    sh("gh", "pr", "merge", url, "--merge")
    sh("git", "fetch", "-q", "origin")
    sh("gh", "release", "create", tag, "-R", REPO, "--target", "main", "--title", f"{tag}",
       "--notes", f"## [{a.version}]{notes}")
    # back-merge em develop + próxima versão de desenvolvimento
    sh("git", "switch", "-q", "develop")
    sh("git", "pull", "-q", "--rebase", "--autostash", "origin", "develop")
    sh("git", "merge", "-q", "--no-ff", branch, "-m", f"Back-merge de {branch} em develop{TRAILER}")
    major, minor, _ = (int(x) for x in a.version.split("."))
    nxt = f"{major}.{minor + 1}.0-SNAPSHOT"
    set_version(nxt)
    sh("git", "add", "-A")
    sh("git", "commit", "-q", "-m", f"Próxima versão de desenvolvimento: {nxt}{TRAILER}")
    sh("git", "push", "-q", "origin", "develop")
    sh("git", "push", "-q", "origin", "--delete", branch, check=False)
    sh("git", "branch", "-q", "-D", branch, check=False)
    log(f"{kind.capitalize()} {a.version} publicada: {tag} em main, back-merge em develop ({nxt})", ref=url, branch="main")
    snapshot_state()
    sh("git", "push", "-q", "origin", "develop")
    print(url)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("feature-start"); s.add_argument("code"); s.add_argument("slug"); s.add_argument("--demand")
    s = sub.add_parser("feature-finish"); s.add_argument("--demand"); s.add_argument("--title"); s.add_argument("--force", action="store_true")
    s = sub.add_parser("release-start"); s.add_argument("version")
    s = sub.add_parser("release-finish"); s.add_argument("version")
    s = sub.add_parser("hotfix-start"); s.add_argument("version"); s.add_argument("slug")
    s = sub.add_parser("hotfix-finish"); s.add_argument("version")
    a = p.parse_args()
    {"feature-start": feature_start, "feature-finish": feature_finish,
     "release-start": release_start, "release-finish": release_finish,
     "hotfix-start": lambda x: release_start(x, source="main", kind="hotfix"),
     "hotfix-finish": lambda x: release_finish(x, kind="hotfix")}[a.cmd](a)


if __name__ == "__main__":
    main()
