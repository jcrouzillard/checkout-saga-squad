# Matriz de rastreabilidade — requisito → mecanismo → teste

> Fonte dos requisitos: `docs/desafio.md` §3 (funcionais), §6 (não funcionais), §7 (cenários de
> falha), demanda D6 (`c6f83b5bb5c7`, testes de integração e timeout em toda etapa). Fonte dos
> mecanismos: ADRs e contratos (`docs/adr/`, `docs/contracts/`, `docs/architecture/saga.md`,
> `docs/architecture/testes.md`, ADR-010). Fonte dos testes: `tests/e2e/run.sh` (12 cenários e2e) e
> `services/*/src/test/**` (unitários) + `services/order-service/src/test/java/com/checkout/order/it/**`
> (integração, Testcontainers — Fase B do D6, ver observação abaixo).
>
> **Regenerada a partir de `tests/e2e/last-report.json`** (`executedAt`: 2026-09-23T18:02:42Z,
> `gitCommit`: `de2fd92`, `total`: 12, `passed`: 12, `failed`: 0, `skipped`: 0). Legenda: ✅ passou ·
> ⚠️ parcial · ❌ falhou.

## 3. Requisitos funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Criar pedido | `POST /orders` (`api.md` §1); outbox `order.created` (`saga.md` §3.3) | e2e: os 12 cenários criam pedido (`tests/e2e/last-report.json`) | ✅ passou |
| Reservar estoque | `inventory.reserve`/`inventory.reserved`, tudo-ou-nada (`events.md` §4.3) | e2e: `happy_path_physical` (`orderId=6852a3b9…`, `INVENTORY/SUCCEEDED`); `timeout_inventory` (reserva real, depois liberada); unitário: `StockAllocatorTest.java` | ✅ passou |
| Autorizar pagamento | `payment.authorize`/`payment.authorized` (`events.md` §4.4) | e2e: `happy_path_physical`, `happy_path_digital`, `coordinator_restart`, `timeout_once`; unitário: `PaymentCommandHandlerTest.java` | ✅ passou |
| Gerar envio quando aplicável | `shipment.create`/`shipment.created`, só `deliveryType=PHYSICAL` | e2e: `happy_path_physical` (`CREATED`); `happy_path_digital` (`404`); `timeout_once` (`CREATED` na 2ª tentativa) | ✅ passou |
| Confirmar pedido | `order.confirm`→`order.confirmed`, `CONFIRMED` (`saga.md` §1-2) | e2e: `happy_path_physical`, `happy_path_digital`, `timeout_once` (`orderId=1550c90a…`), `coordinator_restart`, `idempotency` | ✅ passou |
| Cancelar pedido | `order.cancel`→`order.canceled` com `reason`/`failedStep` | e2e: `payment_failure`, `shipping_failure`, `timeout_step`, `timeout_inventory` (`orderId=24bb5707…`), `timeout_shipping` (`orderId=949cc5e8…`) — todos `STEP_TIMEOUT`/motivo coerente | ✅ passou |
| Consultar status do pedido | `GET /orders/{orderId}` com `history` | e2e: os 12 cenários fazem poll via `wait_for_status` | ✅ passou |
| Listar pedidos de um cliente (D1, ADR-006) | `GET /orders?customerId=&limit=` | e2e: `customer_orders` (`orderId=6d474f33…`, cliente `qa-e2e-cust-32f058f5…`, 3 pedidos, ordem correta, `limit=2`, cliente inexistente `[]`, sem `customerId` `400`) | ✅ passou |

## 4. APIs por domínio

| Operação | Mecanismo | Teste que prova | Status |
|---|---|---|---|
| Estoque: `reserve` | comando Kafka `inventory.reserve` | e2e: `happy_path_physical`; `payment_failure`/`shipping_failure`/`timeout_step`/`timeout_inventory`/`timeout_shipping` (reserva seguida de release) | ✅ passou |
| Estoque: `release` | comando Kafka `inventory.release`, idempotente (`noop`) | e2e: todos os cenários de compensação verificam `GET /inventory/reservations/{id}`=`RELEASED` (`noop=false`) e estoque restaurado — estoque disponível de `SKU-BOOK-001` chegou a 960 após `payment_failure`/`shipping_failure`/`timeout_step`/`timeout_inventory`/`timeout_shipping` na mesma execução (`last-report.json`) | ✅ passou |
| Pagamento: `authorize` | comando Kafka `payment.authorize` | e2e: `happy_path_physical`, `happy_path_digital`, `coordinator_restart`, `timeout_once` (autoriza na tentativa 2, `noop=false`) | ✅ passou |
| Pagamento: `refund` | comando Kafka `payment.refund`, idempotente | e2e: `shipping_failure`, `timeout_step`, `timeout_shipping` (`orderId=949cc5e8…`, `REFUNDED`) | ✅ passou |
| Envio: solicitar entrega | comando Kafka `shipment.create` | e2e: `happy_path_physical`, `timeout_shipping` (cria de fato antes de nunca responder), `timeout_once` | ✅ passou |
| Envio: erro de negócio / timeout | `saga.md` §5.2, §5.2.1 | e2e: `shipping_failure` (erro de negócio); `timeout_shipping` (timeout real, `shipment.cancel`→`CANCELED`, `noop=false`, compensação de 3 passos na ordem `SHIPPING`→`PAYMENT`→`INVENTORY`) | ✅ passou |

