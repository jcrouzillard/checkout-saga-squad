# Cenários e2e — roteiro para demo ao vivo

> Automatizado em `tests/e2e/run.sh` (12 cenários, um por função). Este documento traz o `curl`
> manual equivalente de cada cenário — útil para apresentar a demo sem depender do script, ou
> para investigar uma falha reportada pelo script. URLs assumem `docker compose up --build` com
> as portas padrão (`docs/contracts/api.md` §5 para as demais variáveis de ambiente).
>
> Todos os pedidos usam `Idempotency-Key` obrigatório (gere com `uuidgen` ou `python3 -c "import uuid;print(uuid.uuid4())"`).
> Substitua `<orderId>` pelo valor de `orderId` retornado no `POST /orders`.

## 1. Caminho feliz com envio (PHYSICAL) → CONFIRMED

```bash
curl -i -X POST http://localhost:8081/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "customerId": "c-demo-1",
    "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL",
    "shippingAddress": { "street": "Av. Paulista", "number": "1000", "complement": null,
      "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": null
  }'

# poll até terminal
curl -s http://localhost:8081/orders/<orderId> | jq .
curl -s http://localhost:8084/shipments/<orderId> | jq .
```

**Esperado**: `202 Accepted` na criação; `GET /orders/{id}` chega a `status=CONFIRMED` com
`history` contendo `INVENTORY/SUCCEEDED`, `PAYMENT/SUCCEEDED`, `SHIPPING/SUCCEEDED`,
`ORDER/CONFIRMED`; `GET /shipments/{id}` retorna `200` com `status=CREATED` e `trackingCode`.

**O que mostrar na demo**: `GET /orders/{id}` com o `history` completo dos 4 passos até
`CONFIRMED`, e o trace no Jaeger (`saga-orchestrator` → `order` → `inventory` → `payment` →
`shipping`) com um único `trace_id` ponta a ponta.

## 2. Pedido sem envio aplicável (DIGITAL) → CONFIRMED sem `shipment.created`

```bash
curl -i -X POST http://localhost:8081/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "customerId": "c-demo-2",
    "items": [ { "sku": "SKU-EBOOK-001", "quantity": 1, "unitPrice": 39.90 } ],
    "deliveryType": "DIGITAL",
    "shippingAddress": null,
    "simulate": null
  }'

curl -s http://localhost:8081/orders/<orderId> | jq .
curl -i http://localhost:8084/shipments/<orderId>   # deve ser 404
```

**Esperado**: `status=CONFIRMED`; `history` sem nenhuma entrada `step=SHIPPING`;
`GET /shipments/{id}` retorna `404` (nenhum `shipment.created` publicado).

**O que mostrar na demo**: `GET /orders/{id}` lado a lado com o do cenário 1 — mesmo fluxo, mas
sem passo `SHIPPING` no `history` — e `GET /shipments/{id}` retornando `404`.

## 3. Falha no pagamento → estoque liberado, pedido cancelado

```bash
curl -s http://localhost:8082/inventory/stock/SKU-BOOK-001 | jq .available   # anote o valor "antes"

curl -i -X POST http://localhost:8081/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "customerId": "c-demo-3",
    "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL",
    "shippingAddress": { "street": "Av. Paulista", "number": "1000", "complement": null,
      "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": { "payment": "DECLINE" }
  }'

curl -s http://localhost:8081/orders/<orderId> | jq '.status, .cancellationReason, .history'
curl -s http://localhost:8082/inventory/reservations/<orderId> | jq .status
curl -s http://localhost:8082/inventory/stock/SKU-BOOK-001 | jq .available   # deve voltar ao valor "antes"
```

**Esperado**: `status=CANCELED`, `cancellationReason=PAYMENT_DECLINED`; `history` mostra
`PAYMENT/FAILED` e `INVENTORY/COMPENSATED` (`detail` contendo `inventory.released`);
`GET /inventory/reservations/{id}` → `status=RELEASED`; estoque volta ao valor original
(nenhum `payment.refund`, pois nada foi autorizado).

**O que mostrar na demo**: `GET /orders/{id}` com `cancellationReason=PAYMENT_DECLINED` e
`INVENTORY/COMPENSATED` no `history`; `GET /inventory/stock/{sku}` antes/depois mostrando o
estoque restaurado.

## 4. Falha no envio → estorno + liberação + cancelamento

```bash
curl -i -X POST http://localhost:8081/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "customerId": "c-demo-4",
    "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL",
    "shippingAddress": { "street": "Av. Paulista", "number": "1000", "complement": null,
      "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": { "shipping": "FAIL" }
  }'

curl -s http://localhost:8081/orders/<orderId> | jq '.status, .cancellationReason'
curl -s http://localhost:8083/payments/<orderId> | jq .status      # REFUNDED
curl -s http://localhost:8082/inventory/reservations/<orderId> | jq .status  # RELEASED
```

