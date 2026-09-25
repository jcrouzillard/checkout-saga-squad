#!/usr/bin/env python3
"""Append-only event log da squad (memória episódica compartilhada).

Exemplo:
  python3 tools/squad/log.py --agent backend --type handoff --to qa \
      --title "Saga implementada" --detail "Outbox, retries e retomada" \
      --evidence "Build e testes unitários=pass" --evidence "Concorrência=validate"

Modelo (ADR-012): `--model <ID exato>` ou env `SQUAD_MODEL`; `--run` herda de `SQUAD_RUN` (exportados por
run_agent.py). `SQUAD_LOG=<arquivo>` grava em outro log (testes).
Delegação (D19, ADR-022): `--type delegation` é RECUSADO (código 2; só o servidor grava, na confirmação do humano).
`--delegation <id>` (padrão: $SQUAD_DELEGATION, exportado por run_agent.py --delegation) liga o evento à delegação;
`--change-request <id> --resolution aceita|recusada` num `decision` fecha um change-request; `--refs <id>` = `--ref`.
Executores (D26, ADR-027): `--runner-configured/--model-configured/--config-source/--profile/--fallback` (opcionais)
registram o configurado ao lado do efetivo. Os eventos `executor-*` NÃO passam por aqui (executores.py/servidor).
Passo (D14, ADR-017): `--step "F2 · implementação"` (opcional) em `progress`/`handoff` alimenta o cartão do integrante.
"""
import argparse
import json
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
if (HERE / "product.py").exists():   # D23 (F2a §2): caminho pelo resolvedor ($SQUAD_LOG > $SQUAD_ROOT_DATA > repositório)
    sys.path.insert(0, str(HERE))
    import product
else:                                 # cópia isolada do script (testes antigos): comportamento de antes
    product = None
LOG = pathlib.Path(os.environ.get("SQUAD_LOG") or HERE.parents[1] / "docs/squad/memory/decisions.jsonl")
if product is not None:
    try:
        LOG = product.resolve().log
    except product.ProductError as _e:
        print(f"log.py: {_e}", file=sys.stderr)
        sys.exit(2)
AGENTS = {"humano", "orquestrador", "arquiteto", "backend", "devops", "observabilidade", "qa", "auditor", "frontend"}
TYPES = {"task", "decision", "handoff", "gate", "defect", "change-request", "human", "evidence", "start", "control", "progress", "validation", "clarification", "edit", "review", "delivered", "review-rejected",
         # D15 (ADR-018): ambiente de teste e produtivo — gravados por tools/squad/testenv.py e prod.py
         "test-env-request", "test-env-publishing", "test-env-published", "test-env-failed", "test-env-released",
         "test-env-reset", "prod-updated", "prod-update-failed",
         # D16 (ADR-019): evidência acrescentada a uma demanda de bug — gravado pelo servidor (POST /api/bug/evidence)
         "bug-evidence",
         # D19 (ADR-022): delegação pela conversa — o tipo `delegation` NÃO entra aqui (só o servidor o grava)
         "delegation-start", "delegation-result", "review-updated", "pr-conflict", "pr-conflict-cleared",
         # D24 (ADR-025): publicação do Squad Control — gravados pelo servidor e por tools/squad/publisher.py
         "squad-publish-requested", "squad-updated", "squad-update-failed", "squad-server-crashed"}
DELEGATION_STATUS = {"ok", "falhou", "obsoleta", "recusada", "cancelada"}
# campos obrigatórios por tipo novo (contrato delegacao-pela-conversa §3.2)
REQUIRED = {"delegation-start": ("demand", "delegation", "branch", "to"),
            "delegation-result": ("demand", "delegation", "status"),
            "review-updated": ("demand", "pr", "url", "branch", "sha", "delegation"),
            "pr-conflict": ("demand", "pr", "url", "mergeable"),
            "pr-conflict-cleared": ("demand", "pr", "url", "mergeable")}


