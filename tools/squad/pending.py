#!/usr/bin/env python3
"""Lista o que o plantão do Orquestrador precisa tratar. Código de saída 0 = há trabalho; 1 = nada pendente.

D19 (ADR-022): a consulta de cada PR em revisão traz `state` e `mergeable` na MESMA chamada (`gh pr view --json
state,mergeable`, no máximo 1 por PR a cada 30 s); lista `conflito de PR`/`conflito resolvido` pela transição em relação
ao último `pr-conflict`/`pr-conflict-cleared` do PR no log, e `delegação: <id> · <tipo> · <código>` para cada
`delegation` ainda não iniciada de demanda não pausada. Testes: `SQUAD_ROOT_DATA`/`SQUAD_LOG` e `gh` simulado no PATH.
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(os.environ.get("SQUAD_ROOT_DATA") or pathlib.Path(__file__).resolve().parents[2])
LOG = pathlib.Path(os.environ.get("SQUAD_LOG") or ROOT / "docs/squad/memory/decisions.jsonl")
rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
pending = []
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
for d in [r for r in rows if r.get("type") == "task" and r.get("agent") == "humano" and r.get("kind") and not r.get("backlog")]:
    rel = [r for r in rows if r.get("demand") == d["id"]]
    if any(r.get("type") in ("validation", "start") for r in rel) or any(r.get("type") == "control" and r.get("action") == "cancel" for r in rel):
        continue
    busy = [r for r in rel if r.get("type") == "progress" and r.get("agent") == "arquiteto"
            and now - datetime.fromisoformat(r["ts"]) < timedelta(minutes=5)]
    if not busy:
        pending.append(f"validação: {d['id']}")
# D19 §8.2: delegações confirmadas pelo humano e ainda não iniciadas (depois das validações, antes da fila C)
codes = {}
if (pathlib.Path(__file__).resolve().parent / "product.py").exists():   # D23 (F2a §4.4): cálculo único
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import product
    codes = product.demand_codes(rows)
else:   # cópia isolada do script (testes antigos): a regra posicional de antes
    n = 0
    for r in rows:
        if r.get("type") == "task" and r.get("agent") == "humano" and r.get("id"):
            n += 1
            codes[r["id"]] = f"D{n}"
paused = {}
for r in rows:
    if r.get("type") == "control" and r.get("demand") and r.get("action") in ("pause", "resume"):
        paused[r["demand"]] = r["action"] == "pause"
canceled_d = {r.get("demand") for r in rows if r.get("type") == "control" and r.get("action") == "cancel"}
for dl in [r for r in rows if r.get("type") == "delegation"]:
    linked = [r for r in rows if r.get("delegation") == dl["id"]]
    ended = any(r.get("type") == "delegation-result" for r in linked)
    started = any(r.get("type") == "delegation-start" for r in linked)
    if ended:
        continue
    if dl.get("demand") in canceled_d:
        pending.append(f"delegação cancelada: {dl['id']} · {dl.get('category')} · {codes.get(dl.get('demand'), '?')}")
    elif not started and not paused.get(dl.get("demand")):
        pending.append(f"delegação: {dl['id']} · {dl.get('category')} · {codes.get(dl.get('demand'), '?')}")
RANK = {"alta": 0, "normal": 1, "baixa": 2}
queue = []
for f in (ROOT / "docs/squad/inbox").glob("*.json"):
    try:
        item = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        item = {}
    # prioridade efetiva = última repriorização humana da demanda, senão a do início (contrato D5 §2.6)
    repri = [r for r in rows if r.get("type") == "control" and r.get("action") == "reprioritize"
             and r.get("demand") == item.get("demand") and r.get("priority")]
    pri = repri[-1]["priority"] if repri else item.get("priority", "normal")
    queue.append((RANK.get(pri, 1), item.get("startedAt", ""), f.name, pri))
queue.sort()
for i, (_, _, name, pri) in enumerate(queue, 1):
    pending.append(f"fila {i}/{len(queue)}: {name} · {pri}")
handled_ctl = {r.get("demand") for r in rows if r.get("agent") == "orquestrador" and "cancelada" in r.get("title", "")}
for c in [r for r in rows if r.get("type") == "control" and r.get("action") == "cancel" and r.get("demand") not in handled_ctl]:
    pending.append(f"cancelamento: {c['demand']}")
for g in [r for r in rows if r.get("type") == "gate" and r.get("recommendation") == "RETURN" and r.get("demand")]:
    later = [r for r in rows if r["ts"] > g["ts"] and r.get("demand") == g["demand"]]
    hum = [r for r in later if r.get("type") == "human" and r.get("gate") == g["gate"]]
    if hum and not [r for r in later if r.get("agent") == "orquestrador" and r["ts"] > hum[-1]["ts"]]:
        pending.append(f"decisão humana: {g['gate']} de {g['demand']} → {hum[-1].get('recommendation')}")
# D8: PR em revisão humana integrado ou fechado → o plantão registra o desfecho (review-sync / release-publish)
import subprocess
open_reviews = [r for r in rows if r.get("type") == "review"
                and not any(x.get("type") in ("delivered", "review-rejected") and x.get("url") == r.get("url") for x in rows)]
cache_file = ROOT / ".squad/pr-state.json"  # o vigia roda a cada 3 s: consulta cada PR no GitHub no máximo a cada 30 s
try:
    cache = json.loads(cache_file.read_text())
except (OSError, json.JSONDecodeError):
    cache = {}
for r in open_reviews:
    hit = cache.get(r["url"])
    if hit and hit["state"] == "OPEN" and now.timestamp() - hit["at"] < 30:
        state, mergeable = hit["state"], hit.get("mergeable", "UNKNOWN")
    else:
        # D19: `mergeable` sai da MESMA chamada (sem requisição extra); UNKNOWN = GitHub ainda calculando
        out = subprocess.run(["gh", "pr", "view", r["url"], "--json", "state,mergeable"], capture_output=True, text=True)
        try:
            info = json.loads(out.stdout or "{}")
        except json.JSONDecodeError:
            info = {}
        state = info.get("state") or (hit or {}).get("state", "OPEN")
        mergeable = info.get("mergeable") or "UNKNOWN"
        cache[r["url"]] = {"state": state, "mergeable": mergeable, "at": now.timestamp()}
    what = f"demanda {r['demand']}" if r.get("demand") else f"release {r.get('release')}"
    if state == "OPEN" and r.get("demand") and str(r.get("branch", "")).startswith("feature/"):
        marks = [x for x in rows if x.get("type") in ("pr-conflict", "pr-conflict-cleared")
                 and (x.get("url") == r["url"] or (x.get("demand") == r["demand"] and x.get("pr") == r.get("pr")))]
        in_conflict = bool(marks) and marks[-1]["type"] == "pr-conflict"
        if mergeable == "CONFLICTING" and not in_conflict:
            pending.append(f"conflito de PR: {what} (PR #{r.get('pr')})")
        elif mergeable == "MERGEABLE" and in_conflict:
            pending.append(f"conflito resolvido: {what} (PR #{r.get('pr')})")
    if state == "MERGED":
        pending.append(f"{'release pronta' if r.get('release') and not r['release'].endswith('back-merge') else 'revisão integrada'}: {what} (PR #{r.get('pr')})")
    elif state == "CLOSED":
        pending.append(f"revisão recusada: {what} (PR #{r.get('pr')})")
try:
    cache_file.parent.mkdir(exist_ok=True)
    cache_file.write_text(json.dumps(cache))
except OSError:
    pass
print("\n".join(pending) or "nada pendente")
sys.exit(0 if pending else 1)
