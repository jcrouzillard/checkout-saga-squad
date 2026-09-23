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

## Correção pós-e2e (ciclo 1) — reinício do coordenador terminava CANCELED
- Causa: após SIGKILL, o membro antigo ficava no grupo até `session.timeout.ms` (45 s); os deadlines de 5 s venciam 3× → compensação.
- Static membership (`saga-orchestrator/application.yml`): `group.instance.id=${KAFKA_GROUP_INSTANCE_ID:saga-orchestrator-1}`,
  `session.timeout.ms=15000`, `heartbeat.interval.ms=3000` (envs `KAFKA_SESSION_TIMEOUT_MS`/`KAFKA_HEARTBEAT_INTERVAL_MS`).
  Default fixo pressupõe 1 réplica; para escalar, um id por réplica (change-request ao DevOps).
- Carência no startup: antes da 1ª varredura do scheduler, sagas com deadline vencido (ou < 1 prazo restante) ganham
  `deadline_at = now + SAGA_STEP_TIMEOUT_MS` sem consumir tentativa/reenviar; `saga_step_log` `RESUMED_AFTER_RESTART`,
  log INFO e métrica extra `saga_resumed_total` (`SagaStateMachine.resumeAfterRestart` + 4 testes unitários; 20 no total).
- Evidência: `coordinator_restart` verde (step log: RESUMED_AFTER_RESTART → payment.authorized aceito 91 ms depois, tentativa 1);
  suíte completa 7/7.

## D1 — `GET /orders?customerId=&limit=` (ADR-006)
- `OrderController.listByCustomer` + `OrderRepository.findByCustomer` (só database `orders`; `created_at desc, order_id desc`);
  migração `V2__idx_orders_customer_created.sql`. `cancellationReason` só em `CANCELED`. Sem mudanças em common/Saga/eventos.
- 400 problem+json: `customerId` ausente/vazio/>100 **ou com espaços nas pontas (sem trim)**; `limit` não inteiro ou fora de 1–200 (default 50).
- Testes: `order-service/src/test/.../OrderListByCustomerTest` (6: ordem, `[]`, limit default/explícito, 400s).
- Compose: `console-teste` → 1 pedido; inexistente → `[]` 200; ausente → 400; ` console-teste` e `limit=201` → 400;
  2 pedidos de `d1-backend-check` retornam do mais recente ao mais antigo. Cenário e2e criar+listar: pendente do QA.
