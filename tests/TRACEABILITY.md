# Matriz de rastreabilidade — requisito → mecanismo → teste

> Fonte dos requisitos: `docs/desafio.md` §3 (funcionais), §6 (não funcionais), §7 (cenários de
> falha). Fonte dos mecanismos: ADRs e contratos (`docs/adr/`, `docs/contracts/`,
> `docs/architecture/saga.md`). Fonte dos testes: `tests/e2e/run.sh` (cenários e2e, execução real
> contra `docker compose up --build`) e `services/*/src/test/**` (testes unitários do Backend).
>
> **Status atualizado após execução real** (ver `tests/e2e/last-report.json` e seção "Histórico de
> execução" abaixo). Legenda: ✅ passou · ⚠️ parcial (funciona mas sem asserção automatizada, ou
> gap de cobertura conhecido) · ❌ falhou.

## 3. Requisitos funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Criar pedido | `POST /orders` (`docs/contracts/api.md` §1); outbox `order.created` (`saga.md` §3.3) | e2e: `happy_path_physical` (PASS, `orderId=9a9b6317...`) e os demais 6 cenários (todos criam pedido, `tests/e2e/last-report.json`) | ✅ passou |
| Reservar estoque | `inventory.reserve`/`inventory.reserved`, tudo-ou-nada (`events.md` §4.3); tabela `stock`/`reservations` (`saga.md` §3.1) | e2e: `happy_path_physical` (`history` com `INVENTORY/SUCCEEDED`); unitário: `services/inventory-service/src/test/java/com/checkout/inventory/domain/StockAllocatorTest.java` (5 testes, alocação tudo-ou-nada) | ✅ passou |
| Autorizar pagamento | `payment.authorize`/`payment.authorized` (`events.md` §4.4) | e2e: `happy_path_physical`/`happy_path_digital` (`PAYMENT/SUCCEEDED`); `coordinator_restart` (`GET /payments/{id}`=`AUTHORIZED`, 1 única autorização); unitário: `services/payment-service/src/test/java/com/checkout/payment/messaging/PaymentCommandHandlerTest.java` (9 testes) | ✅ passou |
| Gerar envio quando aplicável | `shipment.create`/`shipment.created`, só `deliveryType=PHYSICAL` (`events.md` §4.5; `api.md` regra de validação) | e2e: `happy_path_physical` (`GET /shipments/{id}`=`CREATED`, tracking presente); `happy_path_digital` (ausência: `404`); unitário: `services/shipping-service/src/test/java/com/checkout/shipping/messaging/ShippingCommandHandlerTest.java` (7 testes) | ✅ passou |
| Confirmar pedido | `order.confirm`→`order.confirmed`, estado terminal `COMPLETED`/`CONFIRMED` (`saga.md` §1-2) | e2e: `happy_path_physical`, `happy_path_digital`, `coordinator_restart`, `idempotency` (todos chegam a `CONFIRMED`); unitário: `services/saga-orchestrator/src/test/java/com/checkout/saga/domain/SagaStateMachineTest.java` (20 testes, transições terminais) | ✅ passou |
| Cancelar pedido | `order.cancel`→`order.canceled` com `reason`/`failedStep` (`events.md` §4.1) | e2e: `payment_failure` (PASS, `PAYMENT_DECLINED`), `shipping_failure` (PASS, `SHIPMENT_FAILED`), `timeout_step` (PASS, `STEP_TIMEOUT`); unitário: `SagaStateMachineTest.java` (transições de compensação/cancelamento) | ✅ passou |
| Consultar status do pedido | `GET /orders/{orderId}` com `history` (`api.md` §1) | e2e: os 7 cenários originais fazem poll de `GET /orders/{orderId}` via `wait_for_status` (`tests/e2e/run.sh`) | ✅ passou |
| Listar pedidos de um cliente (demanda D1, Squad Control → ADR-006) | `GET /orders?customerId=&limit=` (`docs/contracts/api.md` §1; `docs/adr/006-consulta-de-pedidos-por-cliente.md`) — leitura só no database `orders`, ordenação `createdAt desc`/`orderId desc`, `limit` 1–200 (default 50), `200`+`[]` nunca `404`, `400` sem `customerId` | e2e: `customer_orders` (`tests/e2e/run.sh`) — 3 pedidos do mesmo cliente (DIGITAL feliz, PHYSICAL feliz, PHYSICAL com `payment=DECLINE`), lista completa na ordem correta com os 6 campos do contrato, `limit=2`, cliente inexistente `[]`, sem `customerId` `400` | ✅ passou (e2e 8/8, customer_orders) |
| Melhorar o visual do checkout (demanda D2, Squad Control → ADR-007) | `checkout-console/index.html` servido em `http://localhost:8090` via proxy nginx; contrato `docs/contracts/ui-checkout-console.md` (CA1–CA12, sem API nova, sem regra de negócio no front) | Checklist manual `tests/ui/checklist-console.md` — CA1–CA12 (10 ✅, 2 ⚠️ parcial: CA7 e CA9 não observados interativamente no navegador); fluxo real pelo proxy (feliz e `payment=DECLINE`) igual ao direto no `order-service`; capturas `tests/ui/console-1440.png`/`console-390.png` (Chrome headless) | ✅ passou (com ressalvas ⚠️ registradas) |

