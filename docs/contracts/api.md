# Contrato de APIs HTTP

> Autoridade: Agente Arquiteto. Erros no formato **RFC 7807** (`application/problem+json`):
> `{ "type": "about:blank", "title": "...", "status": 400, "detail": "...", "instance": "/orders", "errors": [ {"field": "...", "message": "..."} ] }`.
> Todos os serviços expõem `GET /actuator/health` (healthcheck do compose) e `GET /actuator/prometheus`.
> Header opcional `X-Correlation-Id` (UUID) em todas as requisições; ecoado na resposta.

## 1. order-service (porta 8081)

### `POST /orders`
Headers: `Content-Type: application/json`, **`Idempotency-Key`** (obrigatório, string 1–100 chars, recomendado UUID).

```json
{
  "customerId": "c-123",
  "items": [
    { "sku": "SKU-BOOK-001", "quantity": 2, "unitPrice": 49.90 }
  ],
  "deliveryType": "PHYSICAL",
  "shippingAddress": {
    "street": "Av. Paulista", "number": "1000", "complement": null,
    "city": "São Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR"
  },
  "simulate": { "payment": "DECLINE" }
}
```

Validação (400 em violação):
- `customerId` não vazio; `items` com 1..50 elementos; `sku` não vazio; `quantity` int 1..1000; `unitPrice` decimal > 0 (2 casas).
- `deliveryType` ∈ `PHYSICAL | DIGITAL`. **Envio só se aplica a `PHYSICAL`**: `shippingAddress` obrigatório
  (todos os campos exceto `complement`) quando `PHYSICAL`; ignorado/gravado `null` quando `DIGITAL`.
- `simulate` opcional; chaves e valores conforme `events.md` §3 (valor desconhecido → 400).
- SKU inexistente **não** é erro HTTP: vira `inventory.rejected (UNKNOWN_SKU)` → pedido cancelado.

Processamento: numa única transação grava `orders` + `order_items` + `order_status_history (CREATED)` + outbox
`order.created`. Gera `orderId` e `sagaId` (UUID). A saga é **assíncrona**.

Respostas:
| Status | Quando | Corpo |
|--------|--------|-------|
| `202 Accepted` | Pedido criado | `{ "orderId": "uuid", "sagaId": "uuid", "status": "PENDING", "links": { "self": "/orders/{orderId}" } }` + header `Location: /orders/{orderId}` |
| `200 OK` | Mesmo `Idempotency-Key` **e** mesmo corpo (hash SHA-256 do JSON canônico) | mesmo corpo do 202 original + header `Idempotent-Replayed: true` |
| `400 Bad Request` | Header ausente ou corpo inválido | problem+json |
| `409 Conflict` | Mesmo `Idempotency-Key` com corpo diferente | problem+json |

Concorrência: `UNIQUE(idempotency_key)`; em violação de unicidade, reler e aplicar a regra 200/409.

### `GET /orders/{orderId}`
`200 OK`:
```json
{
  "orderId": "uuid", "sagaId": "uuid", "customerId": "c-123",
  "status": "CANCELED",
  "deliveryType": "PHYSICAL",
  "totalAmount": 99.80, "currency": "BRL",
  "items": [ { "sku": "SKU-BOOK-001", "quantity": 2, "unitPrice": 49.90 } ],
  "shippingAddress": { "...": "..." },
  "paymentId": null, "shipmentId": null, "trackingCode": null,
  "cancellationReason": "PAYMENT_DECLINED",
  "createdAt": "2026-09-23T14:05:12.100Z", "updatedAt": "2026-09-23T14:05:14.000Z",
  "history": [
    { "step": "ORDER",     "status": "CREATED",      "attempt": 1, "detail": null, "at": "..." },
    { "step": "INVENTORY", "status": "SUCCEEDED",    "attempt": 1, "detail": null, "at": "..." },
    { "step": "PAYMENT",   "status": "FAILED",       "attempt": 1, "detail": "DECLINED", "at": "..." },
    { "step": "INVENTORY", "status": "COMPENSATED",  "attempt": 1, "detail": "inventory.released", "at": "..." },
    { "step": "ORDER",     "status": "CANCELED",     "attempt": 1, "detail": "PAYMENT_DECLINED", "at": "..." }
  ]
}
```
`status`: `PENDING | CONFIRMED | CANCELED` (terminal = `CONFIRMED`/`CANCELED`; clientes/testes fazem *poll* até terminal).
`history` ordenado por `at`, originado de `saga.step-changed` + transições locais. `404` se não existir (problem+json).

