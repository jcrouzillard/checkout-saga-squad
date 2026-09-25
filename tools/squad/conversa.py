"""Conversa direta com o Orquestrador (D17, ADR-020, docs/contracts/conversa-com-o-orquestrador.md).

Sessão dedicada, somente leitura, fora do plantão e fora de `run_agent.py`:
- cada pergunta dispara um processo do runner (`SQUAD_CHAT_RUNNER`, senão `SQUAD_RUNNER`, senão `claude`) que retoma
  a sessão da conversa (`claude -p --resume <uuid>` / `codex exec resume <thread>`), com cwd dedicado
  `<DATA_ROOT>/.squad/conversas/.sessao/` e ambiente do filho por lista de permissão;
- o histórico é gravado por nós em `<DATA_ROOT>/.squad/conversas/<id>.jsonl` (append-only, fora do git, sem demanda);
- o modelo só PROPÕE destravar (bloco ```destravar); o servidor valida contra a lista fechada do §6.1 e só grava no
  `decisions.jsonl` na confirmação do humano, pela mesma função de `/api/human` e `/api/demand/control`.

Nada aqui chama `log.py`, `run_agent.py`, `github_sync.py`, `gitflow.py`, `testenv.py` nem `prod.py`.
Somente stdlib. `SQUAD_CHAT_RUNNER=fake` + `SQUAD_CHAT_FAKE=<script>` roda um runner simulado com os argumentos do
Claude (testes determinísticos).
"""
import json
import os
import pathlib
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import alerts as al  # noqa: E402
import evidence_rules as er  # noqa: E402
import transcripts as tr  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROMPT_FILE = ROOT / "docs/squad/prompts/conversa.md"

ID_RE = re.compile(r"^c-[0-9a-f]{12}$")
PID_RE = re.compile(r"^p-[0-9a-f]{6}$")
MAX_BODY = 32 * 1024          # corpo de POST das rotas /api/conversas* (checado pelo Content-Length)
MAX_TEXT = 8000               # mensagem do humano (após strip)
MAX_NOTE = 2000               # nota editável da confirmação
MAX_MESSAGES = 2000           # teto por conversa
MAX_FILE = 4 * 1024 * 1024
CONTEXT_MAX = 24 * 1024
HISTORY_MSGS, HISTORY_MAX = 20, 16 * 1024
RECENT_EVENTS, TITLE_MAX = 40, 160
PING_S = 15

TOOLS = ["Read", "Glob", "Grep"]
DENY_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"]
# G1-D17 ressalva 1: nunca `Read(~/**)` (DATA_ROOT fica sob o $HOME); negações pontuais dos segredos pessoais.
HOME_DENY_DIRS = [".ssh", ".aws", ".config", ".claude", ".codex", ".gnupg", ".docker", ".kube", ".azure",
                  "Library/Keychains"]
HOME_DENY_FILES = [".netrc", ".gitconfig", ".git-credentials", ".npmrc", ".pypirc", ".pgpass"]
ENV_ALLOW = {"PATH", "HOME", "USER", "LANG", "TERM", "TMPDIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR"}
ENV_PREFIX = ("LC_", "ANTHROPIC_", "CLAUDE_CODE_", "OPENAI_")
RUNNERS = ("claude", "codex", "fake")
CODEX_WARNING = ("Com o runner codex o Orquestrador pode ler qualquer arquivo desta máquina (o sandbox read-only do "
                 "Codex não restringe leitura). Segredos são filtrados da resposta, mas prefira o runner claude.")