## 6. Requisitos não funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Idempotência | `Idempotency-Key` + `processed_messages` (ADR-005) | e2e: `idempotency` (`orderId=590621ab…`, `Idempotent-Replayed=true`, estoque 958→957, reduz uma vez); IT: `OrderApiIT`/`IdempotentConsumerIT` (Fase B, ver observação) | ✅ passou (e2e) · ⚠️ IT pendente (Fase B) |
| Retries | Scheduler de timeouts, `SAGA_STEP_MAX_RETRIES` (2), backoff exponencial | e2e: `timeout_step` (`PAYMENT/TIMED_OUT`, 20s); `timeout_inventory` (20s); `timeout_shipping` (22s); `timeout_once` (retry com sucesso, `attempt=2`, 7s) | ✅ passou |
| Timeouts **em qualquer etapa** | `deadline_at`/`SAGA_STEP_TIMEOUT_MS` | e2e: agora cobre as **3 etapas participantes** — `timeout_step` (pagamento), `timeout_inventory` (estoque), `timeout_shipping` (envio) — antes só pagamento era coberto (lacuna fechada pela D6) | ✅ passou |
| Recuperação após falhas | Estado em Postgres, offset após commit, scheduler retoma | e2e: `coordinator_restart` (`orderId=98807308…`, 1 única autorização) | ✅ passou |
| Rastreabilidade ponta a ponta | `traceparent` W3C propagado via outbox/Kafka/HTTP, spans nos 5 serviços | e2e: **agora automatizado** — `trace_end_to_end` (`orderId=987d784e…`, trace `2dad6d78f94ba8fee5757e6cd7f4578f`, verificado via `GET /api/traces/{id}` do Jaeger com os 5 `processes[*].serviceName` presentes); antes da D6 era só inspeção manual | ✅ passou (automatizado) |
| Publicação de eventos | outbox transacional + relay (ADR-002) | e2e: os 12 cenários dependem da publicação real para a saga progredir; IT: `OutboxRelayIT` prova o mecanismo isoladamente (Fase B) | ✅ passou (e2e) · ⚠️ IT pendente (Fase B) |

## 7. Cenários de falha obrigatórios

| Cenário | Mecanismo de continuidade | Compensações esperadas | Teste que prova | Status |
|---|---|---|---|---|
| Falha no pagamento | `payment.failed`, sem retry (negócio) | `inventory.release` → `order.cancel(PAYMENT_DECLINED)` | e2e: `payment_failure` (`orderId=e484b376…`, 2s) | ✅ passou |
| Falha no envio | `shipment.failed`, sem retry (negócio) | `payment.refund` → `inventory.release` → `order.cancel(SHIPMENT_FAILED)` | e2e: `shipping_failure` (`orderId=815ef918…`, 2s) | ✅ passou |
| Timeout no **pagamento** | Deadline + scheduler; retry mesmo `messageId`; esgotado → compensação | `payment.refund`(autorização real) → `inventory.release` → `order.cancel(STEP_TIMEOUT)` | e2e: `timeout_step` (`orderId=cf5fa59a…`, 20s) | ✅ passou |
| Timeout no **estoque** (D6, antes era lacuna) | Idem, aplicado à etapa `INVENTORY` (`saga.md` §5.2.1) | `inventory.release` → `order.cancel(STEP_TIMEOUT)`; nenhum pagamento/envio | e2e: `timeout_inventory` (`orderId=24bb5707…`, 20s) | ✅ passou |
| Timeout no **envio** (D6, antes era lacuna) | Idem, aplicado à etapa `SHIPPING`; compensação de 3 passos | `shipment.cancel` → `payment.refund` → `inventory.release` → `order.cancel(STEP_TIMEOUT)`, **nesta ordem** | e2e: `timeout_shipping` (`orderId=949cc5e8…`, 22s, ordem do `history` verificada por índice) | ✅ passou |
| Timeout com retry bem-sucedido (D6) | 1ª tentativa expira, 2ª (mesmo `messageId`) responde | Nenhuma — a saga se recupera sozinha, sem compensar | e2e: `timeout_once` (`orderId=1550c90a…`, 7s, `attempt=1`→`TIMED_OUT`, `attempt=2`→`SUCCEEDED`) | ✅ passou |
| Reinício inesperado do coordenador | Estado em Postgres; offset após commit; scheduler retoma | Nenhuma extra | e2e: `coordinator_restart` (`orderId=98807308…`, 10s) | ✅ passou |

## 8. Testes de integração (D6, ADR-010, `services/order-service/src/test/java/com/checkout/order/it/`)

> Fase B da demanda: aguardando o Backend adicionar `maven-failsafe-plugin` (`pom.xml` raiz) e as
> dependências de teste do `order-service` (Testcontainers, Awaitility) via `change-request` do QA
> (ADR-010 §7). QA escreve as 4 classes `*IT` e roda `mvn -B -pl services/order-service -am verify`
> assim que o handoff "D6: pom pronto…" for registrado pelo Backend.