def main() -> None:
    argv = sys.argv[1:]
    for i, tok in enumerate(argv):   # D19 §10: só o servidor grava `delegation` (confirmação humana no cartão)
        if tok in ("--type=delegation",) or (tok == "--type" and i + 1 < len(argv) and argv[i + 1] == "delegation"):
            print("log.py: o tipo `delegation` só é gravado pelo servidor na confirmação do humano (ADR-022)",
                  file=sys.stderr)
            sys.exit(2)
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
    p.add_argument("--run", default=os.environ.get("SQUAD_RUN") or None,
                   help="id da execução (tools/squad/run_agent.py); padrão: $SQUAD_RUN")
    p.add_argument("--model", default=os.environ.get("SQUAD_MODEL") or None,
                   help="ID exato do modelo que produziu o evento (ex.: claude-opus-5-5); padrão: $SQUAD_MODEL")
    p.add_argument("--status", choices=["ok", "perguntas", *sorted(DELEGATION_STATUS - {"ok"})],
                   help="resultado da validação agêntica (ok|perguntas) ou da delegação (delegation-result)")
    p.add_argument("--question", action="append", default=[], help='pergunta da validação: "dimensão::texto"')
    p.add_argument("--suggested-kind", choices=["produto", "operacao"])
    p.add_argument("--kind", choices=["produto", "operacao"], help="tipo da demanda")
    p.add_argument("--pr", type=int, help="número do pull request")
    p.add_argument("--url", help="url do pull request")
    p.add_argument("--release", help="versão da release (eventos de release/hotfix)")
    p.add_argument("--merge-commit", help="commit de merge do PR")
    p.add_argument("--runner", help="fornecedor que executou (claude, codex, ...)")
    # D26 (ADR-027, contrato §9.2): configurado × efetivo — opcionais, gravados por run_agent.py
    p.add_argument("--runner-configured", choices=["claude", "codex"], help="executor configurado para o papel")
    p.add_argument("--model-configured", help="modelo configurado (alias, ID ou ausente = padrão do executor)")
    p.add_argument("--config-source", choices=["demanda", "agente", "squad"], help="camada que decidiu o executor")
    p.add_argument("--profile", choices=["leitura", "auditoria", "escrita", "orquestracao"], help="perfil de permissão")
    p.add_argument("--fallback", help='JSON {"reason","from"} quando rodou no padrão por indisponibilidade')
    p.add_argument("--ref", "--refs", dest="ref", action="append", default=[],
                   help="arquivo ou id de evento relacionado (D19: id do handoff pendente)")
    p.add_argument("--delegation", default=os.environ.get("SQUAD_DELEGATION") or None,
                   help="id do evento `delegation` a que este evento pertence (D19); padrão: $SQUAD_DELEGATION")
    p.add_argument("--change-request", help="id do change-request que este `decision` fecha (D19)")
    p.add_argument("--resolution", choices=["aceita", "recusada"], help="desfecho do change-request (D19)")
    p.add_argument("--sha", help="commit (D19: review-updated, pr-conflict-cleared, delegation-result)")
    p.add_argument("--mergeable", choices=["MERGEABLE", "CONFLICTING"], help="estado de merge do PR (D19)")
    p.add_argument("--evidence", action="append", default=[], help="nome=pass|fail|validate")
    p.add_argument("--step", help="passo atual, curto (≤ 40 caracteres), ex.: 'F2 · implementação' (D14, ADR-017)")
    a = p.parse_args()
    if a.step is not None and len(a.step.strip()) > 40:
        p.error("--step deve ter no máximo 40 caracteres")
    if a.status is not None and a.type == "delegation-result" and a.status not in DELEGATION_STATUS:
        p.error("--status de delegation-result: ok|falhou|obsoleta|recusada|cancelada")
    if a.status is not None and a.type != "delegation-result" and a.status not in ("ok", "perguntas"):
        p.error(f"--status {a.status} só vale com --type delegation-result")
    if (a.change_request or a.resolution) and a.type != "decision":
        p.error("--change-request/--resolution só valem com --type decision")
    if bool(a.change_request) != bool(a.resolution):
        p.error("--change-request exige --resolution aceita|recusada (e vice-versa)")
    if a.resolution == "recusada" and not a.detail.strip():
        p.error("--resolution recusada exige a justificativa em --detail")
    if a.type == "pr-conflict" and a.mergeable not in (None, "CONFLICTING"):
        p.error("pr-conflict exige --mergeable CONFLICTING")
    if a.type == "pr-conflict-cleared" and a.mergeable not in (None, "MERGEABLE"):
        p.error("pr-conflict-cleared exige --mergeable MERGEABLE")
    missing = [f for f in REQUIRED.get(a.type, ()) if getattr(a, f) in (None, "")]
    if missing:
        p.error(f"--type {a.type} exige: " + ", ".join("--" + f for f in missing))
    if a.type == "delegation-result" and len(a.detail) > 1500:
        a.detail = a.detail[:1499] + "…"

    fallback = None
    if a.fallback:
        try:
            fallback = json.loads(a.fallback)
        except json.JSONDecodeError:
            p.error("--fallback deve ser JSON")

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
        "model": a.model,
        "runnerConfigured": a.runner_configured,
        "modelConfigured": a.model_configured,
        "configSource": a.config_source,
        "profile": a.profile,
        "fallback": fallback,
        "status": a.status,
        "questions": [{"id": f"q{i}", "dimension": q.split("::", 1)[0].strip() if "::" in q else "escopo",
                       "text": q.split("::", 1)[-1].strip()} for i, q in enumerate(a.question, 1)],
        "suggestedKind": a.suggested_kind,
        "kind": a.kind,
        "pr": a.pr,
        "url": a.url,
        "release": a.release,
        "mergeCommit": a.merge_commit,
        "refs": a.ref,
        "evidences": evidences,
        "step": a.step.strip() if a.step else None,   # opcional: ausente não altera o formato gravado
        # D19 (ADR-022) — ausentes não são gravados
        "delegation": a.delegation,
        "changeRequest": a.change_request,
        "resolution": a.resolution,
        "sha": a.sha,
        "mergeable": a.mergeable,
    }
    entry = {k: v for k, v in entry.items() if v not in (None, [], "")}
    if a.agent == "humano" and a.type == "task" and product is not None:
        # D23 (F2a §4.2): demanda nova nasce com `code`/`code_prefix`, sob trava entre processos (codes.lock)
        try:
            entry = product.append_task(entry, product.resolve().with_log(LOG))
        except product.LockTimeout as e:
            print(f"log.py: {e}", file=sys.stderr)
            sys.exit(1)
        except product.ProductError as e:
            print(f"log.py: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"logged {entry['id']} {a.agent}:{a.type} {a.title} [{entry['code']}]")
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"logged {entry['id']} {a.agent}:{a.type} {a.title}")


if __name__ == "__main__":
    main()
