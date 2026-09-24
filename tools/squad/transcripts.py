"""Leitura incremental das transcrições do Claude Code (D14, ADR-017, contrato §9.3/§9.5).

Cada arquivo `.jsonl` é lido uma única vez do início; nas consultas seguintes só os bytes acrescentados desde o último
offset são decodificados (a sessão principal do Orquestrador passa de 30 MB e muda a cada ação — reparsear por mtime
não cabe no orçamento de 300 ms do `/api/live`). O estado acumulado por arquivo reproduz exatamente o que
`server.parse_run`/`scan_transcript`/`completed_agent_ids` calculavam lendo o arquivo inteiro.
"""
import collections
import json
import os
import pathlib
import re
import shlex

HEREDOC_WRITE = re.compile(r"(?:cat|tee)\s*>{1,2}\s*['\"]?([\w./-]+\.\w+)")
COMPLETED_RE = re.compile(r"<task-id>(\w+)</task-id>\\n<tool-use-id>[^<]*</tool-use-id>\\n<output-file>[^<]*</output-file>\\n<status>completed</status>")
NOTIF_RE = re.compile(r"<task-id>(\w+)</task-id>.*?<status>(\w+)</status>")
AGENT_ID_RE = re.compile(r"agentId:\s*(\w+)")
LOGPY_TITLE = re.compile(r"""--title[ =](?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))""")
LOGPY_AGENT = re.compile(r"--agent[ =]['\"]?([\w-]+)")

# §9.5: segredos mascarados em comandos exibidos.
SECRET_PATTERNS = [
    (re.compile(r"(?i)((?:token|secret|password|passwd|api[_-]?key)=)\S+"), r"\1***"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "***"),
    (re.compile(r"sk-[A-Za-z0-9-]{20,}"), "***"),
    (re.compile(r"Bearer \S+"), "Bearer ***"),
]


def mask(text: str) -> str:
    for rx, rep in SECRET_PATTERNS:
        text = rx.sub(rep, text or "")
    return text


def logpy_calls(command: str) -> list[tuple[str, str]]:
    """(agent, title) de cada chamada a log.py dentro de um comando Bash (mesma regra de server.logpy_calls)."""
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


def is_model_id(model) -> bool:
    return bool(model) and model != "<synthetic>" and not str(model).startswith("<")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