| Classe | Casos | Status |
|---|---|---|
| `OrderApiIT` | `POST /orders` 202+`Location`; replay 200 (`Idempotent-Replayed`); mesma key/corpo diferente → 409; sem header → 400; `GET /orders/{id}` 200 `PENDING`/`CREATED`; id inexistente → 404 | ⏳ pendente (Fase B) |
| `OutboxRelayIT` | `order.created` chega em `order.events` com envelope completo; `outbox.published_at` preenchido | ⏳ pendente (Fase B) |
| `IdempotentConsumerIT` | `order.confirm` 2× mesmo `messageId` → 1 linha em `processed_messages`, 1 `CONFIRMED`, 1 `order.confirmed` | ⏳ pendente (Fase B) |
| `DeadLetterIT` | Mensagem não-JSON em `order.commands` → `order.commands.DLT` (≤30s); consumidor segue processando depois | ⏳ pendente (Fase B) |

## Histórico de execução

**1ª execução (2026-09-23 13:57, integração completa)** — 6/7 verde. Falhou `coordinator_restart`
(rebalance do Kafka de 45s vs. deadline de 5s da Saga; defect `23d3ca1dd0de`). Corrigido pelo
Backend com static membership + carência no startup (handoff 04). **2ª execução** (mesmo dia,
14:00) — 7/7 verde.

**D6 — 3ª execução (2026-09-23 18:02:42Z, commit `de2fd92`)** — 12/12 verde
(`tests/e2e/last-report.json`), 5 cenários novos em relação à suíte original:
`timeout_inventory`, `timeout_shipping`, `timeout_once`, `trace_end_to_end` (mais `customer_orders`
da D1). Dois ajustes de teste feitos nesta rodada (não são defeitos de produto):
1. **`json_bool` novo** em `run.sh`: o helper `json_get` existente usa `// empty` no `jq`, que trata
   `false` como "falsy" e descarta o valor — inválido para os campos `noop` que a D6 passou a checar
   de verdade (`noop=false` em reservas/pagamentos/envios compensados). Corrigido com um helper
   dedicado a booleanos, sem alterar `json_get` (usado em várias outras asserções que dependem do
   comportamento atual para campos ausentes).
2. **`trace_end_to_end`: espera por serviço completo, não só existência do trace**. Os 5 serviços
   exportam spans ao Jaeger de forma assíncrona e independente (`BatchSpanProcessor` por processo);
   em 2 execuções de teste o trace apareceu no Jaeger com só 3-4 serviços dentro da janela de 30s
   sugerida por `testes.md` §5, e o serviço faltante surgia poucos segundos depois. `wait_for_trace`
   foi generalizado para só considerar "pronto" quando os 5 serviços aparecem juntos, com folga de
   60s — sem isso, o cenário seria estruturalmente flaky mesmo com o produto correto.

**Aprendizado (D6)**: cobertura de timeout agora existe nas 3 etapas participantes (pagamento,
estoque, envio) e não só no pagamento; rastreabilidade ponta a ponta deixou de ser verificação
manual e passou a ser um cenário automatizado determinístico (trace id conhecido enviado no
`POST /orders`).

## Observações / lacunas conhecidas

1. ~~**Timeout em INVENTORY e SHIPPING**~~ — **fechada pela D6**: `timeout_inventory` e
   `timeout_shipping` cobrem as duas variantes que antes só tinham o padrão documentado, sem cenário
   e2e dedicado.
2. **`TIMEOUT_ONCE`** — **fechada pela D6**: antes era variante manual documentada em
   `scenarios.md`, agora é o cenário automatizado `timeout_once`.
3. ~~**Rastreabilidade no Jaeger**~~ — **fechada pela D6**: `trace_end_to_end` verifica via API do
   Jaeger; o link manual continua disponível em cada cenário para inspeção visual na demo.
4. **Testes de integração (`*IT`)**: escritos e rodados só depois da Fase B (Backend adiciona
   Testcontainers/failsafe ao `pom.xml` via change-request do QA, ADR-010 §7) — ver seção 8.
5. **Testes unitários**: 66 testes em `services/*/src/test/**`, todos verdes —
   `SagaStateMachineTest` (20), `PaymentCommandHandlerTest`+`ReplyPolicyTest` (12),
   `InventoryCommandHandlerTest`+`StockAllocatorTest`+`ReplyPolicyTest` (15),
   `ShippingCommandHandlerTest`+`CarrierTest`+`ReplyPolicyTest` (13),
   `OrderListByCustomerTest` (6, D1). `common` continua sem `src/test/**` próprio.
6. **409 em `Idempotency-Key` repetida com corpo diferente**: ainda tratado como verificação
   "bônus" em `scenarios.md`, não obrigatória em `scenario_idempotency`; a demanda D6 exige esse
   caso nos testes de **integração** (`OrderApiIT`), não no e2e — cobertura fica completa após a
   Fase B.
