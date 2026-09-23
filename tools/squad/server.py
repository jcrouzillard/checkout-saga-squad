#!/usr/bin/env python3
"""Servidor do painel Squad Control (somente stdlib).

- Serve `squad-control/index.html` (painel genérico da squad; o produto gerenciado vem de docs/squad/project.json).
- GET  /api/state  -> log de decisões + pareceres do Auditor + atividade ao vivo de cada agente
                      (lida das transcrições dos subagentes do Claude Code).
- POST /api/human  -> registra a decisão humana (aceitar/devolver) no log compartilhado;
                      o Orquestrador lê esse evento antes de avançar o gate.

Uso: python3 tools/squad/server.py [--port 7070]   (ou $SQUAD_PORT)
Transcrições: $SQUAD_TRANSCRIPTS ou ~/.claude/projects/<repo-slug>/*/subagents/*.jsonl
Dados (log, gates, handoffs, .squad/runs): $SQUAD_ROOT_DATA (padrão: raiz deste repositório); log: $SQUAD_LOG.
Modelo por agente (D9, ADR-012): runs[] e log[] trazem model/modelProvider (e modelSource nos eventos).
"""
import shlex
import argparse
import json
import os
import pathlib
import re
import time
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


ROOT = pathlib.Path(__file__).resolve().parents[2]
# Dados podem vir de outra cópia do repositório (ex.: validar um worktree com o log/runs da cópia principal).
DATA_ROOT = pathlib.Path(os.environ.get("SQUAD_ROOT_DATA") or ROOT).resolve()
LOG = pathlib.Path(os.environ.get("SQUAD_LOG") or DATA_ROOT / "docs/squad/memory/decisions.jsonl")
GATES_DIR = DATA_ROOT / "docs/squad/gates"
HANDOFFS_DIR = DATA_ROOT / "docs/squad/memory/handoffs"
RUNS_DIR = DATA_ROOT / ".squad/runs"
UI_DIR = ROOT / "squad-control"

AGENT_ALIASES = {
    "arquiteto": "arquiteto", "backend": "backend", "devops": "devops",
    "observabilidade": "observabilidade", "qa": "qa", "auditor": "auditor",
    "frontend": "frontend",
    "jev": "auditor",  # nome antigo do gatekeeper nas transcrições já gravadas
}
RUNNING_WINDOW_S = 45


def transcripts_root() -> pathlib.Path:
    env = os.environ.get("SQUAD_TRANSCRIPTS")
    if env:
        return pathlib.Path(env)
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(DATA_ROOT))
    return pathlib.Path.home() / ".claude/projects" / slug


# ---------- Modelo por agente (D9, ADR-012, docs/contracts/ui-modelo-por-agente.md) ----------
ANTHROPIC, OPENAI = "Anthropic", "OpenAI"
PROVIDER_HINTS = {"anthropic": ANTHROPIC, "openai": OPENAI}
RUNNER_PROVIDER = {"claude": ANTHROPIC, "codex": OPENAI}


def normalize_model(model_id: str) -> str:
    m = re.sub(r"\[.*?\]$", "", (model_id or "").strip().lower())
    return re.sub(r"^(us|eu|apac|global)\.", "", m)


def provider_of(model_id: str | None, hint: str | None = None, runner: str | None = None) -> str | None:
    """Fornecedor de um ID de modelo: hint do runtime > prefixo do ID > runner. None = desconhecido."""
    if hint:
        return PROVIDER_HINTS.get(hint.strip().lower(), hint.strip())
    m = normalize_model(model_id or "")
    if m.startswith(("claude-", "anthropic.")):
        return ANTHROPIC
    if m.startswith(("gpt-", "o1", "o3", "o4", "codex-", "openai/")):
        return OPENAI
    return RUNNER_PROVIDER.get(runner or "")


def is_model_id(model: str | None) -> bool:
    return bool(model) and model != "<synthetic>" and not model.startswith("<")


