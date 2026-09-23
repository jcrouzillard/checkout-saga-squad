# Contrato de mensagens (Kafka)

> Autoridade: Agente Arquiteto. Qualquer mudança de nome de tópico, `type` ou campo exige ADR (`CLAUDE.md`).
> Decisões relacionadas: [ADR-001](../adr/001-saga-orquestrada.md), [ADR-002](../adr/002-outbox-transacional.md),
> [ADR-004](../adr/004-kafka-como-broker.md), [ADR-005](../adr/005-idempotencia-e-retries.md).
> Máquina de estados e timeouts: [`docs/architecture/saga.md`](../architecture/saga.md).

## 1. Padrão de tópicos

- **Um tópico de comandos e um tópico de eventos por participante** (`<contexto>.commands` / `<contexto>.events`).
  O campo `type` do envelope distingue as mensagens dentro do tópico.
- **Comandos** são enviados **somente pelo `saga-orchestrator`**; **eventos** são publicados pelo dono do contexto.
- **Chave de partição = `orderId`** (string UUID) em **todas** as mensagens → ordem garantida por pedido
  (ex.: `payment.authorize` sempre chega antes do `payment.refund` do mesmo pedido).
- **3 partições**, replication factor 1 (ambiente local; produção: RF=3, ver `docs/architecture/README.md` §6).
- Valor: JSON UTF-8 (String serializer). Chave: String.
- Cada serviço declara via `NewTopic` (Spring Kafka) os tópicos que **produz** e **consome** (idempotente; 3 partições, RF 1).
- Mensagens venenosas (JSON inválido/desserialização) → após 3 tentativas locais vão para `<tópico>.DLT`
  (`DeadLetterPublishingRecoverer`). Erros de negócio **nunca** vão para DLT: viram eventos de falha.

| Tópico               | Produtor            | Consumidor(es) (group id)                   | Tipos (`type`) |
|----------------------|---------------------|---------------------------------------------|----------------|
| `order.events`       | `order-service`     | `saga-orchestrator`                          | `order.created`, `order.confirmed`, `order.canceled` |
| `order.commands`     | `saga-orchestrator` | `order-service`                              | `order.confirm`, `order.cancel` |
| `inventory.commands` | `saga-orchestrator` | `inventory-service`                          | `inventory.reserve`, `inventory.release` |
| `inventory.events`   | `inventory-service` | `saga-orchestrator`                          | `inventory.reserved`, `inventory.rejected`, `inventory.released` |
| `payment.commands`   | `saga-orchestrator` | `payment-service`                            | `payment.authorize`, `payment.refund` |
| `payment.events`     | `payment-service`   | `saga-orchestrator`                          | `payment.authorized`, `payment.failed`, `payment.refunded` |
| `shipping.commands`  | `saga-orchestrator` | `shipping-service`                           | `shipment.create`, `shipment.cancel` |
| `shipping.events`    | `shipping-service`  | `saga-orchestrator`                          | `shipment.created`, `shipment.failed`, `shipment.canceled` |
| `saga.events`        | `saga-orchestrator` | `order-service`                              | `saga.step-changed` |

Group id = nome do serviço (`saga-orchestrator`, `order-service`, `inventory-service`, `payment-service`, `shipping-service`).
Tipos desconhecidos em um tópico são **ignorados com log WARN** (compatibilidade futura), e o offset é confirmado.

### Quem publica `order.confirmed` / `order.canceled`
O **order-service**, dono do agregado Pedido. O orquestrador decide o desfecho e envia o comando `order.confirm`
ou `order.cancel`; o order-service atualiza `orders.status` (`PENDING → CONFIRMED | CANCELED`) e, **na mesma
transação**, grava `order.confirmed`/`order.canceled` no outbox. O orquestrador só marca a saga como terminal
(`COMPLETED`/`CANCELED`) ao consumir esse evento. O histórico de etapas exibido em `GET /orders/{orderId}` vem de
`saga.step-changed` (consumido pelo order-service → tabela `order_status_history`).

## 2. Envelope padrão

Toda mensagem (comando ou evento) usa exatamente este envelope:

