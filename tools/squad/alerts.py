"""Bloqueios, avisos e estado dos agentes — calculados no servidor (D14, ADR-017).

Contrato: docs/contracts/ui-governanca-squad-control.md §5 (regras B1–B4, A1–A3), §7 (integrante), §9 (API).
Nada aqui grava no log: alertas e histórico são reconstruídos do `decisions.jsonl` + `docs/squad/gates/` a cada
mudança desses arquivos (reprodutível para auditoria). Somente stdlib.
"""
import math
import os
import pathlib
import re
import sys
from datetime import datetime, timezone


def _load_product():
    """D23 (F2a): tools/squad/product.py ao lado deste arquivo; None numa cópia isolada do script (testes antigos)."""
    here = pathlib.Path(__file__).resolve().parent
    if not (here / "product.py").exists():
        return None
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import product
    return product


_product = _load_product()

# ---- Limites (§5.3, §9.5) — política: mudar exige atualizar o contrato.
STALLED_S = int(os.environ.get("SQUAD_STALLED_S") or 600)   # A2: sem atividade com turno aberto
STALLED_MAX_S = 3600       # além disso a run é considerada abandonada (sessão morta): sai do A2, vira "parado"
LONG_TOOL_S = 180          # ferramenta pendente >= p99 => "comando longo" no cartão (não é aviso)
WAIT_WARN_S = 600          # espera de ação acima disso fica em --warn
LOW_CONFIDENCE = 0.70      # abaixo: intervenção humana obrigatória (AGENTS.md)
MAX_AUTO_CYCLES = 2        # 3º RETURN escala para o humano
DONE_RECENT_S = 15 * 60    # "Concluiu" por até 15 min
INTERRUPTED_WINDOW_S = 3600
# D19 (ADR-022 §7-iii): A6 — handoff sem continuidade há >= 30 min (ajustável)
HANDOFF_STALLED_S = int(os.environ.get("SQUAD_HANDOFF_STALLED_S") or 1800)
LIVE_TEXT = 160            # truncagem dos textos no /api/live

ROLES = ["orquestrador", "arquiteto", "devops", "observabilidade", "backend", "frontend", "qa", "auditor"]
LABEL = {"orquestrador": "Orquestrador", "arquiteto": "Arquiteto", "devops": "DevOps",
         "observabilidade": "Observabilidade", "backend": "Backend", "frontend": "Frontend", "qa": "QA",
         "auditor": "Auditor", "humano": "Você", "squad": "Squad"}
SEV_RANK = {"bloqueio": 0, "aviso": 1}
KIND_RULE = {"cycle-limit": "B3", "human-required": "B2", "gate-return": "B1", "triage-open": "B4",
             "low-confidence": "A1", "agent-stalled": "A2", "pr-waiting": "A3",
             # D15 (ADR-018, contrato ambiente-de-teste §6)
             "prod-update-failed": "B5", "test-env-failed": "A4", "test-env-divergent": "A5",
             # D19 (ADR-022, contrato delegacao-pela-conversa §5)
             "pr-conflict": "B6", "handoff-stalled": "A6", "change-request-open": "A7"}
KIND_SEV = {"cycle-limit": "bloqueio", "human-required": "bloqueio", "gate-return": "bloqueio",
            "triage-open": "bloqueio", "low-confidence": "aviso", "agent-stalled": "aviso", "pr-waiting": "aviso",
            "prod-update-failed": "bloqueio", "test-env-failed": "aviso", "test-env-divergent": "aviso",
            "pr-conflict": "bloqueio", "handoff-stalled": "aviso", "change-request-open": "aviso"}
GATE_KIND_ORDER = ["cycle-limit", "human-required", "gate-return", "low-confidence"]


def thresholds() -> dict:
    return {"stalledSeconds": STALLED_S, "stalledMaxSeconds": STALLED_MAX_S, "longToolSeconds": LONG_TOOL_S,
            "handoffStalledSeconds": HANDOFF_STALLED_S,
            "waitWarnSeconds": WAIT_WARN_S,
            "lowConfidence": LOW_CONFIDENCE, "maxAutoCycles": MAX_AUTO_CYCLES}