MARK = "```destravar"
UNLOCK_KINDS = {"gate-return", "human-required", "cycle-limit"}
REASONS = ("nao_destravavel", "acao_nao_permitida", "alvo_inexistente", "ja_decidido", "formato_invalido")
REASON_TEXT = {"nao_destravavel": "este item não pode ser destravado pela conversa",
               "acao_nao_permitida": "ação não permitida para este item",
               "alvo_inexistente": "alerta ou demanda não encontrado",
               "ja_decidido": "o humano já decidiu este gate",
               "formato_invalido": "proposta em formato inválido"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ChatError(Exception):
    """Erro de API no formato {"error", "code"} (contrato §7)."""

    def __init__(self, status: int, code: str, error: str, **extra):
        super().__init__(error)
        self.status, self.code, self.error, self.extra = status, code, error, extra

    def payload(self) -> dict:
        return {"error": self.error, "code": self.code, **self.extra}


# ================================================================ runner e comando (§3.1)
def default_runner() -> str:
    r = (os.environ.get("SQUAD_CHAT_RUNNER") or os.environ.get("SQUAD_RUNNER") or "claude").strip().lower()
    return r if r in RUNNERS else "claude"


def requested_model() -> str | None:
    return os.environ.get("SQUAD_CHAT_MODEL") or None


def timeout_s() -> float:
    try:
        return float(os.environ.get("SQUAD_CHAT_TIMEOUT_S") or 120)
    except ValueError:
        return 120.0


def binary(runner: str) -> str | None:
    """Executável do runner; None = indisponível (verificado por shutil.which no envio)."""
    if runner == "fake":
        script = os.environ.get("SQUAD_CHAT_FAKE")
        return script if script and pathlib.Path(script).is_file() else None
    return shutil.which(runner)


def available(runner: str) -> bool:
    return binary(runner) is not None


def isolation(runner: str) -> dict:
    """G1-D17 ressalva 3: o runner codex tem isolamento de leitura menor (a UI mostra o aviso)."""
    if runner == "codex":
        return {"readIsolation": "reduzida", "isolationWarning": CODEX_WARNING}
    return {"readIsolation": "restrita", "isolationWarning": None}


def child_env(environ: dict | None = None) -> dict:
    """Ambiente do filho por LISTA DE PERMISSÃO (nunca GH_TOKEN, GITHUB_TOKEN, SQUAD_*)."""
    src = os.environ if environ is None else environ
    return {k: v for k, v in src.items() if k in ENV_ALLOW or k.startswith(ENV_PREFIX)}


def claude_deny_paths(data_root: pathlib.Path) -> list[str]:
    root = str(pathlib.Path(data_root).resolve())
    # G1-D17 ressalva 2: caminho absoluto em regra do Claude Code usa `//` (um `/` só é relativo ao projeto).
    out = [f"Read(/{root}/.env)", f"Read(/{root}/.env.*)", f"Read(/{root}/.git/**)"]
    out += [f"Read(~/{d}/**)" for d in HOME_DENY_DIRS] + [f"Read(~/{f})" for f in HOME_DENY_FILES]
    return out


def system_prompt() -> str:
    try:
        return PROMPT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "Você é o Orquestrador da squad respondendo ao humano num canal direto, somente leitura."


def build_cmd(runner: str, conversa: dict, turno: dict) -> list[str]:
    """Comando do turno (testável sem executar).

    conversa: {"dataRoot", "sessionId" (uuid do claude | threadId do codex | None), "model"?}
    turno:    {"prompt" (contexto + mensagem), "resume" (bool), "systemPrompt"?}
    """
    data_root = str(pathlib.Path(conversa["dataRoot"]).resolve())
    model = conversa.get("model")
    prompt = turno["prompt"]
    sp = turno.get("systemPrompt") if turno.get("systemPrompt") is not None else system_prompt()
    if runner == "codex":
        if turno.get("resume") and conversa.get("sessionId"):
            cmd = ["codex", "exec", "resume", conversa["sessionId"], "--json", "-c", 'sandbox_mode="read-only"']
            return cmd + (["-m", model] if model else []) + [prompt]
        cmd = ["codex", "exec", "--json", "-s", "read-only", "-C", data_root, "--skip-git-repo-check"]
        return cmd + (["-m", model] if model else []) + [f"{sp}\n\n{prompt}"]
    exe = ["claude"] if runner == "claude" else [sys.executable, binary("fake") or "fake-runner"]
    cmd = exe + ["-p", prompt, "--output-format", "stream-json", "--include-partial-messages", "--verbose",
                 "--tools", *TOOLS,
                 "--disallowedTools", *DENY_TOOLS,
                 "--disallowedTools", *claude_deny_paths(pathlib.Path(data_root)),
                 "--add-dir", data_root, "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                 "--append-system-prompt", sp]
    if model:
        cmd += ["--model", model]
    sid = conversa["sessionId"]
    return cmd + (["--resume", sid] if turno.get("resume") else ["--session-id", sid])


# ================================================================ máscara (contexto e saída do codex)
_KEY: bytes | None = None


def mask(text: str, data_root: pathlib.Path | None = None) -> str:
    """SECRET_PATTERNS do transcripts + máscara do evidence_rules (segredos e dados pessoais)."""
    global _KEY
    text = tr.mask(text or "")
    try:
        if _KEY is None:
            _KEY = er.load_key(data_root or ROOT)
        return er.mask_text(text, _KEY)[0]
    except Exception:   # a máscara nunca derruba a conversa; SECRET_PATTERNS já foi aplicado
        return text


# ================================================================ contexto injetado (§4)
def _effective_titles(rows: list[dict]) -> dict:
    titles = {}
    for e in rows:
        if e.get("type") == "task" and e.get("agent") == "humano" and e.get("id"):
            titles[e["id"]] = (e.get("title") or "").replace("Demanda: ", "")
        elif e.get("type") == "edit" and e.get("demand") in titles and (e.get("changes") or {}).get("title"):
            titles[e["demand"]] = e["changes"]["title"]
    return titles


def paused(rows: list[dict], d: str) -> bool:
    last = None
    for e in rows:
        if e.get("type") == "control" and e.get("demand") == d and e.get("action") in ("pause", "resume"):
            last = e["action"]
    return last == "pause"


def _stage(rows: list[dict], rules, d: str) -> str:
    if d in rules.canceled:
        return "cancelada"
    if d in rules.delivered:
        return "entregue"
    if rules.reviews.get(d):
        return "PR aguardando revisão humana"
    gates = [e for e in rows if e.get("type") == "gate" and e.get("demand") == d]
    if gates:
        g = gates[-1]
        return f"{g.get('gate')} {g.get('recommendation') or ''}".strip()
    if any(e.get("type") == "start" and e.get("demand") == d for e in rows):
        return "em andamento"
    task = next((e for e in rows if e.get("id") == d and e.get("type") == "task"), {})
    return "backlog" if task.get("backlog") else "aguardando início"


def build_context(state: dict, data_root: pathlib.Path | None = None) -> str:
    rows, rules = state["rows"], state["rules"]
    codes = rules.codes
    titles = _effective_titles(rows)
    demands = []
    for d, code in codes.items():
        closed = d in rules.canceled or d in rules.delivered
        p = not closed and paused(rows, d)
        item = {"code": code, "id": d, "titulo": al.trunc(titles.get(d), TITLE_MAX), "estagio": _stage(rows, rules, d),
                "pausada": p}
        if p:
            item.update(destravavel=True, acoes=["resume"])
        demands.append(item)
    alerts = []
    for a in state.get("alerts") or []:
        acts = gate_actions(rules, a) if a.get("kind") in UNLOCK_KINDS or set(a.get("kinds") or []) & UNLOCK_KINDS else []
        alerts.append({"id": a.get("id"), "regra": al.KIND_RULE.get(a.get("kind"), a.get("kind")),
                       "demanda": a.get("code"), "gate": a.get("gate"), "titulo": al.trunc(a.get("title"), TITLE_MAX),
                       "destravavel": bool(acts), "acoes": acts})
    agents = []
    for a in state.get("agents") or []:
        task = a.get("task") or {}
        agents.append({"agente": a.get("agent"), "estado": a.get("state"), "demanda": task.get("code"),
                       "passo": al.trunc(task.get("step") or a.get("lastActivity"), TITLE_MAX)})
    te_state = state.get("testEnv") or {}
    recent = [{"ts": e.get("ts"), "agente": e.get("agent"), "tipo": e.get("type"),
               "demanda": codes.get(e.get("demand")) if e.get("demand") else None,
               "titulo": al.trunc(e.get("title"), TITLE_MAX)} for e in rows[-RECENT_EVENTS:] if isinstance(e, dict)]
    ctx = {"demandas": demands, "alertas": alerts, "agentes": agents,
           "ambienteDeTeste": {"estado": te_state.get("state"), "demanda": te_state.get("code")},
           "eventosRecentes": recent}

    def dump() -> str:
        body = json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))
        return f'<dados_da_squad gerado="{now_iso()}">\n{mask(body, data_root)}\n</dados_da_squad>'

    out = dump()
    # ≤ 24 KB: corta primeiro eventos antigos, depois demandas encerradas, depois as mais antigas.
    while len(out.encode()) > CONTEXT_MAX and ctx["eventosRecentes"]:
        ctx["eventosRecentes"] = ctx["eventosRecentes"][len(ctx["eventosRecentes"]) // 4 + 1:]
        out = dump()
    if len(out.encode()) > CONTEXT_MAX:
        ctx["demandas"] = [x for x in ctx["demandas"] if x["estagio"] not in ("cancelada", "entregue")]
        out = dump()
    while len(out.encode()) > CONTEXT_MAX and ctx["demandas"]:
        ctx["demandas"] = ctx["demandas"][len(ctx["demandas"]) // 4 + 1:]
        out = dump()
    return out


def history_block(records: list[dict]) -> str:
    """Últimas 20 mensagens (≤ 16 KB) para reabrir uma sessão perdida (sessionReset)."""
    msgs = [r for r in records if r.get("t") == "msg" and (r.get("text") or "").strip()][-HISTORY_MSGS:]
    lines = [f"{'Humano' if m['role'] == 'humano' else 'Orquestrador'}: {m['text']}" for m in msgs]
    while lines and len("\n\n".join(lines).encode()) > HISTORY_MAX:
        lines.pop(0)
    if not lines:
        return ""
    return "<historico_da_conversa>\n" + "\n\n".join(lines) + "\n</historico_da_conversa>"


def turn_prompt(context: str, text: str, history: str = "") -> str:
    parts = [context] + ([history] if history else []) + [f"Pergunta do humano:\n{text}"]
    return "\n\n".join(parts)


# ================================================================ destravar (§6)
def gate_actions(rules, alert: dict) -> list[str]:
    """Ações aceitas para um alerta de gate aberto (lista fechada §6.1; G1-D17: B1 puro só OVERRIDE)."""
    kinds = set(alert.get("kinds") or [alert.get("kind")])
    if not kinds & UNLOCK_KINDS:
        return []
    d, gname = alert.get("demand"), alert.get("gate")
    if d and (d in rules.canceled or d in rules.delivered):
        return []
    gl = rules.gates.get((d, gname)) or []
    if not gl:
        return []
    gi, g = gl[-1]
    if any(i > gi for i, _ in rules.humans.get((d, gname), [])):
        return []
    if g.get("recommendation") == "RETURN":
        return ["APPROVE", "OVERRIDE"] if kinds & {"human-required", "cycle-limit"} else ["OVERRIDE"]
    if g.get("recommendation") == "APPROVE" and kinds & {"human-required", "cycle-limit"}:
        return ["APPROVE"]
    return []


def _resolve_demand(ref, codes: dict) -> str | None:
    ref = str(ref or "").strip()
    if re.fullmatch(r"[0-9a-f]{12}", ref) and ref in codes:
        return ref
    by_code = {v.upper(): k for k, v in codes.items()}
    return by_code.get(ref.upper())


def validate_proposal(raw, state: dict) -> dict:
    """Converte o bloco do modelo em `proposal` validada contra o estado atual (§6.1/§6.2)."""
    rows, rules = state["rows"], state["rules"]
    out = {"alert": None, "demand": None, "gate": None, "action": None, "note": "", "valid": False, "reason": None}
    if not isinstance(raw, dict):
        return {**out, "reason": "formato_invalido"}
    action = raw.get("acao") if isinstance(raw.get("acao"), str) else None
    note = raw.get("nota") if isinstance(raw.get("nota"), str) else ""
    out.update(action=action, note=note[:MAX_NOTE])
    alert_ref = raw.get("alerta")
    demand_ref = raw.get("demanda")
    if not action or (not alert_ref and not demand_ref) or (alert_ref is not None and not isinstance(alert_ref, str)):
        return {**out, "reason": "formato_invalido"}
    if alert_ref:
        event = alert_ref.split(":", 1)[-1]
        opened = list(rules.open.values())
        a = next((x for x in opened if x.get("id") == alert_ref), None) or next(
            (x for x in opened if (x.get("source") or {}).get("event") == event and x.get("gate")), None)
        if a is None:
            other = next((x for x in state.get("alerts") or [] if x.get("id") == alert_ref), None)
            if other is not None:          # B4, B5, A1–A5: existem, mas não se destravam por aqui
                return {**out, "alert": alert_ref, "demand": other.get("demand"), "gate": other.get("gate"),
                        "reason": "nao_destravavel"}
            g = next((e for e in rows if e.get("id") == event and e.get("type") == "gate"), None)
            if g is not None:
                key = (g.get("demand") or None, g.get("gate"))
                gi = next((i for i, e in (rules.gates.get(key) or []) if e.get("id") == event), None)
                decided = gi is not None and any(i > gi for i, _ in rules.humans.get(key, []))
                return {**out, "alert": alert_ref, "demand": key[0], "gate": key[1],
                        "reason": "ja_decidido" if decided else "nao_destravavel"}
            return {**out, "alert": alert_ref, "reason": "alvo_inexistente"}
        out.update(alert=a["id"], demand=a.get("demand"), gate=a.get("gate"))
        if a.get("kind") not in UNLOCK_KINDS and not set(a.get("kinds") or []) & UNLOCK_KINDS:
            return {**out, "reason": "nao_destravavel"}
        key = (a.get("demand"), a.get("gate"))
        gl = rules.gates.get(key) or []
        if gl and any(i > gl[-1][0] for i, _ in rules.humans.get(key, [])):
            return {**out, "reason": "ja_decidido"}
        acts = gate_actions(rules, a)
        if not acts:
            return {**out, "reason": "nao_destravavel"}
        if action not in acts:
            return {**out, "reason": "acao_nao_permitida"}
        return {**out, "valid": True}
    d = _resolve_demand(demand_ref, rules.codes)
    if d is None:
        return {**out, "reason": "alvo_inexistente"}
    out["demand"] = d
    if action != "resume":
        return {**out, "reason": "acao_nao_permitida"}
    if d in rules.canceled or d in rules.delivered or not paused(rows, d):
        return {**out, "reason": "nao_destravavel"}
    return {**out, "valid": True}


def split_proposal(raw_text: str) -> tuple[str, dict | None, bool]:
    """(texto exibido, bloco JSON da 1ª proposta ou None, havia bloco). Demais blocos são removidos e ignorados."""
    text, block, found = raw_text or "", None, False
    pat = re.compile(r"```destravar[ \t]*\n?(.*?)(?:```|\Z)", re.S)
    m = pat.search(text)
    if m:
        found = True
        try:
            block = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            block = "invalido"
        text = pat.sub("", text)
    return text.strip(), block, found


def streaming_display(raw: str) -> str:
    """Parte já exibível durante o streaming: corta no início do bloco ```destravar e segura um prefixo parcial dele."""
    i = raw.find(MARK)
    if i >= 0:
        return raw[:i]
    for k in range(min(len(MARK) - 1, len(raw)), 0, -1):
        if raw.endswith(MARK[:k]):
            return raw[:-k]
    return raw


# ================================================================ armazenamento (§5)
class Store:
    def __init__(self, data_root: pathlib.Path):
        self.data_root = pathlib.Path(data_root).resolve()
        self.dir = self.data_root / ".squad/conversas"
        self.lock = threading.RLock()
        self._seq: dict[str, int] = {}

    @property
    def session_cwd(self) -> pathlib.Path:
        """cwd absoluto e estável (G1-D17): o --resume do Claude procura a sessão pelo diretório do cwd."""
        p = self.dir / ".sessao"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def path(self, cid: str) -> pathlib.Path:
        if not ID_RE.match(cid or ""):
            raise ChatError(404, "conversa_nao_encontrada", "conversa não encontrada")
        return self.dir / f"{cid}.jsonl"

    def exists(self, cid: str) -> bool:
        return ID_RE.match(cid or "") is not None and self.path(cid).is_file()

    def records(self, cid: str) -> list[dict]:
        p = self.path(cid)
        if not p.is_file():
            raise ChatError(404, "conversa_nao_encontrada", "conversa não encontrada")
        out = []
        with p.open(encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def _write(self, cid: str, rec: dict):
        p = self.path(cid)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def append(self, cid: str, rec: dict) -> dict:
        with self.lock:
            if cid not in self._seq:
                self._seq[cid] = max([r.get("seq") or 0 for r in self.records(cid)] + [0])
            self._seq[cid] += 1
            rec = {"t": rec.pop("t"), "seq": self._seq[cid], **rec}
            self._write(cid, rec)
            return rec

    def create(self, runner: str, model: str | None) -> dict:
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            while True:
                cid = f"c-{uuid.uuid4().hex[:12]}"
                if not self.path(cid).exists():
                    break
            meta = {"t": "meta", "id": cid, "createdAt": now_iso(), "runner": runner, "modelRequested": model,
                    "sessionId": str(uuid.uuid4()) if runner != "codex" else None, "v": 1}
            self._write(cid, meta)
            self._seq[cid] = 0
            return meta

    @staticmethod
    def meta(records: list[dict]) -> dict:
        return next((r for r in records if r.get("t") == "meta"), {})

    @staticmethod
    def session(records: list[dict]) -> tuple[str | None, bool]:
        """(sessão atual, já usada por algum processo) — usada → --resume."""
        sid = Store.meta(records).get("sessionId")
        for r in records:
            if r.get("t") == "meta-update" and r.get("sessionId"):
                sid = r["sessionId"]
        used = any(r.get("t") == "msg" and r.get("role") == "orquestrador" and r.get("sessionId") == sid
                   for r in records) if sid else False
        return sid, used

    def full(self, cid: str, records: list[dict]) -> bool:
        msgs = sum(1 for r in records if r.get("t") == "msg")
        try:
            size = self.path(cid).stat().st_size
        except OSError:
            size = 0
        return msgs >= MAX_MESSAGES or size >= MAX_FILE

    @staticmethod
    def title(records: list[dict]) -> str:
        first = next((r.get("text") or "" for r in records if r.get("t") == "msg" and r.get("role") == "humano"), "")
        first = " ".join(first.split())
        return first if len(first) <= 80 else first[:79] + "…"

    def summary(self, cid: str) -> dict:
        recs = self.records(cid)
        meta = self.meta(recs)
        msgs = [r for r in recs if r.get("t") == "msg"]
        last_o = next((m for m in reversed(msgs) if m.get("role") == "orquestrador"), None)
        updated = max([r.get("ts") or "" for r in recs] + [meta.get("createdAt") or ""])
        return {"id": cid, "title": self.title(recs), "createdAt": meta.get("createdAt"), "updatedAt": updated,
                "messages": len(msgs), "lastStatus": (last_o or {}).get("status"), "runner": meta.get("runner")}

    def list(self) -> list[dict]:
        out = []
        if self.dir.is_dir():
            for p in self.dir.glob("c-*.jsonl"):
                if ID_RE.match(p.stem):
                    try:
                        out.append((self.summary(p.stem), p.stat().st_mtime_ns))
                    except (ChatError, OSError):
                        continue
        # QA-D17-1: `updatedAt` tem resolução de segundo (formato do contrato §5); no empate, desempata pela última
        # escrita no arquivo (mtime em ns, cada append faz fsync) e depois pelo createdAt — nunca pela ordem do glob.
        out.sort(key=lambda it: (it[0]["updatedAt"] or "", it[1], it[0]["createdAt"] or "", it[0]["id"]), reverse=True)
        return [s for s, _ in out]

    def recover(self) -> int:
        """Na subida: turno com mensagem do humano sem resposta é fechado com `interrompida` (§3.2)."""
        n = 0
        if not self.dir.is_dir():
            return 0
        with self.lock:
            for p in self.dir.glob("c-*.jsonl"):
                if not ID_RE.match(p.stem):
                    continue
                recs = self.records(p.stem)
                msgs = [r for r in recs if r.get("t") == "msg"]
                answered = {m.get("turn") for m in msgs if m.get("role") == "orquestrador"}
                meta = self.meta(recs)
                for m in msgs:
                    if m.get("role") == "humano" and m.get("turn") not in answered:
                        self.append(p.stem, {"t": "msg", "turn": m["turn"], "role": "orquestrador", "ts": now_iso(),
                                             "text": "", "status": "interrompida", "runner": meta.get("runner"),
                                             "error": "servidor reiniciado durante o turno"})
                        n += 1
        return n


# ================================================================ turno ativo, streaming e processo (§3.2)
class Turn:
    def __init__(self, cid: str, turn: int, t0: float):
        self.cid, self.turn, self.t0 = cid, turn, t0
        self.cond = threading.Condition()
        self.events: list[tuple[int, str, dict]] = []
        self.phase, self.tool, self.sent = "iniciando", None, ""
        self.done, self.final, self.final_event = False, None, None
        self.proc: subprocess.Popen | None = None
        self.stop_reason: str | None = None     # "cancelada" | "tempo_esgotado"
        self.first_text_ms: int | None = None

    # estado (phase/tool/sent) e eventos mudam juntos sob a mesma trava: o SSE tira um retrato consistente
    def emit(self, event: str, data: dict):
        with self.cond:
            self.events.append((len(self.events) + 1, event, data))
            self.cond.notify_all()

    def set_phase(self, phase: str, tool: dict | None = None):
        with self.cond:
            if phase == self.phase and tool == self.tool:
                return
            self.phase, self.tool = phase, tool
            self.emit("fase", {"phase": phase, **({"tool": tool} if tool else {})})

    def push_text(self, display: str):
        with self.cond:
            if not display.startswith(self.sent) or len(display) == len(self.sent):
                return
            delta = display[len(self.sent):]
            if not delta.strip() and not self.sent:
                return
            self.sent = display
            if self.first_text_ms is None:
                self.first_text_ms = round((time.monotonic() - self.t0) * 1000)
            if self.phase != "respondendo":
                self.set_phase("respondendo")
            self.emit("texto", {"delta": delta})

    def finish(self, message: dict):
        with self.cond:
            self.final = message
            if message.get("status") == "erro":
                self.final_event = ("erro", {"code": message.get("code") or "erro_runner",
                                             "error": message.get("error") or "falha no runner", "message": message})
            else:
                self.final_event = ("fim", {"message": message})
            self.events.append((len(self.events) + 1, *self.final_event))
            self.done = True
            self.cond.notify_all()

    def active_view(self) -> dict:
        return {"turn": self.turn, "phase": self.phase, "text": self.sent, "tool": self.tool}


class Engine:
    """Um turno ativo no servidor inteiro (§3.2). `state_fn()` devolve {rows, rules, alerts, agents, testEnv}."""

    def __init__(self, store: Store, state_fn, log_lock=None):
        self.store, self.state_fn = store, state_fn
        self.log_lock = log_lock or threading.RLock()
        self.lock = threading.Lock()
        self.active: Turn | None = None
        self.turns: dict[tuple[str, int], Turn] = {}

    # ---------------- consultas
    def busy(self) -> dict | None:
        a = self.active
        return {"conversa": a.cid, "turn": a.turn} if a and not a.done else None

    def turn(self, cid: str, n: int) -> Turn | None:
        return self.turns.get((cid, n))

    def view(self, cid: str, after: int = 0) -> dict:
        recs = self.store.records(cid)
        meta = self.store.meta(recs)
        a = self.active
        active = a.active_view() if a and not a.done and a.cid == cid else None
        return {"id": cid, "createdAt": meta.get("createdAt"), "runner": meta.get("runner"),
                **isolation(meta.get("runner")), "title": self.store.title(recs),
                "messages": [r for r in recs if r.get("t") in ("msg", "proposal") and (r.get("seq") or 0) > after],
                "active": active}

    # ---------------- envio
    def send(self, cid: str, text, t0: float | None = None) -> dict:
        t0 = time.monotonic() if t0 is None else t0
        if not isinstance(text, str) or not text.strip():
            raise ChatError(400, "mensagem_vazia", "mensagem vazia")
        text = text.strip()
        if len(text) > MAX_TEXT:
            raise ChatError(413, "mensagem_grande", f"mensagem acima de {MAX_TEXT} caracteres")
        recs = self.store.records(cid)
        meta = self.store.meta(recs)
        runner = meta.get("runner") or default_runner()
        with self.lock:
            if self.active and not self.active.done:
                raise ChatError(409, "turno_em_andamento", "outra conversa está respondendo",
                                conversa=self.active.cid, turn=self.active.turn)
            if self.store.full(cid, recs):
                raise ChatError(409, "conversa_cheia", "conversa cheia: abra uma nova conversa")
            n = max([r.get("turn") or 0 for r in recs if r.get("t") == "msg"] + [0]) + 1
            human = self.store.append(cid, {"t": "msg", "turn": n, "role": "humano", "ts": now_iso(), "text": text})
            if not available(runner):
                self.store.append(cid, {"t": "msg", "turn": n, "role": "orquestrador", "ts": now_iso(), "text": "",
                                        "status": "erro", "runner": runner, "code": "orquestrador_indisponivel",
                                        "error": f"runner {runner} indisponível (verifique `{runner} --version`)"})
                raise ChatError(503, "orquestrador_indisponivel",
                                f"Orquestrador indisponível: runner {runner} ausente (verifique `{runner} --version`)",
                                message=human)
            t = Turn(cid, n, t0)
            self.active = t
            self.turns[(cid, n)] = t
            for k in [k for k in self.turns if k != (cid, n)][:-20]:   # guarda só os últimos turnos em memória
                self.turns.pop(k, None)
        threading.Thread(target=self._run, args=(t, runner, text), daemon=True).start()
        return {"turn": n, "message": human, "stream": f"/api/conversas/{cid}/turnos/{n}/stream"}

    def cancel(self, cid: str, n: int) -> dict:
        t = self.turns.get((cid, n))
        if t is None or t.done:
            raise ChatError(409, "turno_encerrado", "turno já encerrado")
        t.stop_reason = t.stop_reason or "cancelada"
        self._kill(t)
        return {"status": "cancelando"}

    # ---------------- execução
    def _kill(self, t: Turn):
        p = t.proc
        if p is None or p.poll() is not None:
            return

        def killer():
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                return
            try:
                p.wait(3)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(p.pid, signal.SIGKILL)   # o grupo inteiro (netos também), mesmo se o líder já saiu
            except (ProcessLookupError, PermissionError):
                pass
        threading.Thread(target=killer, daemon=True).start()

    def _run(self, t: Turn, runner: str, text: str):
        cid = t.cid
        result = {"text": "", "tools": [], "model": None}
        reset = False
        try:
            recs = self.store.records(cid)
            meta = self.store.meta(recs)
            sid, used = self.store.session(recs)
            try:
                context = build_context(self.state_fn(), self.store.data_root)
            except Exception as e:   # sem estado da squad ainda assim responde (e diz que não sabe)
                context = f"<dados_da_squad erro=\"{type(e).__name__}\">{{}}</dados_da_squad>"
            model = meta.get("modelRequested")
            deadline = t.t0 + timeout_s()
            history = ""
            if runner == "codex" and not sid:
                used = False
            if runner != "codex" and not sid:
                sid, used = str(uuid.uuid4()), False
            result = self._attempt(t, runner, sid, used, turn_prompt(context, text), model, deadline)
            if used and result["code"] != 0 and not result["raw"] and not t.stop_reason and not result["timedOut"]:
                # sessão do fornecedor perdida: abre outra com o histórico recente (sessionReset)
                reset = True
                history = history_block([r for r in recs if not (r.get("t") == "msg" and r.get("turn") == t.turn)])
                sid = str(uuid.uuid4()) if runner != "codex" else None
                if sid:
                    self.store.append(cid, {"t": "meta-update", "sessionId": sid, "reason": "sessionReset"})
                result = self._attempt(t, runner, sid, False, turn_prompt(context, text, history), model, deadline)
            if runner == "codex" and result.get("threadId") and result["threadId"] != sid:
                sid = result["threadId"]
                self.store.append(cid, {"t": "meta-update", "sessionId": sid,
                                        "reason": "sessionReset" if reset else "threadStarted"})
            self._finish(t, runner, sid, reset, result)
        except Exception as e:  # nunca deixa o turno pendurado
            msg = {"t": "msg", "turn": t.turn, "role": "orquestrador", "ts": now_iso(), "text": t.sent.strip(),
                   "status": "erro", "runner": runner, "code": "erro_interno", "error": f"erro interno: {type(e).__name__}"}
            t.finish(self.store.append(cid, msg))
        finally:
            with self.lock:
                if self.active is t:
                    self.active = None

    def _attempt(self, t: Turn, runner: str, sid: str | None, resume: bool, prompt: str, model: str | None,
                 deadline: float) -> dict:
        conv = {"dataRoot": str(self.store.data_root), "sessionId": sid, "model": model}
        cmd = build_cmd(runner, conv, {"prompt": prompt, "resume": resume})
        if runner == "codex":
            cmd[0] = binary("codex") or "codex"
        elif runner == "claude":
            cmd[0] = binary("claude") or "claude"
        res = {"raw": "", "tools": [], "model": None, "code": None, "timedOut": False, "isError": False,
               "error": None, "threadId": None, "resultText": None, "sessionId": sid}
        try:
            proc = subprocess.Popen(cmd, cwd=str(self.store.session_cwd), env=child_env(), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        except OSError as e:
            res.update(code=127, isError=True, error=f"falha ao iniciar o runner: {e.strerror or e}")
            return res
        t.proc = proc
        if t.stop_reason:          # cancelado antes de o processo existir
            self._kill(t)
        q: queue.Queue = queue.Queue()
        err_tail: list[bytes] = []

        def read_out():
            for line in proc.stdout:
                q.put(line)
            q.put(None)

        def read_err():
            for line in proc.stderr:
                err_tail.append(line)
                del err_tail[:-40]
        threading.Thread(target=read_out, daemon=True).start()
        threading.Thread(target=read_err, daemon=True).start()
        if t.phase == "iniciando":
            t.set_phase("pensando")
        eof = False
        while not eof:
            if time.monotonic() > deadline and not res["timedOut"] and not t.stop_reason:
                res["timedOut"] = True
                t.stop_reason = "tempo_esgotado"
                self._kill(t)
            try:
                line = q.get(timeout=0.25)
            except queue.Empty:
                continue
            if line is None:
                eof = True
                break
            try:
                ev = json.loads(line.decode("utf-8", "replace"))
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(ev, dict):
                (self._on_codex if runner == "codex" else self._on_claude)(t, ev, res)
        try:
            res["code"] = proc.wait(5)
        except subprocess.TimeoutExpired:
            self._kill(t)
            res["code"] = proc.wait()
        if res["code"] != 0 and not res["error"]:
            tail = b"".join(err_tail).decode("utf-8", "replace").strip().splitlines()[-3:]
            res["error"] = mask(" ".join(tail))[:300] or f"runner saiu com código {res['code']}"
        if runner == "codex" and res["threadId"] and not res["model"]:
            res["model"] = codex_model(res["threadId"])
        return res

    # ---- Claude: stream-json (system/init, stream_event, assistant, result)
    def _on_claude(self, t: Turn, ev: dict, res: dict):
        typ = ev.get("type")
        if typ == "system" and ev.get("subtype") == "init":
            if ev.get("model") and not res["model"]:
                res["model"] = ev["model"]
            if t.phase == "iniciando":
                t.set_phase("pensando")
        elif typ == "stream_event":
            e = ev.get("event") or {}
            if e.get("type") == "content_block_start":
                cb = e.get("content_block") or {}
                if cb.get("type") == "tool_use":
                    t.set_phase("consultando", {"name": cb.get("name")})
                elif cb.get("type") == "text" and res["raw"].strip() and not res["raw"].endswith("\n\n"):
                    res["raw"] += "\n\n"
                elif cb.get("type") == "thinking" and not t.sent:
                    t.set_phase("pensando")
            elif e.get("type") == "content_block_delta":
                d = e.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    res["raw"] += d["text"]
                    t.push_text(streaming_display(res["raw"]))
            elif e.get("type") == "message_start":
                m = (e.get("message") or {}).get("model")
                if m and server_is_model(m):
                    res["model"] = m
        elif typ == "assistant":
            msg = ev.get("message") or {}
            if msg.get("model") and server_is_model(msg["model"]):
                res["model"] = msg["model"]
            for c in msg.get("content") or []:
                if c.get("type") == "tool_use":
                    tool = tool_summary(c.get("name"), c.get("input") or {}, self.store.data_root)
                    res["tools"].append(tool)
                    t.set_phase("consultando", tool)
        elif typ == "result":
            res["isError"] = bool(ev.get("is_error"))
            res["resultText"] = ev.get("result") if isinstance(ev.get("result"), str) else None
            if res["isError"]:
                res["error"] = mask(str(ev.get("result") or ev.get("subtype") or "erro no runner"))[:300]
            elif not res["raw"] and res["resultText"]:   # sem mensagens parciais: usa o resultado final
                res["raw"] = res["resultText"]
                t.push_text(streaming_display(res["raw"]))

    # ---- Codex: --json (thread.started, item.started/completed, turn.failed, error)
    def _on_codex(self, t: Turn, ev: dict, res: dict):
        typ = ev.get("type")
        item = ev.get("item") or {}
        if typ == "thread.started":
            res["threadId"] = ev.get("thread_id")
        elif typ == "item.started" and item.get("type") == "command_execution":
            tool = {"name": "shell", "path": mask(str(item.get("command") or ""))[:120]}
            res["tools"].append(tool)
            t.set_phase("consultando", tool)
        elif typ == "item.completed" and item.get("type") in ("agent_message", "assistant_message"):
            # G1-D17 ressalva 3: read-only do Codex lê qualquer arquivo — filtra segredos ANTES de exibir/gravar.
            text = mask(item.get("text") or "", self.store.data_root)
            res["raw"] += ("\n\n" if res["raw"].strip() else "") + text
            t.push_text(streaming_display(res["raw"]))
        elif typ == "item.started" and item.get("type") == "reasoning" and not t.sent:
            t.set_phase("pensando")
        elif typ in ("turn.failed", "error"):
            err = (ev.get("error") or {}).get("message") if isinstance(ev.get("error"), dict) else ev.get("message")
            res["isError"] = True
            res["error"] = mask(str(err or "falha no codex"))[:300]

    def _finish(self, t: Turn, runner: str, sid: str | None, reset: bool, res: dict):
        cid = t.cid
        raw = res["raw"]
        if runner == "codex":
            raw = mask(raw, self.store.data_root)
        text, block, found = split_proposal(raw)
        if t.stop_reason:
            status = t.stop_reason
        elif res["code"] == 0 and not res["isError"]:
            status = "ok"
        else:
            status = "erro"
        msg = {"t": "msg", "turn": t.turn, "role": "orquestrador", "ts": now_iso(), "text": text, "status": status,
               "runner": runner}
        if res["model"]:
            msg.update(model=res["model"], modelProvider=provider_of(res["model"], runner))
        msg.update(sessionId=sid, sessionReset=reset, firstTextMs=t.first_text_ms,
                   totalMs=round((time.monotonic() - t.t0) * 1000), tools=res["tools"])
        if status == "erro":
            err = res["error"] or "falha no runner"
            code = "orquestrador_indisponivel" if re.search(r"(?i)log ?in|auth|credential|api key|not found: (claude|codex)", err) else "erro_runner"
            msg.update(error=err, code=code)
        elif status == "tempo_esgotado":
            msg["error"] = f"tempo esgotado ({int(timeout_s())} s)"
        elif status == "cancelada":
            msg["error"] = "cancelada pelo humano"
        if found and status == "ok":
            try:
                state = self.state_fn()
                v = validate_proposal(block if isinstance(block, dict) else None, state)
            except Exception:
                v = {"alert": None, "demand": None, "gate": None, "action": None, "note": "", "valid": False,
                     "reason": "formato_invalido"}
            msg["proposal"] = {"id": f"p-{uuid.uuid4().hex[:6]}", **v}
        t.finish(self.store.append(cid, msg))

    # ---------------- propostas (§6.3)
    def _proposal(self, cid: str, pid: str, recs: list[dict]) -> dict:
        if not PID_RE.match(pid or ""):
            raise ChatError(404, "proposta_nao_encontrada", "proposta não encontrada")
        m = next((r for r in recs if r.get("t") == "msg" and (r.get("proposal") or {}).get("id") == pid), None)
        if m is None:
            raise ChatError(404, "proposta_nao_encontrada", "proposta não encontrada")
        if any(r.get("t") == "proposal" and r.get("id") == pid for r in recs):
            raise ChatError(409, "ja_decidida", "proposta já decidida")
        return m["proposal"]

    def confirm(self, cid: str, pid: str, body: dict, record_human, record_control) -> dict:
        note = body.get("note") if isinstance(body, dict) and "note" in body else None
        if note is not None and not isinstance(note, str):
            raise ChatError(400, "nota_invalida", "nota inválida")
        if note is not None and len(note) > MAX_NOTE:
            raise ChatError(400, "nota_grande", f"nota acima de {MAX_NOTE} caracteres")
        with self.store.lock:
            recs = self.store.records(cid)
            p = self._proposal(cid, pid, recs)
            if not p.get("valid"):
                raise ChatError(422, "proposta_invalida", "proposta inválida: " + REASON_TEXT.get(p.get("reason"), "—"))
            note = (p.get("note") or "") if note is None else note
            with self.log_lock:     # revalidação + gravação atômicas em relação aos demais escritores do log
                raw = ({"alerta": p["alert"], "acao": p["action"]} if p.get("alert")
                       else {"demanda": p.get("demand"), "acao": p["action"]})
                v = validate_proposal(raw, self.state_fn())
                if not v["valid"] or v.get("demand") != p.get("demand") or v.get("gate") != p.get("gate"):
                    self.store.append(cid, {"t": "proposal", "id": pid, "ts": now_iso(), "decision": "obsoleta",
                                            "reason": v.get("reason")})
                    raise ChatError(409, "proposta_obsoleta",
                                    "o estado mudou desde a proposta: " + REASON_TEXT.get(v.get("reason"), "revalide"))
                if p.get("alert"):
                    event = record_human(p["action"], p.get("gate"), p.get("demand"), note, via="conversa")
                else:
                    event = record_control(p["demand"], "resume", note, via="conversa")
            self.store.append(cid, {"t": "proposal", "id": pid, "ts": now_iso(), "decision": "confirmada",
                                    "event": event.get("id")})
            return {"event": event}

    def discard(self, cid: str, pid: str) -> dict:
        with self.store.lock:
            recs = self.store.records(cid)
            self._proposal(cid, pid, recs)
            self.store.append(cid, {"t": "proposal", "id": pid, "ts": now_iso(), "decision": "descartada"})
        return {"decision": "descartada"}


# ================================================================ utilitários
def server_is_model(m: str) -> bool:
    return bool(m) and not m.startswith("<")


def provider_of(model: str, runner: str) -> str:
    m = (model or "").lower()
    if m.startswith(("claude-", "anthropic.")) or runner in ("claude", "fake"):
        return "Anthropic"
    return "OpenAI"


def tool_summary(name: str, inp: dict, data_root: pathlib.Path) -> dict:
    """Nome da ferramenta + caminho relativo (nunca conteúdo)."""
    path = inp.get("file_path") or inp.get("path") or ""
    if path:
        try:
            path = str(pathlib.Path(path).resolve().relative_to(data_root))
        except (ValueError, OSError):
            path = pathlib.Path(path).name
    out = {"name": name, "path": path or None}
    if name in ("Glob", "Grep") and inp.get("pattern"):
        out["pattern"] = mask(str(inp["pattern"]))[:120]
    return out


def codex_model(thread_id: str) -> str | None:
    """Modelo efetivo do codex pelo rollout da sessão (a saída --json não traz cabeçalho)."""
    home = os.environ.get("CODEX_HOME")
    base = (pathlib.Path(home).expanduser() if home else pathlib.Path.home() / ".codex") / "sessions"
    try:
        files = sorted(base.glob(f"*/*/*/rollout-*{thread_id}.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    for f in reversed(files[-1:]):
        try:
            with f.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if '"model"' not in line:
                        continue
                    try:
                        payload = (json.loads(line).get("payload") or {})
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload.get("model"), str):
                        return payload["model"]
        except OSError:
            return None
    return None
