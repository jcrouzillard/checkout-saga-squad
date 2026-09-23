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
AGENTS = {"humano", "orquestrador", "arquiteto", "backend", "devops", "observabilidade", "qa", "auditor", "frontend"}
TYPES = {"task", "decision", "handoff", "gate", "defect", "change-request", "human", "evidence", "start", "control", "progress", "validation", "clarification", "edit"}


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
    p.add_argument("--demand", help="id do evento da demanda a que este evento pertence")
    p.add_argument("--priority", choices=["alta", "normal", "baixa"])
    p.add_argument("--branch", help="branch git relacionada ao evento")
    p.add_argument("--run", help="id da execução (tools/squad/run_agent.py)")
    p.add_argument("--status", choices=["ok", "perguntas"], help="resultado da validação agêntica")
    p.add_argument("--question", action="append", default=[], help='pergunta da validação: "dimensão::texto"')
    p.add_argument("--suggested-kind", choices=["produto", "operacao"])
    p.add_argument("--kind", choices=["produto", "operacao"], help="tipo da demanda")
    p.add_argument("--runner", help="fornecedor que executou (claude, codex, ...)")
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
        "demand": a.demand,
        "priority": a.priority,
        "branch": a.branch,
        "run": a.run,
        "runner": a.runner,
        "status": a.status,
        "questions": [{"id": f"q{i}", "dimension": q.split("::", 1)[0].strip() if "::" in q else "escopo",
                       "text": q.split("::", 1)[-1].strip()} for i, q in enumerate(a.question, 1)],
        "suggestedKind": a.suggested_kind,
        "kind": a.kind,
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