**Esperado**: `status=CANCELED`, `cancellationReason=SHIPMENT_FAILED`; pagamento `REFUNDED`;
reserva `RELEASED`; estoque restaurado.

**O que mostrar na demo**: `GET /orders/{id}` com a cadeia completa de compensação no `history`
(`SHIPPING/FAILED` → `PAYMENT/COMPENSATED` → `INVENTORY/COMPENSATED`) e `GET /payments/{id}`
mostrando `status=REFUNDED`.

## 5. Timeout numa etapa (pagamento) → retries e depois compensação

```bash
curl -i -X POST http://localhost:8081/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "customerId": "c-demo-5",
    "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL",
    "shippingAddress": { "street": "Av. Paulista", "number": "1000", "complement": null,
      "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": { "payment": "TIMEOUT" }
  }'

# aguarde ~20-30s (defaults: 3 tentativas x 5s + backoff) e faça poll:
watch -n1 "curl -s http://localhost:8081/orders/<orderId> | jq '.status, .history'"
curl -s http://localhost:8083/payments/<orderId> | jq .status      # REFUNDED (autorização real estornada)
```

**Esperado**: `history` mostra `PAYMENT/TIMED_OUT` (uma ou mais tentativas), depois
`PAYMENT/COMPENSATED`/`INVENTORY/COMPENSATED`; `status=CANCELED`,
`cancellationReason=STEP_TIMEOUT`; `payment-service` retorna `status=REFUNDED` porque o
`simulate.payment=TIMEOUT` **autoriza de fato** mas nunca responde — o refund estorna uma
autorização real (`noop=false`).

Variante para mostrar o retry **bem-sucedido** (sem compensação): troque `"payment": "TIMEOUT"`
por `"payment": "TIMEOUT_ONCE"` — a 1ª tentativa não responde, a 2ª (mesmo `messageId`) responde
normalmente, e o pedido chega a `CONFIRMED`.

**O que mostrar na demo**: `GET /orders/{id}` com `PAYMENT/TIMED_OUT` no `history` antes da
compensação, e o painel Grafana com o contador `saga_timeouts_total{step="PAYMENT"}` subindo
(`docs/observability.md` §5).

## 6. Reinício do coordenador no meio da saga → retomada sem duplicar efeito

```bash
curl -i -X POST http://localhost:8081/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "customerId": "c-demo-6",
    "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL",
    "shippingAddress": { "street": "Av. Paulista", "number": "1000", "complement": null,
      "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": { "payment": "SLOW" }
  }'

# em seguida, ainda com a saga em andamento (SIMULATE_SLOW_MS=2000 por padrão):
docker compose kill saga-orchestrator
docker compose up -d saga-orchestrator
# aguarde o healthcheck voltar (make ps) e faça poll:
curl -s http://localhost:8081/orders/<orderId> | jq '.status, .history'
curl -s http://localhost:8083/payments/<orderId> | jq .
```

Atalho equivalente já embrulhado no `Makefile`: `make kill-orchestrator`.

**Esperado**: `status=CONFIRMED`; no `history`, **exatamente uma** entrada
`step=PAYMENT, status=SUCCEEDED` (sem autorização duplicada) — o estado da saga está 100% em
Postgres e o offset do Kafka só avança após o commit, então a retomada consome a resposta que
ficou pendente sem reenviar o comando. Pular com `SKIP_RESTART=1` se não houver Docker disponível.

**O que mostrar na demo**: `GET /sagas?orderId={id}` com `RESUMED_AFTER_RESTART` no `log`, e
`GET /orders/{id}` chegando em `CONFIRMED` com só uma entrada `PAYMENT/SUCCEEDED` no `history`
(prova de que o restart não duplicou a autorização de pagamento).

## 7. Idempotência: mesmo `Idempotency-Key` duas vezes

```bash
KEY=$(uuidgen)
BODY='{
  "customerId": "c-demo-7",
  "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
  "deliveryType": "PHYSICAL",
  "shippingAddress": { "street": "Av. Paulista", "number": "1000", "complement": null,
    "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
  "simulate": null
}'

curl -s http://localhost:8082/inventory/stock/SKU-BOOK-001 | jq .available   # "antes"

curl -i -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $KEY" -d "$BODY"        # 202, orderId=X

curl -i -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $KEY" -d "$BODY"        # 200, header Idempotent-Replayed: true, mesmo orderId=X

curl -s http://localhost:8082/inventory/stock/SKU-BOOK-001 | jq .available   # "antes" - 1 (reduziu só uma vez)
```

