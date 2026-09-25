#!/usr/bin/env python3
"""Servidor do painel Squad Control (somente stdlib).

- Serve `squad-control/index.html` (painel genérico da squad; o produto gerenciado vem de docs/squad/project.json).
- GET  /api/usage  -> consumo da IA (Claude Code via tee de statusline, Codex via rollouts) — D11/ADR-014
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
import hashlib
import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import alerts as al  # noqa: E402  (D14, ADR-017: regras B1–B4/A1–A3 e estado dos agentes)
from transcripts import TranscriptStore  # noqa: E402  (leitura incremental das transcrições)
import testenv as te  # noqa: E402  (D15, ADR-018: ambiente de teste compartilhado)
import bugs  # noqa: E402  (D16, ADR-019: demandas de bug — rascunho, links do produtivo, BugStore)
import evidence_rules as er  # noqa: E402  (D16: regras únicas de evidência, máscara e limites)
import instance as inst  # noqa: E402  (D18, ADR-021: ambiente e versão do próprio Squad Control)
import conversa as cv  # noqa: E402  (D17, ADR-020: conversa direta com o Orquestrador)


ROOT = pathlib.Path(__file__).resolve().parents[2]
# Dados podem vir de outra cópia do repositório (ex.: validar um worktree com o log/runs da cópia principal).
DATA_ROOT = pathlib.Path(os.environ.get("SQUAD_ROOT_DATA") or ROOT).resolve()
LOG = pathlib.Path(os.environ.get("SQUAD_LOG") or DATA_ROOT / "docs/squad/memory/decisions.jsonl")
GATES_DIR = DATA_ROOT / "docs/squad/gates"
HANDOFFS_DIR = DATA_ROOT / "docs/squad/memory/handoffs"
RUNS_DIR = DATA_ROOT / ".squad/runs"
UI_DIR = ROOT / "squad-control"
INSTANCE = None   # D18: inst.Instance criada em main() (ou na 1ª consulta, com a porta do servidor)

AGENT_ALIASES = {
    "arquiteto": "arquiteto", "backend": "backend", "devops": "devops",
    "observabilidade": "observabilidade", "qa": "qa", "auditor": "auditor",
    "frontend": "frontend",
    "jev": "auditor",  # nome antigo do gatekeeper nas transcrições já gravadas
}
RUNNING_WINDOW_S = 45
# D14 (contrato §9.5): limites nomeados; valores em tools/squad/alerts.py (SQUAD_STALLED_S ajusta o A2).
STALLED_S, LONG_TOOL_S, WAIT_WARN_S = al.STALLED_S, al.LONG_TOOL_S, al.WAIT_WARN_S
LOW_CONFIDENCE, MAX_AUTO_CYCLES = al.LOW_CONFIDENCE, al.MAX_AUTO_CYCLES
LIVE_MAX_BYTES = 64 * 1024
LOCK = threading.RLock()   # o estado incremental das transcrições é compartilhado entre as threads do servidor


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


_STORE: TranscriptStore | None = None


def store() -> TranscriptStore:
    global _STORE
    if _STORE is None:
        _STORE = TranscriptStore(rel, summarize_tool)
    return _STORE


def scan_transcript(path: pathlib.Path) -> dict:
    """Modelos (message.model, sem <synthetic>), 1º prompt e chamadas a log.py de uma transcrição.
    D14: servido pelo estado incremental (só os bytes novos são lidos a cada consulta)."""
    with LOCK:
        st = store().get(path)
        return {"models": st.models, "first_prompt": st.first_prompt_any, "calls": st.calls}


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


def completed_agent_ids(base: pathlib.Path) -> set[str]:
    """IDs de subagentes cuja notificação de término já chegou à sessão do Orquestrador (leitura incremental)."""
    done: set[str] = set()
    with LOCK:
        for main in base.glob("*.jsonl"):
            done |= store().get(main).completed
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
    elif recent and (not ended_turn or current):
        status = "trabalhando"  # agente retomado várias vezes: notificações antigas de término não valem
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


_meta_cache: dict[str, tuple[float, dict]] = {}


def read_meta(path: pathlib.Path) -> dict:
    meta_path = path.with_suffix(".meta.json")
    try:
        mt = meta_path.stat().st_mtime
    except OSError:
        return {}
    c = _meta_cache.get(str(meta_path))
    if c and c[0] == mt:
        return c[1]
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        meta = {}
    _meta_cache[str(meta_path)] = (mt, meta)
    return meta


def run_from_state(st, agent: str | None = None, orchestrator=False, completed: set[str] | None = None,
                   now: float | None = None, notified_map: dict | None = None) -> dict | None:
    """Mesmo resultado de parse_run (lendo o arquivo inteiro), a partir do estado incremental.
    Orquestrador (§9.3): todas as ferramentas, sem as mensagens de texto; status calculado como o dos demais."""
    if not st.rows:
        return None
    now = time.time() if now is None else now
    meta = read_meta(st.path)
    updated = st.mtime
    ended_turn = st.ended_turn
    recent = (now - updated) < RUNNING_WINDOW_S
    run_id = st.path.stem.replace("agent-", "")
    current = st.current(tools_only=orchestrator)
    if recent and (not ended_turn or current):
        status = "trabalhando"
    elif ended_turn and ((completed is not None and run_id in completed) or (now - updated) > 90):
        status = "concluído"
    elif recent or not ended_turn or current:
        status = "trabalhando"
    else:
        status = "trabalhando" if (now - updated) < 900 else "parado"
    notified = al.ts_epoch((notified_map or {}).get(run_id))
    # Turno encerrado só vale depois da janela de 45 s (uma mensagem de texto pode vir antes do tool_use seguinte)
    # ou quando o Orquestrador já recebeu a notificação de término desta run.
    finished = (ended_turn and not current and not recent) or (notified is not None and notified >= updated - 5)
    return {
        "id": run_id,
        "agent": agent or resolve_agent(meta, st.first_prompt),
        "description": meta.get("description", ""),
        **model_fields(st.models, hint="anthropic" if st.models else None),
        "demand": meta.get("demand") or (None if orchestrator else first_demand(st.first_prompt)),
        "status": status,
        "started": st.started,
        "updated": datetime.fromtimestamp(updated, timezone.utc).isoformat(timespec="seconds"),
        "toolCount": st.tool_count,
        "current": current if status == "trabalhando" else None,
        "files": list(st.files),
        "activity": list(st.tools if orchestrator else st.activity)[-80:],
        # internos (prefixo "_", removidos da resposta)
        "_last": updated, "_open": not finished, "_current": current, "_commands": list(st.commands),
        "_state": st, "_toolUseId": meta.get("toolUseId"),
    }


def collect_runs(now: float | None = None) -> list[dict]:
    base = transcripts_root()
    runs = []
    with LOCK:
        mains = sorted(base.glob("*.jsonl"))
        subs = sorted(base.glob("*/subagents/agent-*.jsonl"))
        store().prune({str(p) for p in mains + subs})
        completed, notified = set(), {}
        for m in mains:
            completed |= store().get(m).completed
            notified.update(store().get(m).notified)
        for path in subs:
            run = run_from_state(store().get(path), completed=completed, now=now, notified_map=notified)
            if run:
                runs.append(run)
        runs.extend(collect_external_runs(now))
        # Sessão principal = Orquestrador (todas as ferramentas; só sessões que delegaram)
        for path in mains:
            if (base / path.stem / "subagents").exists():
                st = store().get(path)
                if st.agent_tool_count:
                    run = run_from_state(st, agent="orquestrador", orchestrator=True, now=now)
                    if run:
                        runs.append(run)
    return runs


def public_run(r: dict) -> dict:
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    out["lastActivityAt"] = al.iso(r.get("_last"))
    out["stalled"] = bool(r.get("_stalled"))
    out["waitingOn"] = r.get("_waitingOn", [])
    return out


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


_tail_cache: dict[str, tuple[float, int, list[str]]] = {}


def _log_tail(path: pathlib.Path, st) -> list[str]:
    c = _tail_cache.get(str(path))
    if c and c[0] == st.st_mtime and c[1] == st.st_size:
        return c[2]
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-40:]
    _tail_cache[str(path)] = (st.st_mtime, st.st_size, lines)
    return lines


def collect_external_runs(now: float | None = None) -> list[dict]:
    """Execuções disparadas por tools/squad/run_agent.py (qualquer fornecedor): metadados + saída ao vivo + progress."""
    runs_dir = RUNS_DIR
    top_level = None  # run_id -> transcrição de topo do `claude -p` (runs antigos, sem sessionId)
    progress = [e for e in read_log() if e.get("type") == "progress" and e.get("run")]
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
        try:
            lst = log_path.stat()
        except OSError:
            lst = None
        mtime = lst.st_mtime if lst else meta_path.stat().st_mtime
        lines = _log_tail(log_path, lst) if lst else []
        if lines:
            activity.append({"ts": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                             "kind": "text", "summary": "\n".join(l for l in lines if l.strip())[-600:]})
        current = None
        last = next((a for a in reversed(activity) if a["kind"] == "tool"), None)
        if status == "trabalhando":
            current = {"tool": meta.get("runner", "runner"), "summary": (last or {}).get("summary", "em execução"),
                       "ts": (last or {}).get("ts", meta.get("started"))}
        runner = meta.get("runner")
        models: dict[str, int] = {}
        hint = meta.get("modelProvider")
        if runner == "codex" and lst:
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
        last_prog = max([al.ts_epoch(a["ts"]) or 0 for a in activity if a["kind"] == "tool"], default=0)
        out.append({"id": meta["id"], "agent": meta.get("agent", "outro"), "description": meta.get("description", ""),
                    **model_fields(models, hint, runner), "modelRequested": meta.get("modelRequested"),
                    "sessionId": meta.get("sessionId"), "demand": meta.get("demand"),
                    "delegation": meta.get("delegation"),   # D19: run iniciada por delegação (run_agent --delegation)
                    "runner": runner, "status": status,
                    "started": meta.get("started"),
                    "updated": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                    "toolCount": len([x for x in activity if x["kind"] == "tool"]), "current": current,
                    "files": [], "activity": activity[-80:],
                    "_last": max(mtime, last_prog), "_open": status == "trabalhando", "_external": True,
                    "_current": {"kind": "tool", "tool": "progress", "summary": current["summary"], "ts": current["ts"]}
                    if current else None, "_commands": []})
    return out


# ---------------------------------------------------------------- D14: log/gates em cache, alertas e agentes
_log_cache: dict = {"sig": None, "rows": []}


def _sig(path: pathlib.Path):
    try:
        st = path.stat()
        return (st.st_size, st.st_mtime)
    except OSError:
        return None


def read_log() -> list[dict]:
    """Log de decisões com cache por (tamanho, mtime)."""
    sig = _sig(LOG)
    if sig != _log_cache["sig"]:
        _log_cache.update(sig=sig, rows=read_jsonl(LOG))
    return _log_cache["rows"]


def _dir_sig(d: pathlib.Path, pattern="*") -> tuple:
    try:
        return tuple(sorted((p.name, p.stat().st_mtime) for p in d.glob(pattern)))
    except OSError:
        return ()


def usage_sig() -> str:
    """Assinatura do consumo da IA (D11) para a `version` do /api/live — D14-QA-3.

    Usa o objeto `usage` já calculado (snapshot do Claude + cauda dos rollouts do Codex, com o cache por
    (caminho, mtime, tamanho) de `_codex_last_rate_limits`): muda quando percentuais, janelas ou estado mudam, e não a
    cada gravação dos rollouts. `collectedAt` fica fora para não forçar recarga do /api/state a cada tique da statusline."""
    try:
        providers = collect_usage()["providers"]
        return repr([{k: v for k, v in p.items() if k != "collectedAt"} for p in providers])
    except Exception:
        return ""


# ---------------------------------------------------------------- D15: ambiente de teste (ADR-018)
class TestEnvProbe:
    """Saúde do checkout-teste (docker ps) e head do PR do ocupante (gh) em cache, renovados em segundo plano:
    /api/live nunca espera docker/gh (orçamento de 300 ms do ADR-017). SQUAD_TESTENV_PROBE=0 desliga (testes)."""
    TTL_HEALTH, TTL_PR = 15, 60

    def __init__(self):
        self.health, self.health_at, self.heads, self.busy = None, 0.0, {}, False
        self.lock = threading.Lock()

    def enabled(self) -> bool:
        return os.environ.get("SQUAD_TESTENV_PROBE", "1") != "0"

    def _refresh(self, ref):
        try:
            h = te.project_health(te.TEST_PROJECT)
            head = None
            if ref:
                head = (te.pr_info(ref) or {}).get("headRefOid")
            with self.lock:
                self.health, self.health_at = h, time.time()
                if ref:
                    self.heads[str(ref)] = (time.time(), head)
        finally:
            self.busy = False

    def get(self, s: dict) -> tuple[dict | None, str | None]:
        if not self.enabled():
            return None, None
        ref = s.get("url") or s.get("pr") if s.get("demand") else None
        now = time.time()
        with self.lock:
            head_entry = self.heads.get(str(ref)) if ref else None
            stale = now - self.health_at > self.TTL_HEALTH or (ref and (not head_entry or now - head_entry[0] > self.TTL_PR))
            if stale and not self.busy:
                self.busy = True
                threading.Thread(target=self._refresh, args=(ref,), daemon=True).start()
            return self.health, (head_entry or (0, None))[1]


TE_PROBE = TestEnvProbe()
TE_SPAWNED: list[list[str]] = []   # comandos disparados (inspecionados pelos testes com SQUAD_TESTENV_SPAWN=0)


def test_env_view() -> dict:
    rows = read_log()
    health, head = TE_PROBE.get(te.derive(rows))
    return te.view(rows, health=health, pr_head=head, codes=al.demand_codes(rows))


def te_spawn(*args: str):
    """Dispara testenv.py em segundo plano (o servidor só grava o pedido; quem mexe no Docker é o testenv.py)."""
    cmd = [sys.executable, str(pathlib.Path(__file__).resolve().parent / "testenv.py"), *args]
    TE_SPAWNED.append(list(args))
    if os.environ.get("SQUAD_TESTENV_SPAWN", "1") == "0":
        return
    import subprocess
    subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def data_version() -> str:
    """Muda quando log, gates, handoffs, inbox, .squad/runs ou o consumo da IA mudam (contrato §9.1)."""
    parts = (_sig(LOG), _dir_sig(GATES_DIR, "*.json"), _dir_sig(HANDOFFS_DIR, "*.md"),
             _dir_sig(DATA_ROOT / "docs/squad/inbox", "*.json"), _dir_sig(RUNS_DIR, "*.json"), usage_sig(),
             repr(TE_PROBE.health) if TE_PROBE.enabled() else "")
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:16]


_gates_cache: dict = {"sig": None, "gates": []}
_rules_cache: dict = {"sig": None, "rules": None}


def gates_cached() -> list[dict]:
    sig = _dir_sig(GATES_DIR, "*.json")
    if sig != _gates_cache["sig"]:
        _gates_cache.update(sig=sig, gates=collect_gates())
    return _gates_cache["gates"]


def rules_cached() -> "al.Rules":
    rows, gates = read_log(), gates_cached()
    sig = (_log_cache["sig"], _gates_cache["sig"])
    if sig != _rules_cache["sig"]:
        _rules_cache.update(sig=sig, rules=al.Rules(rows, gates))
    return _rules_cache["rules"]


def orchestrator_view(runs: list[dict], rules, now: float) -> dict | None:
    """Pendências da sessão principal atual do Orquestrador: subagentes em execução, pergunta ao humano, demanda."""
    orch_runs = [r for r in runs if r.get("agent") == "orquestrador" and r.get("_state") is not None]
    if not orch_runs:
        return None
    cur = max(orch_runs, key=lambda r: r["_last"])
    st = cur["_state"]
    by_id = {r["id"]: r for r in runs}
    by_use = {r.get("_toolUseId"): r for r in runs if r.get("_toolUseId")}
    subs = []
    for agent_id, use in st.launched.items():
        since = al.ts_epoch(use.get("since")) or 0
        notified = al.ts_epoch(st.notified.get(agent_id))
        if notified is not None and notified >= since:
            continue
        run = by_id.get(agent_id)
        if run is None and now - since > al.STALLED_MAX_S:
            continue
        if run is not None and not (run["_open"] or now - run["_last"] < 90):
            continue
        role = (run or {}).get("agent")
        if role in (None, "outro"):   # subagente fora dos 8 papéis nomeados: tenta o 1º termo da descrição
            head = re.split(r"[\s·:]", (use.get("description") or "").strip().lower(), maxsplit=1)[0]
            role = next((r for r in al.ROLES if head.startswith(r[:5])), role)
        subs.append({"runId": agent_id, "description": use.get("description"), "since": use.get("since"),
                     "agent": role})
    ask = None
    for tid, item in st.pending.items():
        if item.get("tool") == "Agent":   # delegação síncrona pendente
            run = by_use.get(tid)
            subs.append({"runId": (run or {}).get("id") or "?", "description": item.get("summary"),
                         "since": item.get("ts"), "agent": (run or {}).get("agent")})
        elif item.get("tool") in ("AskUserQuestion", "ExitPlanMode"):
            ask = item.get("ts")
    rows = read_log()
    demand = None
    for e in reversed(rows):
        d = e.get("demand")
        if d and e.get("agent") == "orquestrador" and not rules._closed(d):
            demand = d
            break
    if demand is None:
        demand = next((e["demand"] for e in reversed(rows) if e.get("type") == "start" and e.get("demand")
                       and not rules._closed(e["demand"])), None)
    return {"demand": demand, "subagents": subs, "ask": ask}


def compute(full: bool) -> dict:
    """Núcleo de /api/live (full=False) e dos campos novos de /api/state (full=True)."""
    t0 = time.perf_counter()
    now = time.time()
    with LOCK:
        runs = collect_runs(now)
        rules = rules_cached()
        rows = read_log()
        test_env = test_env_view()
        gate_alerts = (list(rules.open.values()) + al.env_alerts(rows, test_env, rules.codes)
                       + al.handoff_alerts(rows, rules, runs, now))          # D19: A6 (relógio, como o A2)
        agents, stalled = al.build_agents(runs, rules, rows, gate_alerts, now, orchestrator_view(runs, rules, now))
        alerts = al.with_age(al.sort_alerts(gate_alerts + stalled), now)
        delegations = annotate_delegations(alerts, rows, rules, now)
        out = {"now": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
               "version": data_version(), "thresholds": al.thresholds(),
               "summary": al.summary(alerts, agents), "alerts": alerts,
               "testEnv": test_env if full else te.live_summary(test_env)}
        if full:
            # D19: delegação ativa por demanda (badge). Só no /api/state: o /api/live mantém o conjunto de chaves
            # (test_alertas_d14); toda mudança de delegação muda o log → `version` → o cliente recarrega o /api/state.
            out["delegations"] = delegations
            out["agents"] = agents
            out["alertsHistory"] = sorted(rules.history, key=lambda a: a.get("closedAt") or "", reverse=True)
            out["_runs"] = [public_run(r) for r in runs]
            out["_rules"] = rules
        else:
            out["agents"] = [al.compact_agent(a) for a in agents]
    out["serverMs"] = round((time.perf_counter() - t0) * 1000)
    return out


def annotate_delegations(alerts: list[dict], rows: list[dict], rules, now: float) -> dict:
    """D19 (contrato §5, §7, §11): alertas B6/A6/A7/A2/A4/A5 ganham `delegable`, `delegateReason`, `attempt`/`maxAttempts`
    e `delegation` (a ativa para o mesmo alvo → "Delegado — em execução"). Devolve {demanda: delegação ativa resumida}."""
    active = {}
    for x in al.delegations_of(rows):
        if x["result"] is None and x.get("demand"):
            active[x["demand"]] = x
    state = {"rows": rows, "rules": rules, "alerts": alerts, "now": al.iso(now)}
    for a in alerts:
        if a.get("kind") not in cv.DELEGABLE_KINDS:
            continue
        cur = active.get(a.get("demand"))
        hit = cur if cur and (cur.get("target") in (a["id"], (a.get("source") or {}).get("event"))
                              or (cur.get("run") and cur.get("run") == a.get("runId"))) else None
        if isinstance(a.get("delegation"), str):   # A2: a run parada foi iniciada por delegação (CA-10d) — preserva
            a["runDelegation"] = a["delegation"]
        a["delegation"] = {"id": hit["id"], "state": hit["state"]} if hit else None
        try:
            info = cv.alert_delegation(state, a)
        except Exception:
            info = {"delegable": False, "reason": "erro", "attempt": None, "maxAttempts": None}
        a["delegable"] = bool(info["delegable"]) and not hit
        a["delegateReason"] = None if a["delegable"] else ("delegacao_ativa" if hit else info.get("reason"))
        a["attempt"], a["maxAttempts"] = info.get("attempt"), info.get("maxAttempts")
    return {d: {"id": x["id"], "category": x["category"], "state": x["state"], "owner": x["owner"],
                "risk": x["risk"], "ts": x["ts"], "title": x["title"]} for d, x in active.items()}


def live_payload() -> tuple[bytes, str]:
    data = compute(full=False)
    body = json.dumps(data, ensure_ascii=False).encode()
    if len(body) > LIVE_MAX_BYTES:   # nunca passa de 64 KB: corta o menos essencial primeiro
        for a in data["agents"]:
            a["recentCommands"] = a["recentCommands"][:2]
            a["recentFiles"] = a["recentFiles"][:3]
        for a in data["alerts"]:
            a["detail"] = al.trunc(a.get("detail"), 80)
        body = json.dumps(data, ensure_ascii=False).encode()
    return body, data["version"]


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


# ---------------------------------------------------------------- consumo da IA (D11, ADR-014)
# Só fonte real: Codex pelos rollouts ($CODEX_HOME/sessions), Claude Code pelo snapshot do tee de statusline.
USAGE_FRESH_S = 15 * 60
CODEX_TAIL_BYTES = 512 * 1024
CODEX_DAY_DIRS = 3      # pastas de data mais recentes consideradas (não varre a árvore toda)
CODEX_MAX_FILES = 5
_codex_cache: dict = {}  # (caminho, mtime, tamanho) -> última rate_limits válida


def claude_snapshot_path() -> pathlib.Path:
    return DATA_ROOT / ".squad/usage/claude.json"


def codex_sessions_dir() -> pathlib.Path:
    home = os.environ.get("CODEX_HOME")
    return (pathlib.Path(home).expanduser() if home else pathlib.Path.home() / ".codex") / "sessions"


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value) -> datetime | None:
    """Aceita epoch (s) ou ISO-8601; devolve datetime UTC."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), timezone.utc)
        if isinstance(value, str) and value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return None


