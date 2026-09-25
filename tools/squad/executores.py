#!/usr/bin/env python3
"""Resolvedor único de executor (Claude Code ou Codex) e modelo por agente (D26, ADR-027).

Contrato: docs/contracts/executor-e-modelo-por-agente.md. Só stdlib; nenhum efeito colateral na importação.

  python3 tools/squad/executores.py show [--json]
  python3 tools/squad/executores.py resolve <papel> [--demand <id>] [--context plantao|conversa|triagem|passo]
                                            [--no-snapshot] [--no-check] --json
  python3 tools/squad/executores.py check [--runner claude|codex] [--fresh]
  python3 tools/squad/executores.py set --scope squad|agent|demand|policy [--role] [--demand] --runner --model
                                        [--policy padrao|parar] --by humano [--ack]
  python3 tools/squad/executores.py apply-all --runner --model --by humano [--ack]
  python3 tools/squad/executores.py snapshot --demand <id>
  python3 tools/squad/executores.py guard-agent            (gancho PreToolUse do Claude Code; JSON no stdin)
  python3 tools/squad/executores.py check-session orquestrador --runner claude

Camadas (a mais específica vence): embutido → `[executors]` do product.toml (guarda + semente) → padrão da squad →
por agente (null = "usar o padrão", herda executor E modelo) → por demanda (foto `executor-snapshot` + troca
`executor-config{scope:"demand"}` no log). Runtime por máquina: `<cópia principal>/.squad/executores.json` (ou
`$SQUAD_ROOT_DATA/.squad/`). Códigos: 0 ok · 2 validação · 3 parar (política) · 4 configuração ilegível ·
5 executor fora de `allowed` · 6 executor indisponível (check) · 7 recusado (agente não muda a própria configuração).
"""
import argparse
import dataclasses
import fcntl
import getpass
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product  # noqa: E402

ROLES = ["orquestrador", "arquiteto", "backend", "devops", "observabilidade", "frontend", "qa", "auditor"]
LABEL = {"orquestrador": "Orquestrador", "arquiteto": "Arquiteto", "backend": "Backend", "devops": "DevOps",
         "observabilidade": "Observabilidade", "frontend": "Frontend", "qa": "QA", "auditor": "Auditor"}
RUNNERS = ("claude", "codex")
RUNNER_LABEL = {"claude": "Claude Code", "codex": "Codex"}
CLAUDE_ALIASES = {"opus", "sonnet", "haiku", "fable", "default"}
NATIVE_ALIASES = {"opus", "sonnet", "haiku", "fable"}          # aceitos pela ferramenta Agent do Claude Code
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\[\]-]+$")
CONTEXTS = ("plantao", "conversa", "triagem", "passo")
CURRENT_CONTEXTS = {"plantao", "conversa", "triagem"}           # usam a configuração ATUAL (sem foto, §4)
POLICIES = ("padrao", "parar")
SCOPES = ("squad", "agent", "demand", "policy", "apply-all")
DEMAND_RE = re.compile(r"^[0-9a-f]{12}$")
ENV_VARS = ("SQUAD_RUNNER", "SQUAD_MODEL", "SQUAD_CHAT_RUNNER", "SQUAD_CHAT_MODEL")

# Decisões do humano pendentes (ADR-027 §5; contrato §17). Mudam SÓ com a resposta registrada do humano (PR).
#   Q2: Orquestrador no Codex com danger-full-access. Padrão: não habilitar (recusado com motivo; CA-H2 pendente).
#   Q3: Auditor somente leitura também no Claude (com a verificação pelo chamador, gate.py). Padrão até a resposta:
#       o Auditor fica como hoje no Claude (perfil `escrita`) e só no Codex usa `auditoria` (read-only) + gate.py.
DECISOES = {"Q2": False, "Q3": False}
Q2_REASON = "Orquestrador no Codex exige danger-full-access; aguardando decisão do humano (Q2)"

EXIT_OK, EXIT_VALIDATION, EXIT_STOP, EXIT_CONFIG, EXIT_NOT_ALLOWED, EXIT_UNAVAILABLE, EXIT_REFUSED = 0, 2, 3, 4, 5, 6, 7
STATUS_TTL_S = 300
CHECK_TIMEOUT_S = 5
LOCK_TIMEOUT_S = 5.0
AUTH_FAIL_RE = re.compile(r"(?i)not logged in|please run /login|\b401\b|unauthorized|codex login")
CHECK_ENV_ALLOW = {"PATH", "HOME", "USER", "LANG", "TERM", "TMPDIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR"}
CHECK_ENV_PREFIX = ("LC_", "ANTHROPIC_", "CLAUDE_CODE_", "OPENAI_")
PERFIS_DIR = HERE / "perfis"
CODEX_WARNING = ("Com o Codex o agente pode ler qualquer arquivo desta máquina (o sandbox read-only do Codex não "
                 "restringe leitura; ADR-024 §4.9). Segredos são filtrados da saída, mas prefira o Claude Code nos "
                 "papéis que leem dados sensíveis.")


class ExecError(Exception):
    """Recusa com código de saída (CLI), status HTTP e código de erro estável (API)."""

    def __init__(self, exit_code: int, code: str, message: str, http: int = 400, **extra):
        super().__init__(message)
        self.exit_code, self.code, self.message, self.http, self.extra = exit_code, code, message, http, extra

    def payload(self) -> dict:
        return {"error": self.message, "code": self.code, **self.extra}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ============================================================== onde mora (§3.2 "localização única")
@dataclasses.dataclass
class Ctx:
    product: "product.Product"
    base: pathlib.Path            # cópia principal (ou $SQUAD_ROOT_DATA)
    runtime_dir: pathlib.Path
    locks_dir: pathlib.Path
    log: pathlib.Path
    allowed: list
    seed: dict

    @property
    def config_path(self) -> pathlib.Path:
        return self.runtime_dir / "executores.json"

    @property
    def status_path(self) -> pathlib.Path:
        return self.runtime_dir / "executores-status.json"

    @property
    def runs_dir(self) -> pathlib.Path:
        return self.runtime_dir / "runs"


def main_root() -> pathlib.Path | None:
    """Cópia principal = worktree em `develop` (mesma regra de testenv.find_main_root; `$SQUAD_MAIN_ROOT` sobrepõe)."""
    try:
        import testenv
        return testenv.find_main_root(product.PLATFORM_ROOT, timeout=5)
    except Exception:
        return None


def context(log=None) -> Ctx:
    """Um run_agent chamado de um worktree usa o MESMO arquivo e o MESMO log da cópia principal (nunca o do worktree)."""
    p = product.resolve()
    if os.environ.get("SQUAD_ROOT_DATA"):
        base = p.data_root
        runtime = p.runtime_dir or base / ".squad"
    else:
        base = main_root() or p.data_root
        runtime = base / ".squad"
    if log is None:
        log = p.log if (os.environ.get("SQUAD_LOG") or os.environ.get("SQUAD_ROOT_DATA")) \
            else base / product.CANONICAL_LOG
    ex = p.executors or product.DEFAULT_EXECUTORS
    return Ctx(product=p, base=base, runtime_dir=runtime, locks_dir=runtime / "locks", log=pathlib.Path(log),
               allowed=list(ex.get("allowed") or RUNNERS), seed=dict(ex.get("seed") or {"runner": "claude"}))