**Esperado**: 1ª chamada `202 Accepted`; 2ª chamada `200 OK` com header
`Idempotent-Replayed: true` e o **mesmo** `orderId`; estoque reduz apenas uma unidade no total
(a segunda chamada não dispara uma nova saga). Bônus: repetir com o mesmo `Idempotency-Key` e
corpo **diferente** deve retornar `409 Conflict`.

**O que mostrar na demo**: as duas respostas HTTP lado a lado (`202` vs `200` +
`Idempotent-Replayed: true`, mesmo `orderId`) e `GET /inventory/stock/{sku}` mostrando que só
caiu uma unidade apesar das duas chamadas.

## 8. D1: listar pedidos de um cliente (`GET /orders?customerId=&limit=`, ADR-006)

```bash
CUST="c-demo-d1-$(uuidgen)"

# 3 pedidos do mesmo cliente: DIGITAL feliz, PHYSICAL feliz, PHYSICAL com payment DECLINE.
curl -s -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" -d "{\"customerId\":\"$CUST\",\"items\":[{\"sku\":\"SKU-EBOOK-001\",\"quantity\":1,\"unitPrice\":39.90}],\"deliveryType\":\"DIGITAL\",\"shippingAddress\":null,\"simulate\":null}" | jq .orderId

curl -s -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" -d "{\"customerId\":\"$CUST\",\"items\":[{\"sku\":\"SKU-BOOK-001\",\"quantity\":1,\"unitPrice\":49.90}],\"deliveryType\":\"PHYSICAL\",\"shippingAddress\":{\"street\":\"Av. Paulista\",\"number\":\"1000\",\"complement\":null,\"city\":\"Sao Paulo\",\"state\":\"SP\",\"zipCode\":\"01310-100\",\"country\":\"BR\"},\"simulate\":null}" | jq .orderId

curl -s -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" -d "{\"customerId\":\"$CUST\",\"items\":[{\"sku\":\"SKU-BOOK-001\",\"quantity\":1,\"unitPrice\":49.90}],\"deliveryType\":\"PHYSICAL\",\"shippingAddress\":{\"street\":\"Av. Paulista\",\"number\":\"1000\",\"complement\":null,\"city\":\"Sao Paulo\",\"state\":\"SP\",\"zipCode\":\"01310-100\",\"country\":\"BR\"},\"simulate\":{\"payment\":\"DECLINE\"}}" | jq .orderId

# poll os 3 até estado terminal (CONFIRMED, CONFIRMED, CANCELED), depois:
curl -s "http://localhost:8081/orders?customerId=$CUST" | jq .                       # 3 itens, mais recente -> mais antigo
curl -s "http://localhost:8081/orders?customerId=$CUST&limit=2" | jq .               # só os 2 mais recentes
curl -i "http://localhost:8081/orders?customerId=cliente-sem-pedidos-$(uuidgen)"     # 200, []
curl -i "http://localhost:8081/orders"                                              # 400 (sem customerId)
```

**Esperado**: `GET /orders?customerId=` retorna array com os 3 pedidos ordenados por
`createdAt desc` (desempate `orderId desc`), cada item com `orderId`, `status`, `totalAmount`,
`deliveryType`, `createdAt`, `cancellationReason` (`null` exceto no `CANCELED`); `limit=2` retorna
só os 2 mais recentes na mesma ordem; cliente sem pedidos retorna `200` com `[]` (nunca `404`);
requisição sem `customerId` retorna `400` (problem+json, `docs/contracts/api.md` §1).

**O que mostrar na demo**: `GET /orders?customerId={id}` com os 3 pedidos na ordem correta
(mais recente primeiro) lado a lado com `limit=2`, e o `400` da chamada sem `customerId`.

## 9. D6: timeout no estoque → libera reserva, cancela (sem pagamento nem envio)

```bash
curl -i -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" -d '{
    "customerId": "c-demo-9", "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL", "shippingAddress": { "street": "Av. Paulista", "number": "1000",
      "complement": null, "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": { "inventory": "TIMEOUT" } }'

curl -s http://localhost:8081/orders/<orderId> | jq '.status, .cancellationReason, .history'
curl -s http://localhost:8082/inventory/reservations/<orderId> | jq .        # RELEASED, noop=false
curl -i http://localhost:8083/payments/<orderId>                            # 404 (nunca autorizou)
curl -i http://localhost:8084/shipments/<orderId>                           # 404 (nunca criou envio)
```

**Esperado**: `status=CANCELED`, `cancellationReason=STEP_TIMEOUT`; `history` com `INVENTORY/TIMED_OUT` e
`INVENTORY/COMPENSATED`; reserva `RELEASED` (`noop=false`); estoque restaurado; nenhum pagamento nem envio.

**O que mostrar na demo**: `GET /orders/{id}` mostrando que a Saga nunca chegou a `PAYMENT`/`SHIPPING` — só
`INVENTORY` aparece no `history` antes do cancelamento, e o painel Grafana com `saga_timeouts_total{step="INVENTORY"}`.