def ts_epoch(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return None


def iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds") if epoch is not None else None


def trunc(text, n=LIVE_TEXT):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def pct(conf) -> int | None:
    return round(conf * 100) if isinstance(conf, (int, float)) else None


def pct_text(conf) -> str | None:
    """Percentual para textos: inteiro, exceto quando o arredondamento esconderia que o valor está abaixo do limite
    (0,695 -> "69,5", nunca "70% < 70%"). D14-QA-1."""
    p = pct(conf)
    if p is None:
        return None
    if is_low(conf) and p >= round(LOW_CONFIDENCE * 100):
        tenths = math.floor(conf * 1000 + 1e-9) / 10   # trunca (0,6996 -> 69,9), como o cliente: nunca "70,0% < 70%"
        return f"{tenths:.1f}".replace(".", ",")
    return str(p)


def is_low(conf) -> bool:
    """Confiança < 70% (AGENTS.md) pelo valor bruto: 0,695 (69,5%) é baixa. A folga de 1e-9 evita que um 0,7 vindo
    de conta de ponto flutuante (0,69999999…) seja tratado como baixo."""
    return isinstance(conf, (int, float)) and conf < LOW_CONFIDENCE - 1e-9


def demand_codes(rows) -> dict:
    """code(demand) — D23 (F2a §4.4): cálculo único `product.demand_codes` (congelado > gravado > posicional).
    Sem product.py ao lado (cópia isolada do script), a regra posicional de antes."""
    if _product is not None:
        return _product.demand_codes(rows)
    out, n = {}, 0
    for e in rows:
        if e.get("type") == "task" and e.get("agent") == "humano" and e.get("id"):
            n += 1
            out[e["id"]] = f"D{n}"
    return out


def _agent_of(value) -> str | None:
    """Primeiro papel reconhecido em `to`/`from` (aceita lista, 'a+b', 'humano (revisão do PR)')."""
    vals = value if isinstance(value, list) else [value]
    for v in vals:
        for tok in re.split(r"[+,/ ]", str(v or "")):
            if tok in ROLES:
                return tok
    return None


# =============================================================== regras B1–B4, A1, A3 (§5.2)
class Rules:
    """Reproduz, evento a evento, a abertura e o fechamento de cada item (histórico §5.4)."""

    def __init__(self, rows: list[dict], gate_files: list[dict]):
        self.rows = rows
        self.codes = demand_codes(rows)
        by_code = {v: k for k, v in self.codes.items()}
        self.files: dict[tuple, list[dict]] = {}
        for f in gate_files:
            d = f.get("demand")
            d = by_code.get(d, d) if d else None
            self.files.setdefault((d, f.get("gate")), []).append(f)
        # estado acumulado durante a reprodução
        self.gates: dict[tuple, list[tuple[int, dict]]] = {}
        self.humans: dict[tuple, list[tuple[int, dict]]] = {}
        self.validations: dict = {}
        self.answered: set = set()
        self.override_start: set = set()
        self.canceled: set = set()
        self.delivered: set = set()
        self.g3_approved: set = set()
        self.reviews: dict = {}          # demand -> [(idx, review)]
        self.pr_closed: set = set()      # (demand, pr)
        self.handoffs: list[tuple[int, dict]] = []
        # D19: último pr-conflict/pr-conflict-cleared por (demanda, PR); change-requests e seus fechamentos
        self.pr_conflict: dict[tuple, dict] = {}
        self.change_requests: dict[str, dict] = {}
        self.cr_closed: dict[str, dict] = {}
        self.open: dict[str, dict] = {}
        self.history: list[dict] = []
        self.gate_meta: dict[str, dict] = {}   # id do evento gate -> {cycle, returns}
        self._run()

    # ---------------- helpers
    def _file_for(self, key, g, position) -> dict | None:
        cands = [f for f in self.files.get(key, []) if f.get("recommendation") == g.get("recommendation")]
        if not cands:
            return None
        same_cycle = [f for f in cands if f.get("cycle") == position]
        pool = same_cycle or cands
        t = ts_epoch(g.get("ts")) or 0
        return min(pool, key=lambda f: abs((f.get("mtime") or 0) - t))

    def _closed(self, d) -> bool:
        if d is None:
            return False
        return d in self.canceled or d in self.delivered or (d in self.g3_approved and not self.reviews.get(d))

    def _where(self, d, tab):
        code = self.codes.get(d) if d else None
        if not d:
            return code, "#/painel/squad-base"
        return code, f"#/demandas/{code or d}/{tab}" if tab else f"#/demandas/{code or d}"

    # ---------------- avaliação de uma chave de gate
    def _eval_gate(self, key, closed: bool = False) -> dict | None:
        gl = self.gates.get(key) or []
        if not gl:
            return None
        d, gname = key
        gi, g = gl[-1]
        hs = self.humans.get(key, [])
        last_h = hs[-1][0] if hs else -1
        after = [h for i, h in hs if i > gi]
        decided = bool(after)
        overridden = any(h.get("recommendation") == "OVERRIDE" for h in after)
        returns = sum(1 for i, x in gl if i > last_h and x.get("recommendation") == "RETURN")
        f = self._file_for(key, g, len(gl))
        cycle = max(len(gl), (f or {}).get("cycle") or 0)
        conf, risk = g.get("confidence"), g.get("risk")
        human_req = bool((f or {}).get("human_required") or g.get("human_required"))
        low = is_low(conf)
        kinds, reasons = [], []
        if g.get("recommendation") == "RETURN" and not overridden:
            kinds.append("gate-return")
        if returns > MAX_AUTO_CYCLES and not decided:
            kinds.append("cycle-limit")
        elif not decided and (human_req or low or risk == "alto"):
            kinds.append("human-required")
        if low and any(h.get("recommendation") in ("APPROVE", "OVERRIDE") for h in after):
            kinds.append("low-confidence")
        if closed:
            # Demanda encerrada (G3 APPROVE sem PR): só a intervenção humana ainda pendente segue aberta (errata
            # G2-D14, §5.1); A1 fecha com o encerramento (§5.2) — D14-QA-2.
            kinds = [k for k in kinds if k in ("human-required", "cycle-limit")]
        if low:
            reasons.append(f"confiança {pct_text(conf)}% < {round(LOW_CONFIDENCE * 100)}%")
        if risk == "alto":
            reasons.append("risco alto")
        if human_req:
            reasons.append("intervenção humana pedida pelo Auditor")
        self.gate_meta.setdefault(g.get("id"), {"cycle": cycle, "returns": returns})  # valor no momento do gate
        if not kinds:
            return None
        kinds.sort(key=GATE_KIND_ORDER.index)
        main = kinds[0]
        origin = _agent_of(g.get("to")) if g.get("to") not in (None, "auditor") else None
        origin = origin or _agent_of((f or {}).get("from")) or next(
            (h.get("agent") for _, h in reversed(self.handoffs)
             if h.get("to") == "auditor" and (h.get("demand") or None) == d), None)
        owner = "humano" if {"cycle-limit", "human-required"} & set(kinds) else (
            origin or "orquestrador") if main == "gate-return" else "squad"
        code, href = self._where(d, "gates")
        who = code or "Squad base"
        c = f" · {pct_text(conf)}%" if pct(conf) is not None else ""
        if main == "cycle-limit":
            title = f"{gname} devolvido {returns} vezes — 3º ciclo"
            rule = f"B3 — {returns} devoluções de {gname} sem decisão humana (máx. {MAX_AUTO_CYCLES} ciclos; AGENTS.md, Limites de autonomia)"
            label = f"Decidir {gname} — 3º ciclo"
        elif main == "human-required":
            title = (f"Auditor devolveu {gname}{c}" if "gate-return" in kinds else f"{gname} exige sua decisão{c}")
            rule = f"B2 — {', '.join(reasons) or 'intervenção obrigatória'} sem decisão humana (AGENTS.md, Limites de autonomia)"
            label = f"Decidir {gname}"
        elif main == "gate-return":
            title = f"Auditor devolveu {gname}{c}"
            rule = f"B1 — último parecer de {gname} é RETURN; {LABEL.get(owner, owner)} corrige e reenvia ao Auditor"
            label = f"Ver parecer de {gname}"
        else:
            title = f"Seguiu com {pct_text(conf)}% em {gname}"
            rule = f"A1 — confiança {pct_text(conf)}% < {round(LOW_CONFIDENCE * 100)}% aceita pelo humano (risco aceito)"
            label = "Ver parecer"
        return {"id": f"{main}:{g.get('id')}", "severity": min((KIND_SEV[k] for k in kinds), key=SEV_RANK.get),
                "kind": main, "kinds": kinds, "rule": rule, "demand": d, "code": code, "gate": gname,
                "cycle": cycle, "returns": returns, "confidence": conf, "risk": risk,
                "title": f"{who} · {title}" if not code else title, "detail": trunc(g.get("detail") or g.get("title"), 300),
                "owner": owner, "agent": origin,
                "action": {"label": label, "href": href, "external": None},
                "source": {"event": g.get("id"), "file": (f or {}).get("file")}}

    def _eval_demand(self, d) -> dict[str, dict]:
        out = {}
        closed = self._closed(d)
        hard_closed = d is not None and (d in self.canceled or d in self.delivered)
        for key in [k for k in self.gates if k[0] == d]:
            # G3 APPROVE sem PR encerra a demanda (is_done), mas o próprio G3 ainda pode exigir decisão humana.
            if hard_closed or (closed and key[1] != "G3"):
                continue
            a = self._eval_gate(key, closed)
            if a:
                out[a["id"]] = a
        if not closed:
            vals = self.validations.get(d) or []
            if d and vals:
                v = vals[-1]
                if v.get("status") == "perguntas" and v.get("id") not in self.answered and d not in self.override_start:
                    n = len(v.get("questions") or [])
                    code, href = self._where(d, "validacao")
                    out[f"triage-open:{v['id']}"] = {
                        "id": f"triage-open:{v['id']}", "severity": "bloqueio", "kind": "triage-open",
                        "kinds": ["triage-open"], "demand": d, "code": code, "gate": None,
                        "rule": "B4 — triagem com perguntas em aberto; a demanda só inicia com respostas ou override com nota",
                        "title": f"{n} pergunta{'s' if n != 1 else ''} da triagem", "detail": trunc(v.get("title"), 300),
                        "owner": "humano", "agent": "arquiteto",
                        "action": {"label": f"Responder {n} pergunta{'s' if n != 1 else ''}", "href": href, "external": None},
                        "source": {"event": v["id"], "file": None}}
        for _, rv in self.reviews.get(d, []):
            if (d, rv.get("pr")) in self.pr_closed or d in self.canceled:
                continue
            code, href = self._where(d, None)
            if not d:
                href = "#/auditoria/eventos?tipo=review"
            pr = rv.get("pr", "?")
            rel = f" · release {rv['release']}" if rv.get("release") else ""
            out[f"pr-waiting:{rv['id']}"] = {
                "id": f"pr-waiting:{rv['id']}", "severity": "aviso", "kind": "pr-waiting", "kinds": ["pr-waiting"],
                "demand": d, "code": code, "gate": None, "pr": rv.get("pr"),
                "rule": "A3 — PR aberto para revisão humana sem `delivered`/`review-rejected` posterior",
                "title": f"PR #{pr} aguardando revisão{rel}", "detail": trunc(rv.get("title"), 300),
                "owner": "humano", "agent": "orquestrador",
                "action": {"label": f"Revisar PR #{pr}", "href": href, "external": rv.get("url")},
                "source": {"event": rv["id"], "file": None}}
            # D19 — B6: último `pr-conflict` deste PR sem `pr-conflict-cleared` posterior (PR ainda em revisão)
            c = self.pr_conflict.get((d, rv.get("pr")))
            if c is not None and c.get("type") == "pr-conflict":
                aid = f"pr-conflict:{c['id']}"
                out[aid] = {
                    "id": aid, "severity": "bloqueio", "kind": "pr-conflict", "kinds": ["pr-conflict"],
                    "demand": d, "code": code, "gate": None, "pr": rv.get("pr"), "branch": rv.get("branch"),
                    "rule": "B6 — `pr-conflict` do PR em revisão sem `pr-conflict-cleared` posterior (ADR-022)",
                    "title": f"PR #{pr} em conflito com a develop", "detail": trunc(c.get("detail") or c.get("title"), 300),
                    "owner": "humano", "agent": "orquestrador",
                    "action": {"label": "Delegar correção", "href": delegate_href(href, aid), "external": None,
                               "pedido": aid},
                    "source": {"event": c["id"], "file": None}}
        if d is not None and not hard_closed and not closed:
            # D19 — A7: change-request com demanda aberta e `to` definido, sem `decision` com changeRequest = id
            for crid, cr in self.change_requests.items():
                if (cr.get("demand") or None) != d or crid in self.cr_closed:
                    continue
                to = _agent_of(cr.get("to"))
                if not to:
                    continue
                code, href = self._where(d, None)
                aid = f"change-request-open:{crid}"
                out[aid] = {
                    "id": aid, "severity": "aviso", "kind": "change-request-open", "kinds": ["change-request-open"],
                    "demand": d, "code": code, "gate": None, "owner": "orquestrador", "agent": to,
                    "rule": "A7 — change-request aberto em demanda ativa, sem `decision` com `changeRequest` (ADR-022)",
                    "title": f"Change-request para {LABEL.get(to, to)} em aberto",
                    "detail": trunc(cr.get("title"), 300),
                    "action": {"label": "Delegar ao dono", "href": delegate_href(href, aid), "external": None,
                               "pedido": aid},
                    "source": {"event": crid, "file": None}}
        return out

    # ---------------- reprodução
    def _apply(self, i, e):
        t, d = e.get("type"), e.get("demand") or None
        if t == "gate" and e.get("gate"):
            self.gates.setdefault((d, e["gate"]), []).append((i, e))
            if e["gate"] == "G3" and e.get("recommendation") == "APPROVE" and d:
                self.g3_approved.add(d)
        elif t == "human" and e.get("gate"):
            self.humans.setdefault((d, e["gate"]), []).append((i, e))
        elif t == "validation" and d:
            self.validations.setdefault(d, []).append(e)
        elif t == "clarification" and e.get("validation"):
            self.answered.add(e["validation"])
        elif t == "start" and d and e.get("override"):
            self.override_start.add(d)
        elif t == "control" and e.get("action") == "cancel" and d:
            self.canceled.add(d)
        elif t == "review":
            self.reviews.setdefault(d, []).append((i, e))
        elif t in ("delivered", "review-rejected"):
            self.pr_closed.add((d, e.get("pr")))
            if t == "delivered" and d:
                self.delivered.add(d)
        elif t == "handoff":
            self.handoffs.append((i, e))
        elif t in ("pr-conflict", "pr-conflict-cleared") and d:
            self.pr_conflict[(d, e.get("pr"))] = e
        elif t == "change-request" and e.get("id"):
            self.change_requests[e["id"]] = e
        elif t == "decision" and e.get("changeRequest"):
            self.cr_closed.setdefault(e["changeRequest"], e)

    def _run(self):
        for i, e in enumerate(self.rows):
            if not isinstance(e, dict):
                continue
            self._apply(i, e)
            if e.get("type") not in ("gate", "human", "validation", "clarification", "start", "control", "review",
                                      "delivered", "review-rejected", "pr-conflict", "pr-conflict-cleared",
                                      "change-request") and not (e.get("type") == "decision" and e.get("changeRequest")):
                continue
            d = e.get("demand") or None
            if e.get("type") == "decision" and e.get("changeRequest") in self.change_requests:
                d = self.change_requests[e["changeRequest"]].get("demand") or None   # fecha o A7 da demanda do CR
            desired = self._eval_demand(d)
            for aid in [aid for aid, a in self.open.items() if a["demand"] == d and aid not in desired]:
                a = self.open.pop(aid)
                self.history.append({**a, "closedAt": e.get("ts"), "closedBy": e.get("agent"),
                                     "closedByEvent": e.get("id")})
            for aid, a in desired.items():
                if aid in self.open:
                    self.open[aid].update({k: v for k, v in a.items()})
                else:
                    self.open[aid] = {**a, "openedAt": e.get("ts")}


# =============================================================== integrantes (§7) e A2
def natural(item: dict | None) -> str:
    """Rótulo natural de uma atividade (§7.4)."""
    if not item:
        return ""
    if item.get("kind") != "tool":
        return trunc((item.get("summary") or "").split("\n")[0])
    tool, s = item.get("tool"), item.get("summary") or ""
    if tool == "Bash":
        return trunc(f"Executando: {s}")
    if tool == "Read":
        return trunc(f"Lendo {s}")
    if tool in ("Edit", "Write", "NotebookEdit"):
        return trunc(f"Editando {s}")
    if tool in ("Grep", "Glob"):
        return trunc(f"Procurando {s}")
    if tool == "Agent":
        return trunc(f"Delegando a {s}")
    if tool == "progress":
        return trunc(f"Marco: {s}")
    if tool in ("AskUserQuestion", "ExitPlanMode"):
        return "Pergunta aberta para você no terminal"
    return trunc(f"{tool} · {s}" if s else tool)


def ready_to_test(rows: list[dict], d: str | None) -> bool:
    """D15: "Pronto para testar" = último evento do ambiente de teste da demanda é `test-env-published`."""
    if not d:
        return False
    last = next((e.get("type") for e in reversed(rows) if e.get("demand") == d and e.get("type") in
                 ("test-env-publishing", "test-env-published", "test-env-failed", "test-env-released")), None)
    return last == "test-env-published"


def stage_of(rules: Rules, rows: list[dict], d: str | None) -> str | None:
    if not d:
        return None
    if d in rules.delivered:
        return "Entregue"
    if d in rules.canceled:
        return "Cancelada"
    if any((d, rv.get("pr")) not in rules.pr_closed for _, rv in rules.reviews.get(d, [])):
        return "Pronto para testar" if ready_to_test(rows, d) else "Revisão (PR)"
    if any(k[0] == d for k in rules.gates):
        return "Gates"
    evs = [e for e in rows if e.get("demand") == d]
    if any(e.get("agent") not in ("humano", None) and e.get("type") in ("handoff", "progress", "task") for e in evs):
        return "Execução"
    if any(e.get("type") == "start" for e in evs):
        return "Na fila"
    if any(e.get("type") == "validation" for e in evs):
        return "Validação"
    return "Registrada"


def step_of(role, rules, rows, d) -> str | None:
    if not d:
        return None
    ev = next((e for e in reversed(rows) if e.get("agent") == role and e.get("demand") == d
               and e.get("type") in ("progress", "handoff") and e.get("step")), None)
    if ev:
        return ev["step"]
    if role == "arquiteto":
        started = any(e.get("type") == "start" and e.get("demand") == d for e in rows)
        return "F1 · contrato" if started else "Triagem"
    if role in ("backend", "devops", "observabilidade", "frontend"):
        return "F2 · implementação"
    if role == "qa":
        return "F3 · validação"
    if role == "auditor":
        return f"G{next_gate(rules, d)[1:]} · parecer"
    if role == "orquestrador":
        return stage_of(rules, rows, d)
    return None


def next_gate(rules: Rules, d) -> str:
    approved = {k[1] for k, gl in rules.gates.items() if k[0] == d and gl and gl[-1][1].get("recommendation") == "APPROVE"}
    return f"G{min(3, len(approved) + 1)}"


def _run_age(run, now):
    return now - run["_last"] if run.get("_last") is not None else None


def stalled_alert(run, now, codes) -> dict | None:
    """A2 (§5.2): run não encerrada sem atividade há >= STALLED_S; ou run externa interrompida na última hora."""
    age = _run_age(run, now)
    if age is None:
        return None
    role = run.get("agent")
    lab = LABEL.get(role, role)
    d = run.get("demand")
    base = {"id": f"agent-stalled:{run['id']}", "severity": "aviso", "kind": "agent-stalled", "kinds": ["agent-stalled"],
            "demand": d, "code": codes.get(d) if d else None, "gate": None, "agent": role, "runId": run["id"],
            # D19: início e delegação da run (chave estável do agente parado; run delegada não é delegável)
            "runStartedAt": run.get("started"), "delegation": run.get("delegation"),
            "action": {"label": "Ver integrante", "href": f"#/squad?agente={role}", "external": None},
            "source": {"event": None, "run": run["id"], "file": None}}
    if run.get("status") == "interrompido" and age < INTERRUPTED_WINDOW_S:
        return {**base, "owner": "orquestrador", "openedAt": iso(run["_last"]),
                "title": f"{lab} interrompido (processo encerrado sem finalizar)",
                "rule": "A2 — execução do run_agent.py com processo morto sem 'Finalizado' (última hora); retomar a tarefa",
                "detail": trunc(run.get("description"), 300)}
    if run.get("_open") and STALLED_S <= age < STALLED_MAX_S:
        mins = int(age // 60)
        return {**base, "owner": "orquestrador" if run.get("runner") and run.get("_external") else "humano",
                "openedAt": iso(run["_last"] + STALLED_S),
                "title": f"{lab} sem progresso há {mins} min",
                "rule": f"A2 — turno aberto sem atividade há {mins} min (limite {STALLED_S // 60} min, p99,9 das ferramentas);"
                        " verifique o terminal/permissão" if not run.get("_external") else
                        f"A2 — execução externa sem atividade há {mins} min (limite {STALLED_S // 60} min); retomar",
                "detail": trunc(run.get("description"), 300)}
    return None


def sort_alerts(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda a: (SEV_RANK[a["severity"]], a.get("owner") != "humano", a.get("openedAt") or ""))


def build_agents(runs: list[dict], rules: Rules, rows: list[dict], gate_alerts: list[dict], now: float,
                 orch: dict | None) -> tuple[list[dict], list[dict]]:
    """Estado por papel (§7) + alertas A2. `orch` = pendências da sessão principal atual do Orquestrador."""
    codes = rules.codes
    stalled = {}
    for r in runs:
        a = stalled_alert(r, now, codes)
        if a:
            stalled[r["id"]] = a
            r["_stalled"] = True
    all_open = gate_alerts + list(stalled.values())
    progress_by = {}
    for e in rows:
        if e.get("type") == "progress" and e.get("agent"):
            progress_by[e["agent"]] = e
    handoffs = [e for e in rows if e.get("type") == "handoff"]
    gates_after = {}
    for i, e in enumerate(rows):
        if e.get("type") == "gate":
            gates_after[e.get("demand") or None] = i
    run_by_id = {r["id"]: r for r in runs}

    def active(r):
        age = _run_age(r, now)
        return bool(r.get("_open")) and age is not None and age < STALLED_MAX_S

    def pending_handoff(role=None):
        """Último handoff (do papel, se dado) para o Auditor sem gate posterior na demanda (não encerrada)."""
        for idx in range(len(rows) - 1, -1, -1):
            e = rows[idx]
            if e.get("type") != "handoff" or e.get("to") != "auditor":
                continue
            if role and e.get("agent") != role:
                continue
            d = e.get("demand") or None
            if d and rules._closed(d):
                return None
            if gates_after.get(d, -1) > idx:
                return None
            return e
        return None

    agents = []
    for role in ROLES:
        mine = [r for r in runs if r.get("agent") == role]
        live = [r for r in mine if active(r)]
        pool = live or mine
        cur = max(pool, key=lambda r: r.get("_last") or 0) if pool else None
        d = (cur or {}).get("demand")
        if role == "orquestrador" and orch:
            d = orch.get("demand") or d
        waits = []
        # --- esperas (§7.4)
        subs = []
        if role == "orquestrador" and orch:
            for s in orch.get("subagents", []):
                sub_run = run_by_id.get(s["runId"])
                subs.append({"agent": s.get("agent") or (sub_run or {}).get("agent") or "outro",
                             "description": trunc(s.get("description")), "since": s.get("since"), "runId": s["runId"]})
            if orch.get("ask"):
                waits.append({"on": ["humano"], "reason": "Pergunta aberta para você no terminal",
                              "since": orch["ask"], "alert": None, "action": None})
            human_items = [a for a in sort_alerts(all_open) if a.get("owner") == "humano"]
            if human_items:
                a = human_items[0]
                waits.append({"on": ["humano"], "reason": a["action"]["label"] + (f" ({a['code']})" if a.get("code") else ""),
                              "since": a.get("openedAt"), "alert": a["id"], "action": a["action"]})
            if subs:
                roles_on = list(dict.fromkeys(s["agent"] for s in subs))
                first = min(subs, key=lambda s: s.get("since") or "")
                waits.append({"on": roles_on, "reason": f"Aguardando {LABEL.get(first['agent'], first['agent'])}: {first['description']}"
                              + (f" (+{len(subs) - 1})" if len(subs) > 1 else ""),
                              "since": first.get("since"), "alert": None, "action": None})
        else:
            if d:
                blk = [a for a in sort_alerts(gate_alerts) if a.get("demand") == d and a.get("owner") == "humano"
                       and a["severity"] == "bloqueio"]
                if blk:
                    a = blk[0]
                    waits.append({"on": ["humano"], "reason": a["action"]["label"], "since": a.get("openedAt"),
                                  "alert": a["id"], "action": a["action"]})
            if not live:
                b1 = next((a for a in gate_alerts if a["kind"] == "gate-return" and a.get("owner") == role), None)
                if b1:
                    waits.append({"on": ["orquestrador"], "reason": f"Aguardando reenvio da correção de {b1['gate']}",
                                  "since": b1.get("openedAt"), "alert": b1["id"], "action": None})
            h = pending_handoff(role)
            if h:
                waits.append({"on": ["auditor"], "reason": f"Aguardando parecer do Auditor ({next_gate(rules, h.get('demand'))})",
                              "since": h.get("ts"), "alert": None, "action": None})
            if role == "auditor" and not live:
                h = pending_handoff()
                if h:
                    waits.append({"on": ["orquestrador"],
                                  "reason": f"Aguardando delegação da avaliação de {next_gate(rules, h.get('demand'))}",
                                  "since": h.get("ts"), "alert": None, "action": None})
        waiting = None
        if waits:
            on = list(dict.fromkeys(x for w in waits for x in w["on"]))
            waiting = {**waits[0], "on": on}
            if waiting.get("since"):
                w_age = now - (ts_epoch(waiting["since"]) or now)
                waiting["ageSeconds"] = int(w_age)
                waiting["warn"] = w_age > WAIT_WARN_S
        # --- estado (§7.3)
        age = _run_age(cur, now) if cur else None
        if cur and cur.get("status") == "interrompido" and age is not None and age < INTERRUPTED_WINDOW_S:
            state = "interrompido"
        elif cur and cur.get("_stalled"):
            state = "sem-progresso"
        elif cur and (active(cur) and age < STALLED_S or (role == "orquestrador" and subs)):
            state = "trabalhando"
        elif waiting:
            state = "aguardando"
        elif cur and age is not None and age < DONE_RECENT_S:
            state = "concluido"
        else:
            state = "ocioso"
        cur_item = None
        if cur and state in ("trabalhando", "sem-progresso"):
            p = cur.get("_current")
            if p:
                since = ts_epoch(p.get("ts"))
                dur = now - since if since else 0
                cur_item = {"tool": p.get("tool"), "label": natural(p),
                            "target": trunc(p.get("detail") or p.get("summary"), 200), "since": p.get("ts"),
                            "long": dur >= LONG_TOOL_S, "seconds": int(dur)}
        last_items = (cur or {}).get("activity") or []
        prog = progress_by.get(role)
        last_at = max([x for x in [(cur or {}).get("_last"), ts_epoch((prog or {}).get("ts"))] if x is not None],
                      default=None)
        recent_cmds = []
        for c in reversed((cur or {}).get("_commands") or []):
            it = c["item"]
            recent_cmds.append({"ts": it.get("ts"), "label": trunc(c.get("label") or it.get("summary")),
                                "command": c["command"], "error": bool(it.get("error")), "pending": bool(it.get("pending"))})
        linked = [a["id"] for a in sort_alerts(all_open) if a.get("agent") == role or a.get("owner") == role
                  or (cur and a.get("runId") == cur["id"])]
        agents.append({
            "agent": role, "state": state, "runId": (cur or {}).get("id"),
            "runner": (cur or {}).get("runner") or ("claude" if cur else None),
            "model": (cur or {}).get("model"), "modelProvider": (cur or {}).get("modelProvider"),
            "task": {"description": trunc((cur or {}).get("description")) or (
                         "Coordenação da squad (sessão principal)" if role == "orquestrador" else ""), "demand": d, "code": codes.get(d) if d else None,
                     "step": step_of(role, rules, rows, d), "startedAt": (cur or {}).get("started")} if cur else None,
            "current": cur_item,
            "lastActivityAt": iso(last_at), "ageSeconds": int(now - last_at) if last_at else None,
            "lastActivity": natural(last_items[-1]) if last_items else (trunc(prog["title"]) if prog else None),
            "lastProgress": {"ts": prog["ts"], "title": trunc(prog.get("title")), "step": prog.get("step")} if prog else None,
            "recentFiles": list(reversed(((cur or {}).get("files") or [])[-10:])),
            "recentCommands": recent_cmds[:5],
            "recent": [dict(x) for x in last_items[-20:]],
            "waiting": waiting,
            "subagents": subs if role == "orquestrador" else [],
            "toolCount": (cur or {}).get("toolCount", 0), "alerts": linked,
        })
        if cur is not None:
            cur["_waitingOn"] = (waiting or {}).get("on", [])
    return agents, list(stalled.values())


def summary(alerts: list[dict], agents: list[dict]) -> dict:
    return {"bloqueios": sum(a["severity"] == "bloqueio" for a in alerts),
            "avisos": sum(a["severity"] == "aviso" for a in alerts),
            "voce": sum(a.get("owner") == "humano" for a in alerts),
            "trabalhando": sum(a["state"] == "trabalhando" for a in agents),
            "aguardando": sum(a["state"] == "aguardando" for a in agents),
            "semProgresso": sum(a["state"] == "sem-progresso" for a in agents)}


def with_age(alerts: list[dict], now: float) -> list[dict]:
    out = []
    for a in alerts:
        t = ts_epoch(a.get("openedAt"))
        out.append({**a, "ageSeconds": int(now - t) if t else None})
    return out


def compact_agent(a: dict) -> dict:
    """Versão do /api/live: sem `recent` (linha do tempo fica no /api/state) e textos truncados."""
    out = {k: v for k, v in a.items() if k != "recent"}
    out["recentCommands"] = [{**c, "command": trunc(c["command"], LIVE_TEXT)} for c in a["recentCommands"]]
    if out.get("current"):
        out["current"] = {**out["current"], "target": trunc(out["current"].get("target"), LIVE_TEXT)}
    return out


# =============================================================== D15: B5, A4, A5 (contrato ambiente-de-teste §6)
def env_alerts(rows: list[dict], test_env: dict | None, codes: dict | None = None) -> list[dict]:
    """B5 `prod-update-failed` sem `prod-updated` posterior (humano); A4 falha ao publicar do ocupante;
    A5 ambiente de teste divergente (log diz ocupado, containers não saudáveis)."""
    codes = codes if codes is not None else demand_codes(rows)
    out = []
    last_prod = next((e for e in reversed(rows) if e.get("type") in ("prod-updated", "prod-update-failed")), None)
    if last_prod and last_prod.get("type") == "prod-update-failed":
        svcs = ", ".join(last_prod.get("services") or []) or "—"
        rb = "revertido para a imagem anterior" if last_prod.get("rolledBack") else "SEM rollback automático"
        out.append({"id": f"prod-update-failed:{last_prod.get('id')}", "severity": "bloqueio",
                    "kind": "prod-update-failed", "kinds": ["prod-update-failed"], "demand": None, "code": None,
                    "gate": None, "owner": "humano", "agent": "orquestrador",
                    "rule": "B5 — atualização do produtivo falhou sem `prod-updated` posterior (ADR-018 §8)",
                    "title": f"Produtivo não atualizado ({last_prod.get('phase')}) · {rb}",
                    "detail": trunc(f"serviços: {svcs} · {last_prod.get('detail') or ''}", 300),
                    "action": {"label": "Ver falha do produtivo", "href": "#/auditoria/eventos?tipo=prod-update-failed",
                               "external": None},
                    "openedAt": last_prod.get("ts"), "source": {"event": last_prod.get("id"), "file": None}})
    te = test_env or {}
    d = te.get("demand")
    code = codes.get(d) if d else None
    href = f"#/demandas/{code or d}" if d else "#/painel"
    if te.get("state") == "falhou" and te.get("lastError"):
        err = te["lastError"]
        hint = " · sugestão: apagar dados do teste" if err.get("hint") == "reset-data" else ""
        out.append({"id": f"test-env-failed:{d}:{err.get('at')}", "severity": "aviso", "kind": "test-env-failed",
                    "kinds": ["test-env-failed"], "demand": d, "code": code, "gate": None, "owner": "humano",
                    "agent": "orquestrador", "rule": "A4 — `test-env-failed` do ocupante do ambiente de teste",
                    "title": f"Falha ao publicar no teste ({err.get('phase')}){hint}",
                    "detail": trunc(err.get("detail"), 300),
                    "action": {"label": "Tentar de novo", "href": href, "external": None},
                    "openedAt": err.get("at"), "source": {"event": None, "file": None}})
    if te.get("state") == "divergente":
        bad = [k for k, v in (te.get("health") or {}).items()
               if v.get("state") != "running" or v.get("health") not in ("healthy", None)]
        out.append({"id": f"test-env-divergent:{d}", "severity": "aviso", "kind": "test-env-divergent",
                    "kinds": ["test-env-divergent"], "demand": d, "code": code, "gate": None, "owner": "humano",
                    "agent": "orquestrador",
                    "rule": "A5 — ambiente de teste ocupado no log, mas containers do checkout-teste não saudáveis",
                    "title": "Ambiente de teste divergente",
                    "detail": trunc("não saudáveis: " + (", ".join(bad) or "nenhum container no ar"), 300),
                    "action": {"label": "Republicar", "href": href, "external": None},
                    "openedAt": te.get("publishedAt"), "source": {"event": None, "file": None}})
    return out


# =============================================================== D19: A6, delegações (ADR-022, contrato §3.4, §5)
def delegate_href(href: str, aid: str) -> str:
    """Ação dos alertas delegáveis: abre a conversa nova com o pedido pré-preenchido (sem enviar)."""
    return f"{href}?conversa=nova&pedido={aid}"


def paused_demands(rows: list[dict]) -> set:
    last = {}
    for e in rows:
        if e.get("type") == "control" and e.get("demand") and e.get("action") in ("pause", "resume"):
            last[e["demand"]] = e["action"]
    return {d for d, a in last.items() if a == "pause"}


def handoff_alerts(rows: list[dict], rules: Rules, runs: list[dict], now: float) -> list[dict]:
    """A6: último `handoff` (com `to` e `demand`) de cada (demanda, to) sem evento do `to` na demanda depois dele,
    há >= HANDOFF_STALLED_S, sem run aberta do `to` na demanda, demanda aberta e não pausada. Reavaliado com o relógio
    (como o A2), só a partir do log e das runs."""
    paused = paused_demands(rows)
    last: dict[tuple, tuple[int, dict]] = {}
    for i, e in enumerate(rows):
        if not isinstance(e, dict) or e.get("type") != "handoff" or not e.get("demand"):
            continue
        to = _agent_of(e.get("to"))
        if to and to != e.get("agent"):
            last[(e["demand"], to)] = (i, e)
    out = []
    for (d, to), (i, h) in last.items():
        if rules._closed(d) or d in paused or d not in rules.codes:
            continue
        if any(x.get("agent") == to and (x.get("demand") or None) == d for x in rows[i + 1:] if isinstance(x, dict)):
            continue
        t = ts_epoch(h.get("ts"))
        if t is None or now - t < HANDOFF_STALLED_S:
            continue
        if any(r.get("agent") == to and r.get("demand") == d and r.get("_open")
               and (_run_age(r, now) or 0) < STALLED_MAX_S for r in runs):
            continue
        code, href = rules._where(d, None)
        aid = f"handoff-stalled:{h['id']}"
        mins = int((now - t) // 60)
        out.append({"id": aid, "severity": "aviso", "kind": "handoff-stalled", "kinds": ["handoff-stalled"],
                    "demand": d, "code": code, "gate": None, "owner": "orquestrador", "agent": to,
                    "to": to, "from": h.get("agent"),
                    "rule": f"A6 — handoff para {LABEL.get(to, to)} sem continuidade há {mins} min "
                            f"(limite {HANDOFF_STALLED_S // 60} min, SQUAD_HANDOFF_STALLED_S)",
                    "title": f"Handoff para {LABEL.get(to, to)} sem continuidade há {mins} min",
                    "detail": trunc(h.get("title"), 300),
                    "action": {"label": "Delegar continuidade", "href": delegate_href(href, aid), "external": None,
                               "pedido": aid},
                    "openedAt": iso(t + HANDOFF_STALLED_S), "source": {"event": h["id"], "file": None}})
    return out


DELEGATION_DONE = {"ok": "concluida", "falhou": "falhou", "obsoleta": "obsoleta", "recusada": "recusada",
                   "cancelada": "cancelada"}


def delegations_of(rows: list[dict], demand: str | None = None) -> list[dict]:
    """Estado derivado de cada `delegation` (§3.4): pedida → em-execucao → aguardando-gate → concluida/falhou/…
    Mais antiga primeiro; `events` = eventos com `delegation` = id."""
    out, by_id = [], {}
    for e in rows:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "delegation" and e.get("id") and (demand is None or e.get("demand") == demand):
            item = {"id": e["id"], "ts": e.get("ts"), "demand": e.get("demand"), "category": e.get("category"),
                    "target": e.get("target"), "owner": e.get("owner"), "risk": e.get("risk"),
                    "attempt": e.get("attempt"), "attemptKey": e.get("attemptKey"), "title": e.get("title"),
                    "task": e.get("detail"), "pr": e.get("pr"), "branch": e.get("branch"), "run": e.get("run"),
                    "via": e.get("via"), "proposal": e.get("proposal"), "state": "pedida", "startedAt": None,
                    "endedAt": None, "result": None, "events": [], "_pendingGate": False}
            by_id[e["id"]] = item
            out.append(item)
            continue
        item = by_id.get(e.get("delegation"))
        if item is None:
            continue
        item["events"].append({"id": e.get("id"), "ts": e.get("ts"), "agent": e.get("agent"), "type": e.get("type"),
                               "title": trunc(e.get("title"))})
        t = e.get("type")
        if item["result"] is not None:
            continue
        if t == "delegation-start":
            item["startedAt"] = item["startedAt"] or e.get("ts")
            item["state"] = "em-execucao"
        elif t == "delegation-result":
            item["endedAt"] = e.get("ts")
            item["result"] = {"status": e.get("status"), "detail": e.get("detail"), "pr": e.get("pr"),
                              "sha": e.get("sha")}
            item["state"] = DELEGATION_DONE.get(e.get("status"), "falhou")
        elif t == "handoff" and e.get("to") == "auditor":
            item["_pendingGate"] = True
            if item["state"] in ("em-execucao", "pedida"):
                item["state"] = "aguardando-gate"
        elif t == "gate":
            item["_pendingGate"] = False
            if item["state"] == "aguardando-gate":
                item["state"] = "em-execucao"
    for item in out:
        item.pop("_pendingGate", None)
    return out


def active_delegation(rows: list[dict], demand: str) -> dict | None:
    """Delegação ativa da demanda (sem `delegation-result`): no máximo uma (§2)."""
    act = [x for x in delegations_of(rows, demand) if x["result"] is None]
    return act[-1] if act else None
