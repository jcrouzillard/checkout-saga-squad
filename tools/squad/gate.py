#!/usr/bin/env python3
"""Verificação e registro de gates pelo CHAMADOR (D26, ADR-027 §2.8; contrato executor-e-modelo-por-agente §7.3/§7.4).

  python3 tools/squad/gate.py verify --gate G2 --demand <id> [--worktree <dir>] [--json]
  python3 tools/squad/gate.py record --demand <id> --from-output <arquivo> [--run <id>] [--model <id>]
                                     [--worktree <dir>] [--delegation <id>]

- `verify` roda SÓ a lista fixa de `tools/squad/gate_checks.json` (nem o Auditor nem o prompt acrescentam comandos;
  placeholders só com valores validados; `subprocess` com lista, nunca shell). Grava
  `<runs_dir>/verify-<G>-<demanda>-<ciclo>.json` e um evento `evidence` (`verify:<id>=<status>`).
- `record` extrai o ÚLTIMO bloco ```parecer da saída do Auditor, valida o esquema, mascara o texto (evidence_rules),
  grava `docs/squad/gates/<G>-<código>[-<ciclo>].json` (no worktree) e o evento `gate` (`--agent auditor`).
  Recusa (nada gravado; `progress` "parecer inválido"/"parecer incoerente com a verificação") um bloco ausente/
  inválido ou um `pass` num critério cuja verificação deu `fail` ou está ausente com o caso aplicável.
Códigos: 0 ok · 2 parecer inválido/incoerente ou argumentos · 4 lista de verificações ilegível.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import product  # noqa: E402
import executores as ex  # noqa: E402

CHECKS_FILE = HERE / "gate_checks.json"
GATES = ("G1", "G2", "G3")
STATUSES = ("pass", "fail", "validate")
DEMAND_RE = re.compile(r"^[0-9a-f]{12}$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
TEST_CMD_RES = [
    re.compile(r"mvn -q -pl services/([a-z][a-z0-9-]*) test -Dtest=([A-Za-z_][A-Za-z0-9_]*(?:#[A-Za-z_][A-Za-z0-9_]*)?)"),
    re.compile(r"python3 -m pytest -q (tests/[A-Za-z0-9_/.-]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*)?)"),
]
PARECER_RE = re.compile(r"```parecer\s*\n(.*?)\n```", re.S)
TAIL_LINES = 40


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_checks() -> list[dict]:
    try:
        data = json.loads(CHECKS_FILE.read_text(encoding="utf-8"))
        assert data.get("schema") == 1 and isinstance(data.get("checks"), list)
        return data["checks"]
    except (OSError, json.JSONDecodeError, AssertionError) as e:
        print(f"gate.py: {CHECKS_FILE} ilegível ({e})", file=sys.stderr)
        sys.exit(4)


def gates_of(check: dict) -> list[str]:
    g = check.get("gate")
    return g if isinstance(g, list) else [g]


def _mask(text: str, data_root: pathlib.Path) -> str:
    try:
        import evidence_rules as er
        return er.mask_text(text or "", er.load_key(data_root))[0]
    except Exception:
        try:
            import transcripts as tr
            return tr.mask(text or "")
        except Exception:
            return text or ""


def _git(args, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)


def changed_files(wt: pathlib.Path) -> list[str] | None:
    for base in ("origin/develop", "develop"):
        p = _git(["diff", "--name-only", f"{base}...HEAD"], wt)
        if p.returncode == 0:
            return [l.strip() for l in p.stdout.splitlines() if l.strip()]
    return None


def applies(when: str, files: list[str] | None, demand_row: dict | None) -> bool | None:
    """None = não foi possível decidir (sem diff)."""
    if when == "bug":
        return (demand_row or {}).get("nature") == "bug"
    if files is None:
        return None
    if when == "backend":
        return any(f.startswith("services/") or f == "pom.xml" for f in files)
    if when == "devops":
        return any(f == "docker-compose.yml" or f.startswith(("Dockerfile", "infra/")) or "/Dockerfile" in f
                   for f in files)
    return False


def repro_event(rows: list[dict], demand: str) -> dict | None:
    """Último evento `evidence` do QA com `reproducao=FAIL` da demanda (ADR-019)."""
    out = None
    for e in rows:
        if (e.get("type") == "evidence" and e.get("demand") == demand and e.get("agent") == "qa"
                and any(str(v.get("name", "")).lower().startswith("reproducao") and str(v.get("status", "")).upper() == "FAIL"
                        for v in e.get("evidences") or [])):
            out = e
    return out


def test_cmd_from(event: dict) -> list[str] | None:
    text = " ".join(str(event.get(k) or "") for k in ("title", "detail")) + " " + " ".join(event.get("refs") or [])
    m = TEST_CMD_RES[0].search(text)
    if m:
        return ["mvn", "-q", "-pl", f"services/{m.group(1)}", "test", f"-Dtest={m.group(2)}"]
    m = TEST_CMD_RES[1].search(text)
    if m and ".." not in m.group(1):
        return ["python3", "-m", "pytest", "-q", m.group(1)]
    return None


def cycle_of(rows: list[dict], gate: str, demand: str) -> int:
    return 1 + sum(1 for e in rows if e.get("type") == "gate" and e.get("gate") == gate and e.get("demand") == demand)


def _run(cmd: list[str], cwd: pathlib.Path, timeout: int) -> tuple[str, int | None, str, int]:
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return "done", p.returncode, (p.stdout or "") + (p.stderr or ""), round((time.monotonic() - t0) * 1000)
    except FileNotFoundError:
        return "erro", None, f"ferramenta ausente: {cmd[0]}", round((time.monotonic() - t0) * 1000)
    except subprocess.TimeoutExpired:
        return "erro", None, f"timeout ({timeout}s)", round((time.monotonic() - t0) * 1000)


def _status(expect: str, code: int | None, out: str) -> str:
    if code is None:
        return "erro"
    if expect == "exit0":
        return "pass" if code == 0 else "fail"
    if expect == "fail":
        return "pass" if code != 0 else "fail"
    if expect == "healthcheck-todos":
        if code != 0:
            return "fail"
        try:
            services = json.loads(out[out.index("{"):]).get("services") or {}
        except (ValueError, json.JSONDecodeError, AttributeError):
            return "erro"
        return "pass" if services and all((s or {}).get("healthcheck") for s in services.values()) else "fail"
    return "erro"


def verify(gate: str, demand: str, worktree: pathlib.Path, ctx: "ex.Ctx") -> dict:
    rows = ex.read_rows(ctx)
    demand_row = next((e for e in rows if e.get("id") == demand and e.get("type") == "task"), None)
    files = changed_files(worktree)
    head = _git(["rev-parse", "HEAD"], worktree).stdout.strip() or None
    results = []
    for c in [c for c in load_checks() if gate in gates_of(c)]:
        item = {"id": c["id"], "criterion": c.get("criterion"), "status": "n/a", "exit": None, "durationMs": 0,
                "tail": ""}
        ok = applies(c.get("when"), files, demand_row)
        if ok is False:
            results.append(item)
            continue
        if ok is None:
            item.update(status="erro", tail="diff da demanda indisponível (origin/develop...HEAD)")
            results.append(item)
            continue
        cmd, cwd, tmp = c["cmd"], worktree, None
        rep = None
        if "{testCmd}" in json.dumps(cmd) or "{testCommit}" in str(c.get("cwd")):
            rep = repro_event(rows, demand)
            if rep is None:
                item.update(status="erro", tail="sem evento `evidence reproducao=FAIL` do QA")
                results.append(item)
                continue
        if cmd == "{testCmd}":
            cmd = test_cmd_from(rep)
            if cmd is None:
                item.update(status="erro", tail="alvo do teste não reconhecido (validate)")
                results.append(item)
                continue
        cmd = [str(x).replace("{demand}", demand) for x in cmd]
        cwd_spec = str(c.get("cwd") or "worktree")
        try:
            if cwd_spec.startswith("tmp-worktree:"):
                sha = (rep or {}).get("sha") or ""
                if not SHA_RE.match(sha) or _git(["cat-file", "-e", f"{sha}^{{commit}}"], worktree).returncode != 0:
                    item.update(status="erro", tail="commit do teste ausente ou inválido no evento de reprodução")
                    results.append(item)
                    continue
                tmp = ctx.runtime_dir / "verify" / f"{gate}-{demand}"
                if tmp.exists():
                    _git(["worktree", "remove", "--force", str(tmp)], worktree)
                tmp.parent.mkdir(parents=True, exist_ok=True)
                p = _git(["worktree", "add", "--detach", str(tmp), sha], worktree)
                if p.returncode != 0:
                    item.update(status="erro", tail=p.stderr[-500:])
                    results.append(item)
                    continue
                cwd = tmp
            state, code, out, ms = _run(cmd, cwd, int(c.get("timeoutS") or 900))
        finally:
            if tmp is not None:
                _git(["worktree", "remove", "--force", str(tmp)], worktree)
        tail = "\n".join(out.strip().splitlines()[-TAIL_LINES:])
        item.update(status="erro" if state == "erro" else _status(c.get("expect"), code, out), exit=code,
                    durationMs=ms, tail=_mask(tail, ctx.product.data_root))
        results.append(item)
    cycle = cycle_of(rows, gate, demand)
    out = {"gate": gate, "demand": demand, "commit": head, "cycle": cycle, "at": now_iso(), "checks": results}
    runs = ctx.product.runs_dir
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"verify-{gate}-{demand}-{cycle}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    out["file"] = str(path)
    applicable = [r for r in results if r["status"] != "n/a"]
    args = [sys.executable, str(HERE / "log.py"), "--agent", "orquestrador", "--type", "evidence", "--demand", demand,
            "--title", f"Verificação {gate} (gate.py verify): "
                       + (", ".join(f"{r['id']}={r['status']}" for r in applicable) or "nenhuma aplicável"),
            "--ref", str(path)]
    for r in results:
        args += ["--evidence", f"verify:{r['id']}={r['status']}"]
    subprocess.run(args, capture_output=True, env={**os.environ, "SQUAD_LOG": str(ctx.log)})
    return out


# ============================================================== record
def parse_parecer(text: str) -> tuple[dict | None, str]:
    blocks = PARECER_RE.findall(text or "")
    if not blocks:
        return None, "bloco ```parecer ausente"
    try:
        p = json.loads(blocks[-1])
    except json.JSONDecodeError as e:
        return None, f"JSON inválido no bloco parecer ({e.msg})"
    if not isinstance(p, dict):
        return None, "parecer deve ser um objeto"
    if p.get("gate") not in GATES:
        return None, "gate deve ser G1|G2|G3"
    if p.get("recommendation") not in ("APPROVE", "RETURN"):
        return None, "recommendation deve ser APPROVE|RETURN"
    conf = p.get("confidence")
    if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        return None, "confidence deve estar entre 0 e 1"
    if p.get("risk") not in ("baixo", "moderado", "alto"):
        return None, "risk deve ser baixo|moderado|alto"
    evs = p.get("evidences")
    if not isinstance(evs, list) or not evs or any(
            not isinstance(e, dict) or not e.get("name") or e.get("status") not in STATUSES for e in evs):
        return None, "evidences deve ser lista de {name, status: pass|fail|validate}"
    return p, ""


def latest_verify(runs_dir: pathlib.Path, gate: str, demand: str) -> dict | None:
    files = sorted(runs_dir.glob(f"verify-{gate}-{demand}-*.json"), key=lambda f: f.stat().st_mtime)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _check_id(e: dict, known: dict) -> str | None:
    cid = e.get("check")
    if not cid:
        m = re.search(r"verify:([a-z0-9-]+)", str(e.get("name")) + " " + str(e.get("source") or ""))
        cid = m.group(1) if m else None
    if not cid:
        name = _norm(e.get("name"))
        cid = next((k for k, c in known.items() if _norm(c.get("criterion")) and _norm(c["criterion"]) in name), None)
    return cid if cid in known else None


def incoherent(parecer: dict, ver: dict | None, applicable_ids: set) -> list[str]:
    """(a) `pass` num critério cuja verificação deu fail/erro ou está ausente (com o caso aplicável);
    (b) G2-D26: APPROVE com uma verificação aplicável em fail/erro que NENHUMA evidência não-pass registra —
    pega o `pass` de nome livre que não foi ligado à verificação (a verificação manda, não o texto do parecer)."""
    checks = {c["id"]: c for c in (ver or {}).get("checks") or []}
    known = {c["id"]: c for c in load_checks()}
    gate = parecer.get("gate")
    bad, acknowledged = [], set()
    for e in parecer.get("evidences") or []:
        cid = _check_id(e, known)
        if not cid or gate not in gates_of(known[cid]):
            continue
        if e.get("status") != "pass":
            acknowledged.add(cid)
            continue
        st = (checks.get(cid) or {}).get("status")
        if st in ("fail", "erro"):
            bad.append(f"{cid}: verificação {st}")
        elif st is None and cid in applicable_ids:
            bad.append(f"{cid}: verificação não executada")
    if parecer.get("recommendation") == "APPROVE":
        for cid, c in checks.items():
            if (c.get("status") in ("fail", "erro") and cid in known and gate in gates_of(known[cid])
                    and cid not in acknowledged and not any(b.startswith(cid + ":") for b in bad)):
                bad.append(f"{cid}: verificação {c['status']} sem evidência que a registre (APPROVE)")
    return bad


def _progress(ctx, demand, title, run=None, detail=""):
    args = [sys.executable, str(HERE / "log.py"), "--agent", "auditor", "--type", "progress", "--title", title]
    if demand:
        args += ["--demand", demand]
    if run:
        args += ["--run", run]
    if detail:
        args += ["--detail", detail[:1500]]
    subprocess.run(args, capture_output=True, env={**os.environ, "SQUAD_LOG": str(ctx.log)})


def record(a, ctx: "ex.Ctx") -> int:
    text = pathlib.Path(a.from_output).read_text(encoding="utf-8", errors="ignore")
    parecer, why = parse_parecer(text)
    if parecer is None:
        _progress(ctx, a.demand, "parecer inválido", a.run, why)
        print(f"gate.py: parecer inválido: {why}", file=sys.stderr)
        return 2
    gate = parecer["gate"]
    wt = pathlib.Path(a.worktree).resolve() if a.worktree else ROOT
    rows = ex.read_rows(ctx)
    if a.demand:
        ver = latest_verify(ctx.product.runs_dir, gate, a.demand)
        demand_row = next((e for e in rows if e.get("id") == a.demand and e.get("type") == "task"), None)
        files = changed_files(wt)
        applicable = {c["id"] for c in load_checks() if gate in gates_of(c)
                      and applies(c.get("when"), files, demand_row)}
        bad = incoherent(parecer, ver, applicable)
        if bad:
            _progress(ctx, a.demand, "parecer incoerente com a verificação", a.run, "; ".join(bad))
            print("gate.py: parecer incoerente com a verificação: " + "; ".join(bad), file=sys.stderr)
            return 2
    key = ex.product.demand_codes(rows, ctx.product).get(a.demand) if a.demand else None
    cycle = cycle_of(rows, gate, a.demand) if a.demand else 1
    name = f"{gate}-{key or (a.demand or 'sem-demanda')}" + (f"-{cycle}" if cycle > 1 else "") + ".json"
    masked = json.loads(_mask(json.dumps(parecer, ensure_ascii=False), ctx.product.data_root))
    masked.update({"demand": a.demand, "cycle": cycle, "recordedBy": "gate.py", "run": a.run, "model": a.model})
    masked = {k: v for k, v in masked.items() if v is not None}
    gates_dir = wt / "docs/squad/gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    path = gates_dir / name
    path.write_text(json.dumps(masked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    title = (f"{gate}{'-' + key if key else ''} {parecer['recommendation']}: "
             + str(masked.get("rationale") or masked.get("title") or "parecer do Auditor"))[:200]
    args = [sys.executable, str(HERE / "log.py"), "--agent", "auditor", "--type", "gate", "--gate", gate,
            "--recommendation", parecer["recommendation"], "--confidence", str(parecer["confidence"]),
            "--risk", parecer["risk"], "--title", title, "--ref", str(path.relative_to(wt) if path.is_relative_to(wt) else path),
            "--detail", str(masked.get("rationale") or "")[:1500]]
    if parecer.get("to") in ex.ROLES + ["humano"]:
        args += ["--to", parecer["to"]]
    if a.demand:
        args += ["--demand", a.demand]
    if a.run:
        args += ["--run", a.run]
    if a.model:
        args += ["--model", a.model]
    if a.delegation:
        args += ["--delegation", a.delegation]
    for e in masked.get("evidences") or []:
        args += ["--evidence", f"{str(e['name'])[:120]}={e['status']}"]
    p = subprocess.run(args, capture_output=True, text=True, env={**os.environ, "SQUAD_LOG": str(ctx.log)})
    if p.returncode != 0:
        print(f"gate.py: log.py falhou: {p.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"{path}\n{p.stdout.strip()}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--gate", required=True, choices=GATES)
    v.add_argument("--demand", required=True)
    v.add_argument("--worktree")
    v.add_argument("--json", action="store_true")
    r = sub.add_parser("record")
    r.add_argument("--demand")
    r.add_argument("--from-output", required=True)
    r.add_argument("--run")
    r.add_argument("--model")
    r.add_argument("--worktree")
    r.add_argument("--delegation")
    a = ap.parse_args(argv)
    if getattr(a, "demand", None) and not DEMAND_RE.match(a.demand):
        print("gate.py: --demand deve ser um id de 12 hex", file=sys.stderr)
        return 2
    try:
        ctx = ex.context()
    except product.ProductError as e:
        print(f"gate.py: {e}", file=sys.stderr)
        return 4
    if a.cmd == "verify":
        wt = pathlib.Path(a.worktree).resolve() if a.worktree else ROOT
        out = verify(a.gate, a.demand, wt, ctx)
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            for c in out["checks"]:
                print(f"{c['id']:<24} {c['status']:<5} {c['criterion']}")
        return 0
    return record(a, ctx)


if __name__ == "__main__":
    sys.exit(main())