## 4. APIs por domínio (desafio §4)

| Operação | Mecanismo | Teste que prova | Status |
|---|---|---|---|
| Estoque: `reserve` | comando Kafka `inventory.reserve` (não HTTP, ADR-001) | e2e: `happy_path_physical` (sucesso); `payment_failure`/`shipping_failure`/`timeout_step` (reserva seguida de release); unitário: `StockAllocatorTest.java` + `InventoryCommandHandlerTest.java` (7 testes) | ✅ passou |
| Estoque: `release` | comando Kafka `inventory.release`, idempotente com tombstone `noop` (`events.md` §4.3, §5.4) | e2e: `payment_failure` (estoque restaurado a 996), `shipping_failure`, `timeout_step` — todos checam `GET /inventory/reservations/{id}`=`RELEASED`; unitário: `InventoryCommandHandlerTest.java` (casos de release/noop) | ✅ passou |
| Pagamento: `authorize` | comando Kafka `payment.authorize` | e2e: `happy_path_physical`, `happy_path_digital`, `coordinator_restart`; unitário: `PaymentCommandHandlerTest.java` | ✅ passou |
| Pagamento: `refund` | comando Kafka `payment.refund`, idempotente com `noop` | e2e: `shipping_failure` (`REFUNDED`), `timeout_step` (`REFUNDED`, estorno de autorização real feita por `simulate.payment=TIMEOUT`); unitário: `PaymentCommandHandlerTest.java` | ✅ passou |
| Envio: solicitar entrega | comando Kafka `shipment.create` (`events.md` §4.5) | e2e: `happy_path_physical` (PASS); unitário: `ShippingCommandHandlerTest.java` | ✅ passou |
| Envio: o que acontece se der erro | `saga.md` §5.2 (erro de negócio → `shipment.failed`/compensação; erro técnico → tratado como timeout) | e2e: `shipping_failure` (erro de negócio, PASS); `timeout_step` cobre o mecanismo de timeout via `payment` (variante `shipping=TIMEOUT` não automatizada, ver Observações §1); unitário: `services/shipping-service/src/test/java/com/checkout/shipping/domain/ReplyPolicyTest.java` (3 testes) | ⚠️ parcial (timeout de shipping não tem cenário e2e dedicado) |

