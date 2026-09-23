#!/usr/bin/env python3
"""Lista o que o plantão do Orquestrador precisa tratar. Código de saída 0 = há trabalho; 1 = nada pendente."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
rows = [json.loads(l) for l in (ROOT / "docs/squad/memory/decisions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
pending = []
for f in sorted((ROOT / "docs/squad/inbox").glob("*.json")):
    pending.append(f"fila: {f.name}")
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
