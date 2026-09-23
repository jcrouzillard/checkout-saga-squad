# Handoff 04 — Backend (core) → QA

## Implementado
- `pom.xml` raiz (Boot 3.4.5, Java 21, 6 módulos; OTel API fixada em 1.42.1 p/ o agente 2.8.0).
- `services/common` — envelope, `Simulate`, `Topics`, outbox (`trace_parent` + relay `FOR UPDATE SKIP LOCKED` com header
  `traceparent`), `IdempotencyGuard`, Kafka (ack RECORD pós-commit, DLT p/ venenosas, retry infinito p/ transitórias),
  problem+json, `X-Correlation-Id`, MDC, defaults de observabilidade. Uso: [`services/common/README.md`](../../../../services/common/README.md).
  Flyway: migração comum em `db/common` (versão **0.1**); serviços usam `db/migration` a partir de `V1__` (permite `V2__seed_stock.sql`).
- `order-service` (8081): `POST /orders` (Idempotency-Key, 202/200 replay/400/409, hash SHA-256 do JSON canônico),
  `GET /orders/{id}` (histórico de `saga.step-changed` + transições locais), consome `order.commands`/`saga.events`.
- `saga-orchestrator` (8080): máquina pura `SagaStateMachine` + `SagaService` (1 transação por mensagem/tick),
  `SagaTimeoutScheduler` (deadline/retry persistidos, lock por saga `SKIP LOCKED`, restaura traceparent), `GET /sagas/{id}`,
  `GET /sagas?orderId=`. Métricas de `docs/observability.md` (`outcome` = CONFIRMED|CANCELED) + extra `saga_compensation_stuck_total`.

## Riscos do G1 tratados
coluna `outbox.trace_parent` (saga.md); tag `outcome` COMPLETED→CONFIRMED; credenciais só via `SPRING_DATASOURCE_*`.

## Como rodar
`mvn -B package` (16 testes unitários da máquina em `services/saga-orchestrator/src/test`) · `docker compose up --build`.

## Evidências
- Build + testes: pass. Smoke (postgres, kafka, jaeger, saga, order): pass — saga inicia e envia `inventory.reserve`;
  retry com o MESMO messageId e mesmo `trace_id`; respostas injetadas no Kafka levaram pedido DIGITAL a `CONFIRMED`;
  replay 200/409/400 ok; `kill` + restart do orquestrador → log "Recuperação de sagas…" e `saga_in_flight` preservado.

## Injeção de falha / diagnóstico
`simulate` no `POST /orders` (events.md §3) é validado (400 p/ chave/valor desconhecido) e propagado sem alteração.
`GET /sagas/{sagaId}` mostra `log` (COMMAND_SENT, TIMEOUT, RETRY, IGNORED_LATE_REPLY, COMPENSATION_STUCK…).

## Limitações conhecidas
- `saga.timeouts/retries{step}` também contam timeouts de compensações (tag = passo compensado); passo ORDER não gera métrica.
- `saga.step-changed` não é emitido para `order.confirm/cancel` (o order-service grava ORDER CONFIRMED/CANCELED localmente).
- Relay: ordem garantida com 1 instância por serviço; sem limpeza de `outbox`/`processed_messages` (fora de escopo).
- Formato `10.00` do dinheiro validado em `GET /orders`; nos comandos Kafka depende do ObjectMapper customizado (validar no e2e).