## 6. Requisitos não funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Idempotência | `Idempotency-Key` + `UNIQUE(idempotency_key)` (`api.md` §1); `processed_messages` + retry com mesmo `messageId` (`events.md` §5, ADR-005) | e2e: `idempotency` (PASS — mesmo `orderId=40de2069...`, header `Idempotent-Replayed=true`, estoque reduz de 995→994, uma única vez); indiretamente em `timeout_step`/`coordinator_restart` (retries não duplicam efeito) | ✅ passou |
| Retries | Scheduler de timeouts, `SAGA_STEP_MAX_RETRIES` (2), backoff exponencial (`saga.md` §3.2) | e2e: `timeout_step` (PASS — `history` mostra `PAYMENT/TIMED_OUT` antes da compensação, 20s de duração real); unitário: `SagaStateMachineTest.java` (transições de retry) e `ReplyPolicyTest.java` de cada participante (`shouldReply(mode, attempts)`, `TIMEOUT_ONCE`) | ✅ passou |
| Timeouts | `deadline_at`/`SAGA_STEP_TIMEOUT_MS` (`api.md` §5; `saga.md` §3.2) | e2e: `timeout_step` (PASS — `cancellationReason=STEP_TIMEOUT` após esgotar retries); unitário: `SagaStateMachineTest.java` | ✅ passou |
| Recuperação após falhas | Estado 100% em Postgres, offset só avança após commit, outbox republica pendências, scheduler retoma deadlines (`saga.md` §3.5) | e2e: `coordinator_restart` (PASS na 2ª execução — ver Histórico de execução abaixo; `docker compose kill`/`up -d saga-orchestrator`, saga conclui `CONFIRMED`, exatamente 1 autorização de pagamento); unitário: `SagaStateMachineTest.java` (4 testes de `resumeAfterRestart`, dos 20 totais) | ✅ passou |
| Rastreabilidade ponta a ponta | `traceparent` W3C propagado via outbox → header Kafka → spans (ADR-002; `observability.md` §3); `correlationId` no envelope | Não coberto por asserção automatizada em `run.sh` (checagem visual no Jaeger); script imprime o link do Jaeger por `orderId` em cada cenário (`jaeger_link` em `tests/e2e/run.sh`) para inspeção manual no G3 | ⚠️ parcial (evidência manual/visual, não automatizada) |
| Publicação de eventos | outbox transacional + relay (`events.md` §1, ADR-002); 6 eventos obrigatórios do desafio §5 | e2e: todos os 7 cenários dependem da publicação real dos eventos para a saga progredir (`order.created`, `inventory.reserved`, `payment.authorized`, `shipment.created`, `order.confirmed`, `order.canceled`); efeito observado indiretamente via `GET /orders/{id}` e endpoints de participantes | ✅ passou |

## 7. Cenários de falha obrigatórios

| Cenário | Mecanismo de continuidade | Compensações esperadas | Teste que prova | Status |
|---|---|---|---|---|
| Falha no pagamento | `payment.failed` é resposta de negócio, sem retry (`saga.md` §5) | `inventory.release` → `order.cancel(PAYMENT_DECLINED)` | e2e: `payment_failure` (PASS, 1s, `orderId=02c195dc...`, "CANCELED (PAYMENT_DECLINED), reserva RELEASED, estoque restaurado (996)") | ✅ passou |
| Falha no envio | `shipment.failed`, sem retry (recusa de negócio) | `payment.refund` → `inventory.release` → `order.cancel(SHIPMENT_FAILED)` | e2e: `shipping_failure` (PASS, 2s, `orderId=ce36add0...`, "CANCELED (SHIPMENT_FAILED), payment REFUNDED, reserva RELEASED, estoque restaurado (996)") | ✅ passou |
| Timeout em qualquer etapa | Deadline persistido + scheduler; retry com mesmo `messageId`; esgotado → compensação (`saga.md` §3.2, §5.1) | Compensa o passo expirado + anteriores; aqui: `payment.refund` → `inventory.release` → `order.cancel(STEP_TIMEOUT)` | e2e: `timeout_step` (PASS, 20s, `orderId=b6d2d297...`, "retries esgotados (TIMED_OUT) -> CANCELED (STEP_TIMEOUT), refund+release aplicados") | ✅ passou |
| Reinício inesperado do coordenador da Saga | Estado em Postgres; offset após commit; outbox republica; scheduler retoma (`saga.md` §3.5, §4.5) | Nenhuma extra — saga continua de onde parou | e2e: `coordinator_restart` (❌ na 1ª execução, ✅ **PASS** na 2ª — 11s, `orderId=602c9f34...`, "saga retomou após restart do coordenador; 1 única autorização de pagamento"); unitário: `SagaStateMachineTest.java` (`resumeAfterRestart`) | ✅ passou (após correção — ver Histórico) |

## Histórico de execução

**1ª execução (2026-09-23 13:57, integração completa)** — 6/7 verde.
- Falhou `coordinator_restart`: após `docker compose kill saga-orchestrator`, o membro antigo do
  grupo Kafka só saía do consumer group após `session.timeout.ms` (45s, default). Os deadlines de
  passo da Saga (`SAGA_STEP_TIMEOUT_MS=5000`) venciam 3× antes do rebalance terminar, e o scheduler
  compensava a saga por timeout. As respostas do `payment-service`, que chegaram depois do rebalance,
  foram descartadas como `IGNORED_LATE_REPLY`.
