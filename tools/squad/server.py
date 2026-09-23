#!/usr/bin/env python3
"""Servidor do painel Squad Control (somente stdlib).

- Serve `squad-control/index.html`.
- GET  /api/state  -> log de decisões + pareceres do Jev + atividade ao vivo de cada agente
                      (lida das transcrições dos subagentes do Claude Code).
- POST /api/human  -> registra a decisão humana (aceitar/devolver) no log compartilhado;
                      o Orquestrador lê esse evento antes de avançar o gate.

Uso: python3 tools/squad/server.py [--port 7070]
Transcrições: $SQUAD_TRANSCRIPTS ou ~/.claude/projects/<repo-slug>/*/subagents/*.jsonl
"""
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
LOG = ROOT / "docs/squad/memory/decisions.jsonl"
GATES_DIR = ROOT / "docs/squad/gates"
HANDOFFS_DIR = ROOT / "docs/squad/memory/handoffs"
UI_DIR = ROOT / "squad-control"

AGENT_ALIASES = {
    "arquiteto": "arquiteto", "backend": "backend", "devops": "devops",
    "observabilidade": "observabilidade", "qa": "qa", "jev": "jev",
}
RUNNING_WINDOW_S = 45


def transcripts_root() -> pathlib.Path:
    env = os.environ.get("SQUAD_TRANSCRIPTS")
    if env:
        return pathlib.Path(env)
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))
    return pathlib.Path.home() / ".claude/projects" / slug


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


def parse_run(path: pathlib.Path, agent: str | None = None, delegations_only=False) -> dict | None:
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
                item = {"ts": ts, "kind": "tool", "tool": name, "summary": summarize_tool(name, inp)}
                if name in ("Write", "Edit"):
                    f = rel(inp.get("file_path", ""))
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
                if item and c.get("is_error"):
                    item["error"] = True
    updated = path.stat().st_mtime
    meaningful = [r for r in rows if r.get("type") in ("assistant", "user")]
    last = meaningful[-1] if meaningful else rows[-1]
    last_content = (last.get("message") or {}).get("content")
    ended_turn = last.get("type") == "assistant" and isinstance(last_content, list) and all(
        x.get("type") != "tool_use" for x in last_content)
    recent = (time.time() - updated) < RUNNING_WINDOW_S
    if delegations_only:
        status = "coordenando"
    elif ended_turn and (time.time() - updated) > 10:
        status = "concluído"
    else:
        status = "trabalhando" if recent or not ended_turn else "aguardando"
    return {
        "id": path.stem.replace("agent-", ""),
        "agent": agent or resolve_agent(meta, first_prompt),
        "description": meta.get("description", ""),
        "model": meta.get("model", ""),
        "status": status,
        "started": rows[0].get("timestamp"),
        "updated": datetime.fromtimestamp(updated, timezone.utc).isoformat(timespec="seconds"),
        "toolCount": tool_count,
        "files": files,
        "activity": activity[-80:],
    }


def collect_runs() -> list[dict]:
    base = transcripts_root()
    runs = []
    for path in sorted(base.glob("*/subagents/agent-*.jsonl")):
        run = parse_run(path)
        if run:
            runs.append(run)
    # Sessão principal = Orquestrador (apenas delegações)
    for path in sorted(base.glob("*.jsonl")):
        if (base / path.stem / "subagents").exists():
            run = parse_run(path, agent="orquestrador", delegations_only=True)
            if run and run["toolCount"]:
                runs.append(run)
    return runs


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
            return self._json({
                "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "log": read_jsonl(LOG),
                "gates": collect_gates(),
                "runs": collect_runs(),
                "handoffs": collect_handoffs(),
            })
        if self.path.startswith("/api/policy"):
            return self._json({
                "gates": (ROOT / "docs/squad/gates.md").read_text(encoding="utf-8"),
                "constituicao": (ROOT / "CLAUDE.md").read_text(encoding="utf-8"),
            })
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/human"):
            return self._json({"error": "not found"}, 404)
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        action = data.get("action")
        if action not in ("APPROVE", "RETURN"):
            return self._json({"error": "action deve ser APPROVE ou RETURN"}, 400)
        entry = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent": "humano",
            "type": "human",
            "title": data.get("title") or ("Humano aceitou a recomendação" if action == "APPROVE" else "Humano devolveu a etapa"),
            "detail": data.get("note", ""),
            "gate": data.get("gate"),
            "recommendation": action,
        }
        entry = {k: v for k, v in entry.items() if v not in (None, "")}
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return self._json(entry, 201)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7070)
    port = ap.parse_args().port
    print(f"Squad Control em http://localhost:{port}  (transcrições: {transcripts_root()})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
