#!/usr/bin/env python3
"""Lista o que o plantão do Orquestrador precisa tratar. Código de saída 0 = há trabalho; 1 = nada pendente."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
rows = [json.loads(l) for l in (ROOT / "docs/squad/memory/decisions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
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
RANK = {"alta": 0, "normal": 1, "baixa": 2}
queue = []
for f in (ROOT / "docs/squad/inbox").glob("*.json"):
    try:
        item = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        item = {}
    queue.append((RANK.get(item.get("priority", "normal"), 1), item.get("startedAt", ""), f.name, item.get("priority", "normal")))
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
print("\n".join(pending) or "nada pendente")
sys.exit(0 if pending else 1)