```json
{
  "messageId": "7b1e0c1a-4f7e-4d5e-9a57-2d7a0b1c9e11",
  "type": "payment.authorize",
  "version": 1,
  "source": "saga-orchestrator",
  "occurredAt": "2026-09-23T14:05:12.345Z",
  "sagaId": "0f8c3b9e-2c1d-4a8e-b6f1-5a9d2e7c4b30",
  "orderId": "a3d5e8f0-1b2c-4d3e-8f9a-0b1c2d3e4f50",
  "correlationId": "c0ffee00-1234-4abc-9def-000000000001",
  "causationId": "5e6f7a8b-9c0d-4e1f-8a2b-3c4d5e6f7a8b",
  "payload": { }
}
```

| Campo          | Tipo                  | Regra |
|----------------|-----------------------|-------|
| `messageId`    | UUID (string)         | Único por mensagem lógica. **Chave de idempotência** (`processed_messages`). Um *retry* de comando reutiliza o **mesmo** `messageId` (ver §5). |
| `type`         | string                | Um dos tipos das tabelas abaixo. |
| `version`      | int                   | Versão do schema do payload. Hoje sempre `1`. |
| `source`       | string                | Nome do serviço produtor. |
| `occurredAt`   | string ISO-8601 UTC   | Instante em que o fato/comando foi gerado (gravação no outbox). |
| `sagaId`       | UUID                  | Gerado pelo order-service no `POST /orders`; presente em todas as mensagens. |
| `orderId`      | UUID                  | Também é a chave Kafka. |
| `correlationId`| UUID                  | Valor do header HTTP `X-Correlation-Id` do `POST /orders` (gerado se ausente); **inalterado** em toda a saga. |
| `causationId`  | UUID \| null          | `messageId` da mensagem que causou esta. `null` só em `order.created`. Respostas de participantes usam o `messageId` do comando → é assim que o orquestrador casa resposta ↔ tentativa. |
| `payload`      | objeto                | Específico do `type`. **Não repete** `orderId`/`sagaId` (use os do envelope). |

**Headers Kafka**: `traceparent` (W3C Trace Context) — injetado pelo agente OpenTelemetry. Como a publicação ocorre
pelo relay do outbox (outra thread), o `traceparent` corrente **deve ser gravado na linha do outbox** e reaplicado
como header pelo relay (ver ADR-002). Opcional: `tracestate`. Header `type` com o mesmo valor do envelope (facilita filtro).

Tipos comuns nos payloads: dinheiro = número JSON com 2 casas (`BigDecimal`, `scale=2`), moeda = `"BRL"`;
datas = ISO-8601 UTC; enums em MAIÚSCULAS.

## 3. Objeto `simulate` (injeção de falha — propagado sem alteração)

Enviado opcionalmente no `POST /orders` (ver `api.md`), persistido no pedido e copiado para `order.created` e para
cada comando do participante correspondente. Ausente/`null` = comportamento normal.

```json
{ "inventory": "OUT_OF_STOCK", "payment": "DECLINE", "shipping": "FAIL" }
```

| Chave       | Valores                         | Efeito no participante |
|-------------|---------------------------------|------------------------|
| `inventory` | `OUT_OF_STOCK`                  | Responde `inventory.rejected` (`reason=OUT_OF_STOCK`), sem reservar. |
|             | `TIMEOUT`                       | **Reserva de fato** mas **nunca responde** (nem nos retries) → compensação `inventory.release` libera a reserva real. |
| `payment`   | `DECLINE`                       | Persiste pagamento `DECLINED`, responde `payment.failed` (`reason=DECLINED`). |
|             | `TIMEOUT`                       | **Autoriza de fato** (persiste `AUTHORIZED`) mas **nunca responde** → demonstra a ambiguidade do timeout (o refund de compensação estorna uma autorização real). |
|             | `TIMEOUT_ONCE`                  | Não responde à 1ª tentativa; responde normalmente ao retry (mesmo `messageId`). Demonstra retry com sucesso. |
|             | `SLOW`                          | Responde após `SIMULATE_SLOW_MS` (< timeout). Usado para derrubar o coordenador no meio da saga. |
| `shipping`  | `FAIL`                          | Persiste `FAILED`, responde `shipment.failed` (`reason=CARRIER_REJECTED`). |
|             | `TIMEOUT`                       | **Cria o envio** mas nunca responde (compensação envia `shipment.cancel`). |
|             | `TIMEOUT_ONCE`                  | Igual ao de pagamento. |