class TranscriptState:
    """Estado acumulado de uma transcrição. `rel`/`summarize` vêm do servidor (mesma formatação de antes)."""

    def __init__(self, path: pathlib.Path, rel, summarize):
        self.path, self._rel, self._summarize = path, rel, summarize
        self.reset()

    def reset(self):
        self.offset, self.ino, self.size, self.mtime = 0, None, -1, -1.0
        self.rows = 0
        self.started = None
        self.first_prompt = ""        # parse_run: 1º user com content str
        self.first_prompt_any = ""    # scan_transcript: 1º user com texto (str ou lista)
        self._fp_any_done = False
        self.activity: collections.deque = collections.deque(maxlen=80)   # parse_run (texto incluso)
        self.tools: collections.deque = collections.deque(maxlen=80)      # só ferramentas (Orquestrador §9.3)
        self.pending: dict[str, dict] = {}
        self.files: list[str] = []
        self.tool_count = 0
        self.agent_tool_count = 0
        self.models: dict[str, int] = {}
        self.calls: list[dict] = []
        self.commands: collections.deque = collections.deque(maxlen=5)
        self.last_type = None
        self.ended_turn = False
        self.last_ts = None
        self.completed: set[str] = set()
        self.notified: dict[str, str] = {}      # task-id -> ts da última notificação (qualquer status)
        self.launched: dict[str, dict] = {}     # agentId -> {description, since, toolUseId}
        self._agent_uses: dict[str, dict] = {}  # tool_use id de Agent -> {description, since}

    # ------------------------------------------------------------------ leitura
    def refresh(self) -> bool:
        """Lê só o que foi acrescentado. Devolve True se algo mudou."""
        try:
            st = self.path.stat()
        except OSError:
            return False
        if st.st_size == self.size and st.st_mtime == self.mtime:
            return False
        if st.st_ino != self.ino or st.st_size < self.offset:
            self.reset()
            self.ino = st.st_ino
        self.mtime = st.st_mtime
        with self.path.open("rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end >= 0:
            for raw in chunk[:end].split(b"\n"):
                self._line(raw.decode("utf-8", errors="ignore"))
            self.offset += end + 1
        self.size = st.st_size
        return True

    def _line(self, line: str):
        if not line.strip():
            return
        if "<task-notification>" in line:
            self.completed.update(COMPLETED_RE.findall(line))
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(r, dict):
            return
        self.rows += 1
        typ = r.get("type")
        msg = r.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        ts = r.get("timestamp")
        if self.rows == 1:
            self.started = ts
        if ts:
            self.last_ts = ts
        if typ == "user":
            if isinstance(content, str) and not self.first_prompt:
                self.first_prompt = content
            if not self._fp_any_done:
                if isinstance(content, str):
                    self.first_prompt_any, self._fp_any_done = content, bool(content)
                elif isinstance(content, list):
                    self.first_prompt_any = next((c.get("text", "") for c in content if c.get("type") == "text"), "")
                    self._fp_any_done = bool(self.first_prompt_any)
            text = _text_of(content)
            if "<task-notification>" in text:
                for task, status in NOTIF_RE.findall(text.replace("\n", " ")):
                    self.notified[task] = ts
        if typ in ("assistant", "user"):
            self.last_type = typ
            self.ended_turn = typ == "assistant" and isinstance(content, list) and all(
                x.get("type") != "tool_use" for x in content)
        model = msg.get("model") if isinstance(msg, dict) else None
        counted = typ == "assistant" and is_model_id(model)
        if counted:
            self.models[model] = self.models.get(model, 0) + 1
        if not isinstance(content, list):
            return
        for c in content:
            t = c.get("type")
            if typ == "assistant" and t == "tool_use":
                name, inp = c.get("name", ""), c.get("input") or {}
                if counted and name == "Bash" and "log.py" in inp.get("command", ""):
                    for agent, title in logpy_calls(inp.get("command", "")):
                        self.calls.append({"ts": ts, "agent": agent, "title": title, "model": model})
                self.tool_count += 1
                if name == "Agent":
                    self.agent_tool_count += 1
                    self._agent_uses[c.get("id")] = {"description": inp.get("description", ""), "since": ts,
                                                     "toolUseId": c.get("id")}
                detail = ""
                if name in ("Bash", "Edit", "Grep", "Glob"):
                    detail = mask(inp.get("command") or inp.get("old_string") or inp.get("pattern") or "")[:400]
                item = {"ts": ts, "kind": "tool", "tool": name, "summary": self._summarize(name, inp),
                        "pending": True, "detail": detail}
                written = [self._rel(inp.get("file_path", ""))] if name in ("Write", "Edit") else []
                if name == "Bash":
                    written = [w for w in HEREDOC_WRITE.findall(inp.get("command", "")) if not w.startswith("/dev/")]
                    self.commands.append({"item": item, "label": inp.get("description") or "",
                                          "command": mask(inp.get("command", ""))[:200]})
                for f in written:
                    if f not in self.files:
                        self.files.append(f)
                self.pending[c.get("id")] = item
                self.activity.append(item)
                self.tools.append(item)
            elif typ == "assistant" and t == "text":
                text = (c.get("text") or "").strip()
                if text:
                    self.activity.append({"ts": ts, "kind": "text", "summary": text[:600]})
            elif typ == "user" and t == "tool_result":
                tid = c.get("tool_use_id")
                item = self.pending.pop(tid, None)
                if item:
                    item["pending"] = False
                    item["endedAt"] = ts
                    if c.get("is_error"):
                        item["error"] = True
                use = self._agent_uses.pop(tid, None)
                if use:
                    txt = c.get("content")
                    txt = txt if isinstance(txt, str) else _text_of(txt)
                    m = AGENT_ID_RE.search(txt)
                    if m and "Async agent launched" in txt:
                        self.launched[m.group(1)] = use

    # ------------------------------------------------------------------ consultas
    def current(self, tools_only=False):
        items = self.tools if tools_only else self.activity
        return next((a for a in reversed(items) if a["kind"] == "tool" and a.get("pending")), None)

    def pending_items(self) -> list[dict]:
        return [i for i in self.pending.values()]


class TranscriptStore:
    """Estados por caminho, com remoção dos arquivos que sumiram."""

    def __init__(self, rel, summarize):
        self._rel, self._summarize = rel, summarize
        self.states: dict[str, TranscriptState] = {}

    def get(self, path: pathlib.Path) -> TranscriptState:
        key = str(path)
        st = self.states.get(key)
        if st is None:
            st = self.states[key] = TranscriptState(path, self._rel, self._summarize)
        st.refresh()
        return st

    def prune(self, alive: set[str]):
        for k in [k for k in self.states if k not in alive]:
            self.states.pop(k, None)


def file_mtime(path: pathlib.Path) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None