# ============================================================== log (eventos aditivos, fora do TYPES do log.py)
def read_rows(ctx: Ctx) -> list[dict]:
    try:
        text = ctx.log.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def append_event(ctx: Ctx, entry: dict, writer=None) -> dict:
    """Grava um evento (append-only). `writer` = função do servidor (mantém o cache e a trava dele)."""
    entry = {"id": uuid.uuid4().hex[:12], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    entry = {k: v for k, v in entry.items() if v not in (None, "", [])
             or k in ("before", "after", "model", "acknowledged", "warnings")}
    if writer is not None:
        return writer(entry)
    # mesmo caminho e mesma disciplina do log.py: O_APPEND, UMA escrita por linha (sem ler/regravar o arquivo)
    ctx.log.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(ctx.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return entry


def machine_id(ctx: Ctx) -> str:
    """Id da máquina do ADR-026 (`.squad/sync/machine.json`) ou o hostname."""
    try:
        m = json.loads((ctx.runtime_dir / "sync/machine.json").read_text(encoding="utf-8"))
        if m.get("id"):
            return str(m["id"])
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return socket.gethostname()


def os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "desconhecido"


# ============================================================== validação de valores
def provider_of(model: str | None) -> str | None:
    m = re.sub(r"\[.*?\]$", "", (model or "").strip().lower())
    m = re.sub(r"^(us|eu|apac|global)\.", "", m)
    if m.startswith(("claude-", "anthropic.")):
        return "anthropic"
    if m.startswith(("gpt-", "o1", "o3", "o4", "codex-", "openai/")):
        return "openai"
    return None


def validate_pair(runner, model, allowed) -> tuple[dict, list]:
    """{runner, model} válido (§3.2) → (par normalizado, avisos). ExecError 400/código 2 ou 5 na recusa."""
    if runner not in RUNNERS:
        raise ExecError(EXIT_VALIDATION, "formato_invalido", f"executor inválido: {runner!r} (claude|codex)")
    if runner not in allowed:
        raise ExecError(EXIT_NOT_ALLOWED, "executor_nao_permitido",
                        f"executor {runner} não permitido neste produto (executors.allowed = {allowed})")
    warnings = []
    if model in ("", None):
        return {"runner": runner, "model": None}, warnings
    if not isinstance(model, str) or len(model) > 100 or not MODEL_RE.match(model):
        raise ExecError(EXIT_VALIDATION, "formato_invalido", "modelo inválido (máx. 100 caracteres, ^[A-Za-z0-9._:/\\[\\]-]+$)")
    if model.lower() in CLAUDE_ALIASES:
        if runner != "claude":
            raise ExecError(EXIT_VALIDATION, "modelo_incompativel", f"alias {model} só vale com o Claude Code")
        return {"runner": runner, "model": model.lower()}, warnings
    prov = provider_of(model)
    if prov is None:
        warnings.append("modelo_fornecedor_desconhecido")
    elif (runner == "claude") != (prov == "anthropic"):
        raise ExecError(EXIT_VALIDATION, "modelo_incompativel",
                        f"modelo {model} ({prov}) incompatível com o executor {RUNNER_LABEL[runner]}")
    return {"runner": runner, "model": model}, warnings


def validate_config(cfg, allowed=RUNNERS) -> dict:
    """Esquema do runtime (§3.2). Qualquer desvio → ExecError código 4 (nunca um padrão silencioso)."""
    def bad(msg):
        raise ExecError(EXIT_CONFIG, "configuracao_ilegivel", f"configuração de executores ilegível: {msg}", http=500)
    if not isinstance(cfg, dict) or cfg.get("schema") != 1:
        bad("campo `schema` deve ser 1")
    if not isinstance(cfg.get("version"), int):
        bad("campo `version` deve ser inteiro")
    try:
        validate_pair((cfg.get("squad") or {}).get("runner"), (cfg.get("squad") or {}).get("model"), RUNNERS)
    except ExecError as e:
        bad(f"squad: {e.message}")
    agents = cfg.get("agents")
    if not isinstance(agents, dict) or any(k not in ROLES for k in agents):
        bad("`agents` deve ter só os 8 papéis")
    for role, v in agents.items():
        if v is None:
            continue
        if not isinstance(v, dict):
            bad(f"agents.{role} deve ser objeto ou null")
        try:
            validate_pair(v.get("runner"), v.get("model"), RUNNERS)
        except ExecError as e:
            bad(f"agents.{role}: {e.message}")
    if (cfg.get("policy") or {}).get("onUnavailable") not in POLICIES:
        bad("policy.onUnavailable deve ser padrao|parar")
    return cfg


# ============================================================== trava + arquivo
_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


class _Lock:
    """flock entre processos + RLock entre threads; reentrante no mesmo thread (save → load → migração)."""

    def __init__(self, ctx: Ctx):
        self.path = ctx.locks_dir / "executores.lock"
        with _LOCKS_GUARD:
            self.state = _LOCKS.setdefault(str(self.path), {"rlock": threading.RLock(), "depth": 0, "fd": None})

    def __enter__(self):
        st = self.state
        if not st["rlock"].acquire(timeout=LOCK_TIMEOUT_S):
            raise ExecError(EXIT_CONFIG, "trava_executores", "trava de executores ocupada (5 s)", http=503)
        if st["depth"] == 0:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
            except OSError:
                st["rlock"].release()
                raise
            deadline = time.monotonic() + LOCK_TIMEOUT_S
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        os.close(fd)
                        st["rlock"].release()
                        raise ExecError(EXIT_CONFIG, "trava_executores", "trava de executores ocupada (5 s)", http=503)
                    time.sleep(0.05)
            st["fd"] = fd
        st["depth"] += 1
        return self

    def __exit__(self, *_):
        st = self.state
        st["depth"] -= 1
        if st["depth"] == 0 and st["fd"] is not None:
            fcntl.flock(st["fd"], fcntl.LOCK_UN)
            os.close(st["fd"])
            st["fd"] = None
        st["rlock"].release()


def _write_atomic(path: pathlib.Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _env_pair(runner_var: str, model_var: str) -> tuple[str | None, str | None]:
    r = (os.environ.get(runner_var) or "").strip().lower() or None
    m = (os.environ.get(model_var) or "").strip() or None
    if model_var == "SQUAD_MODEL" and os.environ.get("SQUAD_RUN"):
        m = None   # dentro de uma run, SQUAD_MODEL é herança do efetivo (ADR-012), nunca configuração
    return r, m


def _migrate(ctx: Ctx) -> tuple[dict, list]:
    """§3.3: semente do product.toml + variáveis antigas, só na criação do arquivo."""
    warnings = []
    seed = {"runner": ctx.seed.get("runner") or "claude", "model": ctx.seed.get("model")}
    squad = dict(seed)
    r, m = _env_pair("SQUAD_RUNNER", "SQUAD_MODEL")
    if r or m:
        try:
            squad, w = validate_pair(r or seed["runner"], m, ctx.allowed)
            warnings += w
        except ExecError as e:
            warnings.append(f"migracao_ignorada:SQUAD_RUNNER/SQUAD_MODEL ({e.code})")
    agents = {k: None for k in ROLES}
    cr, cm = _env_pair("SQUAD_CHAT_RUNNER", "SQUAD_CHAT_MODEL")
    if cr == "fake":
        cr = None
    if (cr or cm) and ((cr or squad["runner"]) != squad["runner"] or (cm or None) != squad["model"]):
        try:
            agents["orquestrador"], w = validate_pair(cr or squad["runner"], cm, ctx.allowed)
            warnings += w
        except ExecError as e:
            warnings.append(f"migracao_ignorada:SQUAD_CHAT_RUNNER/SQUAD_CHAT_MODEL ({e.code})")
    cfg = {"schema": 1, "version": 1, "updatedAt": now_iso(), "squad": squad, "agents": agents,
           "policy": {"onUnavailable": "padrao"}, "codexAck": None}
    _pin_orchestrator(cfg, warnings)
    return cfg, warnings


def _pin_orchestrator(cfg: dict, warnings: list, current_model=None):
    """Q2 sem aceite: o Orquestrador nunca resolve para `codex` — fica `claude` (com o modelo atual, se Claude)."""
    if DECISOES["Q2"]:
        return
    orch = cfg["agents"].get("orquestrador") or cfg["squad"]
    if orch["runner"] == "codex":
        model = current_model if current_model and (current_model in CLAUDE_ALIASES or
                                                    provider_of(current_model) == "anthropic") else None
        cfg["agents"]["orquestrador"] = {"runner": "claude", "model": model}
        warnings.append("orquestrador_codex_pendente_q2")


def load(ctx: Ctx, migrate: bool = True, writer=None) -> dict:
    path = ctx.config_path
    if not path.exists():
        if not migrate:
            cfg, _ = _migrate(ctx)
            return cfg
        with _Lock(ctx):
            if not path.exists():
                cfg, warnings = _migrate(ctx)
                _write_atomic(path, cfg)
                append_event(ctx, {"agent": "humano", "type": "executor-config", "scope": "squad", "via": "migracao",
                                   "title": f"Executores: configuração criada (padrão {cfg['squad']['runner']})",
                                   "before": None, "after": {"squad": cfg["squad"], "agents": cfg["agents"],
                                                             "policy": cfg["policy"]},
                                   "by": "migracao", "user": os_user(), "machine": machine_id(ctx),
                                   "configVersion": 1, "warnings": warnings, "acknowledged": False}, writer)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ExecError(EXIT_CONFIG, "configuracao_ilegivel", f"configuração de executores ilegível: {e}", http=500)
    cfg.setdefault("agents", {})
    for r in ROLES:
        cfg["agents"].setdefault(r, None)
    return validate_config(cfg)


# ============================================================== checagem (§6.1)
def _check_env() -> dict:
    return {k: v for k, v in os.environ.items() if k in CHECK_ENV_ALLOW or k.startswith(CHECK_ENV_PREFIX)}


def _probe(runner: str) -> dict:
    out = {"installed": False, "loggedIn": None, "version": None, "checkedAt": now_iso(), "detail": "nao-instalado"}
    exe = shutil.which(runner)
    if not exe:
        return out
    out["installed"] = True
    env = _check_env()

    def run(args):
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=CHECK_TIMEOUT_S, env=env,
                              stdin=subprocess.DEVNULL)
    try:
        v = run(["--version"])
        m = re.search(r"\d+\.\d+(?:\.\d+)?", v.stdout or "")
        out["version"] = m.group(0) if m else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        if runner == "claude":
            p = run(["auth", "status", "--json"])
            try:
                data = json.loads(p.stdout or "{}")
            except json.JSONDecodeError:
                data = None
            logged = isinstance(data, dict) and data.get("loggedIn") is True
            if p.returncode == 0 and logged:
                out.update(loggedIn=True, detail="ok")
            elif env.get("ANTHROPIC_API_KEY"):
                out.update(loggedIn=True, detail="ok")
            elif isinstance(data, dict) and "loggedIn" in data or (p.returncode != 0 and data is not None):
                out.update(loggedIn=False, detail="sem-login")
            elif p.returncode != 0 and re.search(r"(?i)unknown (command|option)|usage:", (p.stderr or "") + (p.stdout or "")):
                out.update(detail="desconhecido")
            elif p.returncode != 0:
                out.update(loggedIn=False, detail="sem-login")
            else:
                out.update(detail="desconhecido")
        else:
            p = run(["login", "status"])
            if p.returncode == 0:
                out.update(loggedIn=True, detail="ok")
            elif re.search(r"(?i)unknown|unrecognized|usage:", p.stderr or ""):
                out.update(detail="desconhecido")
            else:
                out.update(loggedIn=False, detail="sem-login")
    except subprocess.TimeoutExpired:
        out.update(detail="timeout")
    except OSError:
        out.update(detail="desconhecido")
    return out   # a saída dos comandos NUNCA é gravada nem exibida (pode conter e-mail/conta)


def check(ctx: Ctx, runner: str | None = None, fresh: bool = False) -> dict:
    """Estado dos executores, com cache de 5 min em `<runtime_dir>/executores-status.json`."""
    try:
        cache = json.loads(ctx.status_path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, json.JSONDecodeError):
        cache = {}
    out, changed = {}, False
    for r in ([runner] if runner else RUNNERS):
        c = cache.get(r)
        if fresh or not isinstance(c, dict) or time.time() - (c.get("_at") or 0) > STATUS_TTL_S:
            c = {**_probe(r), "_at": time.time()}
            cache[r] = c
            changed = True
        out[r] = {k: v for k, v in c.items() if not k.startswith("_")}
    if changed:
        try:
            _write_atomic(ctx.status_path, cache)
        except OSError:
            pass
    return out


def invalidate(ctx: Ctx, runner: str):
    try:
        cache = json.loads(ctx.status_path.read_text(encoding="utf-8"))
        cache.pop(runner, None)
        _write_atomic(ctx.status_path, cache)
    except (OSError, json.JSONDecodeError, AttributeError):
        pass


def usable(st: dict) -> bool:
    """`desconhecido`/`timeout` não bloqueiam (aviso); só `nao-instalado`/`sem-login` bloqueiam."""
    return st.get("detail") not in ("nao-instalado", "sem-login")


# ============================================================== resolução (§4)
def frontmatter_alias(role: str) -> str | None:
    if role == "orquestrador":
        return None
    try:
        text = (product.PLATFORM_ROOT / f".claude/agents/{role}.md").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    mm = re.search(r"^model:\s*(\S+)", m.group(1), flags=re.M) if m else None
    return mm.group(1) if mm else None


def profile_of(role: str, runner: str, ctx_name: str) -> str:
    """§7.1: leitura (conversa/triagem), auditoria (Auditor), escrita (demais), orquestracao (Orquestrador)."""
    if ctx_name in ("conversa", "triagem"):
        return "leitura"
    if role == "auditor":
        return "auditoria" if (runner == "codex" or DECISOES["Q3"]) else "escrita"
    if role == "orquestrador":
        return "orquestracao"
    return "escrita"


def via_of(runner: str, model: str | None) -> str:
    return "nativo" if runner == "claude" and (model is None or model in NATIVE_ALIASES) else "run_agent"


def demand_override(rows: list[dict], demand: str, role: str) -> dict | None:
    last = None
    for e in rows:
        if (e.get("type") == "executor-config" and e.get("scope") == "demand" and e.get("demand") == demand
                and e.get("role") == role):
            last = e
    return (last or {}).get("after") or None


def find_snapshot(rows: list[dict], demand: str) -> dict | None:
    return next((e for e in rows if e.get("type") == "executor-snapshot" and e.get("demand") == demand), None)


def current_table(cfg: dict) -> dict:
    out = {}
    for role in ROLES:
        a = cfg["agents"].get(role)
        out[role] = ({"runner": a["runner"], "model": a.get("model"), "source": "agente"} if a
                     else {"runner": cfg["squad"]["runner"], "model": cfg["squad"].get("model"), "source": "squad"})
    return out


def snapshot(ctx: Ctx, demand: str, cfg: dict | None = None, writer=None) -> dict:
    """§4.1: uma foto por demanda (a segunda chamada devolve a existente)."""
    if not DEMAND_RE.match(demand or ""):
        raise ExecError(EXIT_VALIDATION, "formato_invalido", "demanda deve ser um id de 12 hex")
    cfg = cfg or load(ctx, writer=writer)
    with _Lock(ctx):
        existing = find_snapshot(read_rows(ctx), demand)
        if existing:
            return existing
        return append_event(ctx, {"agent": "orquestrador", "type": "executor-snapshot", "demand": demand,
                                  "title": "Executores fixados para a demanda", "executors": current_table(cfg),
                                  "squad": cfg["squad"], "policy": cfg["policy"], "configVersion": cfg["version"]},
                            writer)


def ignored_env(resolved_orch: dict | None = None, cfg: dict | None = None) -> list[str]:
    """Variáveis antigas definidas com valor diferente do resolvido: ignoradas (aviso)."""
    out = []
    squad = (cfg or {}).get("squad") or {}
    r, m = _env_pair("SQUAD_RUNNER", "SQUAD_MODEL")
    if r and r != squad.get("runner"):
        out.append("SQUAD_RUNNER")
    if m and m != squad.get("model"):
        out.append("SQUAD_MODEL")
    cr, cm = _env_pair("SQUAD_CHAT_RUNNER", "SQUAD_CHAT_MODEL")
    orch = resolved_orch or {}
    if cr and cr != "fake" and cr != orch.get("runner"):
        out.append("SQUAD_CHAT_RUNNER")
    if cm and cm != orch.get("model"):
        out.append("SQUAD_CHAT_MODEL")
    return out


def resolve(role: str, demand: str | None = None, ctx_name: str = "passo", make_snapshot: bool = True,
            do_check: bool = True, ctx: Ctx | None = None, run: str | None = None, forced_unavailable: dict | None = None,
            writer=None, record: bool = True, persist: bool = True) -> dict:
    """(executor, modelo, origem, via, perfil) de um acionamento. ExecError: 3 parar · 4 ilegível · 5 não permitido.
    `persist=False` (--dry-run): nada é gravado — nem o arquivo da migração, nem a foto, nem o `executor-fallback`."""
    if not persist:
        make_snapshot, record = False, False
    if role not in ROLES:
        raise ExecError(EXIT_VALIDATION, "papel_invalido", f"papel desconhecido: {role}")
    if ctx_name not in CONTEXTS:
        raise ExecError(EXIT_VALIDATION, "formato_invalido", f"contexto inválido: {ctx_name}")
    if demand is not None and not DEMAND_RE.match(demand):
        raise ExecError(EXIT_VALIDATION, "formato_invalido", "demanda deve ser um id de 12 hex")
    ctx = ctx or context()
    cfg = load(ctx, migrate=persist, writer=writer)
    squad = {"runner": cfg["squad"]["runner"], "model": cfg["squad"].get("model")}
    configured, source = None, None
    if demand and ctx_name not in CURRENT_CONTEXTS:
        rows = read_rows(ctx)
        ov = demand_override(rows, demand, role)
        if ov and ov.get("runner"):
            configured, source = {"runner": ov["runner"], "model": ov.get("model")}, "demanda"
        else:
            snap = find_snapshot(rows, demand)
            if snap is None and make_snapshot:
                snap = snapshot(ctx, demand, cfg, writer)
            if snap and (snap.get("executors") or {}).get(role):
                s = snap["executors"][role]
                configured, source = {"runner": s["runner"], "model": s.get("model")}, s.get("source") or "squad"
    if configured is None:
        a = cfg["agents"].get(role)
        configured, source = (({"runner": a["runner"], "model": a.get("model")}, "agente") if a
                              else (dict(squad), "squad"))
    warnings = []
    if configured["runner"] not in ctx.allowed:
        raise ExecError(EXIT_NOT_ALLOWED, "executor_nao_permitido",
                        f"{LABEL[role]}: executor {configured['runner']} não permitido neste produto")
    if role == "orquestrador" and configured["runner"] == "codex" and not DECISOES["Q2"]:
        raise ExecError(EXIT_NOT_ALLOWED, "orquestrador_codex_pendente_q2", Q2_REASON)
    effective, fallback = dict(configured), None
    if do_check or forced_unavailable:
        st = (forced_unavailable if forced_unavailable and forced_unavailable.get("runner") == configured["runner"]
              else check(ctx, configured["runner"])[configured["runner"]])
        if st.get("detail") in ("desconhecido", "timeout"):
            warnings.append(f"estado_{st['detail']}:{configured['runner']}")
        if not usable(st):
            reason = st.get("detail") or "sem-login"
            policy = cfg["policy"]["onUnavailable"]
            same = configured["runner"] == squad["runner"]
            squad_ok = (not same) and usable(check(ctx, squad["runner"])[squad["runner"]])
            if role == "orquestrador" and squad["runner"] == "codex" and not DECISOES["Q2"]:
                squad_ok = False
            if policy == "padrao" and squad_ok:
                effective, fallback = dict(squad), {"reason": reason, "from": configured, "action": "padrao"}
            else:
                fallback = {"reason": reason, "from": configured, "action": "parou"}
            if record:
                append_event(ctx, {"agent": "orquestrador", "type": "executor-fallback", "demand": demand,
                                   "role": role, "run": run, "configured": configured, "reason": reason,
                                   "action": fallback["action"],
                                   "effective": effective if fallback["action"] == "padrao" else None,
                                   "title": (f"{LABEL[role]}: {RUNNER_LABEL[configured['runner']]} indisponível ({reason})"
                                             + (f" → padrão {RUNNER_LABEL[squad['runner']]}" if fallback["action"] == "padrao"
                                                else " → passo parado"))}, writer)
            if fallback["action"] == "parou":
                raise ExecError(EXIT_STOP, "executor_indisponivel",
                                f"{LABEL[role]}: executor {configured['runner']} indisponível ({reason}); "
                                f"política {policy} — passo não iniciado", http=503, fallback=fallback)
    model = effective.get("model")
    if effective["runner"] == "claude":
        model_arg = model if model not in (None, "default") else frontmatter_alias(role)
    else:
        model_arg = model
    if effective["runner"] == "codex":
        warnings.append("codex_leitura_nao_isolada")
    warnings += [f"variavel_ignorada:{v}" for v in ignored_env(effective if role == "orquestrador" else None, cfg)]
    return {"role": role, "runner": effective["runner"], "model": model, "modelArg": model_arg, "source": source,
            "via": via_of(effective["runner"], model), "profile": profile_of(role, effective["runner"], ctx_name),
            "configured": configured, "fallback": fallback, "warnings": warnings, "demand": demand,
            "context": ctx_name, "policy": cfg["policy"]["onUnavailable"], "configVersion": cfg["version"]}


# ============================================================== gravação (CLI e servidor)
def _record_config(ctx: Ctx, scope: str, before, after, cfg_version: int, via: str, warnings: list, ack: bool,
                   title: str, role=None, demand=None, writer=None) -> dict:
    return append_event(ctx, {"agent": "humano", "type": "executor-config", "scope": scope, "role": role,
                              "demand": demand, "via": via, "before": before, "after": after, "by": "humano",
                              "user": os_user(), "machine": machine_id(ctx), "configVersion": cfg_version,
                              "warnings": warnings, "acknowledged": bool(ack), "title": title}, writer)


def _availability_warnings(ctx: Ctx, runners: set, ack: bool, fresh: bool = True) -> list:
    """§6.2: executor `nao-instalado`/`sem-login` → 409 na 1ª tentativa; com acknowledge grava com os avisos."""
    st = check(ctx, fresh=fresh) if runners else {}
    warns = [{"runner": r, "detail": st[r]["detail"]} for r in sorted(runners) if not usable(st[r])]
    if warns and not ack:
        raise ExecError(EXIT_VALIDATION, "executor_indisponivel",
                        "executor indisponível: " + ", ".join(f"{w['runner']} ({w['detail']})" for w in warns),
                        http=409, warnings=warns)
    return [f"{w['runner']}:{w['detail']}" for w in warns]


def _pair_title(p) -> str:
    if not p:
        return "usar o padrão"
    return RUNNER_LABEL.get(p.get("runner"), p.get("runner")) + (f" · {p['model']}" if p.get("model") else "")


def save(ctx: Ctx, body: dict, via: str = "painel", writer=None, fresh: bool = True) -> dict:
    """POST /api/executores e `set --scope squad|agent|policy`: {baseVersion, squad?, agents?, policy?, acknowledge?}."""
    ack = bool(body.get("acknowledge"))
    with _Lock(ctx):
        cfg = load(ctx, writer=writer)
        if body.get("baseVersion") is not None and body.get("baseVersion") != cfg["version"]:
            raise ExecError(EXIT_VALIDATION, "versao_desatualizada",
                            f"configuração mudou (versão {cfg['version']}); recarregue", http=409, version=cfg["version"])
        new = json.loads(json.dumps(cfg))
        warnings, touched = [], set()
        if "squad" in body:
            new["squad"], w = validate_pair((body["squad"] or {}).get("runner"), (body["squad"] or {}).get("model"),
                                            ctx.allowed)
            warnings += w
            touched.add(new["squad"]["runner"])
        if "agents" in body:
            if not isinstance(body["agents"], dict) or any(k not in ROLES for k in body["agents"]):
                raise ExecError(EXIT_VALIDATION, "formato_invalido", "agents deve ter só os 8 papéis")
            for role, v in body["agents"].items():
                if v is None or (isinstance(v, dict) and not v.get("runner")):
                    new["agents"][role] = None
                    continue
                if not isinstance(v, dict):
                    raise ExecError(EXIT_VALIDATION, "formato_invalido", f"agents.{role} deve ser objeto ou null")
                new["agents"][role], w = validate_pair(v.get("runner"), v.get("model"), ctx.allowed)
                warnings += w
                touched.add(new["agents"][role]["runner"])
        if "policy" in body:
            pol = (body["policy"] or {}).get("onUnavailable") if isinstance(body["policy"], dict) else body["policy"]
            if pol not in POLICIES:
                raise ExecError(EXIT_VALIDATION, "formato_invalido", "policy.onUnavailable deve ser padrao|parar")
            new["policy"] = {"onUnavailable": pol}
        orch = new["agents"].get("orquestrador") or new["squad"]
        if orch["runner"] == "codex" and not DECISOES["Q2"]:
            raise ExecError(EXIT_VALIDATION, "orquestrador_codex_pendente_q2", Q2_REASON)
        _codex_ack_required(ctx, cfg, new, body)
        changed = {k: new[k] != cfg[k] for k in ("squad", "agents", "policy")}
        if not any(changed.values()):
            return {"version": cfg["version"], "warnings": warnings, "events": []}
        warnings += _availability_warnings(ctx, {r for r in touched if r}, ack, fresh)
        new["version"] = cfg["version"] + 1
        new["updatedAt"] = now_iso()
        validate_config(new)
        _write_atomic(ctx.config_path, new)
        events = []
        if changed["squad"]:
            events.append(_record_config(ctx, "squad", cfg["squad"], new["squad"], new["version"], via, warnings, ack,
                                         f"Padrão da squad: {_pair_title(cfg['squad'])} → {_pair_title(new['squad'])}",
                                         writer=writer))
        for role in ROLES:
            if new["agents"].get(role) != cfg["agents"].get(role):
                events.append(_record_config(ctx, "agent", cfg["agents"].get(role), new["agents"].get(role),
                                             new["version"], via, warnings, ack,
                                             f"{LABEL[role]}: {_pair_title(cfg['agents'].get(role))} → "
                                             f"{_pair_title(new['agents'].get(role))}", role=role, writer=writer))
        if changed["policy"]:
            events.append(_record_config(ctx, "policy", cfg["policy"], new["policy"], new["version"], via, warnings,
                                         ack, f"Executor indisponível: {cfg['policy']['onUnavailable']} → "
                                              f"{new['policy']['onUnavailable']}", writer=writer))
        return {"version": new["version"], "warnings": warnings, "events": [e["id"] for e in events]}


def apply_all(ctx: Ctx, body: dict, via: str = "painel", writer=None, fresh: bool = True) -> dict:
    """§10 aplicar-a-todos: squad = escolhido e os 8 agents = null (Q2: Orquestrador fica `claude`)."""
    ack = bool(body.get("acknowledge"))
    with _Lock(ctx):
        cfg = load(ctx, writer=writer)
        if body.get("baseVersion") is not None and body.get("baseVersion") != cfg["version"]:
            raise ExecError(EXIT_VALIDATION, "versao_desatualizada",
                            f"configuração mudou (versão {cfg['version']}); recarregue", http=409, version=cfg["version"])
        pair, warnings = validate_pair(body.get("runner"), body.get("model"), ctx.allowed)
        new = json.loads(json.dumps(cfg))
        new["squad"] = pair
        new["agents"] = {r: None for r in ROLES}
        current_orch = (cfg["agents"].get("orquestrador") or cfg["squad"]).get("model")
        _pin_orchestrator(new, warnings, current_orch)
        _codex_ack_required(ctx, cfg, new, body)
        warnings += _availability_warnings(ctx, {pair["runner"]}, ack, fresh)
        new["version"] = cfg["version"] + 1
        new["updatedAt"] = now_iso()
        validate_config(new)
        _write_atomic(ctx.config_path, new)
        ev = _record_config(ctx, "apply-all", {"squad": cfg["squad"], "agents": cfg["agents"]},
                            {"squad": new["squad"], "agents": new["agents"]}, new["version"], via, warnings, ack,
                            f"Aplicar a todos: {_pair_title(pair)}", writer=writer)
        return {"version": new["version"], "warnings": warnings, "events": [ev["id"]]}


def _codex_ack_required(ctx: Ctx, cfg: dict, new: dict, body: dict):
    """ADR-024 §4.9: com 2+ produtos cadastrados, salvar papel em `codex` exige `codexAck` (hoje 1 produto: não exige)."""
    try:
        n = len([d for d in (product.PLATFORM_ROOT / product.PRODUCTS_DIR).iterdir() if (d / "product.toml").exists()])
    except OSError:
        n = 1
    uses_codex = any(p["runner"] == "codex" for p in current_table(new).values())
    if n >= 2 and uses_codex and not (cfg.get("codexAck") or body.get("codexAck")):
        raise ExecError(EXIT_VALIDATION, "codex_ack_exigido",
                        "com 2+ produtos, escolher o Codex exige reconhecer a leitura não isolada (ADR-024 §4.9)")
    if n >= 2 and body.get("codexAck"):
        new["codexAck"] = {"by": "humano", "at": now_iso(), "products": [ctx.product.id]}


def set_demand(ctx: Ctx, demand: str, role: str, runner, model=None, ack: bool = False, via: str = "painel",
               writer=None, fresh: bool = True) -> dict:
    """POST /api/demand/executores: troca só nesta demanda (runner null = volta à foto)."""
    if role not in ROLES:
        raise ExecError(EXIT_VALIDATION, "papel_invalido", f"papel desconhecido: {role}")
    if not DEMAND_RE.match(demand or ""):
        raise ExecError(EXIT_VALIDATION, "formato_invalido", "demanda deve ser um id de 12 hex")
    rows = read_rows(ctx)
    if not any(e.get("id") == demand and e.get("type") == "task" and e.get("agent") == "humano" for e in rows):
        raise ExecError(EXIT_VALIDATION, "demanda_nao_encontrada", "demanda não encontrada", http=404)
    if any(e.get("demand") == demand and (e.get("type") == "delivered" or
                                          (e.get("type") == "control" and e.get("action") == "cancel")) for e in rows):
        raise ExecError(EXIT_VALIDATION, "demanda_encerrada", "demanda entregue ou cancelada", http=409)
    warnings, after = [], None
    if runner:
        after, warnings = validate_pair(runner, model, ctx.allowed)
        if role == "orquestrador" and after["runner"] == "codex" and not DECISOES["Q2"]:
            raise ExecError(EXIT_VALIDATION, "orquestrador_codex_pendente_q2", Q2_REASON)
        warnings += _availability_warnings(ctx, {after["runner"]}, ack, fresh)
    before = demand_override(rows, demand, role)
    if before is None:
        snap = find_snapshot(rows, demand)
        s = ((snap or {}).get("executors") or {}).get(role)
        before = {"runner": s["runner"], "model": s.get("model")} if s else None
    cfg = load(ctx, writer=writer)
    ev = _record_config(ctx, "demand", before, after, cfg["version"], via, warnings, ack,
                        f"{LABEL[role]} só nesta demanda: {_pair_title(before)} → "
                        f"{_pair_title(after) if after else 'configuração da demanda'}",
                        role=role, demand=demand, writer=writer)
    return {"event": ev["id"], "warnings": warnings}


def view(ctx: Ctx, rows: list[dict] | None = None, runs: list[dict] | None = None, fresh: bool = False,
         writer=None) -> dict:
    """GET /api/executores e `show --json`."""
    cfg = load(ctx, writer=writer)
    rows = read_rows(ctx) if rows is None else rows
    resolved = []
    for role in ROLES:
        try:
            r = resolve(role, ctx_name="plantao" if role == "orquestrador" else "passo", do_check=False, ctx=ctx,
                        writer=writer)
            resolved.append({k: r[k] for k in ("role", "runner", "model", "modelArg", "source", "via", "profile")})
        except ExecError as e:
            resolved.append({"role": role, "error": e.code, "detail": e.message})
    last_eff = {}
    for r in sorted(runs or [], key=lambda x: x.get("started") or ""):
        if r.get("agent") in ROLES and r.get("model"):
            last_eff[r["agent"]] = {"runner": r.get("runner") or "claude", "model": r.get("model"),
                                    "modelProvider": r.get("modelProvider"), "run": r.get("id"),
                                    "at": r.get("updated") or r.get("started")}
    history = [e for e in rows if e.get("type") == "executor-config"][-20:][::-1]
    orch = next((x for x in resolved if x["role"] == "orquestrador"), {})
    return {"config": cfg, "version": cfg["version"], "resolved": resolved, "status": check(ctx, fresh=fresh),
            "allowed": ctx.allowed, "policy": cfg["policy"],
            "ignoredEnv": ignored_env(orch if orch.get("runner") else None, cfg),
            "lastEffective": last_eff, "history": history,
            "plantao": {"runner": orch.get("runner"),
                        "via": "sessao" if orch.get("runner") == "claude" else "plantao.sh", "at": now_iso()},
            "decisions": dict(DECISOES), "codexWarning": CODEX_WARNING,
            "configPath": str(ctx.config_path)}


# ============================================================== comandos por perfil × executor (§7.1)
DENY_BASE = ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"]
AUDIT_ALLOW = ["Read", "Glob", "Grep", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
               "Bash(git status:*)", "Bash(ls:*)"]
# G2-D26 (antes da Q3): as regras `Bash(git diff:*)` são por PREFIXO — `git diff HEAD --output=x` ou
# `git diff --no-index ~/.ssh/id x` passariam. O perfil ganha um gancho PreToolUse(Bash) que valida o comando
# inteiro (lista branca, falha FECHADA): git diff|log|show|status e ls, sem opções que escrevem/leem fora do repo.
AUDIT_GIT_SUB = {"diff", "log", "show", "status"}
AUDIT_FORBIDDEN_OPT = ("--output", "--no-index", "--ext-diff", "--textconv", "--git-dir", "--work-tree",
                       "--exec", "--upload-pack", "--receive-pack", "--paginate", "--config-env", "--attr-source",
                       "--orderfile", "--ignore-revs-file", "--contents", "--pathspec-from-file", "--exclude-from")
AUDIT_METACHARS = set(";&|<>`$\n\r\\")


def audit_bash_ok(command: str, cwd: str | None = None) -> tuple[bool, str]:
    """(permitido, motivo) de um comando Bash no perfil `auditoria`. Sem shell: metacaractere → negado."""
    import shlex
    cmd = (command or "").strip()
    if not cmd:
        return False, "comando vazio"
    bad = sorted({c for c in cmd if c in AUDIT_METACHARS})
    if bad:
        return False, f"metacaractere de shell não permitido: {''.join(bad)!r}"
    try:
        tok = shlex.split(cmd)
    except ValueError as e:
        return False, f"comando ilegível ({e})"
    base = pathlib.Path(cwd or os.getcwd()).resolve()

    def inside(arg: str) -> bool:
        if arg.startswith("~"):
            return False
        try:
            return (base / arg).resolve().is_relative_to(base)
        except (OSError, ValueError):
            return False

    if tok[0] == "git":
        if len(tok) < 2 or tok[1] not in AUDIT_GIT_SUB:
            return False, "git só com diff|log|show|status (sem opções antes do subcomando)"
        for t in tok[2:]:
            if t == "--":
                continue
            if t.startswith("--"):
                name = t.split("=", 1)[0].lower()
                # o git aceita abreviações de opções longas: `--outp=x` = `--output=x`
                if any(f == name or (len(name) >= 4 and f.startswith(name)) for f in AUDIT_FORBIDDEN_OPT):
                    return False, f"opção não permitida no perfil auditoria: {t}"
                continue
            if t.startswith("-O"):
                return False, f"opção não permitida no perfil auditoria: {t} (lê arquivo arbitrário)"
            if t.startswith("-"):
                continue
            if ("/" in t or t.startswith(".") or t.startswith("~")) and ":" not in t and not inside(t):
                return False, f"caminho fora do repositório: {t}"
        return True, ""
    if tok[0] == "ls":
        for t in tok[1:]:
            if not t.startswith("-") and not inside(t):
                return False, f"caminho fora do repositório: {t}"
        return True, ""
    return False, "no perfil auditoria só git diff|log|show|status e ls"


def cmd_audit_bash(_a) -> int:
    """Gancho PreToolUse(Bash) do perfil `auditoria`: falha FECHADA (qualquer erro nega)."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        ti = payload.get("tool_input") or {}
        ok, why = audit_bash_ok(ti.get("command") or "", payload.get("cwd"))
    except Exception as e:   # noqa: BLE001
        ok, why = False, f"validador falhou ({type(e).__name__})"
    if not ok:
        print(f"perfil auditoria: {why}", file=sys.stderr)
        return 2
    return 0


def audit_settings() -> str:
    """perfis/auditoria.json + o gancho de Bash com caminho absoluto (o worktree auditado pode não ter o validador)."""
    cfg = json.loads((PERFIS_DIR / "auditoria.json").read_text(encoding="utf-8"))
    hook = f'python3 "{pathlib.Path(__file__).resolve()}" audit-bash'
    cfg["hooks"] = {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": hook, "timeout": 10}]}]}
    return json.dumps(cfg, ensure_ascii=False)


def claude_deny_paths(data_root: pathlib.Path) -> list[str]:
    try:
        import conversa
        return conversa.claude_deny_paths(data_root)
    except Exception:
        root = str(pathlib.Path(data_root).resolve())
        return [f"Read(/{root}/.env)", f"Read(/{root}/.env.*)", f"Read(/{root}/.git/**)"]


def profile_cmd(profile: str, runner: str, prompt: str, cwd: pathlib.Path, data_root: pathlib.Path,
                log_dir: pathlib.Path, runs_dir: pathlib.Path) -> list[str]:
    """Comando do executor para o perfil (sem o modelo; o prompt é o ÚLTIMO argumento no codex)."""
    cwd = str(cwd)
    if runner == "claude":
        if profile == "leitura":
            return ["claude", "-p", prompt, "--setting-sources", "project", "--settings", str(PERFIS_DIR / "leitura.json"),
                    "--tools", "Read", "Glob", "Grep",
                    "--disallowedTools", "Bash", *DENY_BASE, *claude_deny_paths(data_root),
                    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--permission-mode", "dontAsk"]
        if profile == "auditoria":
            return ["claude", "-p", prompt, "--setting-sources", "project",
                    "--settings", audit_settings(), "--tools", "Read", "Glob", "Grep", "Bash",
                    "--allowedTools", *AUDIT_ALLOW,
                    "--disallowedTools", *DENY_BASE, *claude_deny_paths(data_root), "--permission-mode", "dontAsk"]
        # escrita e orquestracao: como hoje (fontes de settings padrão)
        return ["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                "--allowedTools", "Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    common = ["--skip-git-repo-check", "-c", 'approval_policy="never"']
    if profile == "leitura":
        return ["codex", "exec", "-s", "read-only", "-C", cwd, *common, "-c", "mcp_servers={}", prompt]
    if profile == "auditoria":   # errata §7.1 (G2-D26): sem MCP do ~/.codex/config.toml, como o leitura
        return ["codex", "exec", "-s", "read-only", "-C", cwd, *common, "-c", "mcp_servers={}", prompt]
    if profile == "orquestracao":
        if not DECISOES["Q2"]:
            raise ExecError(EXIT_NOT_ALLOWED, "orquestrador_codex_pendente_q2", Q2_REASON)
        return ["codex", "exec", "-s", "danger-full-access", "-C", cwd, *common, prompt]
    add = []
    for d in dict.fromkeys([str(log_dir), str(runs_dir)]):
        add += ["--add-dir", d]
    return ["codex", "exec", "-s", "workspace-write", "-C", cwd, *add,
            "-c", "sandbox_workspace_write.network_access=true", *common, prompt]


def with_model(cmd: list[str], runner: str, model_arg: str | None) -> list[str]:
    if not model_arg:
        return cmd
    if runner == "codex":
        return cmd[:-1] + ["-m", model_arg, cmd[-1]]
    return cmd + ["--model", model_arg]


# ============================================================== gancho guard-agent (§8.6)
ROLE_IN_PROMPT = re.compile(r"agente \*\*(Orquestrador|Arquiteto|Backend|DevOps|Observabilidade|Frontend|QA|Auditor)"
                            r"\*\*|--agent[ =]['\"]?(orquestrador|arquiteto|backend|devops|observabilidade|frontend|"
                            r"qa|auditor)\b", re.I)
DEMAND_IN_PROMPT = re.compile(r"--demand[ =]['\"]?([0-9a-f]{12})\b")


def guard_role(tool_input: dict) -> str | None:
    st = (tool_input.get("subagent_type") or "").strip().lower()
    if st in ROLES:
        return st
    m = ROLE_IN_PROMPT.search(tool_input.get("prompt") or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).lower()


def guard(payload: dict, ctx: Ctx | None = None) -> tuple[int, str]:
    """(0 permite | 2 nega, motivo). Com a configuração padrão (tudo no Claude, modelo padrão) SEMPRE permite."""
    tool_input = payload.get("tool_input") or {}
    role = guard_role(tool_input)
    if role is None:
        return 0, ""
    m = DEMAND_IN_PROMPT.search(tool_input.get("prompt") or "")
    demand = m.group(1) if m else None
    ctx = ctx or context()
    try:
        r = resolve(role, demand, "passo", do_check=False, ctx=ctx, record=False)
    except ExecError as e:
        if e.code == "trava_executores":   # G2-D26: trava ocupada não é configuração ilegível → falha ABERTA
            return 0, f"executores guard-agent: {e.message}; subagente permitido sem checar a configuração"
        if e.exit_code == EXIT_CONFIG:
            return 2, (f"executores: configuração ilegível ({e.message}); corrija {ctx.config_path} "
                       "no painel antes de delegar")
        return 2, f"executores: {e.message}"
    tool = ctx.base / "tools/squad/run_agent.py"
    tool = tool if tool.exists() else product.PLATFORM_ROOT / "tools/squad/run_agent.py"
    cmd = (f'python3 "{tool}" {role} "<tarefa>"'
           + (f" --demand {demand}" if demand else ""))
    if r["via"] != "nativo":
        return 2, (f"executores: {LABEL[role]} está configurado para {RUNNER_LABEL[r['runner']]}"
                   f"{' · ' + r['model'] if r['model'] else ''} (origem {r['source']}); subagente nativo negado. "
                   f"Use: {cmd}")
    asked = (tool_input.get("model") or "").strip().lower() or None
    if r["model"] not in (None, "default") and asked and asked != r["model"]:
        return 2, (f"executores: {LABEL[role]} está configurado com o modelo {r['model']}, não {asked}; "
                   f"omita `model` ou use model={r['model']}")
    try:
        if dispatch_changed(read_rows(ctx), demand, role, r["configured"]):
            append_event(ctx, {"agent": "orquestrador", "type": "executor-dispatch", "demand": demand, "role": role,
                               "via": "nativo", "configured": r["configured"], "source": r["source"],
                               "title": f"{LABEL[role]}: subagente nativo ({_pair_title(r['configured'])})"})
    except OSError:
        pass
    return 0, ""


def dispatch_changed(rows: list[dict], demand: str | None, role: str, configured: dict) -> bool:
    """Decisão D26 (volume): `executor-dispatch` só no 1º despacho nativo de (papel, demanda) ou quando o
    executor/modelo configurado muda — não a cada Agent/Task."""
    pair = {"runner": configured.get("runner"), "model": configured.get("model")}
    for e in reversed(rows):
        if e.get("type") == "executor-dispatch" and e.get("role") == role and (e.get("demand") or None) == demand:
            c = e.get("configured") or {}
            return {"runner": c.get("runner"), "model": c.get("model")} != pair
    return True


def cmd_guard_agent(_a) -> int:
    """Falha ABERTA: qualquer erro inesperado permite o subagente e avisa em stderr (não trava o plantão)."""
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            return 0
        code, msg = guard(payload)
        if msg:
            print(msg, file=sys.stderr)
        return code
    except Exception as e:   # noqa: BLE001 — o gancho nunca derruba a sessão
        print(f"executores guard-agent: erro no gancho ({type(e).__name__}: {e}); subagente permitido", file=sys.stderr)
        return 0


# ============================================================== CLI
def _refuse_agent_writes():
    if os.environ.get("SQUAD_RUN") or os.environ.get("CLAUDECODE") or not sys.stdin.isatty():
        raise ExecError(EXIT_REFUSED, "recusado_dentro_de_agente",
                        "agente não muda a própria configuração: use o painel (Squad Control → Executores)")


def _print(obj, as_json=True):
    print(json.dumps(obj, ensure_ascii=False, indent=2) if as_json else obj)


def cmd_show(a) -> int:
    ctx = context()
    v = view(ctx, fresh=False)
    if a.json:
        _print(v)
        return 0
    print(f"arquivo: {v['configPath']} (versão {v['version']}) · política: {v['policy']['onUnavailable']}")
    for r in v["resolved"]:
        if r.get("error"):
            print(f"  {r['role']:<16} ERRO {r['error']}: {r['detail']}")
        else:
            print(f"  {r['role']:<16} {r['runner']:<7} {r['model'] or '(padrão do executor)':<22} "
                  f"origem={r['source']:<7} via={r['via']:<9} perfil={r['profile']}")
    for k, s in v["status"].items():
        print(f"  [{k}] instalado={s['installed']} login={s['loggedIn']} versão={s['version']} ({s['detail']})")
    for var in v["ignoredEnv"]:
        print(f"  aviso: variável {var} ignorada (a configuração vem do painel)")
    return 0


def cmd_resolve(a) -> int:
    ctx = context()
    try:
        r = resolve(a.role, a.demand, a.context, make_snapshot=not a.no_snapshot, do_check=not a.no_check, ctx=ctx)
    except ExecError as e:
        _print({"role": a.role, "error": e.code, "detail": e.message, **e.extra})
        return e.exit_code
    for w in r["warnings"]:
        if w.startswith("variavel_ignorada:"):
            print(f"aviso: {w.split(':', 1)[1]} ignorada (a configuração vem do painel/executores.py)", file=sys.stderr)
    _print(r)
    return 0


def cmd_check(a) -> int:
    st = check(context(), a.runner, fresh=a.fresh)
    _print(st)
    return 0 if all(usable(s) for s in st.values()) else EXIT_UNAVAILABLE


def cmd_set(a) -> int:
    _refuse_agent_writes()
    ctx = context()
    if a.by != "humano":
        raise ExecError(EXIT_VALIDATION, "formato_invalido", "--by humano é obrigatório")
    model = a.model if a.model not in (None, "", "padrao") else None
    if a.scope == "squad":
        out = save(ctx, {"squad": {"runner": a.runner, "model": model}, "acknowledge": a.ack}, via="cli")
    elif a.scope == "agent":
        if a.role not in ROLES:
            raise ExecError(EXIT_VALIDATION, "papel_invalido", "--role obrigatório (um dos 8 papéis)")
        pair = None if a.runner in (None, "", "padrao") else {"runner": a.runner, "model": model}
        out = save(ctx, {"agents": {a.role: pair}, "acknowledge": a.ack}, via="cli")
    elif a.scope == "policy":
        out = save(ctx, {"policy": {"onUnavailable": a.policy}}, via="cli")
    else:
        if not a.demand:
            raise ExecError(EXIT_VALIDATION, "formato_invalido", "--demand obrigatório")
        runner = None if a.runner in (None, "", "padrao") else a.runner
        out = set_demand(ctx, a.demand, a.role, runner, model, a.ack, via="cli")
    _print(out)
    return 0


def cmd_apply_all(a) -> int:
    _refuse_agent_writes()
    if a.by != "humano":
        raise ExecError(EXIT_VALIDATION, "formato_invalido", "--by humano é obrigatório")
    _print(apply_all(context(), {"runner": a.runner, "model": a.model or None, "acknowledge": a.ack}, via="cli"))
    return 0


def cmd_snapshot(a) -> int:
    _print(snapshot(context(), a.demand))
    return 0


def cmd_check_session(a) -> int:
    """§8.5: o plantão numa sessão do Claude Code só roda com o Orquestrador em `claude`."""
    try:
        r = resolve(a.role, None, "plantao", do_check=False)
    except ExecError as e:
        print(f"plantão desta sessão suspenso: {e.message}; use tools/squad/plantao.sh")
        return EXIT_STOP
    if r["runner"] != a.runner:
        print(f"plantão desta sessão suspenso: Orquestrador configurado para {r['runner']}; use tools/squad/plantao.sh")
        return EXIT_STOP
    print(f"ok: Orquestrador em {r['runner']}" + (f" · {r['model']}" if r["model"] else ""))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("resolve")
    s.add_argument("role")
    s.add_argument("--demand")
    s.add_argument("--context", default="passo", choices=CONTEXTS)
    s.add_argument("--no-snapshot", action="store_true")
    s.add_argument("--no-check", action="store_true", help="não checa instalação/login (só a configuração)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("check")
    s.add_argument("--runner", choices=RUNNERS)
    s.add_argument("--fresh", action="store_true")
    s.set_defaults(fn=cmd_check)
    s = sub.add_parser("set")
    s.add_argument("--scope", required=True, choices=("squad", "agent", "demand", "policy"))
    s.add_argument("--role")
    s.add_argument("--demand")
    s.add_argument("--runner")
    s.add_argument("--model")
    s.add_argument("--policy", choices=POLICIES)
    s.add_argument("--by", required=True)
    s.add_argument("--ack", action="store_true")
    s.set_defaults(fn=cmd_set)
    s = sub.add_parser("apply-all")
    s.add_argument("--runner", required=True)
    s.add_argument("--model")
    s.add_argument("--by", required=True)
    s.add_argument("--ack", action="store_true")
    s.set_defaults(fn=cmd_apply_all)
    s = sub.add_parser("snapshot")
    s.add_argument("--demand", required=True)
    s.set_defaults(fn=cmd_snapshot)
    s = sub.add_parser("guard-agent")
    s.set_defaults(fn=cmd_guard_agent)
    s = sub.add_parser("audit-bash", help="gancho PreToolUse(Bash) do perfil auditoria (falha fechada)")
    s.set_defaults(fn=cmd_audit_bash)
    s = sub.add_parser("check-session")
    s.add_argument("role", choices=["orquestrador"])
    s.add_argument("--runner", default="claude", choices=RUNNERS)
    s.set_defaults(fn=cmd_check_session)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except ExecError as e:
        print(f"executores: {e.message}", file=sys.stderr)
        if e.extra.get("warnings"):
            print(json.dumps(e.extra, ensure_ascii=False), file=sys.stderr)
        return e.exit_code
    except product.ProductError as e:
        print(f"executores: {e}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
