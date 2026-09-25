#!/usr/bin/env python3
"""Publicador do Squad Control (D24, ADR-025, `docs/contracts/publicacao-do-squad-control.md`) — somente stdlib.

Supervisor local que roda o `server.py` como processo filho e publica a versão nova depois de um merge na `develop`
(detecção por `git ls-remote` a cada 15 s) ou por pedido do humano (botão "Publicar Squad Control" / CLI), com as
travas do ADR-018 adaptadas a processo, pré-voo num candidato com dados sintéticos, ponto seguro da conversa, saúde
depois da troca, rollback pelo worktree `plankton-squad-prev` e página de manutenção.

  start [--port 7070] [--yes]   daemoniza; adota o servidor atual da cópia principal só com confirmação no terminal
  stop                          para o supervisor (e o servidor, graciosamente)
  status [--json]               estado (0 no ar, 1 fora)
  publish [--when now|safe]     grava um pedido como o botão (trigger = cli); 3 sem supervisor
  ensure                        sobe o supervisor se a porta estiver livre (plantão); nunca adota
  selftest                      importa os módulos e valida o CONFIG (antes do execv)
  run                           loop em primeiro plano (usado por start e pelos testes)

Estado em `<dados>/.squad/squad-control/` (supervisor.lock, supervisor.pid, status.json, requests/, server.log*,
publisher.log*, preflight/). Variáveis (testes): SQUAD_PUBLISH_COMMAND, SQUAD_PUBLISH_POLL_S ("15" ou "15,2"),
SQUAD_PUBLISH_SAFE_WAIT_S ("20" ou "20,600"), SQUAD_PUBLISH_AUTO=0, SQUAD_GIT, SQUAD_LSOF, SQUAD_LOG, SQUAD_ROOT_DATA,
e só para acelerar testes: SQUAD_PUBLISH_STABLE_S, SQUAD_PUBLISH_HEALTH_TIMEOUT_S, SQUAD_PUBLISH_STOP_GRACE_S,
SQUAD_PUBLISH_CANDIDATE_PORT, SQUAD_PUBLISH_PREV_WORKTREE.
"""
import argparse
import fcntl
import json
import logging
import os
import pathlib
import py_compile
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import publication as pub  # noqa: E402
import testenv as te  # noqa: E402
import instance as inst  # noqa: E402
import transcripts as tr  # noqa: E402  (máscara de segredos)

DEFAULT_ROOT = HERE.parents[1]
PROD_PORT = 7070
# Espelho do [env.prod] do ADR-024 §3 (na F2b vem do product.toml do squad-platform).
CONFIG = {
    "kind": "process",
    "command": [sys.executable, "tools/squad/server.py", "--port", "{port}"],
    "ports": {"control": PROD_PORT},
    "health": "/api/instance",
    "update": "restart",
    "watch_paths": list(inst.CODE_PATHS),
    "poll_s": 15, "request_poll_s": 2,
    "safe_wait_s": 20, "safe_wait_button_s": 600,
    "health_timeout_s": 20, "stable_s": 10, "stop_grace_s": 8,
    "auto": True,
}
CANDIDATE_PORT = 17070
CANDIDATE_TIMEOUT_S = 15
SYNC_LIMIT_S = 300
CRASH_WINDOW_S, CRASH_MAX = 300, 5
MAINT_RETRY_S = 60
LOG_MAX_BYTES, LOG_KEEP = 5 * 1024 * 1024, 2
OPS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "index.lock")
SELF_FILES = ("tools/squad/publisher.py", "tools/squad/publication.py")
PHASE_TEXT = {"guard": "travas", "sync": "sincronização da develop", "preflight": "verificação prévia",
              "health": "saúde após reinício", "ponto-seguro": "resposta não terminou", "supervisor": "publicador",
              "stop": "parada do servidor", "rollback": "rollback"}
# R1 do G2: memória viva da squad (espelho de gitflow.STATE) e logs append-only (1 evento JSON com "id" por linha)
STATE_PATHS = ("docs/squad/memory/", "docs/squad/inbox/", "docs/squad/produto/bugs/", "docs/squad/operacao/bugs/")
APPEND_LOGS = ("docs/squad/memory/decisions.jsonl",)
MERGE_GRACE_S = 0.3
TMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")

log = logging.getLogger("publisher")


def now_iso() -> str:
    return pub.now_iso()


def load_config(env=None) -> dict:
    env = os.environ if env is None else env
    c = json.loads(json.dumps(CONFIG))
    cmd = (env.get("SQUAD_PUBLISH_COMMAND") or "").strip()
    if cmd:
        c["command"] = json.loads(cmd) if cmd.startswith("[") else shlex.split(cmd)

    def nums(name):
        raw = (env.get(name) or "").strip()
        return [float(x) for x in raw.split(",") if x.strip()] if raw else []
    p = nums("SQUAD_PUBLISH_POLL_S")
    if p:
        c["poll_s"] = p[0]
        if len(p) > 1:
            c["request_poll_s"] = p[1]
    w = nums("SQUAD_PUBLISH_SAFE_WAIT_S")
    if w:
        c["safe_wait_s"] = w[0]
        if len(w) > 1:
            c["safe_wait_button_s"] = w[1]
    for key, var in (("stable_s", "SQUAD_PUBLISH_STABLE_S"), ("health_timeout_s", "SQUAD_PUBLISH_HEALTH_TIMEOUT_S"),
                     ("stop_grace_s", "SQUAD_PUBLISH_STOP_GRACE_S")):
        v = nums(var)
        if v:
            c[key] = v[0]
    if (env.get("SQUAD_PUBLISH_AUTO") or "1").strip() == "0":
        c["auto"] = False
    return c


def validate_config(c: dict) -> list[str]:
    errs = []
    for k in ("kind", "command", "ports", "health", "update", "watch_paths", "poll_s", "safe_wait_s",
              "health_timeout_s", "stable_s", "stop_grace_s", "auto"):
        if k not in c:
            errs.append(f"CONFIG sem {k}")
    if c.get("kind") != "process" or c.get("update") != "restart":
        errs.append("kind/update devem ser process/restart")
    if not isinstance(c.get("command"), list) or not any("{port}" in str(x) for x in c.get("command") or []):
        errs.append("command deve ser uma lista com {port}")
    return errs


# ================================================================ utilidades
def git(root, *args, timeout: float = 30) -> tuple[int, str, str]:
    exe = os.environ.get("SQUAD_GIT") or "git"
    try:
        p = subprocess.run([exe, *args], cwd=str(root), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout após {int(timeout)} s: git {' '.join(args)}"


def git_raw(root, *args, timeout: float = 30) -> subprocess.CompletedProcess:
    """Como `git`, mas sem strip e em bytes (status -z, show de blob)."""
    return subprocess.run([os.environ.get("SQUAD_GIT") or "git", *args], cwd=str(root), capture_output=True,
                          timeout=timeout)


def git_out(root, *args, timeout: float = 30) -> str | None:
    rc, out, _ = git(root, *args, timeout=timeout)
    return out if rc == 0 else None


def listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def free_port(start: int) -> int:
    for p in range(start, start + 500):
        if listening(p):
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"nenhuma porta livre a partir de {start}")


def http_get(port: int, path: str, timeout: float = 2.0) -> tuple[int | None, bytes]:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": f"127.0.0.1:{port}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return None, b""


def http_json(port: int, path: str, timeout: float = 2.0) -> dict | None:
    code, body = http_get(port, path, timeout)
    if code != 200:
        return None
    try:
        d = json.loads(body)
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def lsof_pid(port: int) -> int | None:
    exe = os.environ.get("SQUAD_LSOF") or shutil.which("lsof")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
                           timeout=5)
        pids = [int(x) for x in p.stdout.split() if x.strip().isdigit()]
        return pids[0] if pids else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def mask(text: str, limit: int = 1500) -> str:
    t = tr.mask(text or "")
    return t if len(t) <= limit else t[: limit - 1] + "…"


def tail(path: pathlib.Path, n: int = 20) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16384))
            lines = f.read().decode("utf-8", "replace").splitlines()[-n:]
        return mask("\n".join(lines))
    except OSError:
        return ""


