# Handoff 06: Backend (participantes) → QA

## O que foi feito
- `services/inventory-service` (8082), `services/payment-service` (8083), `services/shipping-service` (8084): listener Kafka → handler `@Transactional` (`IdempotencyGuard` + efeito + `OutboxWriter` na mesma TX, `SagaMdc`), repositório JdbcClient, Flyway `V1__schema.sql` (+ `V2__seed_stock.sql` no inventory, seeds de api.md §4) e endpoints de diagnóstico de api.md §3 (404 = problem+json).
- Idempotência: `UNIQUE(order_id)` (PK) em `reservations`/`payments`/`shipments`. Um comando de ação duplicado (mesmo messageId) ou uma nova ação para o mesmo pedido **não reexecuta** e re-publica a resposta a partir do estado (`causationId` = messageId do comando). As compensações sempre respondem a partir do estado.
- Tombstone (§5.4): `release`/`refund`/`cancel` sem ação prévia gravam `RELEASED`/`REFUNDED`/`CANCELED` com `noop=true`. Uma ação posterior responde `*.rejected|failed` `ALREADY_COMPENSATED`, sem efeito e sem aplicar `simulate`.
- Reserva tudo-ou-nada: SKUs agregados e ordenados, `SELECT ... FOR UPDATE ORDER BY sku` e débito condicional `available >= q`. `UNKNOWN_SKU` tem precedência sobre `OUT_OF_STOCK`.
- simulate (§3): `attempts` persistido na linha de domínio. `TIMEOUT` executa e nunca responde. `TIMEOUT_ONCE` responde a partir da 2ª tentativa. `DECLINE`/`FAIL`/`OUT_OF_STOCK` são persistidos como `DECLINED`/`FAILED`/`REJECTED`. `SLOW` (só no pagamento) grava a resposta em `delayed_replies` (`due_at = now()+SIMULATE_SLOW_MS`) e o agendador `DelayedReplies` a move para o outbox, sem `Thread.sleep` e sem perda em caso de reinício. Um valor de simulate desconhecido é ignorado com WARN.
- Decisões fora do texto do contrato: refund de pagamento `DECLINED` → `refunded noop=true` (status mantido); release de `REJECTED` / cancel de `FAILED` → `noop=true`; `shipment.failed INVALID_ADDRESS` se o endereço estiver incompleto; `trackingCode` = `BR`+9 dígitos, `carrier` = `LOCAL-EXPRESS`, previsão = hoje+7 dias.

## Evidências
- `mvn -q -B -pl services/inventory-service,services/payment-service,services/shipping-service -am package` → pass (34 testes unitários: StockAllocator, ReplyPolicy, Carrier e handlers com mocks cobrindo duplicata, TIMEOUT, TIMEOUT_ONCE, SLOW, tombstone+ALREADY_COMPENSATED, compensação idempotente).
- Smoke fora do compose (Postgres descartável, sem Kafka): os 3 jars sobem, Flyway aplica, `/inventory/stock/SKU-LIMITED-001` = `{"available":1,"reserved":0}`, 404 em `application/problem+json`, `/actuator/prometheus` com `application=<serviço>`.

## Para o QA
- Integração real (Kafka + Postgres) só foi exercida via compose. Priorizar: e2e dos 4 cenários, concorrência em `SKU-LIMITED-001` (2 pedidos simultâneos → 1 reservado), retry do orquestrador com o mesmo messageId e `SLOW` + kill do orquestrador.
- Testes em `services/*/src/test/java/**` (unitários mínimos). Integração com Testcontainers fica com o QA.

## Riscos
- `ReplyPolicy` está duplicada nos 3 serviços. Change-request aberto para movê-la ao common.
- `attempts` também conta redeliveries do Kafka após o commit (raro). Com `TIMEOUT_ONCE`, a resposta pode sair um ciclo antes, sem impacto funcional.