def _usage_window(pct, resets, minutes) -> dict | None:
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    used = float(pct)
    r = _parse_time(resets)
    return {"usedPercent": used, "remainingPercent": max(0.0, 100.0 - used),
            "resetsAt": _iso_z(r) if r else None,
            "windowMinutes": int(minutes) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) else None}


def _usage_provider(pid: str, label: str, source: str, collected: datetime | None,
                    five: dict | None, week: dict | None, reason_none: str | None = None, **extra) -> dict:
    base = {"id": pid, "label": label, "source": source, **extra}
    if collected is None or (five is None and week is None):
        return {**base, "status": "none", "available": False, "collectedAt": None,
                "reason": reason_none or "Sem fonte real", "fiveHour": None, "week": None}
    now = datetime.now(timezone.utc)
    reason = None
    for name, w in (("Janela de 5 h", five), ("Janela semanal", week)):
        r = _parse_time(w and w.get("resetsAt"))
        if r and r < now:
            loc = r.astimezone()
            when = loc.strftime("%H:%M") if loc.date() == now.astimezone().date() else loc.strftime("%d/%m %H:%M")
            reason = f"{name} renovada às {when}"
            break
    if reason is None and (now - collected).total_seconds() > USAGE_FRESH_S:
        reason = "Coleta com mais de 15 min"
    return {**base, "status": "stale" if reason else "fresh", "available": reason is None,
            "collectedAt": _iso_z(collected), "reason": reason, "fiveHour": five, "week": week}