def rotate(path: pathlib.Path):
    """copytruncate (o filho escreve com O_APPEND): server.log e publisher.log com 5 MB e 3 arquivos."""
    try:
        if path.stat().st_size <= LOG_MAX_BYTES:
            return
        for i in range(LOG_KEEP, 1, -1):
            older = path.with_name(f"{path.name}.{i - 1}")
            if older.exists():
                os.replace(older, path.with_name(f"{path.name}.{i}"))
        shutil.copyfile(path, path.with_name(f"{path.name}.1"))
        with path.open("r+b") as f:
            f.truncate(0)
    except OSError:
        pass


def sha7(s) -> str | None:
    return s[:7] if s else None


def is_tmp(p: pathlib.Path) -> bool:
    s = str(p.resolve()) + "/"
    return s.startswith(TMP_PREFIXES) or s.startswith(tempfile.gettempdir().rstrip("/") + "/")


# ================================================================ caminhos
class Paths:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root).resolve()
        env_data = os.environ.get("SQUAD_ROOT_DATA")
        self.data = pathlib.Path(env_data).resolve() if env_data else self.root
        self.sdir = pub.state_dir(self.data)
        self.lock = self.sdir / "supervisor.lock"
        self.pidfile = self.sdir / "supervisor.pid"
        self.status = self.sdir / "status.json"
        self.server_log = self.sdir / "server.log"
        self.pub_log = self.sdir / "publisher.log"
        self.preflight = self.sdir / "preflight"
        self.publish_lock = self.data / ".squad/locks/squad-publish.lock"
        self.log = pathlib.Path(os.environ.get("SQUAD_LOG") or self.data / "docs/squad/memory/decisions.jsonl")
        self.prev = pathlib.Path(os.environ.get("SQUAD_PUBLISH_PREV_WORKTREE")
                                 or self.root.parent / te.PUBLISHER_WORKTREE).resolve()


def main_root_of(root: pathlib.Path) -> pathlib.Path | None:
    return te.find_main_root(root)


def on_develop(root) -> bool:
    return git_out(root, "symbolic-ref", "-q", "HEAD", timeout=10) == "refs/heads/develop"


def op_in_progress(root) -> str | None:
    for name in OPS:
        p = git_out(root, "rev-parse", "--git-path", name, timeout=10)
        if p is None:
            return "git indisponível"
        path = pathlib.Path(p)
        if not path.is_absolute():
            path = pathlib.Path(root) / path
        if path.exists():
            return name
    return None


def structural_guard(root: pathlib.Path, port: int) -> str | None:
    """CA-15: com a porta do CONFIG, qualquer comando que suba/derrube um servidor exige a cópia principal em develop
    (e nunca um diretório temporário). Checado antes de qualquer kill, bind ou escrita git."""
    if port != CONFIG["ports"]["control"]:
        return None
    if is_tmp(root):
        return f"porta {port} recusada: {root} é um diretório temporário (testes nunca tocam a {port})"
    main = main_root_of(root)
    if main is None or main != root.resolve():
        return f"porta {port} recusada: {root} não é a cópia principal ({main})"
    if not on_develop(root):
        return f"porta {port} recusada: a cópia principal não está em develop"
    return None


