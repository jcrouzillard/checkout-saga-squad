#!/usr/bin/env python3
"""Ambiente de teste compartilhado (D15, ADR-018, docs/contracts/ambiente-de-teste.md) — somente stdlib.

  request --action publish|cancel|release|reset-data|down --demand <id> [--confirm APAGAR]
                                grava `test-env-request` (agent humano). Só o humano pede (terminal/Squad Control).
  reconcile                     idempotente: libera ocupante entregue/devolvido/cancelado, tira obsoletos da fila,
                                executa "apagar dados"/republicação pendentes e publica o 1º da fila se livre.
  publish --demand <id>         publica o PR da demanda (recusa sem pedido do humano pendente — CA5).
  release --demand <id> --reason delivered|review-rejected|canceled|human|obsolete
                                `stop` do projeto checkout-teste (dados ficam) + reconcile.
  down                          `down` SEM -v do checkout-teste (libera memória, preserva dados).
  reset-data                    `down -v` só do checkout-teste, exige pedido do humano com APAGAR.
  status                        estado do ambiente (formato de GET /api/test-env) — só leitura.
  check-ports                   guard de projeto/portas/imagens/volumes sobre o `config` do teste — só leitura.
  prod-fingerprint [--out f] [--compare f]
                                impressão digital do produtivo checkout-saga (CA4) — só leitura.

Regras: todo `docker compose` daqui leva `-p checkout-teste --env-file infra/teste/teste.env` e roda dentro do
worktree dedicado (`$SQUAD_TEST_WORKTREE`, padrão `<pai da cópia principal>/plankton-teste`); o produtivo
(`checkout-saga`) só é LIDO (fingerprint). Executáveis injetáveis para testes: `$SQUAD_DOCKER`, `$SQUAD_GH`,
`$SQUAD_GIT`, `$SQUAD_LSOF`; dados em `$SQUAD_ROOT_DATA`/`$SQUAD_LOG` (como o server.py).
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_ROOT = pathlib.Path(os.environ.get("SQUAD_ROOT_DATA") or ROOT).resolve()
LOG = pathlib.Path(os.environ.get("SQUAD_LOG") or DATA_ROOT / "docs/squad/memory/decisions.jsonl")
# Lock fora do git: .squad/ é ignorado (docs/squad/memory/ é commitado pelo gitflow.snapshot_state).
LOCK_FILE = DATA_ROOT / ".squad/test-env.lock"

TEST_PROJECT = "checkout-teste"
PROD_PROJECT = "checkout-saga"
ENV_FILE = "infra/teste/teste.env"
APP_SERVICES = ["saga-orchestrator", "order-service", "inventory-service", "payment-service", "shipping-service"]
# Portas do produtivo (§2.1; grafana 3001 pelo .env da cópia principal, 3000 é o default do compose).
PROD_PORTS = {5432, 29092, 4317, 4318, 16686, 9090, 3000, 3001, 8080, 8081, 8082, 8083, 8084, 8090}
FORBIDDEN_PORTS = PROD_PORTS | {7070}
TEST_PORT_RANGE = (13001, 39092)
OFFSET = 10000
CONFIRM = "APAGAR"
ACTIONS = ("publish", "cancel", "release", "reset-data", "down")
REASONS = ("delivered", "review-rejected", "canceled", "human", "obsolete")
TE_TYPES = ("test-env-request", "test-env-publishing", "test-env-published", "test-env-failed",
            "test-env-released", "test-env-reset")
BUILD_TIMEOUT = 15 * 60
UP_WAIT = 300
MIN_FREE_GB = float(os.environ.get("SQUAD_TEST_MIN_FREE_GB") or 2)


# ================================================================ execução injetável
class Result:
    def __init__(self, rc: int, out: str = "", err: str = ""):
        self.rc, self.out, self.err = rc, out, err

    @property
    def ok(self) -> bool:
        return self.rc == 0


class Exec:
    """Executor de comandos externos. Os testes trocam por um executor falso (só registra) — nada real é criado."""
    BIN_ENV = {"docker": "SQUAD_DOCKER", "gh": "SQUAD_GH", "git": "SQUAD_GIT", "lsof": "SQUAD_LSOF"}

    def __init__(self):
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], cwd=None, timeout: float = 120) -> Result:
        self.calls.append(list(cmd))
        real = [os.environ.get(self.BIN_ENV.get(cmd[0], ""), "") or cmd[0], *cmd[1:]]
        try:
            p = subprocess.run(real, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            return Result(p.returncode, p.stdout or "", p.stderr or "")
        except FileNotFoundError as e:
            return Result(127, "", str(e))
        except subprocess.TimeoutExpired:
            return Result(124, "", f"timeout após {int(timeout)} s: {' '.join(cmd)}")


EXEC: Exec = Exec()


def set_exec(ex: Exec):
    global EXEC
    EXEC = ex


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


# ================================================================ caminhos
def find_main_root(root: pathlib.Path | None = None, timeout: float = 10) -> pathlib.Path | None:
    """Cópia principal = o worktree em `develop` (hoje `plankton/`; ele próprio pode ser um worktree ligado a outro
    repositório, então NÃO é o diretório do .git comum). `$SQUAD_MAIN_ROOT` sobrepõe (testes).
    Sem fallback: None quando o git falha ou nenhum worktree está em `develop` (D18, ressalva R1 do G1)."""
    env = os.environ.get("SQUAD_MAIN_ROOT")
    if env:
        return pathlib.Path(env).resolve()
    try:
        p = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=root or ROOT, capture_output=True,
                           text=True, timeout=timeout)
        if p.returncode != 0:
            return None
        path = None
        for line in p.stdout.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):]
            elif line.strip() == "branch refs/heads/develop" and path:
                return pathlib.Path(path).resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def main_root() -> pathlib.Path:
    """Cópia principal (ver `find_main_root`); na falta dela, a raiz deste repositório (comportamento da D15)."""
    return find_main_root() or ROOT


PUBLISHER_WORKTREE = "plankton-squad-prev"   # D24 (ADR-025 §5.5.7): rollback do publicador — nunca é ambiente de teste


def is_publisher_worktree(p: pathlib.Path) -> bool:
    return pathlib.Path(p).name == PUBLISHER_WORKTREE


def worktree() -> pathlib.Path:
    env = os.environ.get("SQUAD_TEST_WORKTREE")
    return pathlib.Path(env).resolve() if env else main_root().parent / "plankton-teste"


def env_file_path(base: pathlib.Path | None = None) -> pathlib.Path:
    base = base or worktree()
    p = base / ENV_FILE
    return p if p.exists() else ROOT / ENV_FILE


def read_env(path: pathlib.Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def test_ports(env: dict | None = None) -> dict:
    env = env if env is not None else read_env(env_file_path())
    g = lambda k, d: int(env.get(k) or d)  # noqa: E731
    return {"saga": g("SAGA_PORT", 18080), "order": g("ORDER_PORT", 18081), "inventory": g("INVENTORY_PORT", 18082),
            "payment": g("PAYMENT_PORT", 18083), "shipping": g("SHIPPING_PORT", 18084),
            "console": g("CONSOLE_PORT", 18090), "grafana": g("GRAFANA_PORT", 13001),
            "jaeger": g("JAEGER_UI_PORT", 26686), "prometheus": g("PROMETHEUS_PORT", 19090),
            "postgres": g("POSTGRES_PORT", 15432), "kafka": g("KAFKA_EXTERNAL_PORT", 39092)}


def test_urls(ports: dict) -> dict:
    keys = ("console", "grafana", "jaeger", "prometheus", "saga", "order", "inventory", "payment", "shipping")
    return {k: f"http://localhost:{ports[k]}" for k in keys}


# ================================================================ log (append-only)
def read_log() -> list[dict]:
    rows = []
    try:
        with LOG.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return rows


def append(type_: str, title: str, agent: str = "orquestrador", **fields) -> dict:
    entry = {"id": uuid.uuid4().hex[:12], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "agent": agent, "type": type_, "title": title, **fields}
    if agent != "humano" and os.environ.get("SQUAD_MODEL"):
        entry.setdefault("model", os.environ["SQUAD_MODEL"])
    entry = {k: v for k, v in entry.items() if v is not None and v != ""}   # services=[] é significativo
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


@contextlib.contextmanager
def lock(path: pathlib.Path = None):
    """Uma operação por vez. Rende False se já tomado (quem chamou decide: reconcile não faz nada)."""
    path = path or LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


# ================================================================ estado (derivado só do log)
def open_review(rows: list[dict], demand: str) -> dict | None:
    """Último `review` da demanda sem `delivered`/`review-rejected` para o mesmo PR."""
    reviews = [e for e in rows if e.get("type") == "review" and e.get("demand") == demand]
    if not reviews:
        return None
    rv = reviews[-1]
    closed = any(e.get("type") in ("delivered", "review-rejected") and e.get("demand") == demand
                 and (e.get("pr") == rv.get("pr") or e.get("url") == rv.get("url")) for e in rows)
    return None if closed else rv


def closed_reason(rows: list[dict], demand: str) -> str | None:
    for e in reversed(rows):
        if e.get("demand") != demand:
            continue
        if e.get("type") == "delivered":
            return "delivered"
        if e.get("type") == "review-rejected":
            return "review-rejected"
        if e.get("type") == "control" and e.get("action") == "cancel":
            return "canceled"
    return None


def derive(rows: list[dict]) -> dict:
    """Estado do ambiente pelo log (§3.1): livre | publicando | ocupado | falhou (divergente vem da saúde)."""
    st = {"state": "livre", "demand": None, "pr": None, "url": None, "commit": None, "phase": None,
          "startedAt": None, "publishedAt": None, "urls": None, "ports": None, "lastError": None, "stopped": False,
          "smoke": None, "warning": None}
    queue: list[dict] = []
    republish = None          # pedido de publish do próprio ocupante ainda não atendido
    reset = None              # pedido de reset-data (APAGAR) ainda não atendido
    rejected = None           # último test-env-failed que não mudou o estado (ex.: CA5 sem pedido)
    last_released = None

    def drop(d):
        queue[:] = [q for q in queue if q["demand"] != d]

    for e in rows:
        t, d = e.get("type"), e.get("demand")
        if t not in TE_TYPES:
            continue
        if t == "test-env-request":
            if e.get("agent") != "humano":
                continue
            a = e.get("action")
            if a == "publish" and d:
                if d == st["demand"] and st["state"] in ("ocupado", "falhou"):
                    republish = e
                elif d == st["demand"] and st["state"] == "publicando":
                    pass
                elif not any(q["demand"] == d for q in queue):
                    queue.append({"demand": d, "pr": e.get("pr"), "requestedAt": e.get("ts"), "request": e["id"]})
            elif a == "cancel" and d:
                drop(d)
                if republish and republish.get("demand") == d:
                    republish = None
            elif a == "reset-data" and e.get("confirm") == CONFIRM:
                reset = e
            elif a == "down" and st["state"] in ("ocupado", "falhou"):
                st["stopped"] = True
        elif t == "test-env-publishing":
            if d != st["demand"]:
                st.update(urls=None, ports=None, publishedAt=None, smoke=None)
            st.update(state="publicando", demand=d, pr=e.get("pr"), url=e.get("url"), commit=e.get("commit"),
                      phase="publicando", startedAt=e.get("ts"), lastError=None, stopped=False,
                      warning=e.get("warning"))
            drop(d)
            republish = None
        elif t == "test-env-published":
            if d == st["demand"]:
                st.update(state="ocupado", phase=None, publishedAt=e.get("ts"), urls=e.get("urls"),
                          ports=e.get("ports"), commit=e.get("commit") or st["commit"], smoke=e.get("smoke"),
                          warning=e.get("warning") or st["warning"])
        elif t == "test-env-failed":
            err = {"phase": e.get("phase"), "detail": e.get("detail"), "hint": e.get("hint"), "at": e.get("ts"),
                   "demand": d}
            if d == st["demand"] and st["state"] == "publicando":
                st.update(state="falhou", phase=e.get("phase"), lastError=err)
            else:
                rejected = err
        elif t == "test-env-released":
            if d and d == st["demand"]:
                last_released = {"demand": d, "reason": e.get("reason"), "at": e.get("ts")}
                st.update(state="livre", demand=None, pr=None, url=None, commit=None, phase=None, startedAt=None,
                          publishedAt=None, urls=None, ports=None, lastError=None, stopped=False, smoke=None,
                          warning=None)
                if republish and republish.get("demand") == d:
                    republish = None
            drop(d)
        elif t == "test-env-reset":
            reset = None
    for i, q in enumerate(queue, 1):
        q["position"] = i
    return {**st, "queue": queue, "republish": republish, "reset": reset, "rejected": rejected,
            "lastReleased": last_released}


# ================================================================ sondas (docker/gh) — só leitura
def project_health(project: str = TEST_PROJECT) -> dict:
    """{service: {state, health}} dos containers do projeto (rótulo exato)."""
    r = EXEC.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}", "--format",
                  '{{.Label "com.docker.compose.service"}}\t{{.State}}\t{{.Status}}'], timeout=15)
    out = {}
    if not r.ok:
        return {"_error": (r.err or r.out).strip()[:300]}
    for line in r.out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0]:
            health = "healthy" if "(healthy)" in parts[2] else "unhealthy" if "unhealthy" in parts[2] else \
                "starting" if "starting" in parts[2] else None
            out[parts[0]] = {"state": parts[1], "health": health}
    return out


def healthy(h: dict) -> bool:
    if not h or "_error" in h:
        return False
    return all(v["state"] == "running" and v["health"] in ("healthy", None) for v in h.values())


def pr_info(url_or_number) -> dict | None:
    if not url_or_number:
        return None
    r = EXEC.run(["gh", "pr", "view", str(url_or_number), "--json", "state,headRefOid,number,url"], timeout=30)
    if not r.ok:
        return None
    try:
        return json.loads(r.out)
    except json.JSONDecodeError:
        return None


# ================================================================ visão da API (GET /api/test-env)
def view(rows: list[dict], health: dict | None = None, pr_head: str | None = None, codes: dict | None = None) -> dict:
    s = derive(rows)
    state = s["state"]
    if state == "ocupado" and health is not None and not s["stopped"] and not healthy(health):
        state = "divergente"
    stale = bool(pr_head and s["commit"] and state in ("ocupado", "divergente", "falhou")
                 and not pr_head.startswith(s["commit"]) and not s["commit"].startswith(pr_head))
    codes = codes or {}
    urls = s["urls"] or (test_urls(test_ports()) if s["demand"] else None)
    return {
        "state": state, "demand": s["demand"], "code": codes.get(s["demand"]), "pr": s["pr"], "prUrl": s["url"],
        "commit": s["commit"], "prHead": pr_head, "stale": stale, "phase": s["phase"],
        "startedAt": s["startedAt"], "publishedAt": s["publishedAt"], "stopped": s["stopped"],
        "urls": urls,
        "queue": [{"demand": q["demand"], "code": codes.get(q["demand"]), "pr": q["pr"],
                   "requestedAt": q["requestedAt"], "position": q["position"]} for q in s["queue"]],
        "lastError": s["lastError"], "warning": s["warning"], "lastReleased": s["lastReleased"],
        "health": None if health is None else {k: v for k, v in health.items() if not k.startswith("_")},
        "project": TEST_PROJECT,
    }


def live_summary(v: dict) -> dict:
    return {"state": v["state"], "demand": v["demand"], "code": v.get("code"), "stale": v["stale"],
            "queueSize": len(v["queue"])}


def demand_codes(rows: list[dict]) -> dict:
    out, n = {}, 0
    for e in rows:
        if e.get("type") == "task" and e.get("agent") == "humano" and e.get("id"):
            n += 1
            out[e["id"]] = f"D{n}"
    return out


# ================================================================ pedido do humano
class RequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def request(demand: str | None, action: str, confirm: str | None = None) -> dict:
    """Grava `test-env-request` (agent humano). Erros: 409 publish sem PR aberto; 400 reset sem APAGAR.
    Idempotente: quem já está na fila/publicando devolve o estado atual sem novo evento."""
    if action not in ACTIONS:
        raise RequestError(400, f"ação inválida: {'|'.join(ACTIONS)}")
    rows = read_log()
    s = derive(rows)
    if action == "reset-data" and confirm != CONFIRM:
        raise RequestError(400, f"apagar os dados do teste exige confirm=\"{CONFIRM}\"")
    if action in ("publish", "cancel", "release") and not demand:
        raise RequestError(400, "demand é obrigatório")
    pr = None
    if action == "publish":
        rv = open_review(rows, demand)
        if not rv:
            raise RequestError(409, "a demanda não tem PR aberto: publicar no teste exige PR aberto em revisão")
        pr = rv.get("pr")
        in_queue = next((q for q in s["queue"] if q["demand"] == demand), None)
        if in_queue or (demand == s["demand"] and (s["state"] == "publicando" or s["republish"])):
            return {"state": s["state"], "position": (in_queue or {}).get("position"), "duplicate": True}
    if action == "cancel" and not any(q["demand"] == demand for q in s["queue"]):
        return {"state": s["state"], "duplicate": True}
    titles = {"publish": "Publicar no ambiente de teste", "cancel": "Sair da fila do teste",
              "release": "Liberar ambiente de teste", "reset-data": "Apagar dados do teste",
              "down": "Derrubar ambiente de teste"}
    e = append("test-env-request", titles[action], agent="humano", demand=demand, action=action, pr=pr,
               confirm=confirm if action == "reset-data" else None, to="orquestrador")
    s2 = derive(read_log())
    pos = next((q["position"] for q in s2["queue"] if q["demand"] == demand), None)
    return {"state": s2["state"], "position": pos, "request": e["id"]}


# ================================================================ guard (§4.1 passo 3, R1, R8)
def compose_teste(*args: str) -> list[str]:
    return ["docker", "compose", "-p", TEST_PROJECT, "--env-file", ENV_FILE, *args]


def assert_test_only(cmd: list[str]):
    """Todo comando que muda containers do teste leva -p checkout-teste e --env-file do teste."""
    if cmd[:2] == ["docker", "compose"]:
        if cmd[2:4] != ["-p", TEST_PROJECT] or cmd[4:6] != ["--env-file", ENV_FILE]:
            raise RuntimeError(f"comando recusado (sem -p {TEST_PROJECT} --env-file {ENV_FILE}): {' '.join(cmd)}")
    if PROD_PROJECT in " ".join(cmd):
        raise RuntimeError(f"comando recusado (menciona o produtivo): {' '.join(cmd)}")


def check_config(cfg: dict) -> list[str]:
    """Violações do config resolvido do teste (lista vazia = ok). R1: prefixo de imagem só nos serviços com build."""
    errs = []
    if cfg.get("name") != TEST_PROJECT:
        errs.append(f"projeto resolvido é {cfg.get('name')!r}, esperado {TEST_PROJECT!r}")
    for name, svc in sorted((cfg.get("services") or {}).items()):
        img = svc.get("image") or ""
        if svc.get("build"):
            if not img.startswith(f"{TEST_PROJECT}/"):
                errs.append(f"{name}: imagem {img!r} não começa com {TEST_PROJECT}/ (reescreveria a do produtivo)")
        elif img.startswith(f"{PROD_PROJECT}/"):
            errs.append(f"{name}: usa imagem do produtivo {img!r}")
        for p in svc.get("ports") or []:
            pub = p.get("published") if isinstance(p, dict) else None
            if pub in (None, ""):
                errs.append(f"{name}: porta {p.get('target') if isinstance(p, dict) else p} sem porta fixa no host")
                continue
            try:
                port = int(str(pub).split("-")[0])
            except ValueError:
                errs.append(f"{name}: porta publicada inválida {pub!r}")
                continue
            if port in FORBIDDEN_PORTS:
                errs.append(f"{name}: porta {port} pertence ao produtivo/Squad Control")
            elif port - OFFSET not in PROD_PORTS:
                errs.append(f"{name}: porta {port} não é porta do produtivo + {OFFSET}")
            elif not TEST_PORT_RANGE[0] <= port <= TEST_PORT_RANGE[1]:
                errs.append(f"{name}: porta {port} fora de {TEST_PORT_RANGE[0]}–{TEST_PORT_RANGE[1]}")
        for v in svc.get("volumes") or []:
            if isinstance(v, dict) and v.get("type") == "volume":
                src = v.get("source")
                resolved = ((cfg.get("volumes") or {}).get(src) or {}).get("name") or src
                if not str(resolved).startswith(f"{TEST_PROJECT}_"):
                    errs.append(f"{name}: volume {src!r} resolve para {resolved!r}")
    for key, vol in (cfg.get("volumes") or {}).items():
        if not str((vol or {}).get("name") or "").startswith(f"{TEST_PROJECT}_"):
            errs.append(f"volume {key!r} resolve para {(vol or {}).get('name')!r}")
    for key, net in (cfg.get("networks") or {}).items():
        if not str((net or {}).get("name") or "").startswith(f"{TEST_PROJECT}_"):
            errs.append(f"rede {key!r} resolve para {(net or {}).get('name')!r}")
    return errs


def published_ports(cfg: dict) -> list[int]:
    out = []
    for svc in (cfg.get("services") or {}).values():
        for p in svc.get("ports") or []:
            if isinstance(p, dict) and str(p.get("published") or "").isdigit():
                out.append(int(p["published"]))
    return sorted(set(out))


def port_owners() -> dict:
    """porta -> projeto Compose que a publica (containers de qualquer projeto)."""
    r = EXEC.run(["docker", "ps", "--format", '{{.Label "com.docker.compose.project"}}\t{{.Ports}}'], timeout=15)
    owners = {}
    for line in r.out.splitlines() if r.ok else []:
        proj, _, ports = line.partition("\t")
        for m in re.finditer(r":(\d+)->", ports):
            owners.setdefault(int(m.group(1)), proj or "(sem projeto)")
    return owners


def host_listeners() -> dict:
    """porta -> processo escutando no host (R8: processos não-Docker também contam)."""
    r = EXEC.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=15)
    out = {}
    for line in r.out.splitlines()[1:] if r.ok else []:
        parts = line.split()
        if len(parts) >= 9:
            m = re.search(r":(\d+)$", parts[8])
            if m:
                out.setdefault(int(m.group(1)), parts[0])
    return out


def port_conflicts(ports: list[int]) -> list[str]:
    owners, listeners = port_owners(), host_listeners()
    errs = []
    for p in ports:
        own = owners.get(p)
        if own == TEST_PROJECT:
            continue            # o próprio teste já no ar (republicação)
        if own:
            errs.append(f"porta {p} ocupada pelo projeto {own!r}")
        elif p in listeners:
            errs.append(f"porta {p} ocupada no host pelo processo {listeners[p]!r}")
    return errs


def load_config(cwd: pathlib.Path) -> tuple[dict | None, str]:
    r = EXEC.run(compose_teste("config", "--format", "json"), cwd=cwd, timeout=60)
    if not r.ok:
        return None, (r.err or r.out).strip()[:1500]
    try:
        return json.loads(r.out), ""
    except json.JSONDecodeError as e:
        return None, f"config ilegível: {e}"


def guard(cwd: pathlib.Path, check_ports: bool = True) -> tuple[list[str], dict | None]:
    cfg, err = load_config(cwd)
    if cfg is None:
        return [f"docker compose config falhou: {err}"], None
    errs = check_config(cfg)
    if check_ports and not errs:
        errs += port_conflicts(published_ports(cfg))
    return errs, cfg


def memory_warning(cfg: dict) -> str | None:
    """§2.4: aviso (não bloqueia) quando a memória livre estimada do Docker fica abaixo do mínimo."""
    r = EXEC.run(["docker", "info", "--format", "{{.MemTotal}}"], timeout=15)
    try:
        total = int(r.out.strip())
    except ValueError:
        return None
    ids = EXEC.run(["docker", "ps", "-q"], timeout=15).out.split()
    used = 0
    if ids:
        ri = EXEC.run(["docker", "inspect", "--format", "{{.HostConfig.Memory}}", *ids], timeout=15)
        used = sum(int(x) for x in ri.out.split() if x.isdigit())
    need = 0
    for svc in (cfg.get("services") or {}).values():
        m = svc.get("mem_limit")
        need += int(m) if str(m or "").isdigit() else 0
    free_gb = (total - used - need) / 1024 ** 3
    if free_gb < MIN_FREE_GB:
        return f"memória livre estimada do Docker após publicar: {free_gb:.1f} GB (< {MIN_FREE_GB:g} GB); o produtivo tem prioridade"
    return None


# ================================================================ operações (exigem o lock)
def _fail(s: dict, demand: str, phase: str, detail: str, hint: str | None = None, pr=None, commit=None) -> dict:
    return append("test-env-failed", f"Falha ao publicar no teste ({phase})", demand=demand, pr=pr or s.get("pr"),
                  commit=commit, phase=phase, detail=(detail or "")[:1500], hint=hint)


def _run_test(cmd: list[str], cwd: pathlib.Path, timeout: float) -> Result:
    assert_test_only(cmd)
    return EXEC.run(cmd, cwd=cwd, timeout=timeout)


FLYWAY_RE = re.compile(r"FlywayValidateException|Validate failed|Detected applied migration not resolved|"
                       r"Migration checksum mismatch", re.I)


def publish(demand: str, require_request: bool = True, commit: str | None = None, reason: str = "") -> bool:
    """§4.1. Supõe o lock tomado. Devolve True se publicou com saúde OK."""
    rows = read_log()
    s = derive(rows)
    pending = next((q for q in s["queue"] if q["demand"] == demand), None) or (
        s["republish"] if s["republish"] and s["republish"].get("demand") == demand else None)
    if require_request and not pending:
        _fail({}, demand, "guard", "publicação recusada: não há pedido do humano (test-env-request agent=humano) "
                                   "pendente para esta demanda")
        return False
    if s["demand"] and s["demand"] != demand and s["state"] != "livre":
        print(f"ambiente ocupado por {s['demand']}: o pedido fica na fila (sem furar a fila)", file=sys.stderr)
        return False
    rv = open_review(rows, demand)
    info = pr_info((rv or {}).get("url") or (rv or {}).get("pr")) if rv else None
    if rv and info is None:
        _fail({}, demand, "guard", "não foi possível consultar o PR no GitHub (gh pr view); tente de novo",
              pr=rv.get("pr"))
        return False
    if not rv or info.get("state") != "OPEN":
        if pending and s["demand"] != demand:
            append("test-env-released", "Pedido do teste obsoleto: PR não está aberto", demand=demand,
                   reason="obsolete")
        else:
            _fail({}, demand, "guard", f"PR da demanda não está aberto ({(info or {}).get('state') or 'sem PR'})",
                  pr=(rv or {}).get("pr"))
        return False
    sha = commit or info["headRefOid"]
    pr = info.get("number") or rv.get("pr")
    t0 = time.time()
    wt = worktree()
    if is_publisher_worktree(wt):   # D24: o worktree do publicador nunca é oferecido ao teste
        _fail({}, demand, "guard", f"worktree {wt.name} pertence ao publicador do Squad Control (rollback)")
        return False
    append("test-env-publishing", f"Publicando no teste: PR #{pr} @ {sha[:12]}", demand=demand, pr=pr,
           url=rv.get("url"), commit=sha, detail=reason or None)
    ctx = {"pr": pr}
    # 2. worktree dedicado, HEAD destacado no commit do PR (nunca toca plankton/ nem worktrees das features)
    main = main_root()
    if not (wt / ".git").exists():
        steps = [["git", "-C", str(main), "fetch", "-q", "origin"],
                 ["git", "-C", str(main), "worktree", "add", "--detach", str(wt), sha]]
    else:
        steps = [["git", "-C", str(wt), "fetch", "-q", "origin"],
                 ["git", "-C", str(wt), "checkout", "-q", "--detach", "--force", sha]]
    for cmd in steps:
        r = EXEC.run(cmd, timeout=180)
        if not r.ok:
            _fail(ctx, demand, "checkout", f"{' '.join(cmd)}: {(r.err or r.out).strip()}", commit=sha)
            return False
    # 3. guard (projeto, portas +10000, imagens de app, volumes, rede, portas livres no host)
    errs, cfg = guard(wt)
    if errs:
        _fail(ctx, demand, "guard", "; ".join(errs), commit=sha)
        return False
    warning = memory_warning(cfg)
    # 4. build (falha aqui não derruba o que estava no teste)
    r = _run_test(compose_teste("build", "--build-arg", f"REVISION={sha}"), wt, BUILD_TIMEOUT)
    if not r.ok:
        _fail(ctx, demand, "build", (r.err or r.out)[-1500:], commit=sha)
        return False
    # 5. up com espera de saúde; nunca -v nem --force-recreate
    r = _run_test(compose_teste("up", "-d", "--wait", "--wait-timeout", str(UP_WAIT)), wt, UP_WAIT + 120)
    if not r.ok:
        logs = _run_test(compose_teste("logs", "--no-color", "--tail", "200", *APP_SERVICES), wt, 60)
        hint = "reset-data" if FLYWAY_RE.search(logs.out + logs.err) else None
        _fail(ctx, demand, "health" if hint else "up", ((r.err or r.out)[-900:] + "\n" +
                                                        (FLYWAY_RE.search(logs.out + logs.err) or [""])[0]).strip(),
              hint=hint, commit=sha)
        return False
    # 6. smoke
    ports = test_ports(read_env(env_file_path(wt)))
    urls = test_urls(ports)
    smoke = {}
    for key in ("saga", "order", "inventory", "payment", "shipping"):
        smoke[key] = _probe(f"{urls[key]}/actuator/health")
    smoke["console"] = _probe(f"{urls['console']}/")
    if not all(smoke.values()):
        bad = ", ".join(k for k, v in smoke.items() if not v)
        _fail(ctx, demand, "smoke", f"sem resposta saudável: {bad}", commit=sha)
        return False
    append("test-env-published", f"Pronto para testar: PR #{pr} @ {sha[:12]}", demand=demand, pr=pr, commit=sha,
           project=TEST_PROJECT, ports=ports, urls=urls, durationSec=round(time.time() - t0), smoke=smoke,
           warning=warning)
    return True


def _probe(url: str, tries: int = 5) -> bool:
    for i in range(tries):
        if http_ok(url):
            return True
        if i < tries - 1:
            time.sleep(float(os.environ.get("SQUAD_TEST_SMOKE_SLEEP") or 3))
    return False


def do_release(demand: str, reason: str) -> dict | None:
    """§4.3: stop (containers e volume ficam) + test-env-released. Supõe o lock tomado."""
    s = derive(read_log())
    if demand == s["demand"]:
        wt = worktree()
        if (wt / ".git").exists() or os.environ.get("SQUAD_TEST_WORKTREE"):
            r = _run_test(compose_teste("stop"), wt, 180)
            if not r.ok:
                print(f"aviso: stop do teste falhou: {(r.err or r.out).strip()[:300]}", file=sys.stderr)
        return append("test-env-released", f"Ambiente de teste liberado ({reason})", demand=demand, reason=reason)
    if any(q["demand"] == demand for q in s["queue"]):
        return append("test-env-released", f"Saiu da fila do teste ({reason})", demand=demand, reason=reason)
    return None


def do_reset() -> bool:
    """§4.4: `down -v` só do checkout-teste, com pedido do humano (APAGAR) e guard repetido."""
    s = derive(read_log())
    req = s["reset"]
    if not req:
        print("recusado: não há pedido do humano com confirmação APAGAR pendente", file=sys.stderr)
        return False
    wt = worktree()
    cfg, err = load_config(wt)
    errs = check_config(cfg) if cfg else [err]
    if errs:
        _fail({}, s["demand"] or req.get("demand") or "", "guard", "apagar dados recusado: " + "; ".join(errs))
        return False
    r = _run_test(compose_teste("down", "-v"), wt, 300)
    if not r.ok:
        _fail({}, s["demand"] or "", "up", f"down -v do teste falhou: {(r.err or r.out).strip()}")
        return False
    append("test-env-reset", "Dados do ambiente de teste apagados", requestedBy=req["id"], demand=s["demand"])
    if s["demand"] and s["commit"]:
        publish(s["demand"], require_request=False, commit=s["commit"], reason="republicação após apagar dados")
    return True


def do_down() -> bool:
    wt = worktree()
    r = _run_test(compose_teste("down"), wt, 300)
    if not r.ok:
        print((r.err or r.out).strip(), file=sys.stderr)
    return r.ok


def reconcile() -> dict:
    """§4.6 — idempotente; não faz nada se o lock estiver tomado."""
    actions = []
    with lock() as got:
        if not got:
            return {"skipped": "lock", "actions": []}
        for _ in range(12):
            rows = read_log()
            s = derive(rows)
            if s["state"] == "publicando":       # processo anterior morreu no meio (o lock está livre)
                _fail(s, s["demand"], "up", "publicação interrompida (processo encerrado antes do fim)",
                      commit=s["commit"])
                actions.append(f"interrompida:{s['demand']}")
                continue
            if s["demand"] and (why := closed_reason(rows, s["demand"])):
                do_release(s["demand"], why)
                actions.append(f"liberado:{s['demand']}:{why}")
                continue
            obsolete = [q for q in s["queue"] if closed_reason(rows, q["demand"]) or not open_review(rows, q["demand"])]
            if obsolete:
                for q in obsolete:
                    append("test-env-released", "Pedido do teste obsoleto (demanda sem PR aberto)", demand=q["demand"],
                           reason="obsolete")
                    actions.append(f"obsoleto:{q['demand']}")
                continue
            if s["reset"]:
                do_reset()
                actions.append("reset-data")
                continue
            if s["republish"]:
                publish(s["demand"])
                actions.append(f"republicado:{s['demand']}")
                break
            if s["state"] == "livre" and s["queue"]:
                head = s["queue"][0]["demand"]
                ok = publish(head)
                actions.append(f"publicado:{head}:{'ok' if ok else 'falhou'}")
                after = derive(read_log())
                if not ok and after["state"] == "livre" and not any(q["demand"] == head for q in after["queue"]):
                    continue                      # obsoleto: saiu da fila, tenta o próximo
                break
            break
    return {"actions": actions}


# ================================================================ impressão digital do produtivo (CA4) — só leitura
def prod_fingerprint() -> dict:
    ids = EXEC.run(["docker", "ps", "-a", "-q", "--filter", f"label=com.docker.compose.project={PROD_PROJECT}"],
                   timeout=15).out.split()
    containers = []
    if ids:
        r = EXEC.run(["docker", "inspect", *ids], timeout=30)
        try:
            data = json.loads(r.out) if r.ok else []
        except json.JSONDecodeError:
            data = []
        for c in data:
            labels = (c.get("Config") or {}).get("Labels") or {}
            ports = sorted({f"{b.get('HostPort')}->{k}" for k, v in ((c.get("NetworkSettings") or {}).get("Ports") or {}).items()
                            for b in (v or []) if b.get("HostPort")})
            containers.append({"name": (c.get("Name") or "").lstrip("/"), "service": labels.get("com.docker.compose.service"),
                               "id": c.get("Id"), "image": c.get("Image"),
                               "startedAt": (c.get("State") or {}).get("StartedAt"),
                               "restartCount": c.get("RestartCount"), "status": (c.get("State") or {}).get("Status"),
                               "ports": ports, "configHash": labels.get("com.docker.compose.config-hash"),
                               "workingDir": labels.get("com.docker.compose.project.working_dir")})
    vol = {}
    r = EXEC.run(["docker", "volume", "inspect", f"{PROD_PROJECT}_pgdata"], timeout=15)
    if r.ok:
        try:
            v = json.loads(r.out)[0]
            vol = {"name": v.get("Name"), "createdAt": v.get("CreatedAt"), "mountpoint": v.get("Mountpoint")}
        except (json.JSONDecodeError, IndexError):
            pass
    images = {}
    r = EXEC.run(["docker", "image", "ls", "--no-trunc", "--filter", f"reference={PROD_PROJECT}/*", "--format",
                  "{{.Repository}}:{{.Tag}}\t{{.ID}}"], timeout=15)
    for line in r.out.splitlines() if r.ok else []:
        name, _, iid = line.partition("\t")
        if name.endswith(":local"):
            images[name] = iid
    main = main_root()
    r = EXEC.run(["docker", "compose", "-p", PROD_PROJECT, "config", "--hash", "*"], cwd=main, timeout=60)
    hashes = dict(sorted(tuple(l.split(None, 1)) for l in r.out.splitlines() if len(l.split()) == 2)) if r.ok else {}
    containers.sort(key=lambda c: c["name"])
    for c in containers:
        c["configHashMatchesMain"] = hashes.get(c["service"]) == c["configHash"] if hashes else None
    fp = {"project": PROD_PROJECT, "mainRoot": str(main), "containers": containers, "volume": vol,
          "images": dict(sorted(images.items())), "configHash": hashes}
    fp["digest"] = hashlib.sha256(json.dumps({k: v for k, v in fp.items() if k != "mainRoot"}, sort_keys=True)
                                  .encode()).hexdigest()[:16]
    return fp


def fingerprint_diff(a: dict, b: dict) -> list[str]:
    out = []
    ca = {c["name"]: c for c in a.get("containers", [])}
    cb = {c["name"]: c for c in b.get("containers", [])}
    for n in sorted(set(ca) | set(cb)):
        if n not in ca or n not in cb:
            out.append(f"container {n}: {'novo' if n in cb else 'sumiu'}")
            continue
        for k in ("id", "image", "startedAt", "restartCount", "ports", "configHash"):
            if ca[n].get(k) != cb[n].get(k):
                out.append(f"{n}.{k}: {ca[n].get(k)} -> {cb[n].get(k)}")
    for k in ("volume", "images", "configHash"):
        if a.get(k) != b.get(k):
            out.append(f"{k} mudou")
    return out


# ================================================================ CLI
def status_now() -> dict:
    rows = read_log()
    s = derive(rows)
    health = project_health(TEST_PROJECT)
    head = None
    if s["demand"]:
        info = pr_info(s["url"] or s["pr"])
        head = (info or {}).get("headRefOid")
    return view(rows, health=health, pr_head=head, codes=demand_codes(rows))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("request")
    s.add_argument("--action", required=True, choices=ACTIONS)
    s.add_argument("--demand")
    s.add_argument("--confirm")
    sub.add_parser("reconcile")
    s = sub.add_parser("publish")
    s.add_argument("--demand", required=True)
    s = sub.add_parser("release")
    s.add_argument("--demand", required=True)
    s.add_argument("--reason", default="human", choices=REASONS)
    sub.add_parser("down")
    sub.add_parser("reset-data")
    sub.add_parser("status")
    sub.add_parser("check-ports")
    s = sub.add_parser("prod-fingerprint")
    s.add_argument("--out")
    s.add_argument("--compare")
    a = p.parse_args(argv)

    if a.cmd == "request":
        try:
            print(json.dumps(request(a.demand, a.action, a.confirm), ensure_ascii=False))
            return 0
        except RequestError as e:
            print(f"recusado ({e.status}): {e}", file=sys.stderr)
            return 2
    if a.cmd == "reconcile":
        print(json.dumps(reconcile(), ensure_ascii=False))
        return 0
    if a.cmd == "publish":
        with lock() as got:
            if not got:
                print("outra operação do ambiente de teste em andamento (lock)", file=sys.stderr)
                return 3
            return 0 if publish(a.demand) else 1
    if a.cmd == "release":
        with lock() as got:
            if not got:
                print("outra operação do ambiente de teste em andamento (lock)", file=sys.stderr)
                return 3
            e = do_release(a.demand, a.reason)
            print(json.dumps(e or {"skipped": "a demanda não ocupa o teste nem está na fila"}, ensure_ascii=False))
        reconcile()
        return 0
    if a.cmd == "down":
        with lock() as got:
            if not got:
                print("outra operação do ambiente de teste em andamento (lock)", file=sys.stderr)
                return 3
            s = derive(read_log())
            if s["state"] in ("ocupado", "falhou") and not s["stopped"]:
                append("test-env-request", "Derrubar ambiente de teste", agent="humano", demand=s["demand"],
                       action="down", to="orquestrador")
            return 0 if do_down() else 1
    if a.cmd == "reset-data":
        with lock() as got:
            if not got:
                print("outra operação do ambiente de teste em andamento (lock)", file=sys.stderr)
                return 3
            return 0 if do_reset() else 1
    if a.cmd == "status":
        print(json.dumps(status_now(), ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "check-ports":
        errs, cfg = guard(worktree() if (worktree() / ".git").exists() else ROOT)
        print(json.dumps({"ok": not errs, "errors": errs, "ports": published_ports(cfg or {})}, ensure_ascii=False,
                         indent=2))
        return 0 if not errs else 1
    if a.cmd == "prod-fingerprint":
        fp = prod_fingerprint()
        if a.out:
            pathlib.Path(a.out).write_text(json.dumps(fp, ensure_ascii=False, indent=2, sort_keys=True))
        if a.compare:
            diff = fingerprint_diff(json.loads(pathlib.Path(a.compare).read_text()), fp)
            print(json.dumps({"identical": not diff, "diff": diff, "digest": fp["digest"]}, ensure_ascii=False, indent=2))
            return 0 if not diff else 1
        print(json.dumps(fp, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
