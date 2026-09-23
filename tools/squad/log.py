#!/usr/bin/env python3
"""Append-only event log da squad (memória episódica compartilhada).

Exemplo:
  python3 tools/squad/log.py --agent backend --type handoff --to qa \
      --title "Saga implementada" --detail "Outbox, retries e retomada" \
      --evidence "Build e testes unitários=pass" --evidence "Concorrência=validate"
"""
import argparse
import json
import pathlib
import uuid
from datetime import datetime, timezone

LOG = pathlib.Path(__file__).resolve().parents[2] / "docs/squad/memory/decisions.jsonl"
AGENTS = {"humano", "orquestrador", "arquiteto", "backend", "devops", "observabilidade", "qa", "jev"}
TYPES = {"task", "decision", "handoff", "gate", "defect", "change-request", "human", "evidence"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True, choices=sorted(AGENTS))
    p.add_argument("--type", required=True, choices=sorted(TYPES))
    p.add_argument("--title", required=True)
    p.add_argument("--detail", default="")
    p.add_argument("--to", choices=sorted(AGENTS))
    p.add_argument("--gate")
    p.add_argument("--recommendation", choices=["APPROVE", "RETURN"])
    p.add_argument("--confidence", type=float)
    p.add_argument("--risk", choices=["baixo", "moderado", "alto"])
    p.add_argument("--ref", action="append", default=[], help="arquivo relacionado")
    p.add_argument("--evidence", action="append", default=[], help="nome=pass|fail|validate")
    a = p.parse_args()

    evidences = []
    for e in a.evidence:
        name, _, status = e.rpartition("=")
        evidences.append({"name": name, "status": status})

    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": a.agent,
        "type": a.type,
        "title": a.title,
        "detail": a.detail,
        "to": a.to,
        "gate": a.gate,
        "recommendation": a.recommendation,
        "confidence": a.confidence,
        "risk": a.risk,
        "refs": a.ref,
        "evidences": evidences,
    }
    entry = {k: v for k, v in entry.items() if v not in (None, [], "")}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"logged {entry['id']} {a.agent}:{a.type} {a.title}")


if __name__ == "__main__":
    main()