def usage_claude() -> dict:
    args = ("claude", "Claude Code", "statusline")
    snap = claude_snapshot_path()
    if not snap.exists():
        return _usage_provider(*args, None, None, None, "Statusline não instalada")
    try:
        d = json.loads(snap.read_text(encoding="utf-8"))
        f, w = d.get("fiveHour") or {}, d.get("sevenDay") or {}
        five = _usage_window(f.get("usedPercent"), f.get("resetsAt"), 300)
        week = _usage_window(w.get("usedPercent"), w.get("resetsAt"), 10080)
        return _usage_provider(*args, _parse_time(d.get("collectedAt")), five, week, "Snapshot sem rate_limits")
    except Exception:
        return _usage_provider(*args, None, None, None, "Snapshot ilegível")


def _codex_recent_files(base: pathlib.Path) -> list[tuple[pathlib.Path, float, int]]:
    """Lista só as CODEX_DAY_DIRS pastas AAAA/MM/DD mais recentes e devolve os rollouts de maior mtime."""
    def subdirs(p: pathlib.Path) -> list[pathlib.Path]:
        return sorted((c for c in p.iterdir() if c.is_dir() and c.name.isdigit()), key=lambda c: c.name, reverse=True)
    days: list[pathlib.Path] = []
    for y in subdirs(base):
        for m in subdirs(y):
            for d in subdirs(m):
                days.append(d)
                if len(days) >= CODEX_DAY_DIRS:
                    break
            if len(days) >= CODEX_DAY_DIRS:
                break
        if len(days) >= CODEX_DAY_DIRS:
            break
    files = []
    for d in days:
        for f in d.glob("rollout-*.jsonl"):
            try:
                st = f.stat()
                files.append((st.st_mtime, st.st_size, f))
            except OSError:
                continue
    files.sort(key=lambda t: t[0], reverse=True)
    return [(f, mt, sz) for mt, sz, f in files[:CODEX_MAX_FILES]]


