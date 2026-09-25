#!/usr/bin/env python3
"""Publicação do Squad Control — lado do servidor (D24, ADR-025, `docs/contracts/publicacao-do-squad-control.md`).

Somente stdlib. Importado pelo `server.py` (rotas `/api/squad-control/*`, campo `publication` do `/api/live`, SIGTERM
gracioso) e pelo `publisher.py` (caminhos, leitura/gravação do `status.json` e dos pedidos).
A única interface entre o servidor e o supervisor é o disco: o servidor LÊ `status.json` (cache por mtime) e GRAVA
pedidos em `requests/` (tmp + rename). Nunca sinal nem subprocesso (§4.2).
"""
import json
import os
import pathlib
import signal
import threading
import time
import uuid
from datetime import datetime, timezone

STATE_REL = ".squad/squad-control"
BUSY_STATES = ("verificando", "aguardando-ponto-seguro", "reiniciando", "revertendo")
STATES = ("no-ar", *BUSY_STATES, "revertido", "fora-do-ar", "parado")
WHEN = ("now", "safe")
MAX_BODY = 4096
LIVE_MAX = 1024
REASON_TEXT = {"sem_supervisor": "Rode make squad para iniciar o Squad Control com o publicador",
               "nao_produtivo": "Disponível só no produtivo", "publicacao_em_andamento": "Publicação em andamento"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_dir(data_root) -> pathlib.Path:
    return pathlib.Path(data_root) / STATE_REL


def pid_alive(pid) -> bool:
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def write_json_atomic(path: pathlib.Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- leitura do status.json (cache por mtime)
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def read_status(sdir) -> dict | None:
    p = pathlib.Path(sdir) / "status.json"
    try:
        st = p.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    with _CACHE_LOCK:
        hit = _CACHE.get(str(p))
        if hit and hit[0] == key:
            return hit[1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    with _CACHE_LOCK:
        _CACHE[str(p)] = (key, data)
    return data


def supervised(status: dict | None, env=None) -> bool:
    """§4.1: há status.json, o supervisor está vivo e ESTE servidor foi iniciado por ele (SQUAD_SUPERVISED)."""
    env = os.environ if env is None else env
    if not status or not env.get("SQUAD_SUPERVISED"):
        return False
    return bool(status.get("supervised")) and pid_alive((status.get("supervisor") or {}).get("pid"))


def _short_result(r) -> dict | None:
    if not isinstance(r, dict):
        return None
    return {k: r.get(k) for k in ("type", "commit", "display", "at", "eventId")}


def live_view(sdir, env=None) -> dict | None:
    """§4.3: objeto ≤ 1 KB para o /api/live; null sem supervisor. Sem git e sem rede."""
    st = read_status(sdir)
    if not supervised(st, env):
        return None
    tgt = st.get("target")
    out = {"state": st.get("state"),
           "target": {"commit": tgt.get("commit"), "display": tgt.get("display")} if isinstance(tgt, dict) else None,
           "deadline": st.get("deadline"), "trigger": st.get("trigger"),
           "lastResult": _short_result(st.get("lastResult")),
           "mode": (st.get("server") or {}).get("mode")}
    if len(json.dumps(out, ensure_ascii=False).encode()) > LIVE_MAX:
        if out["lastResult"]:
            out["lastResult"]["display"] = None
        if out["target"]:
            out["target"]["display"] = None
    return out


def api_view(sdir, instance: dict | None, busy: dict | None, env=None) -> dict:
    """§4.1: GET /api/squad-control/publication."""
    st = read_status(sdir)
    sup = supervised(st, env)
    st = st or {}
    out = {"supervised": sup, "state": st.get("state") if sup else None, "server": st.get("server") if sup else None,
           "target": st.get("target") if sup else None, "deadline": st.get("deadline") if sup else None,
           "trigger": st.get("trigger") if sup else None, "busy": busy,
           "lastResult": st.get("lastResult") if sup else None,
           "failedCommit": st.get("failedCommit") if sup else None}
    reason = None
    if not sup:
        reason = "sem_supervisor"
    elif ((instance or {}).get("environment") or {}).get("name") != "produtivo":
        reason = "nao_produtivo"
    elif st.get("state") in BUSY_STATES:
        reason = "publicacao_em_andamento"
    out["canPublish"] = reason is None
    out["reason"] = reason
    return out


# ---------------------------------------------------------------- pedidos (botão / CLI)
def write_request(sdir, when: str, confirm: bool, busy: dict | None, trigger: str) -> dict:
    req = {"id": uuid.uuid4().hex[:12], "at": now_iso(), "when": when, "confirm": bool(confirm), "busy": busy,
           "trigger": trigger}
    rdir = pathlib.Path(sdir) / "requests"
    rdir.mkdir(parents=True, exist_ok=True)
    # nome ordenável pelo tempo: o supervisor processa o mais antigo
    write_json_atomic(rdir / f"{time.time_ns()}-{req['id']}.json", req)
    return req


def read_requests(sdir) -> list[tuple[pathlib.Path, dict]]:
    rdir = pathlib.Path(sdir) / "requests"
    out = []
    for p in sorted(rdir.glob("*.json")) if rdir.is_dir() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict) and d.get("when") in WHEN:
                out.append((p, d))
            else:
                p.unlink(missing_ok=True)
        except (OSError, ValueError):
            p.unlink(missing_ok=True)
    return out


def requested_event(req: dict) -> dict:
    """Evento `squad-publish-requested` (agent humano, §8)."""
    return {"agent": "humano", "type": "squad-publish-requested", "title": "Publicação do Squad Control pedida",
            "requestId": req["id"], "when": req["when"], "confirm": req["confirm"], "busy": req.get("busy"),
            "trigger": req.get("trigger") or "botao"}


def handle_publish(sdir, instance: dict | None, busy: dict | None, content_type: str | None, raw: bytes,
                   append_event, env=None) -> tuple[int, dict]:
    """§4.2, na ordem da tabela (a origem local já foi conferida pelo servidor). `append_event(dict)` grava no log."""
    if (content_type or "").split(";")[0].strip().lower() != "application/json":
        return 400, {"code": "pedido_invalido", "error": "Content-Type deve ser application/json"}
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return 400, {"code": "pedido_invalido", "error": "JSON inválido"}
    if not isinstance(data, dict):
        return 400, {"code": "pedido_invalido", "error": "corpo deve ser um objeto"}
    when = data.get("when", "now")
    confirm = data.get("confirm", False)
    if when not in WHEN or not isinstance(confirm, bool):
        return 400, {"code": "pedido_invalido", "error": "when deve ser now ou safe"}
    view = api_view(sdir, instance, busy, env)
    if view["reason"] == "sem_supervisor":
        return 409, {"code": "sem_supervisor", "error": REASON_TEXT["sem_supervisor"]}
    if view["reason"] == "nao_produtivo":
        return 409, {"code": "nao_produtivo", "error": REASON_TEXT["nao_produtivo"]}
    if view["reason"] == "publicacao_em_andamento":
        return 409, {"code": "publicacao_em_andamento", "state": view["state"],
                     "error": REASON_TEXT["publicacao_em_andamento"]}
    if when == "now" and busy is not None and confirm is not True:
        return 409, {"code": "resposta_em_andamento", "busy": busy,
                     "error": "Há uma resposta da conversa em andamento"}
    req = write_request(sdir, when, confirm, busy, "botao")
    append_event(requested_event(req))
    return 202, {"requestId": req["id"]}


# ---------------------------------------------------------------- parada graciosa do servidor (§6)
def install_signals(httpd, engine_fn, grace_s: float = 3.0):
    """SIGTERM (publicação) e SIGINT (Ctrl+C do modo em primeiro plano): para de aceitar conexões, encerra o turno
    ativo da conversa como `interrompida` (texto parcial preservado) e deixa o `serve_forever` retornar.
    Devolve `wait()`, chamado pelo `main()` depois do `serve_forever`, que espera o encerramento terminar."""
    done = threading.Event()
    started = threading.Event()

    def worker(code: str):
        try:
            threading.Thread(target=httpd.shutdown, daemon=True).start()   # 1. não aceita mais conexões
            eng = engine_fn()
            if eng is not None:
                eng.shutdown(code)                                            # 2. turno ativo → interrompida
        finally:
            done.set()

    def handler(signum, _frame):
        if started.is_set():
            return
        started.set()
        code = "reinicio_publicacao" if signum == signal.SIGTERM else "servidor_encerrado"
        threading.Thread(target=worker, args=(code,), daemon=True).start()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    def wait():
        if started.is_set():
            done.wait(grace_s + 5.5)   # Engine.shutdown espera o runner até ~5 s
            time.sleep(min(grace_s, 0.5))   # requisições não SSE em curso terminam (as SSE caem)
    return wait
