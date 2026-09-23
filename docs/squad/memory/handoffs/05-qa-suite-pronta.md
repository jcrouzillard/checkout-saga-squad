# Handoff 05 — QA → Backend/DevOps (aguardando G2) → Jev (G3)

## O que foi feito (test-first, a partir dos contratos)
- `tests/e2e/run.sh`: bash+curl, fallback `jq`→`python3 -c`; espera `/actuator/health` dos 5
  serviços (timeout 180s); `wait_for_status`/`wait_for_stock_value` fazem poll a cada 1s (sem
  sleep fixo longo). Os 7 cenários de `.claude/agents/qa.md`, cada um em `scenario_<nome>()`:
  `happy_path_physical`, `happy_path_digital`, `payment_failure`, `shipping_failure`,
  `timeout_step`, `coordinator_restart` (`docker compose kill/up saga-orchestrator`, checa 1
  única `PAYMENT/SUCCEEDED` no histórico; `SKIP_RESTART=1` pula), `idempotency` (mesmo
  `Idempotency-Key` → mesmo `orderId`, estoque reduz uma vez). Roda um só: `bash tests/e2e/run.sh
  <cenário>`. Gera `tests/e2e/last-report.json` (scenario/status/duração/orderId) e imprime link
  do Jaeger (`tags={"orderId":...}`, serviço `saga-orchestrator`, conforme `observability.md` §5).
- `tests/e2e/scenarios.md`: `curl` manual equivalente de cada cenário + resultado esperado.
- `tests/TRACEABILITY.md`: requisito (desafio §3/6/7) → mecanismo (ADR/contrato) → teste,
  coluna Status = "pendente execução"; seção "Observações" lista lacunas conhecidas (timeout em
  INVENTORY/SHIPPING não tem função dedicada, `TIMEOUT_ONCE` só documentado em `scenarios.md`).

## Validação (sem subir o ambiente — Backend está codando)
- `bash -n tests/e2e/run.sh` → **pass**.
- `shellcheck` (binário local e `koalaman/shellcheck:stable` via Docker) → **pass** (0 findings;
  suprimido só o falso-positivo SC2329 de funções chamadas indiretamente via `"$fn"`).
- Funções puras (`json_get`, `history_has`, `history_count`, `get_header`, parsing do status HTTP)
  testadas isoladamente com JSON de exemplo, nos dois caminhos (`jq` e fallback `python3`) — OK.

## Pendências / riscos
- Nenhuma execução real ainda: depende de `services/**` existir e G2 passar.
- `payload`/asserções usam nomes de campo exatamente como em `docs/contracts/api.md`/`events.md`;
  se o Backend divergir, o teste falhará e deve virar `--type defect --to backend` (não editar o
  teste para "passar").
- Rastreabilidade no Jaeger é só um link impresso (verificação visual no G3).

## Próximo agente
Backend/DevOps concluem G2 → Jev libera execução real de `bash tests/e2e/run.sh` (ou
`make e2e`) → QA atualiza `tests/TRACEABILITY.md` (coluna Status) com o resultado de
`tests/e2e/last-report.json`.
