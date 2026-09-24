#!/usr/bin/env python3
"""Demandas de bug (D16, ADR-019, docs/contracts/demandas-de-bug.md) — somente stdlib.

- `GitDirStore` (interface `BugStore`): `docs/squad/<kind>/bugs/<demand>/bug.json` + `evidencias/` + `index.jsonl`.
- Rascunhos fora do git em `.squad/bug-drafts/<draft>/` (id `secrets.token_hex(16)`, expira em 24 h).
- Criar a partir de link (§4): o servidor NUNCA acessa a URL colada — extrai só o id (trace, painel, regra) e consulta
  as URLs-base fixas do produtivo (`SQUAD_PROD_JAEGER`, `SQUAD_PROD_GRAFANA`, `SQUAD_PROD_PROMETHEUS`), sem
  credenciais, sem seguir redirecionamentos, sem proxy, 5 s por chamada e no máximo 10 MB lidos.
- Validação, máscara e metadados de imagem: `evidence_rules.py` (módulo único).
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import evidence_rules as er  # noqa: E402
from evidence_rules import EvidenceError  # noqa: E402

KINDS = ("produto", "operacao")
SEVERITIES = ("critica", "alta", "media", "baixa")
DRAFT_TTL_S = 24 * 3600
HTTP_TIMEOUT = 5
HTTP_MAX = 10 * 1024 * 1024
MAX_STACK = 8 * 1024
MAX_LOG_LINES = 500
PREVIEW_LINES = 200
MAX_WINDOW_S = 24 * 3600
MAX_POINTS = 300
DRAFT_RE = re.compile(r"^[0-9a-f]{32}$")
DEMAND_RE = re.compile(r"^[0-9a-f]{12}$")
FILE_RE = re.compile(r"^\d{2}-[a-z0-9._-]{1,80}$")
TRACE_RE = re.compile(r"^(?:[0-9a-f]{16}|[0-9a-f]{32})$")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
JAEGER_PORT = 16686
REPO = "jcrouzillard/checkout-saga-squad"

WARN_HEURISTIC = ("\"Só produtivo\" é heurístico: o trace/painel existir no produtivo é um indício forte, não prova — "
                  "o OTLP do produtivo (4317/4318) aceita spans de qualquer processo local.")
WARN_MEMORY = ("O Jaeger produtivo guarda os traces em memória: o link deixa de funcionar num restart. "
               "A evidência válida é o snapshot gravado.")
WARN_NO_ERROR = "O trace não tem span com erro; descreva o sintoma."

LOCK = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ================================================================ configuração do produtivo
def _read_env(path: pathlib.Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def main_root() -> pathlib.Path:
    import testenv as te
    return te.main_root()


def grafana_port() -> int:
    try:
        return int(_read_env(main_root() / ".env").get("GRAFANA_PORT") or 3000)
    except ValueError:
        return 3000


def jaeger_base() -> str:
    return (os.environ.get("SQUAD_PROD_JAEGER") or f"http://localhost:{JAEGER_PORT}").rstrip("/")


def grafana_base() -> str:
    return (os.environ.get("SQUAD_PROD_GRAFANA") or f"http://localhost:{grafana_port()}").rstrip("/")


def prometheus_base() -> str:
    return (os.environ.get("SQUAD_PROD_PROMETHEUS") or "http://localhost:9090").rstrip("/")


# ================================================================ HTTP para o produtivo (URL-base fixa)
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def http_get_json(base: str, path: str, params: dict | None = None) -> tuple[int, object]:
    """GET <base fixa><path> sem credenciais; devolve (status, json|None). Nunca recebe URL do humano."""
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "squad-bugs/1"})
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT) as r:
            body = r.read(HTTP_MAX + 1)
            status = r.status
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise EvidenceError(502, "produtivo_indisponivel", f"não foi possível consultar o produtivo ({base}): {e}") from None
    if len(body) > HTTP_MAX:
        raise EvidenceError(502, "resposta_grande", "resposta do produtivo acima de 10 MB")
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, None


# ================================================================ link colado → (tipo, identificadores)
def parse_link(link: str) -> dict:
    """Extrai só o identificador. Recusa host não local (anti-SSRF), portas do teste e formatos desconhecidos."""
    try:
        u = urllib.parse.urlsplit((link or "").strip())
        port = u.port
    except ValueError:
        raise EvidenceError(422, "link_invalido", "link inválido") from None
    if u.scheme not in ("http", "https") or not u.hostname:
        raise EvidenceError(422, "link_invalido", "link inválido: use o endereço http://localhost:… do produtivo")
    if u.hostname not in LOCAL_HOSTS:
        raise EvidenceError(422, "host_nao_permitido",
                            "host não permitido: só links do produtivo local (localhost ou 127.0.0.1)")
    port = port or (443 if u.scheme == "https" else 80)
    if port in er.TEST_PORTS:
        raise EvidenceError(422, "ambiente_de_teste",
                            "link do ambiente de teste (porta +10000): bug é só do produtivo")
    q = urllib.parse.parse_qs(u.query)
    if port == JAEGER_PORT:
        m = re.match(r"^/trace/([0-9a-fA-F]+)/?$", u.path)
        if not m:
            raise EvidenceError(422, "link_sem_trace", "link sem trace: abra o trace no Jaeger e copie o link dele")
        tid = m.group(1).lower()
        if not TRACE_RE.match(tid):
            raise EvidenceError(422, "link_sem_trace", "id de trace inválido (16 ou 32 hexadecimais)")
        return {"type": "jaeger-trace", "traceId": tid, "url": f"http://localhost:{JAEGER_PORT}/trace/{tid}"}
    if port == grafana_port():
        m = re.match(r"^/d/([A-Za-z0-9_-]{1,64})(?:/[A-Za-z0-9_-]*)?/?$", u.path)
        if m:
            vp = (q.get("viewPanel") or [""])[0]
            pm = re.match(r"^(?:panel-)?(\d{1,6})$", vp)
            if not pm:
                raise EvidenceError(422, "link_sem_painel",
                                    "link sem painel: abra o painel (Ver/View) e copie o link com viewPanel")
            frm, to = (q.get("from") or ["now-6h"])[0], (q.get("to") or ["now"])[0]
            uid, pid = m.group(1), int(pm.group(1))
            canon = f"http://localhost:{port}/d/{uid}?" + urllib.parse.urlencode(
                {"viewPanel": f"panel-{pid}", "from": frm, "to": to})
            return {"type": "grafana-painel", "dashboardUid": uid, "panelId": pid, "from": frm, "to": to, "url": canon}
        m = re.match(r"^/alerting/grafana/([A-Za-z0-9_-]{1,64})/view/?$", u.path)
        if m:
            return {"type": "grafana-alerta", "ruleUid": m.group(1),
                    "url": f"http://localhost:{port}/alerting/grafana/{m.group(1)}/view"}
        raise EvidenceError(422, "link_nao_suportado",
                            "link do Grafana não suportado: use o de um painel (viewPanel) ou de uma regra de alerta")
    raise EvidenceError(422, "link_nao_suportado",
                        f"link não suportado: aceitos trace do Jaeger (:{JAEGER_PORT}) ou painel/alerta do Grafana "
                        f"(:{grafana_port()}) do produtivo")


# ================================================================ Jaeger (§4.1)
SPAN_ALLOW = ("span.kind", "otel.status_code", "otel.status_description", "http.request.method", "http.route",
              "http.response.status_code", "url.path", "messaging.system", "messaging.destination.name", "db.system")
CORRELATION_KEYS = {"orderId": ("orderId", "order.id", "order_id", "app.order.id"),
                    "sagaId": ("sagaId", "saga.id", "saga_id", "app.saga.id")}


def _tags(items) -> dict:
    return {t.get("key"): t.get("value") for t in (items or []) if isinstance(t, dict)}


def _is_error(tags: dict) -> bool:
    try:
        code = int(tags.get("http.response.status_code") or 0)
    except (TypeError, ValueError):
        code = 0
    return tags.get("otel.status_code") == "ERROR" or tags.get("error") in (True, "true") or code >= 500


def _iso_us(us) -> str:
    try:
        return datetime.fromtimestamp(int(us) / 1e6, timezone.utc).isoformat(timespec="milliseconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _clean_value(k: str, v) -> str:
    s = str(v)
    if k == "url.path":
        s = s.split("?", 1)[0]
    return s.replace("\n", " ")[:500]


def jaeger_snapshot(trace: dict) -> tuple[str, dict]:
    """Snapshot textual (allowlist de atributos, uma linha por span) + resumo extraído."""
    procs = {k: (v or {}).get("serviceName", "?") for k, v in (trace.get("processes") or {}).items()}
    spans = sorted(trace.get("spans") or [], key=lambda s: s.get("startTime") or 0)
    tid = trace.get("traceID", "")
    start = min((s.get("startTime") or 0 for s in spans), default=0)
    end = max(((s.get("startTime") or 0) + (s.get("duration") or 0) for s in spans), default=0)
    services = sorted(set(procs.values()))
    root = next((s for s in spans if not [r for r in (s.get("references") or []) if r.get("refType") == "CHILD_OF"]),
                spans[0] if spans else None)
    corr: dict[str, str] = {}
    errors, lines = [], []
    for s in spans:
        tags = _tags(s.get("tags"))
        for name, keys in CORRELATION_KEYS.items():
            for k in keys:
                if tags.get(k) and name not in corr:
                    corr[name] = str(tags[k])
        svc = procs.get(s.get("processID"), "?")
        parent = next((r.get("spanID") for r in (s.get("references") or []) if r.get("refType") == "CHILD_OF"), "-")
        attrs = " ".join(f"{k}={_clean_value(k, tags[k])}" for k in SPAN_ALLOW if k in tags)
        err = _is_error(tags)
        lines.append(f"{_iso_us(s.get('startTime'))} {svc} \"{s.get('operationName', '')}\" span={s.get('spanID')} "
                     f"parent={parent} dur_ms={round((s.get('duration') or 0) / 1000, 3)} {attrs}"
                     + (" [ERRO]" if err else ""))
        exc = {}
        for k, v in tags.items():
            if str(k).startswith("exception."):
                exc[k] = v
        for lg in s.get("logs") or []:
            f = _tags(lg.get("fields"))
            if f.get("event") == "exception":
                exc.update({k: v for k, v in f.items() if str(k).startswith("exception.")})
        for k in sorted(exc):
            v = str(exc[k])
            if k == "exception.stacktrace":
                v = v[:MAX_STACK] + ("\n[stack truncado em 8 KB]" if len(v) > MAX_STACK else "")
                lines.append(f"  {k}: |")
                lines += [f"    {x}" for x in v.splitlines()]
            else:
                lines.append(f"  {k}: {v.replace(chr(10), ' ')[:2000]}")
        if err:
            errors.append({"service": svc, "operation": s.get("operationName"), "spanId": s.get("spanID"),
                           "statusDescription": tags.get("otel.status_description"),
                           "httpStatus": tags.get("http.response.status_code"),
                           "exceptionType": exc.get("exception.type"), "exceptionMessage": exc.get("exception.message")})
    extracted = {"traceId": tid, "start": _iso_us(start), "durationMs": round((end - start) / 1000, 3),
                 "services": services, "spanCount": len(spans),
                 "rootOperation": f"{procs.get(root.get('processID'), '?')} {root.get('operationName')}" if root else None,
                 "errorSpans": errors, **corr}
    head = [f"# Snapshot do trace {tid} — Jaeger do produtivo (somente leitura), gerado em {now_iso()}",
            f"# {WARN_MEMORY}",
            "# Atributos por allowlist (ADR-019 §4.1); endereços de rede, user agent e query strings descartados.",
            f"traceId: {tid}", f"inicio: {extracted['start']}", f"duracao_ms: {extracted['durationMs']}",
            f"servicos: {', '.join(services)}", f"spans: {len(spans)}", f"operacao_raiz: {extracted['rootOperation']}",
            f"spans_com_erro: {len(errors)}"]
    head += [f"{k}: {corr[k]}" for k in ("orderId", "sagaId") if k in corr]
    return "\n".join(head + ["---"] + lines) + "\n", extracted


def compose_logs(trace_id: str, services: list[str], start_iso: str, dur_ms: float) -> list[str]:
    """Linhas dos containers do produtivo com o trace_id (docker compose -p checkout-saga logs, somente leitura)."""
    import prod
    import testenv as te
    svcs = [s for s in services if s in te.APP_SERVICES]
    if not svcs:
        return []
    try:
        t0 = datetime.fromisoformat(start_iso)
    except ValueError:
        return []
    since = (t0 - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (t0 + timedelta(milliseconds=dur_ms) + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = prod.run(prod.compose("logs", "--no-color", "--since", since, "--until", until, *svcs), timeout=30)
    if not r.ok:
        return []
    out = []
    for line in r.out.splitlines():
        if trace_id not in line:
            continue
        _, sep, payload = line.partition(" | ")
        payload = payload if sep else line
        try:
            obj = json.loads(payload)
            if isinstance(obj, dict) and trace_id not in (obj.get("trace_id"), obj.get("traceId"),
                                                         (obj.get("mdc") or {}).get("trace_id")):
                continue
        except json.JSONDecodeError:
            pass
        out.append(line)
        if len(out) >= MAX_LOG_LINES:
            break
    return out


def extract_jaeger(src: dict, include_logs: bool) -> tuple[dict, list[tuple[str, str, str]], list[str]]:
    tid = src["traceId"]
    status, body = http_get_json(jaeger_base(), f"/api/traces/{tid}")
    data = (body or {}).get("data") if isinstance(body, dict) else None
    if status == 404 or not data:
        raise EvidenceError(422, "trace_nao_encontrado_no_produtivo",
                            "trace não encontrado no Jaeger do produtivo (pode ter expirado: o Jaeger guarda em memória)")
    snap, extracted = jaeger_snapshot(data[0])
    t8 = tid[:8]
    files = [(f"trace-{t8}.log", snap, "jaeger")]
    warnings = [WARN_HEURISTIC, WARN_MEMORY]
    if not extracted["errorSpans"]:
        warnings.append(WARN_NO_ERROR)
    if include_logs:
        lines = compose_logs(tid, extracted["services"], extracted["start"], extracted["durationMs"])
        if lines:
            files.append((f"logs-{t8}.log", "\n".join(lines) + "\n", "compose-logs"))
        else:
            warnings.append("Nenhuma linha de log dos containers do produtivo com este trace_id.")
    return extracted, files, warnings


# ================================================================ Grafana (§4.2 e §4.3)
_REL = re.compile(r"^now(?:-(\d+)([smhdwMy]))?(?:/[smhdwMy])?$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000, "y": 31536000}


def parse_time(value: str, now: float) -> float:
    v = str(value or "").strip()
    if re.fullmatch(r"\d{10,14}", v):
        n = int(v)
        return n / 1000 if n > 10**11 else float(n)
    m = _REL.match(v)
    if m:
        return now - (int(m.group(1)) * _UNIT[m.group(2)] if m.group(1) else 0)
    raise EvidenceError(422, "janela_invalida", f"intervalo de tempo não reconhecido: {v!r}")


def window(frm: str, to: str, now: float | None = None) -> tuple[float, float, list[str]]:
    now = time.time() if now is None else now
    start, end = parse_time(frm, now), parse_time(to, now)
    warns = []
    if end <= start:
        raise EvidenceError(422, "janela_invalida", "intervalo de tempo vazio")
    if end - start > MAX_WINDOW_S:
        start = end - MAX_WINDOW_S
        warns.append("Janela maior que 24 h: recortada para as últimas 24 h do intervalo.")
    return start, end, warns


def step_for(start: float, end: float) -> int:
    return max(15, math.ceil((end - start) / MAX_POINTS))


def resolve_vars(expr: str, start: float, end: float, step: int) -> str:
    rng = f"{int(end - start)}s"
    rate = f"{max(step + 15, 60)}s"
    secs = int(end - start)
    # nomes mais longos primeiro: $__range_s/_ms e $__interval_ms não podem virar "$__range" + sufixo
    for name, val in (("__range_ms", str(secs * 1000)), ("__range_s", str(secs)), ("__range", rng),
                      ("__rate_interval", rate), ("__interval_ms", str(step * 1000)), ("__interval", f"{step}s")):
        expr = expr.replace("${" + name + "}", val).replace("$" + name, val)
    return expr


def _num(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def summarize_series(expr: str, start: float, end: float, threshold: float | None) -> list[str]:
    step = step_for(start, end)
    q = resolve_vars(expr, start, end, step)
    status, body = http_get_json(prometheus_base(), "/api/v1/query_range",
                                 {"query": q, "start": int(start), "end": int(end), "step": step})
    lines = [f"expr: {expr}", f"consulta: {q}  (step {step}s)"]
    if status != 200 or not isinstance(body, dict) or body.get("status") != "success":
        return lines + [f"  (Prometheus respondeu {status}: {(body or {}).get('error') if isinstance(body, dict) else ''})"]
    result = (body.get("data") or {}).get("result") or []
    if not result:
        lines.append("  (nenhuma série no intervalo)")
    for s in result[:50]:
        vals = [(float(t), _num(v)) for t, v in s.get("values") or []]
        nums = [v for _, v in vals if v is not None]
        labels = ",".join(f"{k}={v}" for k, v in sorted((s.get("metric") or {}).items()))
        above = next((t for t, v in vals if v is not None and threshold is not None and v > threshold), None)
        lines.append(f"  serie {{{labels}}} pontos={len(vals)} min={min(nums) if nums else '-'} "
                     f"max={max(nums) if nums else '-'} ultimo={nums[-1] if nums else '-'}"
                     + (f" acima_do_threshold({threshold})_desde={datetime.fromtimestamp(above, timezone.utc).isoformat()}"
                        if above is not None else ""))
    return lines


def _find_panel(panels: list, pid: int) -> dict | None:
    for p in panels or []:
        if p.get("id") == pid:
            return p
        inner = _find_panel(p.get("panels") or [], pid)
        if inner:
            return inner
    return None


def extract_grafana_panel(src: dict) -> tuple[dict, list[tuple[str, str, str]], list[str]]:
    start, end, warns = window(src["from"], src["to"])
    status, body = http_get_json(grafana_base(), f"/api/dashboards/uid/{src['dashboardUid']}")
    dash = (body or {}).get("dashboard") if isinstance(body, dict) else None
    panel = _find_panel((dash or {}).get("panels"), src["panelId"]) if status == 200 and dash else None
    if not panel:
        raise EvidenceError(422, "painel_nao_encontrado", "painel não encontrado no Grafana do produtivo")
    defaults = (panel.get("fieldConfig") or {}).get("defaults") or {}
    steps = [s.get("value") for s in ((defaults.get("thresholds") or {}).get("steps") or []) if _num(s.get("value")) is not None]
    threshold = max(steps) if steps else None
    exprs = [t.get("expr") for t in panel.get("targets") or [] if t.get("expr")]
    lines = [f"# Painel do Grafana do produtivo (somente leitura), gerado em {now_iso()}",
             f"dashboard: {dash.get('title')} (uid {src['dashboardUid']})", f"painel: {panel.get('title')} (id {src['panelId']})",
             f"unidade: {defaults.get('unit') or '-'}", f"thresholds: {steps or '-'}",
             f"janela: {datetime.fromtimestamp(start, timezone.utc).isoformat()} → {datetime.fromtimestamp(end, timezone.utc).isoformat()}",
             "---"]
    for e in exprs:
        lines += summarize_series(e, start, end, threshold)
    extracted = {"dashboard": dash.get("title"), "dashboardUid": src["dashboardUid"], "panel": panel.get("title"),
                 "panelId": src["panelId"], "exprs": exprs, "unit": defaults.get("unit"), "thresholds": steps,
                 "from": datetime.fromtimestamp(start, timezone.utc).isoformat(timespec="seconds"),
                 "to": datetime.fromtimestamp(end, timezone.utc).isoformat(timespec="seconds")}
    name = f"painel-{er.sanitize_name(src['dashboardUid'], 40)}-{src['panelId']}.log"
    return extracted, [(name, "\n".join(lines) + "\n", "grafana")], [WARN_HEURISTIC] + warns


def extract_grafana_alert(src: dict) -> tuple[dict, list[tuple[str, str, str]], list[str]]:
    uid = src["ruleUid"]
    status, rule = http_get_json(grafana_base(), f"/api/v1/provisioning/alert-rules/{uid}")
    if status != 200 or not isinstance(rule, dict) or not rule.get("uid"):
        raise EvidenceError(422, "alerta_nao_encontrado", "regra de alerta não encontrada no Grafana do produtivo")
    _, rules = http_get_json(grafana_base(), "/api/prometheus/grafana/api/v1/rules")
    state = None
    for g in (((rules or {}).get("data") or {}).get("groups") or []) if isinstance(rules, dict) else []:
        for r in g.get("rules") or []:
            if r.get("uid") == uid or (r.get("labels") or {}).get("__alert_rule_uid__") == uid or r.get("name") == rule.get("title"):
                state = r
    alerts = (state or {}).get("alerts") or []
    active = min((a.get("activeAt") for a in alerts if a.get("activeAt")), default=None) or (state or {}).get("activeAt")
    now = time.time()
    start = now - 3600
    if active:
        try:
            start = datetime.fromisoformat(str(active).replace("Z", "+00:00")).timestamp() - 1800
        except ValueError:
            pass
    start = max(start, now - MAX_WINDOW_S)
    exprs = [((d.get("model") or {}).get("expr")) for d in rule.get("data") or [] if (d.get("model") or {}).get("expr")]
    lines = [f"# Regra de alerta do Grafana do produtivo (somente leitura), gerado em {now_iso()}",
             f"regra: {rule.get('title')} (uid {uid})", f"condicao: {rule.get('condition')}", f"for: {rule.get('for')}",
             f"labels: {json.dumps(rule.get('labels') or {}, ensure_ascii=False)}",
             f"anotacoes: {json.dumps(rule.get('annotations') or {}, ensure_ascii=False)}",
             f"estado: {(state or {}).get('state') or 'desconhecido'}", f"activeAt: {active or '-'}"]
    lines += [f"valor: {a.get('value')} ({json.dumps(a.get('labels') or {}, ensure_ascii=False)})" for a in alerts[:20]]
    lines.append("---")
    for e in exprs:
        lines += summarize_series(e, start, now, None)
    extracted = {"rule": rule.get("title"), "ruleUid": uid, "state": (state or {}).get("state"), "activeAt": active,
                 "values": [a.get("value") for a in alerts[:20]], "exprs": exprs}
    return extracted, [(f"alerta-{er.sanitize_name(uid, 60)}.log", "\n".join(lines) + "\n", "grafana")], [WARN_HEURISTIC]


VERIFIED_BY = {"jaeger-trace": "jaeger-produtivo", "grafana-painel": "grafana-produtivo",
               "grafana-alerta": "grafana-produtivo", None: "declaracao-humana"}


# ================================================================ visibilidade do repositório (§8.4)
_vis_cache: dict = {"at": 0.0, "value": None}


def repo_visibility() -> str:
    env = os.environ.get("SQUAD_REPO_VISIBILITY")
    if env:
        return env.upper()
    if _vis_cache["value"] and time.time() - _vis_cache["at"] < 3600:
        return _vis_cache["value"]
    value = "PUBLIC"
    try:
        p = subprocess.run(["gh", "repo", "view", REPO, "--json", "visibility", "-q", ".visibility"],
                           capture_output=True, text=True, timeout=5)
        if p.returncode == 0 and p.stdout.strip():
            value = p.stdout.strip().upper()
    except (OSError, subprocess.TimeoutExpired):
        pass
    _vis_cache.update(at=time.time(), value=value)
    return value


# ================================================================ armazenamento (BugStore → GitDirStore)
class BugStore:
    """Interface estável para a futura troca por NoSQL (ADR-019 §3): bug.json = documento, evidências = blobs."""

    def put_bug(self, kind: str, demand: str, doc: dict, files: list[tuple[str, bytes]]) -> dict: ...
    def add_evidence(self, demand: str, items: list[dict], files: list[tuple[str, bytes]]) -> dict: ...
    def get(self, demand: str) -> dict | None: ...
    def list(self, kind: str) -> list[dict]: ...


class GitDirStore(BugStore):
    def __init__(self, data_root: pathlib.Path):
        self.root = pathlib.Path(data_root)

    def base(self, kind: str) -> pathlib.Path:
        return self.root / "docs/squad" / kind / "bugs"

    def dir_of(self, demand: str) -> pathlib.Path | None:
        if not DEMAND_RE.match(demand or ""):
            return None
        for kind in KINDS:
            d = self.base(kind) / demand
            if (d / "bug.json").is_file():
                return d
        return None

    def put_bug(self, kind, demand, doc, files):
        d = self.base(kind) / demand
        ev = d / "evidencias"
        ev.mkdir(parents=True, exist_ok=False)
        for name, data in files:
            (ev / name).write_bytes(data)
        (d / "bug.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        idx = {"demand": demand, "title": doc.get("title"), "severity": doc.get("severity"),
               "createdAt": doc.get("createdAt"), "dir": doc.get("dir"),
               "source": (doc.get("source") or {}).get("type")}
        with (self.base(kind) / "index.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(idx, ensure_ascii=False) + "\n")
        return doc

    def add_evidence(self, demand, items, files):
        d = self.dir_of(demand)
        doc = json.loads((d / "bug.json").read_text(encoding="utf-8"))
        for name, data in files:
            target = d / "evidencias" / name
            if target.exists():
                raise EvidenceError(409, "evidencia_existente", f"{name} já existe")
            target.write_bytes(data)
        doc["evidences"] = list(doc.get("evidences") or []) + items   # só acrescenta; itens antigos intactos
        (d / "bug.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return doc

    def get(self, demand):
        d = self.dir_of(demand)
        return json.loads((d / "bug.json").read_text(encoding="utf-8")) if d else None

    def list(self, kind):
        from_idx = self.base(kind) / "index.jsonl"
        out = []
        try:
            for line in from_idx.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass
        return out

    def total_size(self, demand: str | None = None) -> int:
        roots = [self.dir_of(demand)] if demand else [self.base(k) for k in KINDS]
        return sum(p.stat().st_size for r in roots if r and r.exists() for p in r.rglob("*") if p.is_file())

    def evidence_path(self, demand: str, name: str) -> pathlib.Path | None:
        d = self.dir_of(demand)
        return safe_child(d / "evidencias", name) if d else None


def safe_child(folder: pathlib.Path, name: str) -> pathlib.Path | None:
    """Arquivo `name` dentro de `folder`, sem `..`, sem link simbólico e sem sair da pasta."""
    if not FILE_RE.match(name or "") or ".." in name:
        return None
    p = folder / name
    if p.is_symlink() or not p.is_file():
        return None
    try:
        p.resolve().relative_to(folder.resolve())
    except ValueError:
        return None
    return p


# ================================================================ rascunhos (.squad/bug-drafts, fora do git)
def drafts_dir(data_root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(data_root) / ".squad/bug-drafts"


def purge_drafts(data_root: pathlib.Path):
    for d in drafts_dir(data_root).glob("*"):
        try:
            meta = json.loads((d / "draft.json").read_text(encoding="utf-8"))
            if time.time() - float(meta.get("createdEpoch", 0)) > DRAFT_TTL_S:
                shutil.rmtree(d, ignore_errors=True)
        except (OSError, json.JSONDecodeError, ValueError):
            if time.time() - d.stat().st_mtime > DRAFT_TTL_S:
                shutil.rmtree(d, ignore_errors=True)


def load_draft(data_root: pathlib.Path, draft: str) -> tuple[pathlib.Path, dict]:
    if not DRAFT_RE.match(str(draft or "")):
        raise EvidenceError(404, "rascunho_expirado", "rascunho inexistente ou expirado; gere a prévia de novo")
    d = drafts_dir(data_root) / draft
    try:
        meta = json.loads((d / "draft.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise EvidenceError(404, "rascunho_expirado", "rascunho inexistente ou expirado; gere a prévia de novo") from None
    if time.time() - float(meta.get("createdEpoch", 0)) > DRAFT_TTL_S:
        shutil.rmtree(d, ignore_errors=True)
        raise EvidenceError(404, "rascunho_expirado", "rascunho expirado (24 h); gere a prévia de novo")
    return d, meta


def draft_file(data_root: pathlib.Path, draft: str, name: str) -> pathlib.Path | None:
    d, _ = load_draft(data_root, draft)
    return safe_child(d / "files", name)


def _process_text(name: str, text: str, origin: str, key: bytes, generated: bool) -> tuple[bytes, dict, list[str]]:
    warns = []
    if generated:
        text, cut = er.truncate_log(text)
        if cut:
            warns.append(f"{name}: log gerado truncado em 1 MB.")
    masked, counts = er.mask_text(text, key)
    return masked.encode("utf-8"), counts, warns


def build_draft(data_root: pathlib.Path, data: dict) -> dict:
    """POST /api/bug/draft: valida, mascara e grava o rascunho. Nada no log nem no git."""
    kind = data.get("kind")
    if kind not in KINDS:
        raise EvidenceError(400, "tipo_obrigatorio", "tipo obrigatório: produto | operacao")
    link = (data.get("link") or "").strip()
    files = data.get("files") or []
    if not isinstance(files, list):
        raise EvidenceError(400, "arquivos_invalidos", "files deve ser uma lista de {name, contentBase64}")
    if not link and not files:
        raise EvidenceError(422, "evidencia_obrigatoria", "informe um link do produtivo ou ao menos um arquivo (log ou imagem)")
    with LOCK:                                      # a chave HMAC é criada uma única vez (sem corrida)
        key = er.load_key(data_root)
    # 1) arquivos enviados (baratos: validados antes de qualquer consulta ao produtivo)
    decoded = []
    for f in files:
        name = str((f or {}).get("name") or "")
        try:
            raw = base64.b64decode((f or {}).get("contentBase64") or "", validate=True)
        except (binascii.Error, ValueError):
            raise EvidenceError(400, "base64_invalido", f"{name or 'arquivo'}: conteúdo base64 inválido") from None
        decoded.append((name, raw))
    er.check_submission([len(r) for _, r in decoded], global_total=GitDirStore(data_root).total_size())
    prepared: list[tuple[str, bytes, dict]] = []   # (nome-base, bytes finais, item)
    warnings: list[str] = []
    for name, raw in decoded:
        info = er.classify(name, raw)
        base = er.sanitize_name(name, er.MAX_NAME - 3)
        if info["type"] == "image":
            clean, n = er.strip_image_metadata(raw)
            prepared.append((base, clean, {"type": "image", "mime": info["mime"], "origin": "upload",
                                           "redactions": {"metadata": n}}))
        else:
            text = raw.decode("utf-8")
            if er.looks_like_test_env(text):
                raise EvidenceError(422, "evidencia_do_teste",
                                    f"{name}: o log é do ambiente de teste (checkout-teste / portas +10000); bug é só do produtivo")
            out, counts, w = _process_text(base, text, "upload", key, generated=False)
            warnings += w
            prepared.append((base, out, {"type": "log", "mime": info["mime"], "origin": "upload", "redactions": counts}))
    # 2) link (extrai só o id; consulta a URL-base fixa do produtivo)
    source, extracted, generated = None, None, []
    if link:
        source = parse_link(link)
        fn = {"jaeger-trace": lambda s: extract_jaeger(s, data.get("includeLogs", True) is not False),
              "grafana-painel": extract_grafana_panel, "grafana-alerta": extract_grafana_alert}[source["type"]]
        extracted, gen, w = fn(source)
        warnings += w
        for name, text, origin in gen:
            out, counts, w2 = _process_text(name, text, origin, key, generated=True)
            warnings += w2
            generated.append((er.sanitize_name(name, er.MAX_NAME - 3), out,
                              {"type": "log", "mime": er.LOG_EXT[".log"], "origin": origin, "redactions": counts}))
    allf = generated + prepared
    if not allf:
        raise EvidenceError(422, "evidencia_obrigatoria", "nenhuma evidência gerada ou enviada")
    # QA-D16-1: o resumo extraído (mensagem da exceção, status do span, títulos de painel/regra), a origem e os
    # avisos são texto livre que vai à prévia e ao bug.json (git público) — mesma máscara dos arquivos
    extracted, source, warnings = (er.mask_obj(extracted, key), er.mask_obj(source, key),
                                   er.mask_obj(warnings, key))
    # QA-D16-2: consultas ao produtivo e máscara acima rodam SEM a trava global; ela só cobre a limpeza de
    # rascunhos vencidos e a criação da pasta (o id do rascunho é aleatório, sem colisão entre requisições)
    with LOCK:
        purge_drafts(data_root)
        draft = secrets.token_hex(16)
        d = drafts_dir(data_root) / draft
        (d / "files").mkdir(parents=True)
    evidences, used = [], set()
    for i, (base, blob, item) in enumerate(allf, 1):
        fname = f"{i:02d}-{base}"
        while fname in used:
            fname = f"{i:02d}-x{fname[3:]}"
        used.add(fname)
        (d / "files" / fname).write_bytes(blob)
        evidences.append({"file": fname, "type": item["type"], "mime": item["mime"].split(";")[0], "size": len(blob),
                          "sha256": er.sha256(blob), "origin": item["origin"], "redactions": item["redactions"]})
    meta = {"draft": draft, "kind": kind, "createdAt": now_iso(), "createdEpoch": time.time(), "source": source,
            "verifiedBy": VERIFIED_BY[(source or {}).get("type")], "extracted": extracted,
            "evidences": evidences, "warnings": warnings}
    (d / "draft.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft_response(d, meta)


def draft_response(d: pathlib.Path, meta: dict) -> dict:
    evs = []
    for ev in meta["evidences"]:
        item = dict(ev)
        if ev["type"] == "log":
            text = (d / "files" / ev["file"]).read_text(encoding="utf-8", errors="replace")
            item["preview"] = "\n".join(text.splitlines()[:PREVIEW_LINES])
        else:
            item["url"] = f"/api/bug/draft/{meta['draft']}/{ev['file']}"
        evs.append(item)
    expires = datetime.fromtimestamp(meta["createdEpoch"] + DRAFT_TTL_S, timezone.utc).isoformat(timespec="seconds")
    return {"draft": meta["draft"], "kind": meta["kind"], "source": meta["source"], "verifiedBy": meta["verifiedBy"],
            "extracted": meta["extracted"], "evidences": evs, "warnings": meta["warnings"], "expiresAt": expires,
            "repoVisibility": repo_visibility()}


def verify_draft(data_root: pathlib.Path, draft: str,
                 remask: bool = True) -> tuple[pathlib.Path, dict, list[tuple[str, bytes]]]:
    """Na confirmação: sha256 de cada arquivo confere e a máscara, reaplicada, não muda nada (defesa em profundidade).
    `remask=False` só confere os sha256 (barato): usado sob a trava depois de uma verificação completa fora dela."""
    d, meta = load_draft(data_root, draft)
    if not meta.get("evidences"):
        raise EvidenceError(422, "evidencia_obrigatoria", "o rascunho não tem evidência (log ou imagem)")
    key = er.load_key(data_root)
    blobs = []
    for ev in meta["evidences"]:
        p = safe_child(d / "files", ev["file"])
        blob = p.read_bytes() if p else b""
        if not p or er.sha256(blob) != ev["sha256"]:
            raise EvidenceError(409, "rascunho_alterado", f"{ev['file']}: o rascunho foi alterado; gere a prévia de novo")
        if not remask:
            blobs.append((ev["file"], blob))
            continue
        er.classify(ev["file"], blob, generated=True)
        if ev["type"] == "log":
            again, _ = er.mask_text(blob.decode("utf-8"), key)
            if again.encode("utf-8") != blob:
                raise EvidenceError(422, "rascunho_alterado", f"{ev['file']}: a revarredura encontrou dados sem máscara")
        else:
            _, n = er.strip_image_metadata(blob)
            if n:
                raise EvidenceError(422, "rascunho_alterado", f"{ev['file']}: a imagem voltou a ter metadados")
        blobs.append((ev["file"], blob))
    # resumo, origem e avisos reapresentados à máscara (rascunhos gravados antes da correção QA-D16-1 incluídos)
    for k in ("extracted", "source", "warnings"):
        if meta.get(k) is not None:
            meta[k] = er.mask_obj(meta[k], key)
    return d, meta, blobs


def check_consent(consent) -> dict:
    c = consent if isinstance(consent, dict) else {}
    if c.get("production") is not True or c.get("public") is not True:
        raise EvidenceError(422, "confirmacao_obrigatoria",
                            "confirmação obrigatória: marque 'ocorreu no produtivo' e 'revisei a prévia e entendo que vai "
                            "para o git público e permanente'")
    return {"production": True, "public": True}


def renumber(files: list[tuple[str, bytes]], items: list[dict], start: int) -> tuple[list, list]:
    out_f, out_i = [], []
    for n, ((name, blob), item) in enumerate(zip(files, items), start):
        new = f"{n:02d}-{name[3:]}"
        out_f.append((new, blob))
        out_i.append({**item, "file": new})
    return out_f, out_i