def _codex_last_rate_limits(path: pathlib.Path, mtime: float, size: int) -> dict | None:
    key = (str(path), mtime, size)
    if key in _codex_cache:
        return _codex_cache[key]
    found = None
    with path.open("rb") as fh:
        start = max(0, size - CODEX_TAIL_BYTES)
        fh.seek(start)
        chunk = fh.read()
    lines = chunk.split(b"\n")
    if start > 0:
        lines = lines[1:]  # primeira linha pode estar cortada
    for raw in reversed(lines):
        if b"token_count" not in raw or b"rate_limits" not in raw:
            continue
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        p = ev.get("payload") or {}
        rl = p.get("rate_limits") if p.get("type") == "token_count" else None
        if not isinstance(rl, dict) or rl.get("limit_id") not in (None, "codex"):
            continue
        ts = _parse_time(ev.get("timestamp"))
        if ts is None:
            continue
        found = {"ts": ts, "rl": rl}
        break
    for k in [k for k in _codex_cache if k[0] == str(path)]:
        _codex_cache.pop(k, None)
    _codex_cache[key] = found
    return found


def usage_codex() -> dict:
    args = ("codex", "Codex", "codex-rollout")
    try:
        base = codex_sessions_dir()
        if not base.is_dir():
            return _usage_provider(*args, None, None, None, "Sem sessões do Codex")
        best = None
        for f, mt, sz in _codex_recent_files(base):
            try:
                hit = _codex_last_rate_limits(f, mt, sz)
            except OSError:
                continue
            if hit and (best is None or hit["ts"] > best["ts"]):
                best = hit
        if best is None:
            return _usage_provider(*args, None, None, None, "Nenhum rate_limits nas sessões recentes do Codex")
        rl = best["rl"]
        pri, sec = rl.get("primary") or {}, rl.get("secondary") or {}
        five = _usage_window(pri.get("used_percent"), pri.get("resets_at"), pri.get("window_minutes"))
        week = _usage_window(sec.get("used_percent"), sec.get("resets_at"), sec.get("window_minutes"))
        plan = rl.get("plan_type") if isinstance(rl.get("plan_type"), str) else None
        return _usage_provider(*args, best["ts"], five, week, "rate_limits sem janelas", plan=plan)
    except Exception:
        return _usage_provider(*args, None, None, None, "Falha ao ler as sessões do Codex")


def collect_usage() -> dict:
    providers = []
    for fn, pid, label, src in ((usage_claude, "claude", "Claude Code", "statusline"),
                                (usage_codex, "codex", "Codex", "codex-rollout")):
        try:
            providers.append(fn())
        except Exception:  # nunca derruba /api/state nem o outro provedor
            providers.append(_usage_provider(pid, label, src, None, None, None, "Falha na leitura"))
    return {"providers": providers}


# ---------------------------------------------------------------- escrita no log (D17: trava comum)
# Todas as gravações do servidor em decisions.jsonl passam por aqui: as rotas existentes e a confirmação pela conversa
# (ThreadingHTTPServer = uma thread por conexão). O evento gravado não muda.
LOG_WRITE_LOCK = threading.RLock()
HUMAN_TITLES = {"APPROVE": "Humano aceitou a recomendação do Auditor", "RETURN": "Humano devolveu a etapa",
                "OVERRIDE": "Humano decidiu seguir apesar da devolução (assume o risco)"}
CONTROL_TITLES = {"pause": "Pausar", "resume": "Retomar", "reprioritize": "Repriorizar", "cancel": "Cancelar"}