- Defeito registrado no log (`docs/squad/memory/decisions.jsonl` id `23d3ca1dd0de`), `--to backend`,
  com passos de reprodução (`saga_step_log` 54-81 da saga `79af41f9`).

**Correção do Backend** (`docs/squad/memory/handoffs/04-backend-core-para-qa.md`, seção
"Correção pós-e2e (ciclo 1)"):
1. **Static membership do Kafka** no `saga-orchestrator`: `group.instance.id` fixo
   (`KAFKA_GROUP_INSTANCE_ID`, default `saga-orchestrator-1`), `session.timeout.ms=15000` e
   `heartbeat.interval.ms=3000` — evita o rebalance completo em um restart de instância única.
2. **Carência no startup**: antes da 1ª varredura do scheduler, sagas com deadline vencido (ou
   próximo do vencimento) ganham `deadline_at = now + SAGA_STEP_TIMEOUT_MS` sem consumir
   tentativa nem reenviar comando (`SagaStateMachine.resumeAfterRestart`, `saga_step_log`
   `RESUMED_AFTER_RESTART`, métrica `saga_resumed_total`, 4 testes unitários novos).

**2ª execução (2026-09-23 14:00, pós-correção)** — 7/7 verde
(`tests/e2e/last-report.json`), incluindo `coordinator_restart` (11s, `RESUMED_AFTER_RESTART` →
`payment.authorized` aceito 91ms depois, tentativa 1, sem duplicar autorização).

**Aprendizado**: o timeout de um passo da Saga (`SAGA_STEP_TIMEOUT_MS`) precisa ser maior que o
tempo de rebalance do consumer group do Kafka (`session.timeout.ms`) para que um restart do
coordenador não seja confundido com uma falha real do passo em andamento — ou, como aqui, usar
static membership para evitar o rebalance completo nesse caso (1 réplica). Isso é uma dependência
implícita entre a config de infraestrutura (Kafka) e a config de negócio (deadlines da Saga) que
não estava explícita em nenhum ADR; vale registrar como nota operacional se o serviço for escalado
para múltiplas réplicas (ver `change-request` do Backend ao DevOps, id `b164b075d5cf`).

## Observações / lacunas conhecidas

1. **Timeout em INVENTORY e SHIPPING**: `timeout_step` cobre apenas `simulate.payment=TIMEOUT` (etapa
   intermediária, exercita compensação de 2 passos). O mecanismo é idêntico para `inventory`/`shipping`
   (`events.md` §3); não há função e2e dedicada para essas variantes — pode ser adicionada com o mesmo
   padrão (`order_payload ... '{"inventory":"TIMEOUT"}'` / `'{"shipping":"TIMEOUT"}'`) se o Auditor exigir
   cobertura mais ampla no G3.
2. **`TIMEOUT_ONCE`** (retry bem-sucedido, sem compensação): documentado como variante manual em
   `tests/e2e/scenarios.md` §5, não automatizado como cenário próprio (os 7 cenários da suíte seguem
   exatamente a lista de `.claude/agents/qa.md`).
3. **Rastreabilidade no Jaeger**: verificação é visual/manual (o script apenas imprime o link); não há
   dependência do cliente HTTP do Jaeger no `run.sh` para manter a suíte simples e sem dependências
   extras. Evidência para o G3 deve ser um screenshot/link anexado pelo Auditor.
4. **Testes unitários**: existem 60 testes em `services/*/src/test/**`, todos verdes (ver
   `services/*/target/surefire-reports/*.txt`) — `SagaStateMachineTest` (20, saga-orchestrator),
   `PaymentCommandHandlerTest`+`ReplyPolicyTest` (12, payment), `InventoryCommandHandlerTest`+
   `StockAllocatorTest`+`ReplyPolicyTest` (15, inventory), `ShippingCommandHandlerTest`+`CarrierTest`+
   `ReplyPolicyTest` (13, shipping). **Gap conhecido**: `order-service` e `common` não têm
   `src/test/**` próprio — sua cobertura vem só da suíte e2e (criação/consulta/idempotência de
   pedido, outbox, `IdempotencyGuard`), sem teste unitário isolado.
5. **409 em `Idempotency-Key` repetida com corpo diferente**: mencionado como verificação "bônus" em
   `scenarios.md` §7, não incluído como assert obrigatório em `scenario_idempotency` (o requisito do
   `.claude/agents/qa.md` cobre apenas "mesmo `Idempotency-Key` duas vezes → um único pedido").
