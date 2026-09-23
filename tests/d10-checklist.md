# D10 — Checklist do QA (demanda `f2324e0f25de`)

Contrato: `docs/contracts/d10-alinhamento.md` · pareceres `docs/squad/gates/G1-D10.json`, `G2-D10.json`.
Execução: 2026-09-23, worktree `plankton-d10`, branch `feature/D10-alinhar-documentacao-codigo-infra`,
HEAD `ba78c68` (o commit da Observabilidade entrou durante a rodada; só mexe em `docs/observability.md`).
Projeto compose `checkout-saga`, `.env` `GRAFANA_PORT=3001`.

## Stack limpa (pré-requisito do CA6)
- [x] `docker compose down -v && docker compose up --build -d`: `up` retornou rc=0 em 33 s.
- [x] **11/11 containers `(healthy)` 40 s** após o início do `up` (poll de `docker compose ps` a cada 2 s):
  checkout-console, grafana, inventory-service, jaeger, kafka, order-service, payment-service, postgres,
  prometheus, saga-orchestrator, shipping-service. Observação: cache de build do Docker quente (camadas
  `CACHED`); com build frio o tempo é maior, mas o risco do G2 (até ~110 s esperando o Jaeger) não ocorreu.

## CA1 — `saga.md` + ADR-013 refletem o código
- [x] `findDue`, `lockDue`, `lockResumable`, `resumeAfterRestart`, `RESUMED_AFTER_RESTART`,
  `incrementAttempts`, `shouldReply` existem em `services/*/src/main` (grep).
- [x] `docs/adr/013-carencia-de-prazos-na-retomada.md` presente.
- [x] Carência provada ao vivo (ver CA6): `deadline 21:58:25.047Z -> 21:58:33.697Z (tentativa mantida)`.

## CA2 — DLT explícito, auto-criação desligada
- [x] `kafka-configs.sh --describe --entity-type brokers --entity-name 1 --all`:
  `auto.create.topics.enable=false` (`STATIC_BROKER_CONFIG`; default seria `true`).
- [x] `kafka-topics.sh --list` no volume limpo: `__consumer_offsets` + 9 tópicos de negócio + 9 `.DLT`
  (`inventory|order|payment|shipping.commands|events`, `saga.events`, cada um com `.DLT`). **Nenhum extra.**
- [x] `--describe`: os 18 tópicos com `PartitionCount: 3` (inclui `order.commands.DLT`); RF 1.
- [x] `DeadLetterIT` verde no `mvn -B verify`.
- [ ] (opcional, "se possível") Kafka do Testcontainers com auto-criação desligada — não aplicado; registrado
  como lacuna em `tests/TRACEABILITY.md`.

## CA3 — MDC/trace no log
- [x] `OTEL_INSTRUMENTATION_LOGBACK_MDC_ENABLED` presente em `docker-compose.yml` e citado em `docs/observability.md`.
- [x] Linha real do `saga-orchestrator` após o `up` desta branch contém `trace_id=ef278fd42bb650d05a2f754dbf265048`,
  `span_id=6b694ec6ee678f33`, `orderId=cc3b85f2-…`, `sagaId=822d9063-…`.
- [x] `GET jaeger /api/traces/ef278fd4…`: 31 spans em saga-orchestrator, order, inventory e payment.
  (A evidência formal no doc é da Observabilidade.)

## CA4 — Healthchecks
- [x] `docker compose ps`: 11/11 `(healthy)`, incluindo jaeger, prometheus, grafana e checkout-console.

## CA5 — README
- [x] Fora do escopo de teste do QA; aprovado pelo Auditor no G2.

## CA6 — Regressão
- [x] `bash tests/e2e/run.sh`: **12/12 PASS** (0 FAIL, 0 SKIP), rc=0; `tests/e2e/last-report.json`
  `executedAt 2026-09-23T21:58:34Z`, `gitCommit "ba78c68"` = HEAD.
- [x] Reinício do coordenador (`coordinator_restart`, orderId `5e22654b-0192-4193-b859-e6b16e0b6a18`,
  sagaId `ecded2d5-5e81-4b7d-a386-dc96528d7b6e`): as duas evidências aparecem:
  `GET /sagas/{sagaId}` tem `action: RESUMED_AFTER_RESTART` (step PAYMENT, attempt 1) e o saga termina
  `COMPLETED/CONFIRMED`; `/actuator/prometheus`: `saga_resumed_total{application="saga-orchestrator"} 1.0`.
  Obs.: `GET /sagas/{id}` recebe o **sagaId**; o orderId dá 404 (use `/sagas?orderId=`).
- [x] `mvn -B verify` (raiz): BUILD SUCCESS em ~27 s. Unitários 66/66; IT 9/9 (`OrderApiIT` 6,
  `OutboxRelayIT` 1, `IdempotentConsumerIT` 1, `DeadLetterIT` 1).

Stack deixada no ar para a Observabilidade.