def codex_header(text: str) -> dict:
    """model/provider do cabeçalho do `codex exec`: só o 1º bloco entre linhas `--------` (o resto é prompt/saída)."""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "--------")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "--------")
    except StopIteration:
        return {}
    out = {}
    for l in lines[start + 1:end]:
        k, sep, v = l.partition(":")
        if sep and k.strip() in ("model", "provider") and v.strip():
            out[k.strip()] = v.strip()
    return out


LOGPY_TITLE = re.compile(r"""--title[ =](?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))""")
LOGPY_AGENT = re.compile(r"--agent[ =]['\"]?([\w-]+)")


def logpy_calls(command: str) -> list[tuple[str, str]]:
    """(agent, title) de cada chamada a log.py dentro de um comando Bash (tolera aspas/escapes do shell).
    Cada chamada tem um único --agent; cortar nele cobre também `python3 "$L" --agent ...`."""
    out = []
    if "log.py" not in command:
        return out
    for chunk in re.split(r"(?=--agent[ =])", command)[1:]:
        agent = title = None
        try:
            toks = shlex.split(chunk.split("\n")[0] if "<<" in chunk else chunk)
            for i, t in enumerate(toks[:-1]):
                if t == "--agent" and agent is None:
                    agent = toks[i + 1]
                elif t == "--title" and title is None:
                    title = toks[i + 1]
                elif t.startswith("--agent=") and agent is None:
                    agent = t.split("=", 1)[1]
                elif t.startswith("--title=") and title is None:
                    title = t.split("=", 1)[1]
        except ValueError:
            pass
        if agent is None and (m := LOGPY_AGENT.search(chunk)):
            agent = m.group(1)
        if title is None and (m := LOGPY_TITLE.search(chunk)):
            title = next(g for g in m.groups() if g is not None).replace('\\"', '"')
        if agent and title:
            out.append((agent, title))
    return out


_scan_cache: dict[str, tuple[float, dict]] = {}