def _write_log_line(entry: dict):
    with LOG_WRITE_LOCK:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_log(entry: dict) -> dict:
    entry = {"id": uuid.uuid4().hex[:12], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    entry = {k: v for k, v in entry.items() if v not in (None, "")}
    _write_log_line(entry)
    return entry


def record_human_decision(action: str, gate, demand, note="", title=None, via: str | None = None) -> dict:
    """Corpo de POST /api/human (mesmo evento); D17: a confirmação pela conversa acrescenta só `via`."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": "humano",
        "type": "human",
        "title": title or HUMAN_TITLES[action],
        "detail": note,
        "gate": gate,
        "demand": demand,
        "recommendation": action,
        "via": via,
    }
    entry = {k: v for k, v in entry.items() if v not in (None, "")}
    _write_log_line(entry)
    return entry


def record_control(demand, action: str, note="", priority=None, via: str | None = None) -> dict:
    """Evento de POST /api/demand/control (validação fica na rota); D17: a conversa acrescenta só `via`."""
    return append_log({"agent": "humano", "type": "control", "to": "orquestrador", "demand": demand,
                       "action": action, "priority": priority,
                       "title": f"{CONTROL_TITLES[action]} demanda", "detail": note, "via": via})


# ---------------------------------------------------------------- D17: conversa com o Orquestrador
_CHAT: "cv.Engine | None" = None
_CHAT_LOCK = threading.Lock()


def chat_state() -> dict:
    """Estado atual para o contexto do chat e para validar/revalidar propostas de destravar (§4, §6)."""
    live = compute(full=False)
    with LOCK:
        rows = read_log()
        rules = rules_cached()
    return {"rows": rows, "rules": rules, "alerts": live["alerts"], "agents": live["agents"],
            "testEnv": live["testEnv"], "now": live["now"]}


def record_delegation(v: dict, task: str, proposal_id: str) -> dict:
    """D19 (contrato §3.1): ÚNICO gravador do evento `delegation` (log.py recusa o tipo). Chamado só na confirmação do
    humano, já revalidado e sob LOG_WRITE_LOCK."""
    return append_log({"agent": "humano", "type": "delegation", "to": "orquestrador", "demand": v["demand"],
                       "category": v["category"], "target": v.get("target"), "owner": v.get("owner"),
                       "risk": v.get("risk"), "attempt": v.get("attempt"), "attemptKey": v.get("attemptKey"),
                       "pr": v.get("pr"), "branch": v.get("branch"), "run": v.get("run"),
                       "title": v.get("title"), "detail": task, "via": "conversa", "proposal": proposal_id})


def conversation_confirmed(event_id: str) -> bool:
    """§8.2.1: há registro `confirmada` com `event` = id em `.squad/conversas/*.jsonl`?"""
    d = DATA_ROOT / ".squad/conversas"
    for f in (d.glob("c-*.jsonl") if d.is_dir() else []):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if f'"{event_id}"' in line:
                    r = json.loads(line)
                    if r.get("t") == "proposal" and r.get("decision") == "confirmada" and r.get("event") == event_id:
                        return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def delegation_items(demand: str) -> list[dict]:
    rows = read_log()
    codes = al.demand_codes(rows)
    out = []
    for x in reversed(al.delegations_of(rows, demand)):
        item = {k: x[k] for k in ("id", "ts", "demand", "category", "target", "owner", "risk", "attempt", "title",
                                  "task", "state", "startedAt", "endedAt", "result", "events", "pr", "branch",
                                  "attemptKey", "run")}
        item["code"] = codes.get(x["demand"])
        out.append(item)
    return out


def delegation_check(event_id: str) -> tuple[int, dict]:
    """Checagem do plantão antes de começar (§8.2): autenticidade + revalidação da pré-condição no estado atual.
    Código 0 = pode começar; 3 = recusada (sem confirmação do humano); 4 = obsoleta; 5 = já iniciada/encerrada."""
    rows = read_log()
    ev = next((e for e in rows if e.get("id") == event_id and e.get("type") == "delegation"), None)
    if ev is None:
        return 5, {"id": event_id, "error": "delegação não encontrada"}
    item = next(x for x in al.delegations_of(rows) if x["id"] == event_id)
    out = {"id": event_id, "demand": ev.get("demand"), "category": ev.get("category"), "state": item["state"]}
    if item["state"] != "pedida":
        return 5, {**out, "reason": "já iniciada ou encerrada"}
    if ev.get("agent") != "humano" or ev.get("via") != "conversa" or not conversation_confirmed(event_id):
        return 3, {**out, "confirmed": False, "reason": "evento sem confirmação do humano"}
    out["confirmed"] = True
    # revalida como se fosse a 1ª proposta: sem contar a própria delegação (ativa e tentativa)
    rows_wo = [e for e in rows if e.get("id") != event_id]
    live = compute(full=False)
    rules = al.Rules(rows_wo, gates_cached())
    state = {"rows": rows_wo, "rules": rules, "alerts": live["alerts"], "now": live["now"]}
    v = cv.validate_delegation({"demanda": ev.get("demand"), "tipo": ev.get("category"), "alvo": ev.get("target"),
                                "tarefa": ev.get("detail") or "-"}, state)
    out.update(valid=v["valid"], reason=v.get("reason"), owner=v.get("owner"), branch=v.get("branch"))
    return (0 if v["valid"] else 4), out


def chat() -> "cv.Engine":
    global _CHAT
    with _CHAT_LOCK:
        if _CHAT is None:
            store = cv.Store(DATA_ROOT)
            store.recover()          # turnos pendentes de uma execução anterior viram `interrompida`
            try:
                store.cleanup_attachments()   # D21: anexos pendentes > 24 h apagados na subida
            except OSError:
                pass
            _CHAT = cv.Engine(store, chat_state, LOG_WRITE_LOCK)
        return _CHAT




class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(UI_DIR), **kw)

    def log_message(self, *_):
        pass

    def _json(self, obj, status=200, close=False):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if close:          # D21: recusa sem ler o corpo → a conexão não pode ser reaproveitada
            self.close_connection = True
            self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------ D16 (ADR-019): demandas de bug
    def _local_ok(self) -> bool:
        """Anti-CSRF/DNS-rebinding nas rotas de bug: Host local e, se houver, Origin local e Sec-Fetch-Site não cross-site."""
        host = (self.headers.get("Host") or "").strip().lower()
        hostname = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0] if ":" in host else host
        if hostname not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin is not None:
            try:
                u = urllib.parse.urlsplit(origin)
                if u.scheme not in ("http", "https") or u.hostname not in ("127.0.0.1", "localhost"):
                    return False
            except ValueError:
                return False
        return (self.headers.get("Sec-Fetch-Site") or "same-origin") in ("same-origin", "none")

    def _forbidden(self):
        return self._json({"error": "origem não permitida: use o Squad Control em http://localhost", "code": "origem_invalida"}, 403)

    # ------------------------------------------------------------ D17 (ADR-020): conversa com o Orquestrador
    def _chat_err(self, e: "cv.ChatError"):
        return self._json(e.payload(), e.status)

    @staticmethod
    def _chat_parts(path: str) -> list[str]:
        return [p for p in urllib.parse.urlsplit(path).path.split("/")[3:] if p != ""]   # /api/conversas/...

    def _chat_get(self):
        if not self._local_ok():
            return self._forbidden()
        parts = self._chat_parts(self.path)
        if parts == ["pedido"]:
            return self._chat_pedido()
        eng = chat()
        try:
            if not parts:
                runner = cv.default_runner()
                return self._json({"runner": runner, "available": cv.available(runner), **cv.isolation(runner),
                                   "busy": eng.busy(), "items": eng.store.list()})
            cid = parts[0]
            if not eng.store.exists(cid):
                raise cv.ChatError(404, "conversa_nao_encontrada", "conversa não encontrada")
            if len(parts) == 1:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    after = int((q.get("after") or ["0"])[0])
                except ValueError:
                    after = 0
                return self._json(eng.view(cid, after))
            if len(parts) == 4 and parts[1] == "turnos" and parts[3] == "stream" and parts[2].isdigit():
                return self._chat_stream(eng, cid, int(parts[2]))
            if len(parts) == 3 and parts[1] == "anexos":
                return self._send_attachment(eng.store.attachment_path(cid, parts[2]))
        except cv.ChatError as e:
            return self._chat_err(e)
        return self._json({"error": "rota não encontrada", "code": "nao_encontrado"}, 404)

    # ------------------------------------------------------------ D21 (ADR-023): imagens na conversa
    def _send_attachment(self, path: "pathlib.Path | None"):
        """GET /api/conversas/<id>/anexos/<aid>: tipo real (pelos bytes), nosniff, CSP restrita.
        Cache-Control `no-store` (desvio consciente do `private, immutable` do contrato, risco apontado no G1): prints
        podem ter segredos/dados pessoais e não devem ficar no cache de disco do navegador; o servidor é local
        (recarregar custa só E/S local) e é o mesmo cabeçalho das evidências da D16."""
        if path is None:
            return self._json({"error": "anexo não encontrado", "code": "anexo_nao_encontrado"}, 404)
        body = path.read_bytes()
        mime = cv.ATTACH_MIME.get(er.image_kind(body) or "")
        if not mime:
            return self._json({"error": "anexo não encontrado", "code": "anexo_nao_encontrado"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _chat_upload(self, cid: str, length: int):
        """POST /api/conversas/<id>/anexos (§4): recusas 403/400/413/415/404 ANTES de ler qualquer byte do corpo."""
        if not self._local_ok():
            self.close_connection = True
            return self._forbidden()
        fname = self.headers.get("X-Filename")
        label = er.sanitize_name(urllib.parse.unquote(fname[:1024], errors="replace")) if fname else "imagem"
        if length <= 0 or "Content-Length" not in self.headers:
            return self._json({"error": "Content-Length inválido", "code": "content_length_invalido"}, 400, close=True)
        if length > er.MAX_IMAGE:
            mb = f"{length / 1048576:.1f}".replace(".", ",")
            return self._json({"error": f"{label}: imagem acima de 5 MB ({mb} MB).", "code": "arquivo_grande"}, 413,
                              close=True)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in cv.UPLOAD_TYPES:
            msg = (f"{label}: HEIC não é aceito. Exporte como JPEG ou PNG." if ctype in ("image/heic", "image/heif")
                   else f"{label}: formato não aceito. Envie PNG, JPEG ou WEBP.")
            return self._json({"error": msg, "code": "tipo_nao_permitido"}, 415, close=True)
        eng = chat()
        if not eng.store.exists(cid):
            return self._json({"error": "conversa não encontrada", "code": "conversa_nao_encontrada"}, 404, close=True)
        data = self.rfile.read(length)
        if len(data) != length:
            return self._json({"error": "corpo incompleto", "code": "content_length_invalido"}, 400, close=True)
        try:
            status, out = eng.store.upload(cid, data, urllib.parse.unquote(fname[:1024], errors="replace")
                                           if fname else None)
        except cv.ChatError as e:
            return self._chat_err(e)
        return self._json(out, status)

    def do_DELETE(self):
        """D21: DELETE /api/conversas/<id>/anexos/<aid> — mesmo efeito de POST …/remover (anexo não usado)."""
        parts = self._chat_parts(self.path) if self.path.startswith("/api/conversas/") else []
        if not self._local_ok():
            self.close_connection = True
            return self._forbidden()
        if len(parts) != 3 or parts[1] != "anexos":
            return self._json({"error": "rota não encontrada", "code": "nao_encontrado"}, 404, close=True)
        try:
            if not chat().store.exists(parts[0]):
                raise cv.ChatError(404, "conversa_nao_encontrada", "conversa não encontrada")
            return self._json(chat().store.remove_attachment(parts[0], parts[2]))
        except cv.ChatError as e:
            return self._chat_err(e)

    def _chat_pedido(self):
        """D19 §7: GET /api/conversas/pedido?ref=<alertId> — texto pré-preenchido; nada é gravado."""
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        ref = (q.get("ref") or [""])[0]
        if not cv.PEDIDO_RE.match(ref):
            return self._json({"error": "alerta não encontrado", "code": "alerta_nao_encontrado"}, 404)
        live = compute(full=False)
        a = next((x for x in live["alerts"] if x.get("id") == ref), None)
        if a is None:
            return self._json({"error": "alerta não encontrado", "code": "alerta_nao_encontrado"}, 404)
        rows = read_log()
        state = {"rows": rows, "rules": rules_cached(), "alerts": live["alerts"], "now": live["now"]}
        info = cv.alert_delegation(state, a)
        if not info["delegable"]:
            return self._json({"error": "alerta não delegável agora: " + cv.REASON_TEXT.get(info.get("reason"), "—"),
                               "code": "nao_delegavel", "reason": info.get("reason")}, 409)
        return self._json({"text": cv.pedido_text(a, info), "demand": info["validation"].get("code"),
                           "tipo": info["tipo"], "alvo": info["validation"].get("target")})

    def _delegations_get(self):
        """D19 §7: GET /api/delegacoes?demand=<id|Dn> — delegações da demanda, mais recente primeiro."""
        if not self._local_ok():
            return self._forbidden()
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        ref = (q.get("demand") or [""])[0]
        d = cv._resolve_demand(ref, al.demand_codes(read_log()))
        if d is None:
            return self._json({"error": "demanda não encontrada", "code": "demanda_nao_encontrada"}, 404)
        return self._json({"items": delegation_items(d)})

    def _chat_stream(self, eng: "cv.Engine", cid: str, n: int):
        """SSE (§7.1): fase/texto/fim/erro; `: ping` a cada 15 s; reconexão reenvia o texto acumulado num `texto`."""
        t = eng.turn(cid, n)
        final = None
        if t is None:   # turno já encerrado em outra execução do servidor: devolve o registro final gravado
            recs = eng.store.records(cid)
            final = next((r for r in recs if r.get("t") == "msg" and r.get("role") == "orquestrador"
                          and r.get("turn") == n), None)
            if final is None:
                return self._json({"error": "turno não encontrado", "code": "turno_nao_encontrado"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def send(event: str | None, data: dict | None = None, eid: int | None = None, comment: str | None = None):
            if comment is not None:
                chunk = f": {comment}\n\n"
            else:
                chunk = (f"id: {eid}\n" if eid is not None else "") + f"event: {event}\n" + \
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()
        try:
            if final is not None:
                if final.get("status") == "erro":
                    send("erro", {"code": final.get("code") or "erro_runner", "error": final.get("error") or "falha",
                                  "message": final})
                else:
                    send("fim", {"message": final})
                return
            with t.cond:
                idx = len(t.events)
                phase, tool, text, done = t.phase, t.tool, t.sent, t.done
            if done:
                send(*t.final_event, eid=idx)
                return
            send("fase", {"phase": phase, **({"tool": tool} if tool else {})}, eid=idx)
            if text:
                send("texto", {"delta": text, "replace": True}, eid=idx)
            last_ping = time.monotonic()
            while True:
                with t.cond:
                    if len(t.events) == idx:
                        t.cond.wait(timeout=1.0)
                    new = t.events[idx:]
                    idx = len(t.events)
                for eid, event, data in new:
                    send(event, data, eid=eid)
                    if event in ("fim", "erro"):
                        return
                    last_ping = time.monotonic()
                if time.monotonic() - last_ping >= cv.PING_S:
                    send(None, comment="ping")
                    last_ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _chat_post(self, raw: bytes):
        parts = self._chat_parts(self.path)
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "JSON inválido", "code": "json_invalido"}, 400)
        if not isinstance(data, dict):
            return self._json({"error": "JSON inválido", "code": "json_invalido"}, 400)
        eng = chat()
        try:
            if not parts:
                runner = cv.default_runner()
                if not cv.available(runner):
                    raise cv.ChatError(503, "orquestrador_indisponivel",
                                       f"Orquestrador indisponível: runner {runner} ausente (verifique `{runner} --version`)")
                meta = eng.store.create(runner, cv.requested_model())
                return self._json({"id": meta["id"], "createdAt": meta["createdAt"], "runner": runner,
                                   **cv.isolation(runner)}, 201)
            cid = parts[0]
            if not eng.store.exists(cid):
                raise cv.ChatError(404, "conversa_nao_encontrada", "conversa não encontrada")
            if len(parts) == 2 and parts[1] == "mensagens":
                return self._json(eng.send(cid, data.get("text"), t0=self._t0, attachments=data.get("attachments")),
                                  202)
            if len(parts) == 4 and parts[1] == "anexos" and parts[3] == "remover":
                return self._json(eng.store.remove_attachment(cid, parts[2]), 200)
            if len(parts) == 4 and parts[1] == "turnos" and parts[3] == "cancelar" and parts[2].isdigit():
                return self._json(eng.cancel(cid, int(parts[2])), 202)
            if len(parts) == 4 and parts[1] == "propostas" and parts[3] == "confirmar":
                return self._json(eng.confirm(cid, parts[2], data, record_human_decision, record_control,
                                              record_delegation), 201)
            if len(parts) == 4 and parts[1] == "propostas" and parts[3] == "descartar":
                return self._json(eng.discard(cid, parts[2]), 200)
        except cv.ChatError as e:
            return self._chat_err(e)
        return self._json({"error": "rota não encontrada", "code": "nao_encontrado"}, 404)

    def _bug_err(self, e: "er.EvidenceError"):
        return self._json(e.payload(), e.status)

    def _send_evidence(self, path: pathlib.Path | None):
        if path is None:
            return self._json({"error": "arquivo não encontrado", "code": "arquivo_nao_encontrado"}, 404)
        ext = er.extension(path.name)
        mime = er.IMAGE_EXT.get(ext) or er.LOG_EXT.get(ext)
        if not mime:
            return self._json({"error": "tipo não permitido", "code": "tipo_nao_permitido"}, 415)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bug_get(self, path: str):
        if not self._local_ok():
            return self._forbidden()
        parts = path.split("/")[3:]     # /api/bug/...
        try:
            if len(parts) == 3 and parts[0] == "draft":
                return self._send_evidence(bugs.draft_file(DATA_ROOT, parts[1], parts[2]))
            store = bugs.GitDirStore(DATA_ROOT)
            if len(parts) == 1:
                doc = store.get(parts[0])
                return self._json(doc) if doc else self._json({"error": "bug não encontrado", "code": "bug_nao_encontrado"}, 404)
            if len(parts) == 3 and parts[1] == "file":
                return self._send_evidence(store.evidence_path(parts[0], parts[2]))
        except er.EvidenceError as e:
            return self._bug_err(e)
        return self._json({"error": "not found"}, 404)

    def _bug_task_meta(self, doc: dict) -> dict:
        return {k: doc[k] for k in ("severity", "environment", "verifiedBy", "source", "dir", "evidences", "consent")}

    def _create_bug(self, data: dict, title: str, when: str):
        """POST /api/demand com nature=bug (§9): rascunho verificado + confirmação dupla → pasta no git + task."""
        if not self._local_ok():
            return self._forbidden()
        found = er.find_secrets(f"{title}\n{data.get('detail') or ''}")
        if found:
            return self._json({"error": f"título/descrição contém segredo ({', '.join(found)}): remova antes de registrar",
                               "code": "segredo_no_texto"}, 422)
        bug = data.get("bug") if isinstance(data.get("bug"), dict) else {}
        if not bug.get("draft"):
            return self._json({"error": "bug exige ao menos uma evidência (log ou imagem): gere a prévia primeiro",
                               "code": "evidencia_obrigatoria"}, 422)
        severity = bug.get("severity") or "media"
        if severity not in bugs.SEVERITIES:
            return self._json({"error": "severidade inválida: critica | alta | media | baixa", "code": "severidade_invalida"}, 400)
        if bug.get("environment") not in (None, "produtivo"):
            return self._json({"error": "bug é só do ambiente produtivo", "code": "ambiente_de_teste"}, 422)
        store = bugs.GitDirStore(DATA_ROOT)
        try:
            bugs.verify_draft(DATA_ROOT, bug["draft"])          # revarredura (cara) fora da trava — QA-D16-2
            with bugs.LOCK:
                d, meta, blobs = bugs.verify_draft(DATA_ROOT, bug["draft"], remask=False)   # só sha256
                consent = bugs.check_consent(bug.get("consent"))
                er.check_submission([len(b) for _, b in blobs], global_total=store.total_size())
                demand = uuid.uuid4().hex[:12]
                kind = meta["kind"]          # o tipo vem do rascunho (o que o humano revisou na prévia)
                if data.get("kind") != kind:
                    return self._json({"error": f"o tipo informado ({data.get('kind')}) diverge do rascunho ({kind}): "
                                                "gere a prévia de novo com o tipo correto", "code": "tipo_divergente"}, 409)
                created = datetime.now(timezone.utc).isoformat(timespec="seconds")
                doc = {"demand": demand, "title": title, "kind": kind, "createdAt": created,
                       "severity": severity, "environment": "produtivo", "verifiedBy": meta["verifiedBy"],
                       "source": meta.get("source"), "dir": f"docs/squad/{kind}/bugs/{demand}",
                       "evidences": meta["evidences"], "consent": consent,
                       "extracted": meta.get("extracted"), "warnings": meta.get("warnings") or []}
                store.put_bug(kind, demand, doc, blobs)
                entry = self._append_log({"id": demand, "agent": "humano", "type": "task", "to": "orquestrador",
                                          "title": f"Demanda: {title}", "detail": data.get("detail", "").strip(),
                                          "priority": data.get("priority", "normal"), "kind": kind,
                                          "backlog": True if when == "backlog" else None,
                                          "nature": "bug", "bug": self._bug_task_meta(doc)})
                import shutil
                shutil.rmtree(d, ignore_errors=True)
        except er.EvidenceError as e:
            return self._bug_err(e)
        return self._json(entry, 201)

    def _bug_evidence(self, data: dict):
        """POST /api/bug/evidence (§7.4): só acrescenta evidências a um bug em andamento."""
        rows = read_jsonl(LOG)
        task = next((e for e in rows if e.get("id") == data.get("demand") and e.get("type") == "task"
                     and e.get("agent") == "humano"), None)
        if not task:
            return self._json({"error": "demanda não encontrada", "code": "demanda_nao_encontrada"}, 404)
        if task.get("nature") != "bug":
            return self._json({"error": "a demanda não é um bug", "code": "nao_e_bug"}, 409)
        if is_canceled(rows, task["id"]):
            return self._json({"error": "demanda cancelada", "code": "demanda_cancelada"}, 409)
        if any(r.get("type") == "delivered" and r.get("demand") == task["id"] for r in rows):
            return self._json({"error": "demanda já entregue", "code": "demanda_entregue"}, 409)
        store = bugs.GitDirStore(DATA_ROOT)
        try:
            bugs.verify_draft(DATA_ROOT, data.get("draft"))     # revarredura (cara) fora da trava — QA-D16-2
            with bugs.LOCK:
                d, meta, blobs = bugs.verify_draft(DATA_ROOT, data.get("draft"), remask=False)   # só sha256
                bugs.check_consent(data.get("consent"))
                current = store.get(task["id"])
                if current is None:
                    return self._json({"error": "pasta do bug não encontrada", "code": "bug_nao_encontrado"}, 404)
                er.check_submission([len(b) for _, b in blobs], bug_total=store.total_size(task["id"]),
                                    global_total=store.total_size())
                start = max([int(e["file"][:2]) for e in current.get("evidences") or []] + [0]) + 1
                files, items = bugs.renumber(blobs, meta["evidences"], start)
                store.add_evidence(task["id"], items, files)
                entry = self._append_log({"agent": "humano", "type": "bug-evidence", "to": "orquestrador",
                                          "demand": task["id"], "title": f"Evidência acrescentada ao bug ({len(items)})",
                                          # name/status: compatível com os leitores atuais de `evidences` (UI, github_sync)
                                          "evidences": [{**i, "name": i["file"], "status": "pass"} for i in items]})
                import shutil
                shutil.rmtree(d, ignore_errors=True)
        except er.EvidenceError as e:
            return self._bug_err(e)
        return self._json(entry, 201)

    def _bug_post(self, path: str, raw: bytes):
        if not self._local_ok():
            return self._forbidden()
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "JSON inválido", "code": "json_invalido"}, 400)
        if not isinstance(data, dict):
            return self._json({"error": "JSON inválido", "code": "json_invalido"}, 400)
        if path == "/api/bug/draft":
            try:          # sem a trava global: build_draft só a toma para criar a pasta (QA-D16-2)
                return self._json(bugs.build_draft(DATA_ROOT, data), 201)
            except er.EvidenceError as e:
                return self._bug_err(e)
        if path == "/api/bug/evidence":
            return self._bug_evidence(data)
        return self._json({"error": "not found"}, 404)

    def _instance(self):
        """D18 (ADR-021): calculado na subida (main); git só aqui, com cache de 30 s — nunca no /api/live."""
        global INSTANCE
        try:
            if INSTANCE is None:
                INSTANCE = inst.Instance(ROOT, self.server.server_address[1], DATA_ROOT, LOG)
            return INSTANCE.snapshot()
        except Exception:  # nunca derruba /api/state
            return None

    def do_GET(self):
        if self.path == "/api/conversas" or self.path.startswith(("/api/conversas/", "/api/conversas?")):
            return self._chat_get()
        if self.path.startswith("/api/bug/"):
            return self._bug_get(urllib.parse.urlsplit(self.path).path)
        if self.path == "/api/delegacoes" or self.path.startswith(("/api/delegacoes?", "/api/delegacoes/")):
            return self._delegations_get()
        if self.path.startswith("/api/live"):
            # D14 (ADR-017, contrato §9.1): canal leve consultado a cada 1,5 s — sem enrich_log nem handoffs.
            body, version = live_payload()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("ETag", f'W/"{version}"')   # versão dos dados (log/gates/handoffs/inbox/runs)
            self.send_header("X-Squad-Version", version)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/state"):
            extra = compute(full=True)
            runs, rules = extra.pop("_runs"), extra.pop("_rules")
            log = enrich_log(read_log(), runs)
            for e in log:   # só na resposta: ciclo e devoluções por gate (o log segue append-only)
                if e.get("type") == "gate" and e.get("id") in rules.gate_meta:
                    for k, v in rules.gate_meta[e["id"]].items():
                        e.setdefault(k, v)
            return self._json({
                "now": extra["now"],
                "log": log,
                "gates": gates_cached(),
                "runs": runs,
                "handoffs": collect_handoffs(),
                "github": github_issues(),
                "usage": collect_usage(),
                # D14 — só acréscimos (contrato §9.2)
                "version": extra["version"], "thresholds": extra["thresholds"], "summary": extra["summary"],
                "alerts": extra["alerts"], "alertsHistory": extra["alertsHistory"], "agents": extra["agents"],
                "serverMs": extra["serverMs"],
                "testEnv": extra["testEnv"],   # D15 — acréscimo (formato de GET /api/test-env)
                "instance": self._instance(),  # D18 — acréscimo (formato de GET /api/instance)
                "delegations": extra["delegations"],   # D19 — acréscimo: delegação ativa por demanda
            })
        if self.path.startswith("/api/instance"):
            return self._json(self._instance())
        if self.path.startswith("/api/test-env"):
            return self._json(test_env_view())
        if self.path.startswith("/api/usage"):
            return self._json({"usage": collect_usage()})
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
        return append_log(entry)

    def do_POST(self):
        self._t0 = time.monotonic()   # D17: firstTextMs conta a partir do recebimento do POST
        # D16 (ressalva 4 do G1): o teto de 22 MB vale antes de ler qualquer byte do corpo (teto geral do servidor).
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        m = cv.UPLOAD_ROUTE_RE.match(urllib.parse.urlsplit(self.path).path)
        if m:   # D21 §4: rota de anexo casada ANTES do teto de 32 KB; teto próprio de 5 MB antes de ler o corpo
            return self._chat_upload(m.group(1), length)
        if self.path == "/api/conversas" or self.path.startswith(("/api/conversas/", "/api/conversas?")):
            # D17: origem local e corpo ≤ 32 KB checados ANTES de ler o corpo.
            if not self._local_ok():
                self.close_connection = True
                return self._forbidden()
            if length < 0 or length > cv.MAX_BODY:
                self.close_connection = True
                return self._json({"error": "corpo da requisição acima de 32 KB" if length > 0 else "Content-Length inválido",
                                   "code": "corpo_grande" if length > 0 else "content_length_invalido"},
                                  413 if length > 0 else 400)
            return self._chat_post(self.rfile.read(length))
        if length < 0 or length > er.MAX_BODY:
            self.close_connection = True
            body = json.dumps({"error": "corpo da requisição acima de 22 MB" if length > 0 else "Content-Length inválido",
                               "code": "corpo_grande" if length > 0 else "content_length_invalido"}, ensure_ascii=False).encode()
            self.send_response(413 if length > 0 else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        raw = self.rfile.read(length)
        if self.path.startswith("/api/bug/"):
            return self._bug_post(urllib.parse.urlsplit(self.path).path, raw)
        if self.path.startswith("/api/test-env/request"):
            # D15: só o humano pede; o servidor grava `test-env-request` e dispara o testenv.py em segundo plano.
            data = json.loads(raw or b"{}")
            action, demand = data.get("action"), data.get("demand")
            if demand and not any(e.get("id") == demand and e.get("type") == "task" for e in read_jsonl(LOG)):
                return self._json({"error": "demanda não encontrada"}, 404)
            try:
                res = te.request(demand, action, data.get("confirm"))
            except te.RequestError as e:
                return self._json({"error": str(e)}, e.status)
            if not res.get("duplicate"):
                if action == "release":
                    te_spawn("release", "--demand", demand, "--reason", "human")
                elif action == "down":
                    te_spawn("down")
                elif action == "reset-data":
                    te_spawn("reset-data")
                else:
                    te_spawn("reconcile")
            return self._json({k: v for k, v in res.items() if v is not None}, 202)
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
            rows = read_jsonl(LOG)
            if not any(e.get("id") == data.get("id") and e.get("type") == "task" for e in rows):
                return self._json({"error": "demanda não encontrada"}, 404)
            if is_canceled(rows, data.get("id")):
                return self._json({"error": "demanda já cancelada"}, 409)
            if action == "cancel" and is_done(rows, data.get("id")):
                return self._json({"error": "demanda já concluída"}, 409)
            entry = record_control(data.get("id"), action, data.get("note", ""), priority=data.get("priority"))
            if action == "cancel":
                s = te.derive(read_jsonl(LOG))   # D15: cancelada libera o teste / sai da fila (reconcile)
                if s["demand"] == data.get("id") or any(q["demand"] == data.get("id") for q in s["queue"]):
                    te_spawn("reconcile")
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
            queued = {
                "demand": demand["id"], "title": demand["title"].replace("Demanda: ", ""), "detail": demand.get("detail", ""),
                "priority": entry["priority"], "route": entry["route"], "target": entry["target"],
                "note": entry.get("detail", ""), "startedAt": entry["ts"], "kind": demand.get("kind"),
                "clarifications": clarifications, "override": bool(data.get("override")),
                "fromBacklog": from_backlog}
            if demand.get("nature") == "bug":   # D16 §7.6: campos novos só em bugs (consumidores atuais os ignoram)
                b = demand.get("bug") or {}
                queued.update(nature="bug", bug={"dir": b.get("dir"), "source": b.get("source"),
                                                 "severity": b.get("severity"),
                                                 "evidences": [{"file": e.get("file")} for e in b.get("evidences") or []]})
            (inbox / f"{demand['id']}.json").write_text(json.dumps(queued, ensure_ascii=False, indent=2))
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
            # D16 (ADR-019): natureza ortogonal ao tipo; sem `nature` (ou "demanda") o evento é o de sempre.
            nature = data.get("nature")
            if nature not in (None, "demanda", "bug"):
                return self._json({"error": "natureza inválida: demanda | bug", "code": "natureza_invalida"}, 400)
            if "bug" in data and nature != "bug":
                return self._json({"error": "objeto bug exige nature: bug", "code": "bug_sem_natureza"}, 400)
            if nature == "bug":
                return self._create_bug(data, title, when)
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
        entry = record_human_decision(action, data.get("gate"), data.get("demand"), data.get("note", ""),
                                      title=data.get("title"))
        return self._json(entry, 201)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("SQUAD_PORT") or 7070))
    ap.add_argument("--delegation-check", metavar="ID",
                    help="D19: checa autenticidade e pré-condição de uma delegação (JSON; código 0 = pode começar)")
    args = ap.parse_args()
    if args.delegation_check:
        code, out = delegation_check(args.delegation_check)
        print(json.dumps(out, ensure_ascii=False))
        sys.exit(code)
    port = args.port
    global INSTANCE
    INSTANCE = inst.Instance(ROOT, port, DATA_ROOT, LOG)   # D18: ambiente e versão fixados na subida
    print(f"Ambiente: {INSTANCE.env['label']} ({INSTANCE.env['reason']}) · versão {INSTANCE.build['display']}")
    print(f"Squad Control em http://localhost:{port}  (transcrições: {transcripts_root()})")
    # Aquecimento: a 1ª leitura das transcrições é completa (dezenas de MB); as seguintes só leem o que foi acrescentado.
    threading.Thread(target=lambda: compute(full=False), daemon=True).start()
    chat()   # D17: fecha como `interrompida` turnos que ficaram abertos numa execução anterior
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