def lock_held(path: pathlib.Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("a+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def supervisor_alive(paths: Paths) -> int | None:
    """pid do supervisor vivo (lock tomado + pid vivo) ou None."""
    if not lock_held(paths.lock):
        return None
    try:
        pid = int(paths.pidfile.read_text().strip())
    except (OSError, ValueError):
        st = pub.read_status(paths.sdir) or {}
        pid = (st.get("supervisor") or {}).get("pid")
    return pid if pub.pid_alive(pid) else None


# ================================================================ processo filho
class Child:
    def __init__(self, pid: int, popen: subprocess.Popen | None, mode: str, commit: str | None, port: int,
                 cwd: pathlib.Path, started: str | None = None):
        self.pid, self.popen, self.mode, self.commit, self.port, self.cwd = pid, popen, mode, commit, port, cwd
        self.started = started or now_iso()
        self.code: int | None = None

    def alive(self) -> bool:
        if self.code is not None:
            return False
        if self.popen is not None:
            rc = self.popen.poll()
            if rc is None:
                return True
            self.code = rc
            return False
        try:   # filho herdado pelo execv: ainda é nosso filho (waitpid); senão, kill(0)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid == 0:
                return True
            self.code = os.waitstatus_to_exitcode(status)
            return False
        except ChildProcessError:
            if pub.pid_alive(self.pid):
                return True
            self.code = -1
            return False

    def wait(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.alive():
                return True
            time.sleep(0.1)
        return not self.alive()


def terminate_pid(pid: int, grace: float, is_dead) -> bool:
    """SIGTERM, espera `grace` s, SIGKILL. Devolve True se precisou do SIGKILL."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    end = time.monotonic() + grace
    while time.monotonic() < end:
        if is_dead():
            return False
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    end = time.monotonic() + 3
    while time.monotonic() < end and not is_dead():
        time.sleep(0.1)
    return True


# ================================================================ página de manutenção (§7.4)
MAINT_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Squad Control fora do ar</title>
<style>body{{font-family:system-ui,sans-serif;background:#1d1f21;color:#e6e6e6;margin:0;padding:2rem}}
main{{max-width:52rem;margin:auto}}pre{{background:#111;padding:1rem;overflow:auto;font-size:.8rem}}
button{{font-size:1rem;padding:.5rem 1rem}}code{{color:#9fd}}</style></head><body><main>
<h1>Squad Control fora do ar</h1>
<p>A publicação de <code>{failed}</code> falhou ({phase}) e a versão anterior <code>{prev}</code> também não subiu.</p>
<p>Logs: <code>{server_log}</code> e <code>{pub_log}</code></p>
<h2>Últimas linhas do server.log</h2><pre>{tail}</pre>
<p><button id="b">Tentar de novo</button> <span id="m" role="status"></span></p></main>
<script>document.getElementById('b').onclick=async()=>{{const m=document.getElementById('m');
try{{const r=await fetch('/api/squad-control/publish',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{when:'now',confirm:true}})}});m.textContent=r.status===202?'Pedido registrado; aguarde…':'Recusado ('+r.status+')';
if(r.status===202)setTimeout(()=>location.reload(),15000);}}catch(e){{m.textContent='Erro: '+e;}}}};</script>
</body></html>"""


def _esc(s) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def local_ok(headers) -> bool:
    host = (headers.get("Host") or "").strip().lower()
    hostname = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0] if ":" in host else host
    if hostname not in ("127.0.0.1", "localhost"):
        return False
    origin = headers.get("Origin")
    if origin is not None:
        try:
            u = urllib.parse.urlsplit(origin)
            if u.scheme not in ("http", "https") or u.hostname not in ("127.0.0.1", "localhost"):
                return False
        except ValueError:
            return False
    return (headers.get("Sec-Fetch-Site") or "same-origin") in ("same-origin", "none")



class Maintenance:
    def __init__(self, sup: "Supervisor", port: int, info: dict):
        self.sup, self.info = sup, info
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _send(self, code, body: bytes, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code, obj):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path == "/api/squad-control/publication":
                    if not local_ok(self.headers):
                        return self._json(403, {"code": "origem_invalida"})
                    st = outer.sup.status
                    return self._json(200, {**{k: st.get(k) for k in ("supervised", "state", "server", "target",
                                                                       "deadline", "trigger", "lastResult",
                                                                       "failedCommit")},
                                            "busy": None, "canPublish": True, "reason": None})
                if path.startswith("/api/"):
                    return self._json(503, {"code": "fora_do_ar", "error": "Squad Control fora do ar"})
                i = outer.info
                html = MAINT_HTML.format(failed=_esc(i.get("failed")), phase=_esc(i.get("phase")),
                                         prev=_esc(i.get("prev")), server_log=_esc(outer.sup.paths.server_log),
                                         pub_log=_esc(outer.sup.paths.pub_log),
                                         tail=_esc(tail(outer.sup.paths.server_log)))
                self._send(200, html.encode(), "text/html; charset=utf-8")

            def do_POST(self):
                path = urllib.parse.urlsplit(self.path).path
                if path != "/api/squad-control/publish":
                    return self._json(503, {"code": "fora_do_ar"})
                if not local_ok(self.headers):
                    return self._json(403, {"code": "origem_invalida"})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = -1
                if n < 0 or n > pub.MAX_BODY:
                    return self._json(400, {"code": "pedido_invalido"})
                raw = self.rfile.read(n)
                code, out = pub.handle_publish(outer.sup.paths.sdir, {"environment": {"name": "produtivo"}}, None,
                                               self.headers.get("Content-Type"), raw, outer.sup.append_raw,
                                               env={"SQUAD_SUPERVISED": "1"})
                return self._json(code, out)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


# ================================================================ supervisor
class Retry(Exception):
    """Condição transitória (operação git em curso, lock ocupado): tenta no próximo ciclo, sem evento."""


class Supervisor:
    def __init__(self, root: pathlib.Path, port: int, cfg: dict | None = None):
        self.paths = Paths(root)
        self.root = self.paths.root
        self.port = port
        self.cfg = cfg or load_config()
        self.child: Child | None = None
        self.maint: Maintenance | None = None
        self.stopping = False
        self.lock_fh = None
        self.last_remote: str | None = None
        self.blocked: dict | None = None          # {"since", "sha"} — limite de 5 min da sincronização
        self.sync_reported: set = set()
        self.auto_failed: set = set()             # SHAs que falharam no automático (não tenta de novo sozinho)
        self.crashes: list[float] = []
        self.restarts = 0
        self.next_restart = 0.0
        self.last_maint_try = 0.0
        self.prev_commit: str | None = None       # commit que estava no ar antes do atual (rollback)
        te.LOG = self.paths.log                   # eventos gravados por testenv.append (§8)
        old = pub.read_status(self.paths.sdir) or {}
        self.status = {"supervised": True,
                       "supervisor": {"pid": os.getpid(), "startedAt": now_iso(),
                                      "commit": sha7(git_out(self.root, "rev-parse", "HEAD", timeout=10))},
                       "server": None, "state": "verificando", "target": None, "trigger": "inicio",
                       "deadline": None, "busy": None, "lastResult": old.get("lastResult"),
                       "failedCommit": old.get("failedCommit")}
        self.old_status = old

    # ------------------------------------------------------------ estado e eventos
    def save(self):
        try:
            pub.write_json_atomic(self.paths.status, self.status)
        except OSError as e:
            log.error("falha ao gravar status.json: %s", e)

    def set_state(self, state: str, **kw):
        self.status["state"] = state
        self.status.update(kw)
        if state in ("no-ar", "revertido", "fora-do-ar"):
            self.status.update(target=None, deadline=None, busy=None, trigger=None)
        self.save()
        log.info("estado: %s %s", state, {k: v for k, v in kw.items() if k != "server"} or "")

    def append_raw(self, entry: dict) -> dict:
        e = dict(entry)
        return te.append(e.pop("type"), e.pop("title"), agent=e.pop("agent", "orquestrador"), **e)

    def event(self, type_: str, title: str, **fields) -> dict:
        e = te.append(type_, title, agent="orquestrador", **fields)
        if type_ in ("squad-updated", "squad-update-failed"):
            self.status["lastResult"] = {"type": type_, "commit": sha7(fields.get("commit")),
                                         "display": fields.get("display") or (self.status.get("server") or {}).get("display"),
                                         "at": e["ts"], "detail": fields.get("detail"), "eventId": e["id"],
                                         "phase": fields.get("phase"), "rolledBack": fields.get("rolledBack")}
            self.save()
        log.info("evento %s: %s", type_, title)
        return e

    def fail(self, commit, frm, trigger, phase, detail, req=None, rolled_back=False, health_before=None,
             running=None):
        if rolled_back:
            title = f"Squad Control: falhou a publicação de {sha7(commit)}, mantida a versão anterior {sha7(running)}"
        else:
            title = f"Squad Control: publicação de {sha7(commit)} não feita ({phase})"
        return self.event("squad-update-failed", title, commit=(commit or "")[:12] or None,
                          **{"from": (frm or "")[:12] or None}, trigger=trigger,
                          requestId=(req or {}).get("id"), phase=phase, rolledBack=rolled_back,
                          runningCommit=(running or "")[:12] or None, detail=mask(detail),
                          healthBefore=health_before)

    def base_state(self) -> str:
        mode = (self.status.get("server") or {}).get("mode")
        return {"principal": "no-ar", "anterior": "revertido", "manutencao": "fora-do-ar"}.get(mode, "no-ar")

    # ------------------------------------------------------------ git
    def head(self) -> str | None:
        return git_out(self.root, "rev-parse", "HEAD", timeout=10)

    def display_of(self, commit: str | None, cwd: pathlib.Path | None = None) -> str:
        cwd = cwd or self.root
        return inst.display({"release": inst.latest_release(cwd), "pom": inst.pom_version(cwd),
                             "commit": sha7(commit)})

    def code_dirty(self) -> list[str]:
        out = git_out(self.root, "status", "--porcelain", "--untracked-files=no", "--", *self.cfg["watch_paths"],
                      timeout=10)
        return [x for x in (out or "").splitlines() if x.strip()] if out is not None else ["git status falhou"]

    def preconditions(self) -> str | None:
        """§5.1.0: antes de QUALQUER escrita git. None = pode escrever; senão, o motivo (tenta no próximo ciclo)."""
        op = op_in_progress(self.root)
        if op:
            return f"operacao:{op}"
        if not on_develop(self.root):
            return "branch"
        if main_root_of(self.root) != self.root:
            return "nao-principal"
        if self.code_dirty():
            return "codigo-sujo"
        return None

    def relation(self) -> tuple[str, str]:
        """(igual|atras|a-frente-memoria|a-frente-codigo|divergente|sem-remoto, detalhe)."""
        head = self.head()
        remote = git_out(self.root, "rev-parse", "-q", "--verify", "refs/remotes/origin/develop", timeout=10)
        if not head:
            return "sem-remoto", "HEAD indisponível"
        if not remote:
            return "sem-remoto", "origin/develop ausente"
        if head == remote:
            return "igual", ""
        behind = git(self.root, "merge-base", "--is-ancestor", "HEAD", "origin/develop", timeout=10)[0] == 0
        if behind:
            return "atras", ""
        ahead = git(self.root, "merge-base", "--is-ancestor", "origin/develop", "HEAD", timeout=10)[0] == 0
        if ahead:
            names = (git_out(self.root, "diff", "--name-only", "origin/develop", "HEAD", timeout=10) or "").split()
            code = [n for n in names if not n.startswith("docs/squad/")]
            return ("a-frente-memoria", "") if not code else ("a-frente-codigo", ", ".join(code[:5]))
        return "divergente", ""

    def note_blocked(self, why: str, remote: str | None):
        """Limite de 5 min com o mesmo SHA remoto → um `squad-update-failed phase=sync` por SHA, e só sem operação
        git em curso (nunca durante o rebase/autostash do sync_develop)."""
        head = self.head()
        pending = remote and remote != head
        if not pending:
            self.blocked = None
            return
        if not self.blocked or self.blocked["sha"] != remote:
            self.blocked = {"since": time.monotonic(), "sha": remote, "why": why}
            log.info("sincronização adiada (%s) para %s", why, sha7(remote))
            return
        self.blocked["why"] = why
        if (time.monotonic() - self.blocked["since"] >= SYNC_LIMIT_S and remote not in self.sync_reported
                and not op_in_progress(self.root)):
            self.sync_reported.add(remote)
            srv = self.status.get("server") or {}
            self.fail(remote, srv.get("commit"), "auto", "sync",
                      f"a develop local não avança para {sha7(remote)} há 5 min: {why}", running=srv.get("commit"))

    def sync(self, remote: str | None = None) -> str | None:
        """§5.1.3: só avanço simples, sem autostash. None = sincronizado; senão, o motivo do bloqueio."""
        rel, detail = self.relation()
        if rel in ("igual", "a-frente-memoria", "sem-remoto"):
            return None
        if rel == "atras":
            why = self.preconditions()     # conferidas de novo logo antes da escrita
            if why:
                return why
            rc, out, err = git(self.root, "merge", "--ff-only", "-q", "origin/develop", timeout=60)
            if rc != 0:
                plan = self.memory_block()          # R1 do G2: só a memória viva impede o avanço?
                if isinstance(plan, str):
                    return f"merge --ff-only falhou: {(err or out)[:300]} ({plan})"
                return self.ff_with_memory(*plan)
            log.info("develop avançada por fast-forward para %s", sha7(self.head()))
            return None
        return f"{rel}{': ' + detail if detail else ''}"

    # ------------------------------------------------------------ R1 do G2: avanço com a memória viva suja
    def memory_block(self):
        """Quando o `merge --ff-only` falha, confere se o ÚNICO bloqueio são arquivos da memória viva (STATE do
        gitflow) que o PR integrado também muda. Devolve (logs, iguais) — logs append-only a juntar por id e arquivos
        cujo conteúdo local já é o do commit novo — ou o motivo (str) para esperar o review-sync, como antes."""
        rng = set((git_out(self.root, "diff", "--name-only", "-z", "HEAD", "origin/develop", timeout=10) or "")
                  .split("\0")) - {""}
        st = git_raw(self.root, "status", "--porcelain", "-z", "--untracked-files=all", timeout=10)
        if st.returncode != 0:
            return "git status falhou"
        out = st.stdout.decode("utf-8", "surrogateescape")
        dirty, toks, i = {}, out.split("\0"), 0
        while i < len(toks):
            t = toks[i]
            i += 1
            if len(t) < 4:
                continue
            if t[0] in "RC":
                return f"renomeação local em {t[3:]}"
            dirty[t[3:]] = t[:2]
        blocking = sorted(p for p in dirty if p in rng)
        if not blocking:
            return "bloqueio fora da memória da squad"
        logs, same = [], []
        for p in blocking:
            xy = dirty[p]
            if not p.startswith(STATE_PATHS):
                return f"arquivo local fora da memória da squad: {p}"
            if xy != "??" and xy[0] != " ":
                return f"memória com alteração no índice: {p}"
            if p in APPEND_LOGS:
                logs.append(p)
                continue
            want = git_out(self.root, "rev-parse", "-q", "--verify", f"origin/develop:{p}", timeout=10)
            have = git_out(self.root, "hash-object", "--", p, timeout=10) if (self.root / p).is_file() else None
            if want and have and want == have:
                same.append((p, xy == "??"))
                continue
            return f"memória local diverge do commit novo e não é log append-only: {p}"
        return logs, same

    def ff_with_memory(self, logs: list[str], same: list[tuple[str, bool]]) -> str | None:
        """Avanço só por fast-forward com a junção append-only do log (§5.1.3, R1 do G2). Nenhum evento é reescrito:
        1. link duro do log vivo para `.squad/squad-control/merge/` (o inode antigo continua recebendo quem já o abriu);
        2. troca atômica (tmp + rename) do caminho pelo conteúdo do HEAD — o arquivo nunca some do disco;
        3. `git merge --ff-only`; se alguém gravou na janela, repete (até 5×) com um novo link;
        4. SEMPRE (sucesso ou não), depois de uma folga, reanexa com um único `write` em O_APPEND os eventos das cópias
           que não estão no log atual, deduplicados por `id` (linha sem id: por texto exato). As cópias só são apagadas
           depois da gravação conferida."""
        bdir = self.paths.sdir / "merge"
        bdir.mkdir(parents=True, exist_ok=True)
        stamp = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
        backups: dict[str, list[pathlib.Path]] = {p: [] for p in logs}
        saved: dict[str, pathlib.Path] = {}
        ok, err = False, ""
        try:
            for attempt in range(5):
                for p in logs:
                    live = self.root / p
                    if not live.exists():
                        continue
                    b = bdir / f"{stamp}-{attempt}-{pathlib.Path(p).name}"
                    os.link(live, b)
                    backups[p].append(b)
                    blob = git_raw(self.root, "show", f"HEAD:{p}")
                    if blob.returncode != 0:          # log sem versão no HEAD: sai do caminho (o link o guarda)
                        live.unlink()
                        continue
                    tmp = live.with_name(f".{live.name}.publisher-{stamp}.tmp")
                    tmp.write_bytes(blob.stdout)
                    os.replace(tmp, live)
                for p, untracked in same:
                    if (self.root / p).exists() and (untracked or attempt == 0):
                        if p not in saved:            # cópia (não link): git pode reescrever no mesmo inode
                            saved[p] = bdir / f"{stamp}-igual-{pathlib.Path(p).name}"
                            shutil.copy2(self.root / p, saved[p])
                        if untracked:
                            (self.root / p).unlink()
                        else:
                            git_raw(self.root, "checkout", "-q", "HEAD", "--", p)
                rc, out, e = git(self.root, "merge", "--ff-only", "-q", "origin/develop", timeout=60)
                if rc == 0:
                    ok = True
                    break
                err = (e or out)[:300]
                log.info("fast-forward com a memória: tentativa %d falhou (%s)", attempt + 1, err)
                time.sleep(0.05)
        finally:
            time.sleep(MERGE_GRACE_S)                 # quem abriu o inode antigo antes da troca termina de gravar
            for p, bs in backups.items():
                if bs:
                    self.reattach(self.root / p, bs)
            for p, b in saved.items():                # sem avanço: devolve o conteúdo local dos arquivos iguais
                live = self.root / p
                if not ok and (not live.exists() or live.read_bytes() != b.read_bytes()):
                    tmp = live.with_name(f".{live.name}.publisher-{stamp}.tmp")
                    shutil.copy2(b, tmp)
                    os.replace(tmp, live)
                b.unlink(missing_ok=True)
        if not ok:
            return f"merge --ff-only falhou mesmo com a junção da memória: {err}"
        log.info("develop avançada por fast-forward para %s com junção append-only de %s", sha7(self.head()),
                 ", ".join(logs + [p for p, _ in same]))
        return None

    @staticmethod
    def reattach(live: pathlib.Path, backups: list[pathlib.Path]):
        """Acrescenta ao log vivo as linhas das cópias que ele não tem (por `id`; sem id, por texto). Append-only."""
        def key(line: str):
            try:
                d = json.loads(line)
                return ("id", d["id"]) if isinstance(d, dict) and d.get("id") else ("txt", line)
            except ValueError:
                return ("txt", line)
        cur = live.read_text(encoding="utf-8") if live.exists() else ""
        have = {key(ln) for ln in cur.splitlines() if ln.strip()}
        add = []
        for b in backups:
            for ln in b.read_text(encoding="utf-8").splitlines():
                if ln.strip() and key(ln) not in have:
                    have.add(key(ln))
                    add.append(ln)
        if add:
            prefix = "\n" if cur and not cur.endswith("\n") else ""
            with live.open("a", encoding="utf-8") as f:
                f.write(prefix + "\n".join(add) + "\n")
                f.flush()
                os.fsync(f.fileno())
            log.info("junção da memória: %d evento(s) locais reanexados em %s", len(add), live.name)
        final = {key(ln) for ln in live.read_text(encoding="utf-8").splitlines() if ln.strip()}
        if all(key(ln) in final for b in backups for ln in b.read_text(encoding="utf-8").splitlines() if ln.strip()):
            for b in backups:
                b.unlink(missing_ok=True)
        else:
            log.error("junção da memória incompleta; cópias mantidas em %s", backups[0].parent)

    def auto_cycle(self):
        why = self.preconditions()
        remote = None
        if why:
            self.note_blocked(why, self.last_remote)
            return
        rel, detail = self.relation()        # trava 3 também antes do fetch (§5.1.0): divergência espera o review-sync
        if rel in ("divergente", "a-frente-codigo"):
            self.note_blocked(f"{rel}{': ' + detail if detail else ''}", self.last_remote)
            return
        rc, out, _ = git(self.root, "ls-remote", "origin", "refs/heads/develop", timeout=10)
        if rc == 0 and out:
            remote = out.split()[0]
            if remote != self.last_remote:
                rc2, _, err = git(self.root, "fetch", "-q", "origin", "develop", timeout=60)
                if rc2 == 0:
                    self.last_remote = remote
                else:
                    log.warning("fetch falhou: %s", err[:200])
        remote = remote or self.last_remote
        why = self.sync(remote)
        if why:
            self.note_blocked(why, remote)
            return
        self.blocked = None
        if self.needs_publish():
            self.publish("auto")

    def needs_publish(self) -> bool:
        head = self.head()
        srv = self.status.get("server") or {}
        if not head or head == self.status.get("failedCommit") or head in self.auto_failed:
            return False
        cur = srv.get("commit")
        if not cur:
            return True
        if cur == head:
            return False
        out = git_out(self.root, "diff", "--name-only", cur, head, "--", *self.cfg["watch_paths"], timeout=10)
        return bool(out and out.strip())

    # ------------------------------------------------------------ travas (§5.2)
    def guards(self) -> str | None:
        """None = ok; Retry = transitória; str = recusa (phase guard)."""
        op = op_in_progress(self.root)
        if op:
            raise Retry(op)
        main = main_root_of(self.root)
        if main != self.root:
            return f"não é a cópia principal ({self.root} ≠ {main})"
        if not on_develop(self.root):
            return "a cópia principal não está em develop"
        dirty = self.code_dirty()
        if dirty:
            return "mudança rastreada em tools/squad/ ou squad-control/: " + "; ".join(dirty[:5])
        rel, detail = self.relation()
        if rel in ("divergente", "a-frente-codigo"):
            return f"develop local {rel} da origin/develop{': ' + detail if detail else ''}"
        if listening(self.port) and not ((self.child and self.child.alive()) or self.maint):
            return f"porta {self.port} ocupada por outro processo"
        return None

    # ------------------------------------------------------------ saúde
    def health_before(self) -> bool:
        return http_json(self.port, self.cfg["health"]) is not None

    def check_endpoints(self, port: int, expect: str | None, env_name: str | None, child: Child,
                        timeout: float) -> tuple[bool, str]:
        end = time.monotonic() + timeout
        last = "sem resposta"
        while time.monotonic() < end and not self.stopping:
            if not child.alive():
                return False, f"o servidor saiu (código {child.code}) durante a verificação"
            left = max(0.5, end - time.monotonic())
            d = http_json(port, self.cfg["health"], timeout=min(3.0, left))
            if d is None:
                last = f"{self.cfg['health']} sem resposta 200"
                time.sleep(0.3)
                continue
            got = (d.get("build") or {}).get("commitFull")
            name = (d.get("environment") or {}).get("name")
            if expect and got != expect:
                return False, f"commit errado: esperado {sha7(expect)}, no ar {sha7(got)}"
            if env_name and name != env_name:
                return False, f"ambiente {name}, esperado {env_name}"
            bad = []
            for path in ("/api/state", "/api/live", "/"):
                code, _ = http_get(port, path, timeout=max(1.0, min(15.0, end - time.monotonic())))
                if code != 200:
                    bad.append(f"{path}={code}")
            if not bad:
                return True, ""
            last = "respostas não 200: " + ", ".join(bad)
            time.sleep(0.5)
        return False, f"sem saúde em {int(timeout)} s: {last}"

    def stable(self, child: Child) -> tuple[bool, str]:
        end = time.monotonic() + self.cfg["stable_s"]
        while time.monotonic() < end and not self.stopping:
            if not child.alive():
                return False, f"o servidor saiu (código {child.code}) em menos de {int(self.cfg['stable_s'])} s"
            time.sleep(0.25)
        return True, ""

    # ------------------------------------------------------------ processo
    def command(self, port: int) -> list[str]:
        return [str(x).replace("{port}", str(port)) for x in self.cfg["command"]]

    def spawn(self, cwd: pathlib.Path, port: int, extra: dict, drop=(), log_path: pathlib.Path | None = None):
        env = dict(os.environ)
        for k in ("SQUAD_SUPERVISED", "SQUAD_PUBLISH_MODE", "SQUAD_PUBLISH_REVERTED", *drop):
            env.pop(k, None)
        env.update(extra)
        log_path = log_path or self.paths.server_log
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rotate(log_path)
        with log_path.open("ab") as out:
            out.write(f"\n==== {now_iso()} {' '.join(self.command(port))} (cwd={cwd}, modo={extra.get('SQUAD_PUBLISH_MODE', 'candidato')})\n".encode())
            out.flush()
            return subprocess.Popen(self.command(port), cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=subprocess.STDOUT, start_new_session=True)

    def start_server(self, mode: str, commit: str | None, reverted: str | None = None) -> Child:
        cwd = self.root if mode == "principal" else self.paths.prev
        extra = {"SQUAD_SUPERVISED": "1", "SQUAD_PUBLISH_MODE": mode, "SQUAD_ENV": "produtivo"}
        if mode == "anterior":
            extra["SQUAD_ROOT_DATA"] = str(self.paths.data)
            extra["SQUAD_PUBLISH_REVERTED"] = reverted or ""
        p = self.spawn(cwd, self.port, extra)
        self.child = Child(p.pid, p, mode, commit, self.port, cwd)
        log.info("servidor %s iniciado (pid %s, %s, %s)", mode, p.pid, sha7(commit), cwd)
        return self.child

    def record_server(self, child: Child, display: str | None = None):
        d = http_json(child.port, self.cfg["health"]) or {}
        self.status["server"] = {"pid": child.pid, "port": child.port, "commit": child.commit,
                                 "display": (d.get("build") or {}).get("display") or display
                                 or self.display_of(child.commit, child.cwd),
                                 "mode": child.mode, "root": str(child.cwd), "startedAt": child.started}
        self.save()

    def stop_child(self) -> bool:
        """§5.5.1: SIGTERM, 8 s, SIGKILL; espera a porta ficar livre. True se precisou do SIGKILL."""
        c = self.child
        killed = False
        if c and c.alive():
            killed = terminate_pid(c.pid, self.cfg["stop_grace_s"], lambda: not c.alive())
        self.child = None
        end = time.monotonic() + 5
        while listening(self.port) and time.monotonic() < end and not self.maint:
            time.sleep(0.1)
        return killed

    def stop_maintenance(self):
        if self.maint:
            self.maint.stop()
            self.maint = None

    def bring_up(self, mode: str, commit: str | None, reverted: str | None = None) -> tuple[bool, str]:
        """Sobe e confere saúde *depois* + estabilidade."""
        c = self.start_server(mode, commit, reverted)
        ok, detail = self.check_endpoints(self.port, commit, "produtivo", c, self.cfg["health_timeout_s"])
        if ok:
            ok, detail = self.stable(c)
        if not ok:
            detail = f"{detail}\n--- server.log ---\n{tail(self.paths.server_log)}"
        return ok, detail

    # ------------------------------------------------------------ worktree de rollback
    def ensure_prev(self, commit: str) -> tuple[bool, str]:
        wt = self.paths.prev
        if not (wt / ".git").exists():
            rc, out, err = git(self.root, "worktree", "add", "--detach", "-q", str(wt), commit, timeout=120)
            return (rc == 0), (err or out)
        cur = git_out(wt, "rev-parse", "HEAD", timeout=10)
        if cur == commit:
            return True, ""
        rc, out, err = git(wt, "checkout", "-q", "--detach", commit, timeout=120)
        return (rc == 0), (err or out)

    def prev_head(self) -> str | None:
        return git_out(self.paths.prev, "rev-parse", "HEAD", timeout=10) if (self.paths.prev / ".git").exists() else None

    # ------------------------------------------------------------ pré-voo (§5.3)
    def preflight(self) -> tuple[bool, str]:
        pyc = pathlib.Path(tempfile.mkdtemp(prefix="squad-pyc-"))
        try:
            for f in sorted((self.root / "tools/squad").glob("*.py")):
                try:
                    py_compile.compile(str(f), cfile=str(pyc / (f.name + "c")), doraise=True)
                except py_compile.PyCompileError as e:
                    return False, f"py_compile: {e.msg}"
        finally:
            shutil.rmtree(pyc, ignore_errors=True)
        rid = uuid.uuid4().hex[:8]
        data = self.paths.preflight / rid
        for d in ("docs/squad/memory/handoffs", "docs/squad/inbox", "docs/squad/gates", "transcripts"):
            (data / d).mkdir(parents=True, exist_ok=True)
        (data / "docs/squad/memory/decisions.jsonl").write_text("", encoding="utf-8")
        port = free_port(int(os.environ.get("SQUAD_PUBLISH_CANDIDATE_PORT") or CANDIDATE_PORT))
        env = {"SQUAD_ENV": "teste", "SQUAD_ROOT_DATA": str(data), "SQUAD_TESTENV_SPAWN": "0",
               "SQUAD_TESTENV_PROBE": "0", "SQUAD_TRANSCRIPTS": str(data / "transcripts")}
        cand_log = data / "candidate.log"
        p = self.spawn(self.root, port, env, drop=("SQUAD_LOG", "SQUAD_ROOT_DATA", "SQUAD_ENV"), log_path=cand_log)
        c = Child(p.pid, p, "candidato", None, port, self.root)
        try:
            ok, detail = self.check_endpoints(port, None, None, c, CANDIDATE_TIMEOUT_S)
            if not ok:
                detail = f"candidato na porta {port}: {detail}\n--- saída ---\n{tail(cand_log)}"
            return ok, detail
        finally:
            if c.alive():
                terminate_pid(c.pid, 3, lambda: not c.alive())
            shutil.rmtree(data, ignore_errors=True)
            log.info("candidato na porta %s encerrado", port)

    # ------------------------------------------------------------ ponto seguro (§5.4)
    def busy(self) -> dict | None:
        d = http_json(self.port, "/api/conversas", timeout=2)
        b = (d or {}).get("busy")
        return b if isinstance(b, dict) else None

    def safe_point(self, trigger: str, when: str | None) -> tuple[bool, float, dict | None]:
        """(pode reiniciar, segundos esperados, resposta interrompida)."""
        t0 = time.monotonic()
        b = self.busy()
        if b is None or (when == "now"):
            return True, 0.0, b
        limit = self.cfg["safe_wait_button_s"] if when == "safe" else self.cfg["safe_wait_s"]
        deadline = datetime.now(timezone.utc) + timedelta(seconds=limit)
        self.set_state("aguardando-ponto-seguro", deadline=deadline.strftime("%Y-%m-%dT%H:%M:%SZ"), busy=b)
        while not self.stopping:
            time.sleep(1)
            b2 = self.busy()
            if b2 is None:
                return True, round(time.monotonic() - t0, 1), None
            if b2 != self.status.get("busy"):
                self.status["busy"] = b2
                self.save()
            if time.monotonic() - t0 >= limit:
                return (when != "safe"), round(time.monotonic() - t0, 1), b2
        return False, round(time.monotonic() - t0, 1), None

    # ------------------------------------------------------------ publicação
    def publish(self, trigger: str, req: dict | None = None) -> str:
        """'done' ou 'retry' (condição transitória; o pedido fica)."""
        t0 = time.monotonic()
        srv = dict(self.status.get("server") or {})
        frm = srv.get("commit")
        target = self.head()
        when = (req or {}).get("when")
        try:
            refusal = self.guards()
        except Retry as e:
            log.info("publicação adiada: %s", e)
            return "retry"
        if refusal:
            if trigger == "auto":
                self.auto_failed.add(target)
            self.fail(target, frm, trigger, "guard", refusal, req, running=frm)
            return "done"
        self.paths.publish_lock.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.publish_lock.open("a+") as lk:
            try:
                fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return "retry"
            try:
                return self._publish_locked(trigger, req, when, target, frm, t0)
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def _publish_locked(self, trigger, req, when, target, frm, t0) -> str:
        base = self.base_state()
        tgt_display = self.display_of(target)
        self.set_state("verificando", target={"commit": sha7(target), "commitFull": target, "display": tgt_display},
                       trigger=trigger, deadline=None, busy=None)
        hb = self.health_before()
        ok, detail = self.preflight()
        if not ok:
            self.auto_failed.add(target)   # o mesmo SHA só volta pelo botão ou por um SHA novo
            self.fail(target, frm, trigger, "preflight", detail, req, health_before=hb, running=frm)
            self.set_state(base)
            return "done"
        go, waited, interrupted = self.safe_point(trigger, when)
        if self.stopping:
            self.set_state(base)
            return "done"
        if not go:
            self.fail(target, frm, trigger, "ponto-seguro", "a resposta não terminou em 10 min; publique de novo",
                      req, health_before=hb, running=frm)
            self.set_state(base)
            return "done"
        self.set_state("reiniciando", deadline=None, busy=None)
        self.stop_child()
        self.stop_maintenance()
        ok, detail = self.bring_up("principal", target)
        if ok:
            self.record_server(self.child)
            self.status["failedCommit"] = None
            self.auto_failed.discard(target)
            same = frm == target
            disp = self.status["server"]["display"]
            self.event("squad-updated", f"Squad Control {'reiniciado em' if same else 'atualizado para'} {disp}",
                       commit=target[:12], **{"from": (frm or "")[:12] or None}, display=disp, trigger=trigger,
                       requestId=(req or {}).get("id"), sameCommit=same,
                       durationSec=round(time.monotonic() - t0, 1), waitedSec=waited, interrupted=interrupted,
                       healthBefore=hb)
            self.crashes, self.restarts = [], 0
            if frm and frm != target:
                self.prev_commit = frm
                okp, why = self.ensure_prev(frm)
                if not okp:
                    log.warning("worktree de rollback não atualizado: %s", why)
            self.set_state("no-ar")
            self.maybe_self_update(frm, target)
            return "done"
        prev = frm if frm and frm != target else self.prev_head()
        self.rollback(target, prev, trigger, "health", detail, req, hb)
        return "done"

    def rollback(self, failed: str, prev: str | None, trigger: str, phase: str, detail: str, req=None, hb=None):
        """§5.5.6: sobe o commit anterior a partir do worktree plankton-squad-prev; senão, página de manutenção."""
        self.set_state("revertendo")
        self.stop_child()
        ok, why = (False, "sem commit anterior conhecido")
        if prev:
            ok, why = self.ensure_prev(prev)
            if ok:
                ok, why = self.bring_up("anterior", prev, reverted=failed)
        if ok:
            self.record_server(self.child)
            self.status["failedCommit"] = failed
            self.prev_commit = prev
            self.fail(failed, prev, trigger, phase, detail, req, rolled_back=True, health_before=hb, running=prev)
            self.set_state("revertido")
            return True
        self.stop_child()
        self.status["failedCommit"] = failed
        self.status["server"] = {"pid": os.getpid(), "port": self.port, "commit": None, "display": None,
                                 "mode": "manutencao", "root": str(self.root), "startedAt": now_iso()}
        self.start_maintenance({"failed": sha7(failed), "prev": sha7(prev) or "—", "phase": PHASE_TEXT.get(phase)})
        self.fail(failed, prev, trigger, "rollback", f"{detail}\n--- anterior ({sha7(prev)}) ---\n{why}", req,
                  rolled_back=False, health_before=hb, running=None)
        self.set_state("fora-do-ar")
        self.last_maint_try = time.monotonic()
        return False

    def start_maintenance(self, info: dict):
        self.stop_maintenance()
        end = time.monotonic() + 5
        while True:
            try:
                self.maint = Maintenance(self, self.port, info)
                log.info("página de manutenção na porta %s", self.port)
                return
            except OSError as e:
                if time.monotonic() > end:
                    log.error("não foi possível servir a página de manutenção: %s", e)
                    return
                time.sleep(0.3)

    def maint_retry(self):
        """fora-do-ar: a cada 60 s tenta de novo o anterior."""
        prev = self.prev_head()
        if not prev:
            return
        self.last_maint_try = time.monotonic()
        self.stop_maintenance()
        ok, why = self.bring_up("anterior", prev, reverted=self.status.get("failedCommit"))
        if ok:
            self.record_server(self.child)
            self.prev_commit = prev
            self.set_state("revertido")
            log.info("anterior %s voltou ao ar", sha7(prev))
        else:
            self.stop_child()
            self.start_maintenance({"failed": sha7(self.status.get("failedCommit")), "prev": sha7(prev),
                                    "phase": "rollback"})

    # ------------------------------------------------------------ o supervisor se atualiza (§5.6)
    def maybe_self_update(self, frm: str | None, target: str):
        base = (self.status.get("supervisor") or {}).get("commit") or frm   # o código que ESTE processo carregou
        if not base:
            return
        out = git_out(self.root, "diff", "--name-only", base, target, "--", *SELF_FILES, timeout=10)
        if not out:
            return
        me = self.root / "tools/squad/publisher.py"
        try:
            rc = subprocess.run([sys.executable, str(me), "selftest"], cwd=str(self.root), capture_output=True,
                                text=True, timeout=60)
            ok, why = rc.returncode == 0, (rc.stderr or rc.stdout)[-800:]
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, why = False, str(e)
        if not ok:
            self.fail(target, frm, "auto", "supervisor", f"selftest do publisher.py novo falhou: {why}",
                      running=target)
            return
        log.info("publisher.py mudou: execv (servidor pid %s continua)", self.child.pid if self.child else None)
        self.save()
        fd = self.lock_fh.fileno()
        os.set_inheritable(fd, True)
        for h in log.handlers:
            h.flush()
        os.execv(sys.executable, [sys.executable, str(me), "run", "--root", str(self.root), "--port", str(self.port),
                                  "--lock-fd", str(fd), "--resume"])

    # ------------------------------------------------------------ queda inesperada (§5.7)
    def on_crash(self):
        c = self.child
        now = time.monotonic()
        if self.next_restart == 0.0:
            self.crashes = [t for t in self.crashes if now - t < CRASH_WINDOW_S] + [now]
            self.restarts += 1
            delay = min(60, 2 ** (len(self.crashes) - 1))
            self.next_restart = now + delay
            if self.restarts == 1 or self.restarts % 5 == 0:
                self.event("squad-server-crashed", f"Squad Control caiu e foi reiniciado ({self.restarts})",
                           commit=(c.commit or "")[:12] or None, mode=c.mode, exitCode=c.code,
                           restarts=self.restarts, detail=tail(self.paths.server_log))
            log.warning("servidor caiu (código %s); nova tentativa em %s s", c.code, delay)
            return
        if now < self.next_restart:
            return
        self.next_restart = 0.0
        if c.mode == "principal" and len(self.crashes) >= CRASH_MAX:
            prev = self.prev_commit or self.prev_head()
            self.child = None
            self.rollback(c.commit, prev if prev != c.commit else None, "auto", "health",
                          f"{len(self.crashes)} quedas em 5 min\n{tail(self.paths.server_log)}")
            self.crashes = []
            return
        self.start_server(c.mode, c.commit, self.status.get("failedCommit") if c.mode == "anterior" else None)
        self.status["server"]["pid"] = self.child.pid
        self.status["server"]["startedAt"] = self.child.started
        self.save()

    # ------------------------------------------------------------ pedidos (§4.2, a cada 2 s)
    def process_requests(self):
        reqs = pub.read_requests(self.paths.sdir)
        if not reqs:
            return
        _, req = reqs[0]
        trigger = req.get("trigger") if req.get("trigger") in ("botao", "cli") else "botao"
        if not self.preconditions():
            why = self.sync()
            if why:
                log.info("pedido %s: develop não sincronizada (%s)", req.get("id"), why)
        res = self.publish(trigger, req)
        if res == "retry":
            try:
                age = time.time() - datetime.strptime(req["at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc).timestamp()
            except (KeyError, ValueError):
                age = 0
            if age < SYNC_LIMIT_S:
                return
            srv = self.status.get("server") or {}
            self.fail(self.head(), srv.get("commit"), trigger, "guard",
                      "operação git em curso na cópia principal há mais de 5 min", req, running=srv.get("commit"))
        consumed = [p for p, _ in reqs]
        extra = pub.read_requests(self.paths.sdir)
        dropped = [p for p, _ in extra if p not in consumed]
        for p in consumed + dropped:
            p.unlink(missing_ok=True)
        if len(consumed) + len(dropped) > 1 and self.status.get("lastResult"):
            self.status["lastResult"]["detail"] = (
                (self.status["lastResult"].get("detail") or "")
                + f" ({len(consumed) + len(dropped) - 1} pedido(s) repetido(s) descartado(s) durante a publicação)"
            ).strip()
            self.save()

    # ------------------------------------------------------------ subida (§5.8) e adoção
    def adopt(self, pid: int):
        inst_ = http_json(self.port, "/api/instance")
        root = ((inst_ or {}).get("environment") or {}).get("root")
        if lsof_pid(self.port) != pid or not root or pathlib.Path(root).resolve() != self.root:
            raise SystemExit(f"adoção recusada: a porta {self.port} não é mais do pid {pid} da cópia principal")
        go, waited, interrupted = self.safe_point("inicio", None)
        log.info("adotando o servidor pid %s (esperou %s s%s)", pid, waited,
                 f", interrompe {interrupted}" if interrupted else "")
        self.set_state("reiniciando", trigger="inicio")
        terminate_pid(pid, self.cfg["stop_grace_s"], lambda: not pub.pid_alive(pid))
        end = time.monotonic() + 5
        while listening(self.port) and time.monotonic() < end:
            time.sleep(0.1)

    def startup(self, adopt_pid: int | None = None):
        t0 = time.monotonic()
        self.save()
        hb = self.health_before() if adopt_pid else None
        if adopt_pid:
            self.adopt(adopt_pid)
        head = self.head()
        old_srv = self.old_status.get("server") or {}
        failed = self.status.get("failedCommit")
        prev = self.prev_head()
        if failed and failed == head and prev and prev != head:
            ok, why = self.bring_up("anterior", prev, reverted=failed)
            if ok:
                self.record_server(self.child)
                self.prev_commit = prev
                self.set_state("revertido")
                return
            self.stop_child()
            self.rollback(failed, None, "inicio", "health", why)
            return
        self.set_state("reiniciando", trigger="inicio")
        ok, why = self.bring_up("principal", head)
        if ok:
            self.record_server(self.child)
            self.status["failedCommit"] = None
            disp = self.status["server"]["display"]
            same = old_srv.get("commit") == head
            self.event("squad-updated", f"Squad Control {'reiniciado em' if same else 'atualizado para'} {disp}",
                       commit=head[:12], **{"from": (old_srv.get("commit") or "")[:12] or None}, display=disp,
                       trigger="inicio", sameCommit=same, durationSec=round(time.monotonic() - t0, 1),
                       waitedSec=0, healthBefore=hb)
            if prev and prev != head:
                self.prev_commit = prev
            self.set_state("no-ar")
            return
        cand = old_srv.get("commit") if old_srv.get("commit") and old_srv.get("commit") != head else prev
        self.rollback(head, cand if cand != head else None, "inicio", "health", why, hb=hb)

    def resume(self):
        """Depois do execv: adota o servidor filho pelo status.json (mesmo pid)."""
        old = self.old_status
        srv = old.get("server") or {}
        self.status.update({k: old.get(k) for k in ("server", "failedCommit", "lastResult")})
        pid = srv.get("pid")
        if srv.get("mode") in ("principal", "anterior") and pub.pid_alive(pid):
            self.child = Child(int(pid), None, srv["mode"], srv.get("commit"), self.port,
                               pathlib.Path(srv.get("root") or self.root), srv.get("startedAt"))
            self.prev_commit = self.prev_head()
            self.set_state(self.base_state())
            log.info("supervisor reiniciado por execv; servidor pid %s mantido", pid)
            return True
        return False

    # ------------------------------------------------------------ loop
    def acquire(self, lock_fd: int | None = None) -> bool:
        self.paths.sdir.mkdir(parents=True, exist_ok=True)
        if lock_fd is not None:
            self.lock_fh = os.fdopen(lock_fd, "a+")
            os.set_inheritable(lock_fd, False)
        else:
            self.lock_fh = self.paths.lock.open("a+")
            try:
                fcntl.flock(self.lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock_fh.close()
                self.lock_fh = None
                return False
        self.paths.pidfile.write_text(str(os.getpid()))
        return True

    def run(self, adopt_pid: int | None = None, resume: bool = False):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopping", True))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "stopping", True))
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        if not (resume and self.resume()):
            self.startup(adopt_pid)
        last_auto = time.monotonic() - self.cfg["poll_s"] + 1 if self.cfg["auto"] else float("inf")
        last_req = 0.0
        while not self.stopping:
            now = time.monotonic()
            try:
                if self.child and not self.child.alive():
                    self.on_crash()
                elif self.status.get("state") == "fora-do-ar" and now - self.last_maint_try >= MAINT_RETRY_S:
                    self.maint_retry()
                if now - last_req >= self.cfg["request_poll_s"]:
                    last_req = now
                    self.process_requests()
                if self.cfg["auto"] and now - last_auto >= self.cfg["poll_s"]:
                    last_auto = now
                    self.auto_cycle()
                rotate(self.paths.server_log)
                rotate(self.paths.pub_log)
            except SystemExit:
                raise
            except Exception:
                log.exception("erro no ciclo do supervisor (continua)")
            time.sleep(0.25)
        self.shutdown()

    def shutdown(self):
        log.info("parando o supervisor")
        self.stop_child()
        self.stop_maintenance()
        self.status.update(supervised=False, state="parado", target=None, deadline=None, busy=None, trigger=None)
        if self.status.get("server"):
            self.status["server"]["pid"] = None
        self.save()
        try:
            self.paths.pidfile.unlink(missing_ok=True)
        except OSError:
            pass


# ================================================================ CLI
def setup_logging(paths: Paths, to_stderr: bool):
    paths.sdir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.handlers.clear()
    fh = logging.FileHandler(paths.pub_log, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if to_stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    log.setLevel(logging.INFO)


def show_status(paths: Paths, as_json=False) -> int:
    st = pub.read_status(paths.sdir) or {}
    pid = supervisor_alive(paths)
    st = {**st, "supervised": bool(pid) and bool(st.get("supervised"))}
    if as_json:
        print(json.dumps(st, ensure_ascii=False, indent=1))
    elif not pid:
        print("publicador fora do ar (rode make squad)")
    else:
        srv = st.get("server") or {}
        print(f"publicador no ar (pid {pid}) · estado {st.get('state')} · servidor pid {srv.get('pid')} "
              f"porta {srv.get('port')} · {srv.get('display')} · modo {srv.get('mode')}")
        lr = st.get("lastResult") or {}
        if lr:
            print(f"último resultado: {lr.get('type')} {lr.get('commit')} em {lr.get('at')}")
        print(f"logs: {paths.server_log} · {paths.pub_log}")
    return 0 if pid else 1


def cmd_start(a, ensure=False) -> int:
    root, port = pathlib.Path(a.root).resolve(), a.port
    paths = Paths(root)
    why = structural_guard(root, port)
    if why:
        print(f"recusado: {why}", file=sys.stderr)
        return 0 if ensure else 2
    if main_root_of(root) != root or not on_develop(root):
        print(f"recusado (guard): {root} não é a cópia principal em develop", file=sys.stderr)
        return 0 if ensure else 2
    if supervisor_alive(paths):
        return 0 if ensure else show_status(paths)
    adopt = None
    if listening(port):
        if ensure:
            print(f"ensure: porta {port} ocupada; a 1ª adoção é só por make squad", file=sys.stderr)
            return 0
        d = http_json(port, "/api/instance")
        rroot = ((d or {}).get("environment") or {}).get("root")
        if not rroot or pathlib.Path(rroot).resolve() != root:
            print(f"recusado: a porta {port} está ocupada por outra coisa ({rroot or 'não é um Squad Control'})",
                  file=sys.stderr)
            return 2
        pid = lsof_pid(port)
        if not pid:
            print("recusado: lsof indisponível para achar o processo. Pare o make squad antigo (Ctrl+C) e rode "
                  "make squad de novo.", file=sys.stderr)
            return 2
        if not a.yes:
            if not sys.stdin.isatty():
                print(f"recusado: o Squad Control atual (pid {pid}) só é encerrado com confirmação no terminal",
                      file=sys.stderr)
                return 2
            ans = input(f"Encerrar o Squad Control atual (pid {pid}) e subir o supervisionado? [s/N] ")
            if ans.strip().lower() != "s":
                print("recusado: nada foi alterado", file=sys.stderr)
                return 2
        adopt = pid
    paths.sdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "run", "--root", str(root), "--port", str(port)]
    if adopt:
        cmd += ["--adopt-pid", str(adopt)]
    with paths.pub_log.open("ab") as out:
        p = subprocess.Popen(cmd, cwd=str(root), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)
    cfg = load_config()
    limit = cfg["safe_wait_s"] + cfg["stop_grace_s"] + 2 * (cfg["health_timeout_s"] + cfg["stable_s"]) + 15
    end = time.monotonic() + limit
    st = {}
    while time.monotonic() < end:
        if p.poll() is not None:
            print(f"o supervisor saiu (código {p.returncode}); veja {paths.pub_log}", file=sys.stderr)
            return 1
        st = pub.read_status(paths.sdir) or {}
        if (st.get("supervisor") or {}).get("pid") == p.pid and st.get("state") in ("no-ar", "revertido",
                                                                                     "fora-do-ar"):
            break
        time.sleep(0.3)
    srv = st.get("server") or {}
    print(f"Squad Control em http://localhost:{port} · estado {st.get('state')} · supervisor pid {p.pid} · "
          f"servidor pid {srv.get('pid')} · {srv.get('display')}")
    print(f"logs: {paths.server_log} · {paths.pub_log}")
    return 0 if st.get("state") in ("no-ar", "revertido", "fora-do-ar") else 1


def cmd_stop(a) -> int:
    paths = Paths(pathlib.Path(a.root))
    pid = supervisor_alive(paths)
    if not pid:
        print("publicador não está no ar")
        return 0
    os.kill(pid, signal.SIGTERM)
    end = time.monotonic() + 30
    while time.monotonic() < end and lock_held(paths.lock):
        time.sleep(0.2)
    print("publicador parado" if not lock_held(paths.lock) else "publicador ainda no ar (veja o log)")
    return 0


def cmd_publish(a) -> int:
    paths = Paths(pathlib.Path(a.root))
    if not supervisor_alive(paths):
        print("sem supervisor: rode make squad", file=sys.stderr)
        return 3
    te.LOG = paths.log
    req = pub.write_request(paths.sdir, a.when, True, None, "cli")
    e = pub.requested_event(req)
    te.append(e.pop("type"), e.pop("title"), agent=e.pop("agent"), **e)
    print(f"pedido {req['id']} registrado (when={a.when})")
    return 0


def cmd_selftest(_a) -> int:
    errs = validate_config(load_config())
    for mod in ("server", "conversa", "alerts"):
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001
            errs.append(f"import {mod}: {type(e).__name__}: {e}")
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    print("selftest ok")
    return 0


def cmd_run(a) -> int:
    root = pathlib.Path(a.root).resolve()
    why = structural_guard(root, a.port)
    if why:
        print(f"recusado: {why}", file=sys.stderr)
        return 2
    sup = Supervisor(root, a.port)
    setup_logging(sup.paths, sys.stderr.isatty())
    if not sup.acquire(a.lock_fd):
        print("já há um supervisor para esta cópia", file=sys.stderr)
        return show_status(sup.paths) and 0
    if main_root_of(root) != root or not on_develop(root):
        log.error("recusado (guard): %s não é a cópia principal em develop", root)
        return 2
    log.info("supervisor no ar (pid %s, porta %s, raiz %s)", os.getpid(), a.port, root)
    sup.run(adopt_pid=a.adopt_pid, resume=a.resume)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(s, port=True):
        s.add_argument("--root", default=str(DEFAULT_ROOT), help=argparse.SUPPRESS)
        if port:
            s.add_argument("--port", type=int, default=CONFIG["ports"]["control"])
    s = sub.add_parser("start"); common(s); s.add_argument("--yes", action="store_true", help="só testes")
    s = sub.add_parser("ensure"); common(s); s.set_defaults(yes=False)
    common(sub.add_parser("stop"), port=False)
    s = sub.add_parser("status"); common(s, port=False); s.add_argument("--json", action="store_true")
    s = sub.add_parser("publish"); common(s, port=False); s.add_argument("--when", choices=pub.WHEN, default="now")
    sub.add_parser("selftest")
    s = sub.add_parser("run"); common(s)
    s.add_argument("--adopt-pid", type=int, help=argparse.SUPPRESS)
    s.add_argument("--lock-fd", type=int, help=argparse.SUPPRESS)
    s.add_argument("--resume", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.cmd == "start":
        return cmd_start(a)
    if a.cmd == "ensure":
        cmd_start(a, ensure=True)
        return 0
    if a.cmd == "stop":
        return cmd_stop(a)
    if a.cmd == "status":
        return show_status(Paths(pathlib.Path(a.root)), a.json)
    if a.cmd == "publish":
        return cmd_publish(a)
    if a.cmd == "selftest":
        return cmd_selftest(a)
    return cmd_run(a)


if __name__ == "__main__":
    sys.exit(main())