A simulação afeta **apenas** comandos de ação (`reserve`, `authorize`, `create`); comandos de compensação
(`release`, `refund`, `cancel`) e `order.confirm/cancel` **sempre** executam normalmente.
Contagem de "tentativa" para `TIMEOUT_ONCE`: o participante guarda `attempts` no registro de dedupe/domínio.

## 4. Mensagens e payloads

### 4.1 `order.events` (produtor: order-service)

**`order.created`** (obrigatório) — início da saga. `causationId = null`.
```json
{
  "customerId": "c-123",
  "deliveryType": "PHYSICAL",
  "items": [ { "sku": "SKU-BOOK-001", "quantity": 2, "unitPrice": 49.90 } ],
  "totalAmount": 99.80,
  "currency": "BRL",
  "shippingAddress": {
    "street": "Av. Paulista", "number": "1000", "complement": null,
    "city": "São Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR"
  },
  "simulate": null,
  "createdAt": "2026-09-23T14:05:12.100Z"
}
```
`deliveryType`: `PHYSICAL | DIGITAL`. `shippingAddress` obrigatório se `PHYSICAL`, `null` se `DIGITAL`.
`items[].quantity`: int > 0; `unitPrice`: decimal > 0; `totalAmount = Σ quantity × unitPrice`.

**`order.confirmed`** (obrigatório)
```json
{ "status": "CONFIRMED", "paymentId": "uuid", "shipmentId": "uuid|null", "trackingCode": "BR123456789|null",
  "confirmedAt": "2026-09-23T14:05:14.000Z" }
```

**`order.canceled`** (obrigatório)
```json
{ "status": "CANCELED", "reason": "PAYMENT_DECLINED", "failedStep": "PAYMENT",
  "message": "Pagamento recusado pelo emissor", "canceledAt": "2026-09-23T14:05:14.000Z" }
```
`reason`: `OUT_OF_STOCK | UNKNOWN_SKU | PAYMENT_DECLINED | SHIPMENT_FAILED | STEP_TIMEOUT | ALREADY_COMPENSATED`.
`failedStep`: `INVENTORY | PAYMENT | SHIPPING`.

### 4.2 `order.commands` (produtor: saga-orchestrator → order-service)

**`order.confirm`**: `{ "paymentId": "uuid", "shipmentId": "uuid|null", "trackingCode": "string|null" }`
**`order.cancel`**: `{ "reason": "PAYMENT_DECLINED", "failedStep": "PAYMENT", "message": "string" }`

Idempotentes: confirmar pedido já `CONFIRMED` (ou cancelar já `CANCELED`) re-publica o evento correspondente.
Transição inválida (confirmar pedido `CANCELED`) não deve ocorrer; se ocorrer: log ERROR e re-publica o estado atual.

### 4.3 `inventory.commands` / `inventory.events`

**`inventory.reserve`** (comando): `{ "items": [ { "sku": "SKU-BOOK-001", "quantity": 2 } ], "simulate": null }`
Reserva é **tudo-ou-nada** (todos os SKUs numa transação, `SELECT ... FOR UPDATE` em `stock`).

**`inventory.reserved`** (obrigatório): `{ "reservationId": "uuid", "items": [ { "sku": "SKU-BOOK-001", "quantity": 2 } ] }`

**`inventory.rejected`**:
```json
{ "reason": "OUT_OF_STOCK", "message": "Estoque insuficiente",
  "details": [ { "sku": "SKU-LIMITED-001", "requested": 2, "available": 1 } ] }
```
`reason`: `OUT_OF_STOCK | UNKNOWN_SKU | ALREADY_COMPENSATED`.

**`inventory.release`** (compensação): `{ "reason": "PAYMENT_DECLINED" }`
**`inventory.released`**: `{ "reservationId": "uuid|null", "noop": false }` — `noop=true` quando não havia reserva
(liberação de reserva inexistente é registrada como `RELEASED` *tombstone* e não é erro).

### 4.4 `payment.commands` / `payment.events`

