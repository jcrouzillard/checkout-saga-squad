#!/usr/bin/env python3
"""Atualização incremental do produtivo local (D15, ADR-018, docs/contracts/ambiente-de-teste.md §8) — só stdlib.

  update [--auto]     depois do merge na develop: rebuild/recriação SÓ dos serviços alterados desde o último deploy.
                      `--auto` (chamado por `gitflow.py review-sync`) respeita SQUAD_PROD_AUTOUPDATE (padrão 1; 0 desliga).
  baseline            registra o commit atual como implantado SEM tocar containers (R2) — rodar na integração da D15.
  plan [--from <sha>] mostra o que o update faria (só leitura).

Salvaguardas: roda só na cópia principal, em develop, com HEAD == origin/develop, sem mudança rastreada fora de
docs/squad/**, com lock; build ANTES de tocar containers; ponto de retorno `:rollback` a partir da imagem do container
em execução (R3); `up -d --no-deps` só nos alterados; mudança no compose → só serviços cujo `config --hash` mudou
(R5); espera healthy; rollback por retag — exceto com migração Flyway nova (R4), que vira bloqueio B5 para o humano.
NUNCA gera `down`, `-v`, `prune`, `rm`, `--remove-orphans` nem `--force-recreate` (CA16: `assert_safe`).
Executáveis injetáveis como em testenv.py (`$SQUAD_DOCKER`, `$SQUAD_GIT`).
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import testenv as te  # noqa: E402  (executor injetável, log, lock)

PROJECT = te.PROD_PROJECT
APP = te.APP_SERVICES
LOCK_FILE = te.DATA_ROOT / ".squad/prod-update.lock"
UP_WAIT = 300
MIGRATION_RE = re.compile(r"(^|/)db/(migration|common)/")          # R4: **/db/migration/** e **/db/common/**
FORBIDDEN_TOKENS = {"down", "-v", "--volumes", "prune", "rm", "rmi", "--remove-orphans", "--force-recreate",
                    "kill", "--rmi"}


class Abort(Exception):
    def __init__(self, phase: str, detail: str):
        super().__init__(detail)
        self.phase = phase


# ================================================================ comandos (todos passam por assert_safe)
def compose(*args: str) -> list[str]:
    return ["docker", "compose", "-p", PROJECT, *args]


def assert_safe(cmd: list[str]):
    """CA16: lista fechada de proibidos no produtivo; todo `docker compose` leva `-p checkout-saga`."""
    bad = [t for t in cmd if t in FORBIDDEN_TOKENS]
    if cmd[:2] == ["docker", "volume"] or cmd[:2] == ["docker", "system"] or cmd[:2] == ["docker", "network"]:
        bad.append(cmd[1])
    if cmd[:2] == ["docker", "compose"] and cmd[2:4] != ["-p", PROJECT]:
        bad.append("compose sem -p checkout-saga")
    if te.TEST_PROJECT in " ".join(cmd):
        bad.append("menciona o projeto de teste")
    if bad:
        raise RuntimeError(f"comando destrutivo recusado no produtivo ({', '.join(bad)}): {' '.join(cmd)}")


def run(cmd: list[str], timeout: float = 120, cwd=None) -> te.Result:
    assert_safe(cmd)
    return te.EXEC.run(cmd, cwd=cwd or te.main_root(), timeout=timeout)


def git(*args: str, timeout: float = 60) -> te.Result:
    return run(["git", "-C", str(te.main_root()), *args], timeout=timeout)


# ================================================================ plano (puro)
def plan_paths(changes: list[tuple[str, str]]) -> dict:
    """changes = [(status, caminho)] do `git diff --name-status`. Tabela do §8 passo 2."""
    build, restart, warnings = set(), set(), []
    compose_changed = migrations = False
    for status, path in changes:
        if MIGRATION_RE.search(path) and status[:1] in ("A", "M", "R", "C"):
            migrations = True
        if path.startswith("services/"):
            mod = path.split("/")[1] if path.count("/") >= 1 else ""
            if mod in APP:
                build.add(mod)
            else:                           # services/common/**, services/pom.xml, módulo novo → os 5
                build.update(APP)
        elif path in ("pom.xml", "Dockerfile", ".dockerignore"):
            build.update(APP)
        elif path == "docker-compose.yml":
            compose_changed = True
        elif path == "checkout-console/nginx.conf":
            restart.add("checkout-console")
        elif path.startswith("infra/observability/prometheus/"):
            restart.add("prometheus")
        elif path.startswith("infra/observability/grafana/"):
            restart.add("grafana")
        elif path.startswith("infra/observability/"):
            restart.update({"prometheus", "grafana"})
        elif path.startswith("infra/postgres/init/"):
            warnings.append(f"{path}: só vale na 1ª criação do volume (nada aplicado)")
    return {"build": sorted(build), "restart": sorted(restart), "compose": compose_changed,
            "migrations": migrations, "warnings": warnings}


# ================================================================ estado no log
def last_deployed(rows: list[dict]) -> str | None:
    for e in reversed(rows):
        if e.get("type") == "prod-updated" and e.get("commit"):
            return e["commit"]
    return None


def image_revision() -> str | None:
    """1ª vez sem prod-updated: rótulo org.opencontainers.image.revision comum às 5 imagens (senão None)."""
    revs = set()
    for svc in APP:
        r = run(["docker", "image", "inspect", "--format",
                 '{{index .Config.Labels "org.opencontainers.image.revision"}}', f"{PROJECT}/{svc}:local"])
        rev = r.out.strip() if r.ok else ""
        if not rev or rev == "<no value>":
            return None
        revs.add(rev)
    return revs.pop() if len(revs) == 1 else None


# ================================================================ guard
def guard() -> str:
    main = te.main_root()
    # Cópia principal = worktree em develop (testenv.main_root). Rodar de um worktree de feature/teste é recusado.
    if not os.environ.get("SQUAD_MAIN_ROOT") and te.ROOT.resolve() != main:
        raise Abort("guard", f"prod.py deve rodar na cópia principal ({main}), não em {te.ROOT}")
    r_top = git("rev-parse", "--path-format=absolute", "--show-toplevel")
    if not r_top.ok or pathlib.Path(r_top.out.strip()).resolve() != main:
        raise Abort("guard", f"{main} não é a raiz de um checkout git")
    if not (main / "docker-compose.yml").exists():
        raise Abort("guard", f"{main}/docker-compose.yml não existe")
    br = git("rev-parse", "--abbrev-ref", "HEAD").out.strip()
    if br != "develop":
        raise Abort("guard", f"a cópia principal está em {br!r}, não em develop")
    git("fetch", "-q", "origin", timeout=120)
    head = git("rev-parse", "HEAD").out.strip()
    remote = git("rev-parse", "origin/develop").out.strip()
    if not head or head != remote:
        raise Abort("guard", f"HEAD ({head[:12]}) != origin/develop ({remote[:12]})")
    dirty = [l[3:] for l in git("status", "--porcelain", "--untracked-files=no").out.splitlines()
             if l.strip() and not l[3:].startswith("docs/squad/")]
    if dirty:
        raise Abort("guard", "mudanças rastreadas fora de docs/squad/**: " + ", ".join(dirty[:10]))
    r = run(compose("config", "--format", "json"), timeout=60)
    try:
        name = json.loads(r.out).get("name") if r.ok else None
    except json.JSONDecodeError:
        name = None
    if name != PROJECT:
        raise Abort("guard", f"projeto resolvido {name!r} != {PROJECT!r}")
    return head


def config_hashes(compose_file: pathlib.Path | None = None) -> dict:
    args = ["-f", str(compose_file), "--project-directory", str(te.main_root())] if compose_file else []
    r = run(["docker", "compose", "-p", PROJECT, *args, "config", "--hash", "*"], timeout=60)
    if not r.ok:
        raise Abort("guard", f"config --hash falhou: {(r.err or r.out).strip()[:500]}")
    return dict(tuple(l.split(None, 1)) for l in r.out.splitlines() if len(l.split()) == 2)


def compose_changed_services(frm: str) -> list[str]:
    """R5: serviços cuja definição mudou entre o compose implantado e o de HEAD (nunca `up -d` global)."""
    old = git("show", f"{frm}:docker-compose.yml")
    if not old.ok:
        return []
    tmp = te.DATA_ROOT / ".squad" / f"prod-compose-{frm[:12]}.yml"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(old.out, encoding="utf-8")
    try:
        before, after = config_hashes(tmp), config_hashes()
    finally:
        tmp.unlink(missing_ok=True)
    return sorted(s for s in after if before.get(s) != after[s])


# ================================================================ update
def rollback_points(services: list[str]) -> dict:
    """R3: `:rollback` a partir do Image id do container EM EXECUÇÃO (a tag :local pode ter sido reescrita)."""
    points = {}
    for svc in services:
        cid = run(compose("ps", "-q", svc)).out.strip().split("\n")[0]
        if not cid:
            continue
        img = run(["docker", "inspect", "--format", "{{.Image}}", cid]).out.strip()
        if img and run(["docker", "tag", img, f"{PROJECT}/{svc}:rollback"]).ok:
            points[svc] = img
    return points


def update(auto: bool = False) -> int:
    if auto and os.environ.get("SQUAD_PROD_AUTOUPDATE", "1") == "0":
        print("atualização automática do produtivo desligada (SQUAD_PROD_AUTOUPDATE=0)")
        return 0
    t0 = time.time()
    rows = te.read_log()
    delivered = next((e["id"] for e in reversed(rows) if e.get("type") == "delivered"), None)
    head, frm, services = None, None, []
    with te.lock(LOCK_FILE) as got:
        if not got:
            print("outra atualização do produtivo em andamento (lock)", file=sys.stderr)
            return 3
        try:
            head = guard()
            frm = last_deployed(rows) or image_revision()
            if frm and len(frm) >= 7 and (head.startswith(frm) or frm.startswith(head)):
                te.append("prod-updated", "Produtivo já está no commit atual", commit=head, **{"from": frm},
                          services=[], durationSec=0, delivered=delivered)
                print("nada a fazer: produtivo já no commit atual")
                return 0
            if frm:
                diff = git("diff", "--name-status", f"{frm}..{head}")
                if not diff.ok:
                    raise Abort("guard", f"git diff {frm[:12]}..{head[:12]} falhou: {diff.err.strip()[:300]}")
                changes = [(l.split("\t")[0], l.split("\t")[-1]) for l in diff.out.splitlines() if "\t" in l]
                p = plan_paths(changes)
            else:
                p = {"build": list(APP), "restart": [], "compose": False, "migrations": False,
                     "warnings": ["sem baseline nem rótulo de revisão: reconstrói os 5 serviços (rode prod.py baseline)"]}
            recreate = compose_changed_services(frm) if (p["compose"] and frm) else []
            targets = sorted(set(p["build"]) | set(recreate))
            restarts = [s for s in p["restart"] if s not in targets]
            services = sorted(set(targets) | set(restarts))
            if not services:
                te.append("prod-updated", "Produtivo atualizado: nada a reiniciar", commit=head, **{"from": frm},
                          services=[], durationSec=round(time.time() - t0), delivered=delivered,
                          detail="; ".join(p["warnings"]) or None)
                print("nada a reiniciar (docs/tools/tests/squad-control)")
                return 0
            points = rollback_points(p["build"])
            if p["build"]:
                r = run(compose("build", "--build-arg", f"REVISION={head}", *p["build"]), timeout=1800)
                if not r.ok:
                    raise Abort("build", (r.err or r.out)[-1500:])
            if targets:
                r = run(compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", str(UP_WAIT), *targets),
                        timeout=UP_WAIT + 120)
                if not r.ok:
                    rolled = False
                    if not p["migrations"] and points:
                        for svc in points:
                            run(["docker", "tag", f"{PROJECT}/{svc}:rollback", f"{PROJECT}/{svc}:local"])
                        rr = run(compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", str(UP_WAIT),
                                         *sorted(points)), timeout=UP_WAIT + 120)
                        rolled = rr.ok
                    detail = (r.err or r.out)[-1200:]
                    if p["migrations"]:
                        detail = ("migração Flyway nova no diff: sem rollback automático (o banco pode já ter migrado); "
                                  "decisão do humano (B5). ") + detail
                    te.append("prod-update-failed", f"Falha ao atualizar o produtivo ({'revertido' if rolled else 'sem rollback'})",
                              commit=head, **{"from": frm}, services=services, phase="health", rolledBack=rolled,
                              detail=detail[:1500], delivered=delivered)
                    return 1
            for svc in restarts:
                r = run(compose("restart", svc), timeout=180)
                if not r.ok:
                    raise Abort("up", f"restart {svc}: {(r.err or r.out).strip()[:500]}")
            te.append("prod-updated", f"Produtivo atualizado: {', '.join(services)}", commit=head, **{"from": frm},
                      services=services, durationSec=round(time.time() - t0), delivered=delivered,
                      detail="; ".join(p["warnings"]) or None)
            print(f"produtivo atualizado: {', '.join(services)}")
            return 0
        except Abort as e:
            te.append("prod-update-failed", f"Falha ao atualizar o produtivo ({e.phase})", commit=head,
                      **{"from": frm}, services=services, phase=e.phase, rolledBack=False, detail=str(e)[:1500],
                      delivered=delivered)
            print(f"falhou ({e.phase}): {e}", file=sys.stderr)
            return 1


def baseline() -> int:
    """R2: marca HEAD como implantado sem tocar containers (nenhum comando docker que altere algo)."""
    with te.lock(LOCK_FILE) as got:
        if not got:
            print("outra atualização do produtivo em andamento (lock)", file=sys.stderr)
            return 3
        try:
            head = guard()
        except Abort as e:
            print(f"baseline recusado: {e}", file=sys.stderr)
            return 1
        te.append("prod-updated", f"Baseline do produtivo em {head[:12]} (sem tocar containers)", commit=head,
                  services=[], durationSec=0, baseline=True)
        print(f"baseline registrado: {head}")
        return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("update")
    s.add_argument("--auto", action="store_true")
    sub.add_parser("baseline")
    s = sub.add_parser("plan")
    s.add_argument("--from", dest="frm")
    a = p.parse_args(argv)
    if a.cmd == "update":
        return update(auto=a.auto)
    if a.cmd == "baseline":
        return baseline()
    frm = a.frm or last_deployed(te.read_log())
    if not frm:
        print(json.dumps({"from": None, "build": APP, "note": "sem baseline"}, ensure_ascii=False))
        return 0
    diff = git("diff", "--name-status", f"{frm}..HEAD")
    changes = [(l.split("\t")[0], l.split("\t")[-1]) for l in diff.out.splitlines() if "\t" in l]
    print(json.dumps({"from": frm, **plan_paths(changes)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