def scan_transcript(path: pathlib.Path) -> dict:
    """Modelos (message.model, sem <synthetic>), 1º prompt e chamadas a log.py de uma transcrição.
    Cache por (arquivo, mtime): o /api/state é consultado a cada poll."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"models": {}, "first_prompt": "", "calls": []}
    cached = _scan_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    models: dict[str, int] = {}
    first_prompt, calls = "", []
    for r in read_jsonl(path):
        msg = r.get("message") or {}
        content = msg.get("content")
        if r.get("type") == "user" and not first_prompt:
            if isinstance(content, str):
                first_prompt = content
            elif isinstance(content, list):
                first_prompt = next((c.get("text", "") for c in content if c.get("type") == "text"), "")
        if r.get("type") != "assistant":
            continue
        model = msg.get("model")
        if not is_model_id(model):
            continue
        models[model] = models.get(model, 0) + 1  # dict preserva a ordem do 1º uso
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_use" and c.get("name") == "Bash":
                cmd = (c.get("input") or {}).get("command", "")
                if "log.py" in cmd:
                    for agent, title in logpy_calls(cmd):
                        calls.append({"ts": r.get("timestamp"), "agent": agent, "title": title, "model": model})
    info = {"models": models, "first_prompt": first_prompt, "calls": calls}
    _scan_cache[str(path)] = (mtime, info)
    return info


def model_fields(models: dict[str, int], hint: str | None = None, runner: str | None = None) -> dict:
    """model = o mais usado (empate: o 1º usado); models = IDs distintos em ordem de 1º uso."""
    ids = list(models)
    model = max(ids, key=lambda m: models[m]) if ids else None
    return {"model": model, "models": ids, "modelProvider": provider_of(model, hint, runner) if model else None}


DEMAND_RE = re.compile(r"--demand[ =]['\"]?([0-9a-f]{12})\b")


def first_demand(text: str) -> str | None:
    m = DEMAND_RE.search(text or "")
    return m.group(1) if m else None


def read_jsonl(path: pathlib.Path) -> list[dict]:
    out = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return out


def rel(p: str) -> str:
    try:
        return str(pathlib.Path(p).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return p


def summarize_tool(name: str, inp: dict) -> str:
    if name in ("Write", "Edit", "Read", "NotebookEdit"):
        return rel(inp.get("file_path", ""))
    if name == "Bash":
        return inp.get("description") or inp.get("command", "")[:140]
    if name in ("Grep", "Glob"):
        return inp.get("pattern", "")
    if name == "Agent":
        return inp.get("description", "")
    return ", ".join(f"{k}={str(v)[:40]}" for k, v in list(inp.items())[:2])


def resolve_agent(meta: dict, first_prompt: str) -> str:
    desc = (meta.get("description") or "").lower()
    head = desc.split(":")[0].strip()
    for key, name in AGENT_ALIASES.items():
        if head.startswith(key):
            return name
    m = re.search(r"\*\*(?:agente\s+)?([a-zà-ú]+)", first_prompt.lower())
    if m:
        for key, name in AGENT_ALIASES.items():
            if m.group(1).startswith(key[:4]):
                return name
    return "outro"


HEREDOC_WRITE = re.compile(r"(?:cat|tee)\s*>{1,2}\s*['\"]?([\w./-]+\.\w+)")
_completed_cache: dict[str, tuple[float, set[str]]] = {}


def completed_agent_ids(base: pathlib.Path) -> set[str]:
    """IDs de subagentes cuja notificação de término já chegou à sessão do Orquestrador."""
    done: set[str] = set()
    for main in base.glob("*.jsonl"):
        mtime = main.stat().st_mtime
        cached = _completed_cache.get(str(main))
        if cached and cached[0] == mtime:
            done |= cached[1]
            continue
        text = main.read_text(encoding="utf-8", errors="ignore")
        ids = set(re.findall(r"<task-id>(\w+)</task-id>\\n<tool-use-id>[^<]*</tool-use-id>\\n<output-file>[^<]*</output-file>\\n<status>completed</status>", text))
        _completed_cache[str(main)] = (mtime, ids)
        done |= ids
    return done


def parse_run(path: pathlib.Path, agent: str | None = None, delegations_only=False,
              completed: set[str] | None = None) -> dict | None:
    rows = read_jsonl(path)
    if not rows:
        return None
    meta_path = path.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    first_prompt = ""
    activity, files, tool_count = [], [], 0
    pending: dict[str, dict] = {}
    for r in rows:
        msg = r.get("message") or {}
        content = msg.get("content")
        ts = r.get("timestamp")
        if r.get("type") == "user" and isinstance(content, str) and not first_prompt:
            first_prompt = content
        if not isinstance(content, list):
            continue
        for c in content:
            t = c.get("type")
            if r.get("type") == "assistant" and t == "tool_use":
                name, inp = c.get("name", ""), c.get("input") or {}
                if delegations_only and name != "Agent":
                    continue
                tool_count += 1
                item = {"ts": ts, "kind": "tool", "tool": name, "summary": summarize_tool(name, inp), "pending": True,
                        "detail": (inp.get("command") or inp.get("old_string") or inp.get("pattern") or "")[:400]
                        if name in ("Bash", "Edit", "Grep", "Glob") else ""}
                written = [rel(inp.get("file_path", ""))] if name in ("Write", "Edit") else []
                if name == "Bash":
                    written = [w for w in HEREDOC_WRITE.findall(inp.get("command", "")) if not w.startswith("/dev/")]
                for f in written:
                    if f not in files:
                        files.append(f)
                pending[c.get("id")] = item
                activity.append(item)
            elif r.get("type") == "assistant" and t == "text" and not delegations_only:
                text = (c.get("text") or "").strip()
                if text:
                    activity.append({"ts": ts, "kind": "text", "summary": text[:600]})
            elif r.get("type") == "user" and t == "tool_result":
                item = pending.pop(c.get("tool_use_id"), None)
                if item:
                    item["pending"] = False
                    item["endedAt"] = ts
                    if c.get("is_error"):
                        item["error"] = True
    updated = path.stat().st_mtime
    meaningful = [r for r in rows if r.get("type") in ("assistant", "user")]
    last = meaningful[-1] if meaningful else rows[-1]
    last_content = (last.get("message") or {}).get("content")
    ended_turn = last.get("type") == "assistant" and isinstance(last_content, list) and all(
        x.get("type") != "tool_use" for x in last_content)
    recent = (time.time() - updated) < RUNNING_WINDOW_S
    run_id = path.stem.replace("agent-", "")
    scan = scan_transcript(path)
    current = next((a for a in reversed(activity) if a["kind"] == "tool" and a.get("pending")), None)
    if delegations_only:
        status = "coordenando"
    elif ended_turn and ((completed is not None and run_id in completed) or (time.time() - updated) > 90):
        status = "concluído"
    elif recent or not ended_turn or current:
        status = "trabalhando"
    else:
        status = "trabalhando" if (time.time() - updated) < 900 else "parado"
    return {
        "id": path.stem.replace("agent-", ""),
        "agent": agent or resolve_agent(meta, first_prompt),
        "description": meta.get("description", ""),
        **model_fields(scan["models"], hint="anthropic" if scan["models"] else None),
        "demand": meta.get("demand") or (None if delegations_only else first_demand(first_prompt)),
        "status": status,
        "started": rows[0].get("timestamp"),
        "updated": datetime.fromtimestamp(updated, timezone.utc).isoformat(timespec="seconds"),
        "toolCount": tool_count,
        "current": current if status == "trabalhando" else None,
        "files": files,
        "activity": activity[-80:],
    }


def collect_runs() -> list[dict]:
    base = transcripts_root()
    runs = []
    completed = completed_agent_ids(base)
    for path in sorted(base.glob("*/subagents/agent-*.jsonl")):
        run = parse_run(path, completed=completed)
        if run:
            runs.append(run)
    runs.extend(collect_external_runs())
    # Sessão principal = Orquestrador (apenas delegações)
    for path in sorted(base.glob("*.jsonl")):
        if (base / path.stem / "subagents").exists():
            run = parse_run(path, agent="orquestrador", delegations_only=True)
            if run and run["toolCount"]:
                runs.append(run)
    return runs


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def collect_external_runs() -> list[dict]:
    """Execuções disparadas por tools/squad/run_agent.py (qualquer fornecedor): metadados + saída ao vivo + progress."""
    runs_dir = RUNS_DIR
    top_level = None  # run_id -> transcrição de topo do `claude -p` (runs antigos, sem sessionId)
    progress = [e for e in read_jsonl(LOG) if e.get("type") == "progress" and e.get("run")]
    out = []
    for meta_path in sorted(runs_dir.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        log_path = meta_path.with_suffix(".log")
        status = meta.get("status", "trabalhando")
        if status == "trabalhando" and not pid_alive(meta.get("pid")):
            status = "interrompido"
        activity = [{"ts": e["ts"], "kind": "tool", "tool": "progress", "summary": e["title"], "pending": False,
                     "detail": e.get("detail", "")} for e in progress if e["run"] == meta["id"]]
        mtime = log_path.stat().st_mtime if log_path.exists() else meta_path.stat().st_mtime
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-40:] if log_path.exists() else []
        if lines:
            activity.append({"ts": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                             "kind": "text", "summary": "\n".join(l for l in lines if l.strip())[-600:]})
        current = None
        if status == "trabalhando":
            last = next((a for a in reversed(activity) if a["kind"] == "tool"), None)
            current = {"tool": meta.get("runner", "runner"), "summary": (last or {}).get("summary", "em execução"),
                       "ts": (last or {}).get("ts", meta.get("started"))}
        runner = meta.get("runner")
        models: dict[str, int] = {}
        hint = meta.get("modelProvider")
        if runner == "codex" and log_path.exists():
            # O cabeçalho reflete o que rodou; vale mais que o gravado (que vem dele de todo modo).
            with log_path.open(encoding="utf-8", errors="ignore") as f:
                head = codex_header(f.read(20000))
            if head.get("model"):
                models = {head["model"]: 1}
                hint = head.get("provider") or hint
        elif runner == "claude":
            tpath = None
            if meta.get("sessionId"):
                tpath = transcripts_root() / f"{meta['sessionId']}.jsonl"
            else:
                if top_level is None:
                    top_level = {}
                    for t in transcripts_root().glob("*.jsonl"):
                        m = re.search(r"--run (\S+?-[0-9a-f]{6})\b", scan_transcript(t)["first_prompt"])
                        if m:
                            top_level[m.group(1)] = t
                tpath = top_level.get(meta["id"])
            if tpath and tpath.exists():
                models = dict(scan_transcript(tpath)["models"])
                hint = "anthropic" if models else hint
        if not models and is_model_id(meta.get("model")):
            models = {meta["model"]: 1}
        out.append({"id": meta["id"], "agent": meta.get("agent", "outro"), "description": meta.get("description", ""),
                    **model_fields(models, hint, runner), "modelRequested": meta.get("modelRequested"),
                    "sessionId": meta.get("sessionId"), "demand": meta.get("demand"),
                    "runner": runner, "status": status,
                    "started": meta.get("started"),
                    "updated": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                    "toolCount": len([x for x in activity if x["kind"] == "tool"]), "current": current,
                    "files": [], "activity": activity[-80:]})
    return out


MATCH_WINDOW_S = 120


def _ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def enrich_log(rows: list[dict], runs: list[dict]) -> list[dict]:
    """Acrescenta model/modelProvider/modelSource a cada evento (somente na resposta; o log segue append-only).
    Ordem: gravado no evento > run do evento > chamada a log.py numa transcrição (agente + título, ±120 s) > none."""
    by_run = {r["id"]: r for r in runs if r.get("model")}
    calls: dict[tuple[str, str], list[tuple[float, str]]] = {}
    base = transcripts_root()
    for path in list(base.glob("*.jsonl")) + list(base.glob("*/subagents/agent-*.jsonl")):
        for c in scan_transcript(path)["calls"]:
            t = _ts(c["ts"])
            if t is not None:
                calls.setdefault((c["agent"], c["title"]), []).append((t, c["model"]))
    out = []
    for e in rows:
        e = dict(e)
        if e.get("agent") == "humano":
            e.update({"model": None, "modelProvider": None, "modelSource": "n/a"})
        elif is_model_id(e.get("model")):
            e.update({"modelProvider": provider_of(e["model"], runner=e.get("runner")), "modelSource": "logged"})
        elif e.get("run") in by_run:
            r = by_run[e["run"]]
            e.update({"model": r["model"], "modelProvider": r["modelProvider"], "modelSource": "run"})
        else:
            t = _ts(e.get("ts"))
            cands = [(abs(ct - t), m) for ct, m in calls.get((e.get("agent"), e.get("title")), [])
                     if t is not None and abs(ct - t) <= MATCH_WINDOW_S]
            if cands:
                model = min(cands)[1]
                e.update({"model": model, "modelProvider": provider_of(model, "anthropic"), "modelSource": "transcript"})
            else:
                e.update({"model": None, "modelProvider": None, "modelSource": "none"})
        out.append(e)
    return out


def effective_demand(rows: list[dict], demand: dict) -> dict:
    """task + eventos `edit` aplicados em ordem (D5)."""
    eff = dict(demand)
    for e in sorted((r for r in rows if r.get("type") == "edit" and r.get("demand") == demand["id"]), key=lambda r: r["ts"]):
        for k, v in (e.get("changes") or {}).items():
            eff[k] = f"Demanda: {v}" if k == "title" else v
    return eff


def is_canceled(rows: list[dict], demand_id: str) -> bool:
    return any(r.get("type") == "control" and r.get("action") == "cancel" and r.get("demand") == demand_id for r in rows)


def is_done(rows: list[dict], demand_id: str) -> bool:
    return any(r.get("type") == "gate" and r.get("gate") == "G3" and r.get("recommendation") == "APPROVE"
               and r.get("demand") == demand_id for r in rows)


def in_backlog(rows: list[dict], demand: dict) -> bool:
    return bool(demand.get("backlog")) and not any(
        r.get("demand") == demand["id"] and (r.get("type") == "start" or (r.get("type") == "control" and r.get("action") == "cancel"))
        for r in rows)


def collect_gates() -> list[dict]:
    gates = []
    for p in sorted(GATES_DIR.glob("*.json")):
        try:
            g = json.loads(p.read_text())
            g["file"] = rel(str(p))
            g["mtime"] = p.stat().st_mtime
            gates.append(g)
        except json.JSONDecodeError:
            pass
    return sorted(gates, key=lambda g: g["mtime"])


def github_issues() -> dict:
    """id do evento -> {number, url} das issues criadas pelo github_sync (para links no painel)."""
    st = DATA_ROOT / "docs/squad/memory/github-sync.json"
    try:
        data = json.loads(st.read_text(encoding="utf-8"))
        return {k: {"number": v["number"], "url": v["url"], "closed": v.get("closed", False)}
                for k, v in data.get("issues", {}).items()}
    except (OSError, json.JSONDecodeError):
        return {}


def collect_handoffs() -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(HANDOFFS_DIR.glob("*.md"))}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(UI_DIR), **kw)

    def log_message(self, *_):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            runs = collect_runs()
            return self._json({
                "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "log": enrich_log(read_jsonl(LOG), runs),
                "gates": collect_gates(),
                "runs": runs,
                "handoffs": collect_handoffs(),
                "github": github_issues(),
            })
        if self.path.startswith("/api/project"):
            # Portas locais podem variar (.env do compose): placeholders {{VAR}} são resolvidos aqui.
            pj = ROOT / "docs/squad/project.json"
            raw = pj.read_text(encoding="utf-8") if pj.exists() else '{"current": null, "products": []}'
            env = dict(os.environ)
            dotenv = ROOT / ".env"
            if dotenv.exists():
                for line in dotenv.read_text().splitlines():
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1); env.setdefault(k.strip(), v.strip())
            raw = re.sub(r"\{\{(\w+)\}\}", lambda m: env.get(m.group(1), {"GRAFANA_PORT": "3000", "CONSOLE_PORT": "8090"}.get(m.group(1), "")), raw)
            return self._json(json.loads(raw))
        if self.path.startswith("/api/policy"):
            return self._json({
                "gates": (ROOT / "docs/squad/gates.md").read_text(encoding="utf-8"),
                "constituicao": (ROOT / "CLAUDE.md").read_text(encoding="utf-8"),
            })
        return super().do_GET()

    def _append_log(self, entry: dict) -> dict:
        entry = {"id": uuid.uuid4().hex[:12], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
        entry = {k: v for k, v in entry.items() if v not in (None, "")}
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/api/demand/clarify"):
            data = json.loads(raw or b"{}")
            rows = read_jsonl(LOG)
            demand = next((e for e in rows if e.get("id") == data.get("id") and e.get("type") == "task"), None)
            val = next((e for e in rows if e.get("id") == data.get("validation") and e.get("type") == "validation"
                        and e.get("demand") == data.get("id")), None)  # a validação precisa ser desta demanda
            if not demand or not val:
                return self._json({"error": "demanda ou validação não encontrada"}, 404)
            if is_canceled(rows, demand["id"]):
                return self._json({"error": "demanda cancelada"}, 409)
            answers = [a for a in (data.get("answers") or []) if (a.get("text") or "").strip()]
            if not answers:
                return self._json({"error": "respostas vazias"}, 400)
            entry = self._append_log({"agent": "humano", "type": "clarification", "to": "orquestrador", "demand": demand["id"],
                                      "validation": val["id"], "title": "Respostas à validação", "answers": answers})
            return self._json(entry, 201)
        if self.path.startswith("/api/demand/control"):
            # Controle humano sobre uma demanda em andamento: pausar, retomar, repriorizar, cancelar.
            data = json.loads(raw or b"{}")
            action = data.get("action")
            if action not in ("pause", "resume", "reprioritize", "cancel"):
                return self._json({"error": "ação inválida"}, 400)
            titles = {"pause": "Pausar", "resume": "Retomar", "reprioritize": "Repriorizar", "cancel": "Cancelar"}
            rows = read_jsonl(LOG)
            if not any(e.get("id") == data.get("id") and e.get("type") == "task" for e in rows):
                return self._json({"error": "demanda não encontrada"}, 404)
            if is_canceled(rows, data.get("id")):
                return self._json({"error": "demanda já cancelada"}, 409)
            if action == "cancel" and is_done(rows, data.get("id")):
                return self._json({"error": "demanda já concluída"}, 409)
            entry = self._append_log({"agent": "humano", "type": "control", "to": "orquestrador", "demand": data.get("id"),
                                      "action": action, "priority": data.get("priority"),
                                      "title": f"{titles[action]} demanda", "detail": data.get("note", "")})
            return self._json(entry, 201)
        if self.path.startswith("/api/demand/edit"):
            data = json.loads(raw or b"{}")
            rows = read_jsonl(LOG)
            demand = next((e for e in rows if e.get("id") == data.get("id") and e.get("type") == "task"
                           and e.get("agent") == "humano"), None)
            if not demand:
                return self._json({"error": "demanda não encontrada"}, 404)
            if is_canceled(rows, demand["id"]):
                return self._json({"error": "demanda cancelada"}, 409)
            if not in_backlog(rows, demand):
                return self._json({"error": "só é possível editar demandas em backlog"}, 409)
            eff = effective_demand(rows, demand)
            changes = {}
            if "title" in data:
                t = (data.get("title") or "").strip()
                if not 1 <= len(t) <= 200:
                    return self._json({"error": "título deve ter de 1 a 200 caracteres"}, 400)
                if f"Demanda: {t}" != eff["title"]:
                    changes["title"] = t
            if "detail" in data and (data.get("detail") or "").strip() != (eff.get("detail") or ""):
                changes["detail"] = (data.get("detail") or "").strip()
            if "kind" in data:
                if data["kind"] not in ("produto", "operacao"):
                    return self._json({"error": "tipo inválido: produto | operacao"}, 400)
                if data["kind"] != eff.get("kind"):
                    changes["kind"] = data["kind"]
            if "priority" in data:
                if data["priority"] not in ("alta", "normal", "baixa"):
                    return self._json({"error": "prioridade inválida: alta | normal | baixa"}, 400)
                if data["priority"] != eff.get("priority", "normal"):
                    changes["priority"] = data["priority"]
            if not changes:
                return self._json({"error": "nenhuma mudança"}, 400)
            entry = self._append_log({"agent": "humano", "type": "edit", "to": "orquestrador", "demand": demand["id"],
                                      "title": "Demanda editada no backlog", "changes": changes})
            return self._json(entry, 201)
        if self.path.startswith("/api/demand/start"):
            # Gatilho: o humano inicia a demanda. Vira evento `start` no log e um arquivo na fila docs/squad/inbox/,
            # que a sessão do Orquestrador (em plantão) consome.
            data = json.loads(raw or b"{}")
            demand = next((e for e in read_jsonl(LOG) if e.get("id") == data.get("id") and e.get("type") == "task"
                           and e.get("agent") == "humano"), None)
            if not demand:
                return self._json({"error": "demanda não encontrada"}, 404)
            rows = read_jsonl(LOG)
            if is_canceled(rows, demand["id"]):
                return self._json({"error": "demanda cancelada"}, 409)
            if any(r.get("type") == "start" and r.get("demand") == demand["id"] for r in rows):
                return self._json({"error": "demanda já iniciada"}, 409)
            from_backlog = in_backlog(rows, demand)
            demand = effective_demand(rows, demand)
            clarifications = []
            if demand.get("kind") and not from_backlog:  # demandas v2 (D4); backlog não é validado (ADR-009): Iniciar só após validação ok, respostas ou override com nota
                vals = [e for e in rows if e.get("type") == "validation" and e.get("demand") == demand["id"]]
                last = vals[-1] if vals else None
                answered = last and any(e.get("type") == "clarification" and e.get("validation") == last["id"] for e in rows)
                ready = last and (last.get("status") == "ok" or answered)
                if data.get("override"):
                    if not (data.get("note") or "").strip():
                        return self._json({"error": "override exige nota"}, 400)
                elif not ready:
                    return self._json({"error": "demanda aguardando validação"}, 409)
                if last:
                    ans = next((e for e in reversed(rows) if e.get("type") == "clarification" and e.get("validation") == last["id"]), None)
                    amap = {a["id"]: a["text"] for a in (ans or {}).get("answers", [])}
                    clarifications = [{"question": q["text"], "dimension": q.get("dimension"), "answer": amap.get(q["id"])}
                                      for q in last.get("questions", [])]
            entry = self._append_log({"agent": "humano", "type": "start", "to": "orquestrador", "demand": demand["id"],
                                      "override": True if data.get("override") else None,
                                      "fromBacklog": True if from_backlog else None,
                                      "title": f"Iniciar: {demand['title'].replace('Demanda: ', '')}",
                                      "detail": data.get("note", ""),
                                      "priority": data.get("priority") or demand.get("priority") or "normal",
                                      "route": data.get("route", "padrao"), "target": data.get("target", "auto")})
            inbox = DATA_ROOT / "docs/squad/inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            (inbox / f"{demand['id']}.json").write_text(json.dumps({
                "demand": demand["id"], "title": demand["title"].replace("Demanda: ", ""), "detail": demand.get("detail", ""),
                "priority": entry["priority"], "route": entry["route"], "target": entry["target"],
                "note": entry.get("detail", ""), "startedAt": entry["ts"], "kind": demand.get("kind"),
                "clarifications": clarifications, "override": bool(data.get("override")),
                "fromBacklog": from_backlog}, ensure_ascii=False, indent=2))
            return self._json(entry, 201)
        if self.path.startswith("/api/demand"):
            # Nova demanda para a squad: vira evento `task` para o Orquestrador (e issue no GitHub via github_sync).
            data = json.loads(raw or b"{}")
            title = (data.get("title") or "").strip()
            if not title:
                return self._json({"error": "título obrigatório"}, 400)
            if data.get("kind") not in ("produto", "operacao"):
                return self._json({"error": "tipo obrigatório: produto | operacao"}, 400)
            when = data.get("when", "imediato")
            if when not in ("imediato", "backlog"):
                return self._json({"error": "quando iniciar: imediato | backlog"}, 400)
            if data.get("priority", "normal") not in ("alta", "normal", "baixa"):
                return self._json({"error": "prioridade inválida: alta | normal | baixa"}, 400)
            entry = self._append_log({"agent": "humano", "type": "task", "to": "orquestrador",
                                      "title": f"Demanda: {title}", "detail": data.get("detail", "").strip(),
                                      "priority": data.get("priority", "normal"), "kind": data.get("kind"),
                                      "backlog": True if when == "backlog" else None})
            return self._json(entry, 201)
        if not self.path.startswith("/api/human"):
            return self._json({"error": "not found"}, 404)
        data = json.loads(raw or b"{}")
        action = data.get("action")
        if action not in ("APPROVE", "RETURN", "OVERRIDE"):
            return self._json({"error": "action deve ser APPROVE, RETURN ou OVERRIDE"}, 400)
        titles = {"APPROVE": "Humano aceitou a recomendação do Auditor", "RETURN": "Humano devolveu a etapa",
                  "OVERRIDE": "Humano decidiu seguir apesar da devolução (assume o risco)"}
        entry = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent": "humano",
            "type": "human",
            "title": data.get("title") or titles[action],
            "detail": data.get("note", ""),
            "gate": data.get("gate"),
            "demand": data.get("demand"),
            "recommendation": action,
        }
        entry = {k: v for k, v in entry.items() if v not in (None, "")}
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return self._json(entry, 201)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("SQUAD_PORT") or 7070))
    port = ap.parse_args().port
    print(f"Squad Control em http://localhost:{port}  (transcrições: {transcripts_root()})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