**`payment.authorize`**: `{ "customerId": "c-123", "amount": 99.80, "currency": "BRL", "simulate": null }`
**`payment.authorized`** (obrigatório): `{ "paymentId": "uuid", "authorizationCode": "AUTH-8F3K2", "amount": 99.80, "currency": "BRL" }`
**`payment.failed`**: `{ "reason": "DECLINED", "message": "Pagamento recusado pelo emissor" }` — `reason`: `DECLINED | ALREADY_COMPENSATED`.
**`payment.refund`** (compensação): `{ "amount": 99.80, "currency": "BRL", "reason": "SHIPMENT_FAILED" }`
**`payment.refunded`**: `{ "paymentId": "uuid|null", "amount": 99.80, "noop": false }` — `noop=true` se não existia autorização.

### 4.5 `shipping.commands` / `shipping.events` (somente `deliveryType = PHYSICAL`)

**`shipment.create`**:
```json
{ "address": { "street": "Av. Paulista", "number": "1000", "complement": null, "city": "São Paulo",
               "state": "SP", "zipCode": "01310-100", "country": "BR" },
  "items": [ { "sku": "SKU-BOOK-001", "quantity": 2 } ], "simulate": null }
```
**`shipment.created`** (obrigatório):
`{ "shipmentId": "uuid", "trackingCode": "BR123456789", "carrier": "LOCAL-EXPRESS", "estimatedDeliveryDate": "2026-09-30" }`
**`shipment.failed`**: `{ "reason": "CARRIER_REJECTED", "message": "Transportadora indisponível" }` —
`reason`: `CARRIER_REJECTED | INVALID_ADDRESS | ALREADY_COMPENSATED`.
**`shipment.cancel`** (compensação, só após timeout de `shipment.create`): `{ "reason": "STEP_TIMEOUT" }`
**`shipment.canceled`**: `{ "shipmentId": "uuid|null", "noop": false }`

### 4.6 `saga.events` (produtor: saga-orchestrator → order-service, para histórico)

**`saga.step-changed`**:
```json
{ "step": "PAYMENT", "stepStatus": "TIMED_OUT", "attempt": 2, "sagaStatus": "AUTHORIZING_PAYMENT",
  "detail": "Sem resposta em 5000 ms; reenviando payment.authorize" }
```
`step`: `INVENTORY | PAYMENT | SHIPPING | ORDER`.
`stepStatus`: `STARTED | SUCCEEDED | FAILED | TIMED_OUT | RETRYING | COMPENSATING | COMPENSATED`.
`sagaStatus`: estado da máquina (ver `saga.md`). Publicado a cada transição, no mesmo outbox/transação da transição.

## 5. Regras de idempotência e correlação (obrigatórias para o Backend)

1. **Consumidor**: na mesma transação do efeito de negócio, `INSERT INTO processed_messages(message_id, consumer)`;
   conflito de PK ⇒ mensagem já processada.
2. **Participante recebendo comando duplicado** (mesmo `messageId`, i.e. retry do orquestrador): **não** reexecuta o
   efeito; **re-publica a resposta** a partir do estado persistido (reserva/pagamento/envio do `orderId`), com novo
   `messageId` e `causationId` = `messageId` do comando. Exceções: simulação `TIMEOUT` (continua sem responder) e
   `TIMEOUT_ONCE` (responde a partir da 2ª tentativa).
3. **Idempotência por chave de negócio**: no máximo uma reserva, um pagamento e um envio por `orderId`
   (`UNIQUE(order_id)`). Um segundo comando de ação para o mesmo pedido devolve o resultado existente.
4. **Tombstone de compensação**: se `release`/`refund`/`cancel` chega antes (ou no lugar) da ação, o participante grava
   o registro já compensado (`noop=true`). Uma ação que chegue depois para esse `orderId` responde falha com
   `reason = ALREADY_COMPENSATED` sem efeito.
5. **Orquestrador**: aceita uma resposta somente se `causationId` = `last_command_id` do passo corrente **e** o `type`
   é esperado no estado atual; caso contrário registra em `saga_step_log` (`IGNORED_LATE_REPLY`) e confirma o offset.
6. **Offset**: `enable.auto.commit=false`; ack do registro **após** o commit da transação do banco (AckMode `RECORD`
   com listener transacional). Falha antes do commit ⇒ reentrega ⇒ dedupe.
7. **Produtor**: nunca `kafkaTemplate.send` dentro do handler; sempre grava no outbox (ADR-002). Producer com
   `enable.idempotence=true`, `acks=all`.