## 2. saga-orchestrator (porta 8080) — diagnóstico

### `GET /sagas/{sagaId}` e `GET /sagas?orderId={orderId}`
`200 OK`:
```json
{
  "sagaId": "uuid", "orderId": "uuid",
  "status": "REFUNDING_PAYMENT", "outcome": null,
  "currentStep": "PAYMENT", "attempt": 1,
  "deadlineAt": "2026-09-23T14:05:20.000Z", "nextRetryAt": null,
  "failureReason": "SHIPMENT_FAILED",
  "createdAt": "...", "updatedAt": "...",
  "log": [ { "step": "SHIPPING", "action": "REPLY_RECEIVED", "messageType": "shipment.failed",
             "messageId": "uuid", "attempt": 1, "at": "..." } ]
}
```
`outcome`: `null | CONFIRMED | CANCELED`. `404` se não existir.

## 3. Participantes — consulta (usadas pelos testes e2e para verificar compensações)

| Serviço | Endpoint | Resposta 200 |
|---------|----------|--------------|
| inventory-service (8082) | `GET /inventory/stock/{sku}` | `{ "sku": "SKU-BOOK-001", "available": 998, "reserved": 2 }` |
| inventory-service | `GET /inventory/reservations/{orderId}` | `{ "orderId", "reservationId", "status": "RESERVED\|RELEASED\|REJECTED", "items": [...], "noop": false }` |
| payment-service (8083) | `GET /payments/{orderId}` | `{ "orderId", "paymentId", "status": "AUTHORIZED\|DECLINED\|REFUNDED", "amount", "currency", "authorizationCode", "noop": false }` |
| shipping-service (8084) | `GET /shipments/{orderId}` | `{ "orderId", "shipmentId", "status": "CREATED\|FAILED\|CANCELED", "trackingCode", "noop": false }` |

`404` quando não há registro para o `orderId`. As operações `reserve/release`, `authorize/refund` e
`solicitar entrega` (seção 4 do desafio) são expostas **como comandos Kafka** (`events.md`), não como HTTP —
o orquestrador é o único cliente delas (ADR-001).

## 4. Seeds de estoque (inventory-service, migração Flyway `V2__seed_stock.sql`)

| SKU | Disponível | Uso |
|-----|-----------:|-----|
| `SKU-BOOK-001`    | 1000   | Caminho feliz físico |
| `SKU-PHONE-001`   | 100    | Caminho feliz físico |
| `SKU-EBOOK-001`   | 100000 | Pedido `DIGITAL` (sem envio) |
| `SKU-COURSE-001`  | 100000 | Pedido `DIGITAL` |
| `SKU-LIMITED-001` | 1      | Falta de estoque real (sem `simulate`) |

## 5. Variáveis de ambiente (defaults entre parênteses)

Ligar em `application.yml` como `${VAR:default}`.

| Variável | Serviço | Default | Significado |
|----------|---------|---------|-------------|
| `SAGA_STEP_TIMEOUT_MS` | saga-orchestrator | `5000` | Prazo para resposta de cada comando (deadline persistido). |
| `SAGA_STEP_MAX_RETRIES` | saga-orchestrator | `2` | Retries de um passo de **ação** após timeout (3 tentativas no total); esgotado → compensação. |
| `SAGA_RETRY_BACKOFF_MS` | saga-orchestrator | `1000` | Backoff base (exponencial ×2) entre retries de ação. |
| `SAGA_COMPENSATION_BACKOFF_MAX_MS` | saga-orchestrator | `30000` | Teto do backoff das compensações e de `order.confirm/cancel` (retry **infinito**). |
| `SAGA_COMPENSATION_ALERT_AFTER` | saga-orchestrator | `5` | Tentativas de compensação a partir das quais loga ERROR `COMPENSATION_STUCK` + métrica. |
| `SAGA_TIMEOUT_SCAN_INTERVAL_MS` | saga-orchestrator | `1000` | Intervalo do scheduler que varre deadlines vencidos. |
| `OUTBOX_POLL_INTERVAL_MS` | todos | `200` | Intervalo do relay do outbox. |
| `OUTBOX_BATCH_SIZE` | todos | `100` | Linhas por varredura do relay. |
| `SIMULATE_SLOW_MS` | participantes | `2000` | Atraso do modo `SLOW` (deve ser < `SAGA_STEP_TIMEOUT_MS`). |
| `SPRING_DATASOURCE_URL`, `SPRING_KAFKA_BOOTSTRAP_SERVERS`, `OTEL_*` | todos | — | Padrão Spring/OTel (ADR-000). |