## 10. D6: timeout no envio → cancela envio, estorna pagamento, libera estoque (compensação de 3 passos)

```bash
curl -i -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" -d '{
    "customerId": "c-demo-10", "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL", "shippingAddress": { "street": "Av. Paulista", "number": "1000",
      "complement": null, "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": { "shipping": "TIMEOUT" } }'

curl -s http://localhost:8081/orders/<orderId> | jq '.status, .cancellationReason, .history'
curl -s http://localhost:8084/shipments/<orderId> | jq .    # CANCELED, noop=false
curl -s http://localhost:8083/payments/<orderId> | jq .     # REFUNDED
curl -s http://localhost:8082/inventory/reservations/<orderId> | jq .status  # RELEASED
```

**Esperado**: `status=CANCELED`, `STEP_TIMEOUT`; `history` na ordem `SHIPPING/TIMED_OUT` → `SHIPPING/COMPENSATED`
→ `PAYMENT/COMPENSATED` → `INVENTORY/COMPENSATED`; shipment `CANCELED` (`noop=false`); payment `REFUNDED`;
reserva `RELEASED`; estoque restaurado — a compensação de 3 passos completa (o maior "efeito dominó" da suíte).

**O que mostrar na demo**: a linha do tempo/trace no Jaeger mostrando os 3 comandos de compensação em cadeia
(`shipment.cancel` → `payment.refund` → `inventory.release`) disparados por um único timeout.

## 11. D6: timeout só na 1ª tentativa (retry com sucesso) → CONFIRMED

```bash
curl -i -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" -d '{
    "customerId": "c-demo-11", "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL", "shippingAddress": { "street": "Av. Paulista", "number": "1000",
      "complement": null, "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": { "payment": "TIMEOUT_ONCE" } }'

curl -s http://localhost:8081/orders/<orderId> | jq '.status, .history'
curl -s http://localhost:8083/payments/<orderId> | jq .    # AUTHORIZED, noop=false
```

**Esperado**: `history` com `PAYMENT/TIMED_OUT` (`attempt=1`) seguido de `PAYMENT/SUCCEEDED` (`attempt=2`);
`status=CONFIRMED`; **uma só** autorização real; `shipment=CREATED`. Prova que o retry com o mesmo `messageId`
recupera a Saga sem compensar nem duplicar efeito.

**O que mostrar na demo**: `GET /orders/{id}` com as duas entradas de `PAYMENT` lado a lado (tentativa 1
falhou por timeout, tentativa 2 teve sucesso) — o "retry que funciona", contraponto do cenário 5 (timeout
que esgota as tentativas).

## 12. D6: rastreabilidade ponta a ponta — um trace, 5 serviços, via API do Jaeger

```bash
TRACE_ID=$(python3 -c "import secrets;print(secrets.token_hex(16))")
SPAN_ID=$(python3 -c "import secrets;print(secrets.token_hex(8))")
curl -i -X POST http://localhost:8081/orders -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" -H "traceparent: 00-$TRACE_ID-$SPAN_ID-01" -d '{
    "customerId": "c-demo-12", "items": [ { "sku": "SKU-BOOK-001", "quantity": 1, "unitPrice": 49.90 } ],
    "deliveryType": "PHYSICAL", "shippingAddress": { "street": "Av. Paulista", "number": "1000",
      "complement": null, "city": "Sao Paulo", "state": "SP", "zipCode": "01310-100", "country": "BR" },
    "simulate": null }'

# depois de CONFIRMED:
curl -s "http://localhost:16686/api/traces/$TRACE_ID" | jq '.data[0].processes | to_entries[].value.serviceName'
```

**Esperado**: exatamente 1 trace com esse id; `processes[*].serviceName` contém os 5 serviços
(`order-service`, `saga-orchestrator`, `inventory-service`, `payment-service`, `shipping-service`) —
o `traceparent` enviado no `POST` é continuado pelo agente OTel de cada serviço via Kafka/HTTP.

**O que mostrar na demo**: abrir `http://localhost:16686/trace/<traceId>` no navegador — a cachoeira
(waterfall) com os 5 serviços em ordem, prova visual da rastreabilidade ponta a ponta exigida pelo desafio.

## Diagnóstico complementar (todos os cenários)

- Trace ponta a ponta: `http://localhost:16686/search?service=saga-orchestrator&tags={"orderId":"<id>"}`
  (Jaeger; ver `docs/observability.md` §5 para o que procurar em cada cenário).
- Estado da saga: `GET http://localhost:8080/sagas?orderId=<id>` (log de transições, `saga_step_log`).
- Métricas: `curl -s http://localhost:8080/actuator/prometheus | grep saga_`.
