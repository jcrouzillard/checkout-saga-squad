"""D16 (`841f9a27e64a`) — corpus SINTÉTICO de logs do Spring Boot no formato real do produtivo (QA).

Formato conferido (somente leitura) em `docker logs checkout-saga-*-1`: logback estruturado ECS 8.11 do Spring Boot 3.4
(`@timestamp`, `log.level`, `process.thread.name`, `service.name`, `log.logger`, `message`, `error.type`,
`error.message`, `error.stack_trace`, MDC `orderId`/`sagaId`/`correlationId`, `trace_id`/`span_id` do OTel), prefixo
`<servico>-1  | ` do `docker compose logs`. Payloads como em `docs/contracts/events.md` §4 (order.created com
`customerId` e `shippingAddress`), toString de `record Address` (services/shipping-service/.../Address.java), SQL do
`OutboxRelay` e dump do `ProducerConfig`. **Nenhum dado real**: todos os valores abaixo são inventados.

Usado por `tests/squad/test_bugs_d16_qa.py` (máscara e prévia = arquivo gravado) e por `tests/ui/d16_simulados.py`
(executor `docker compose logs` simulado do fluxo de UI).
"""
import json

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
ORDER_ID = "2c21ea15-924e-48c1-b409-cc6ccdf475c6"
SAGA_ID = "490195fd-74c5-431f-9544-7b43e8ae2b45"
CUSTOMER = "c-9f31a7"

PAYLOAD = {"customerId": CUSTOMER, "deliveryType": "PHYSICAL",
           "items": [{"sku": "SKU-BOOK-001", "quantity": 2, "unitPrice": 49.90}], "totalAmount": 99.80, "currency": "BRL",
           "shippingAddress": {"street": "Rua das Acacias Ficticias", "number": "4521", "complement": "ap 87",
                               "city": "Cidade Inventada", "state": "SP", "zipCode": "04567-321", "country": "BR"},
           "simulate": None, "createdAt": "2026-09-24T12:00:00.100Z"}
ENVELOPE = {"messageId": "7d0c1b52-0f1e-4a57-9d8c-0a1b2c3d4e5f", "type": "order.created", "orderId": ORDER_ID,
            "sagaId": SAGA_ID, "causationId": None, "payload": json.dumps(PAYLOAD)}
ADDRESS_TOSTRING = ("Address[street=Rua das Acacias Ficticias, number=4521, complement=ap 87, city=Cidade Inventada, "
                    "state=SP, zipCode=04567-321, country=BR]")

# valores que NÃO podem sobrar no arquivo mascarado (e no git)
SENSITIVE = [CUSTOMER, "Rua das Acacias Ficticias", "04567-321", "ap 87", "ana.ficticia@exemplo.com.br",
             "kafka-s3cr3t-inventado", "pg-s3cr3t-inventado", "hunter2-inventado", "tok_live_inventado",
             "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbmEifQ.c2lnbmF0dXJh", "529.982.247-25", "4111 1111 1111 1111",
             "Ana Ficticia Souza", "cvv-999", "pin-4321", "frase secreta inventada", "8.8.4.4"]
# o que precisa sobrar (diagnóstico): ids opacos, SKU, frames e tipos de exceção
PRESERVED = [ORDER_ID, SAGA_ID, TRACE_ID, "SKU-BOOK-001", "java.lang.IllegalStateException",
             "\\tat com.checkout.shipping.messaging.ShippingCommandHandler.handle(ShippingCommandHandler.java:70)",
             "com.checkout.common.outbox.OutboxRelay.publishBatch(OutboxRelay.java:62)", "FOR UPDATE SKIP LOCKED",
             "10.0.3.7"]


def ecs(ts, level, svc, logger, message, thread="http-nio-8081-exec-3", **extra):
    d = {"@timestamp": ts, "log.level": level, "process.pid": 1, "process.thread.name": thread, "service.name": svc,
         "service.version": "1.1.0-SNAPSHOT", "log.logger": logger, "message": message, **extra,
         "orderId": ORDER_ID, "sagaId": SAGA_ID, "trace_id": TRACE_ID, "trace_flags": "01", "span_id": "7906ecf654862f47",
         "ecs.version": "8.11"}
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def lines() -> list[str]:
    """Linhas de aplicação (JSON ECS), uma por evento; sem o prefixo do compose."""
    stack = (f"java.lang.IllegalStateException: endereço inválido: {ADDRESS_TOSTRING}\n"
             "\tat com.checkout.shipping.messaging.ShippingCommandHandler.handle(ShippingCommandHandler.java:70)\n"
             "\tat org.springframework.kafka.listener.KafkaMessageListenerContainer$ListenerConsumer.doInvokeRecordListener"
             "(KafkaMessageListenerContainer.java:2800)\n")
    sql_stack = ("org.springframework.dao.DataAccessResourceFailureException: PreparedStatementCallback; SQL [SELECT id, "
                 "payload::text AS payload FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT ? FOR UPDATE SKIP LOCKED\n"
                 "]; FATAL: terminating connection\n\tat com.checkout.common.outbox.OutboxRelay.publishBatch(OutboxRelay.java:62)\n")
    return [
        ecs("2026-09-24T12:00:00.101Z", "INFO", "order-service", "com.checkout.order.domain.OrderService",
            f"Pedido criado orderId={ORDER_ID} sagaId={SAGA_ID} deliveryType=PHYSICAL total=99.80 customerId={CUSTOMER}"),
        # payload do outbox logado como texto: JSON escapado 1 vez dentro do JSON do logback
        ecs("2026-09-24T12:00:00.120Z", "DEBUG", "order-service", "com.checkout.common.outbox.OutboxRelay",
            f"Publicando outbox id=42 topic=order.events key={ORDER_ID} payload={json.dumps(PAYLOAD, ensure_ascii=False)}",
            thread="scheduling-1"),
        # ConsumerRecord com o envelope cujo payload é JSON-string: escapado 2 vezes
        ecs("2026-09-24T12:00:00.300Z", "ERROR", "saga-orchestrator", "org.springframework.kafka.listener.DefaultErrorHandler",
            "Backoff FixedBackOff exhausted for ConsumerRecord(topic = order.events, partition = 0, offset = 17, "
            f"key = {ORDER_ID}, value = {json.dumps(ENVELOPE, ensure_ascii=False)})",
            thread="org.springframework.kafka.KafkaListenerEndpointContainer#0-0-C-1"),
        # stack trace com o toString do record Address
        ecs("2026-09-24T12:00:00.420Z", "ERROR", "shipping-service",
            "com.checkout.shipping.messaging.ShippingCommandHandler", "Falha ao processar shipment.create",
            thread="org.springframework.kafka.KafkaListenerEndpointContainer#0-0-C-1",
            **{"error.type": "java.lang.IllegalStateException", "error.message": f"endereço inválido: {ADDRESS_TOSTRING}",
               "error.stack_trace": stack}),
        # SQL com aspas simples (toString / JDBC) e SQL do OutboxRelay
        ecs("2026-09-24T12:00:00.500Z", "ERROR", "payment-service", "org.springframework.jdbc.core.JdbcTemplate",
            "PreparedStatementCallback; bad SQL grammar [INSERT INTO payments (order_id, contact) VALUES "
            f"('{ORDER_ID}', 'ana.ficticia@exemplo.com.br')]", **{"error.stack_trace": sql_stack}),
        ecs("2026-09-24T12:00:00.510Z", "WARN", "payment-service", "com.checkout.payment.messaging.PaymentCommandHandler",
            f"AuthorizePayment{{customerId='{CUSTOMER}', cardHolder='x', password='hunter2-inventado', "
            "cardToken='tok_live_inventado', cvv='cvv-999', pin='pin-4321', passphrase='frase secreta inventada'}"),
        # dump do ProducerConfig (Kafka) e URL JDBC com credencial
        ecs("2026-09-24T12:00:00.600Z", "INFO", "order-service", "org.apache.kafka.clients.producer.ProducerConfig",
            "ProducerConfig values: \n\tacks = -1\n\tbootstrap.servers = [kafka:9092]\n\tssl.key.password = null\n\t"
            "sasl.jaas.config = org.apache.kafka.common.security.plain.PlainLoginModule required username=\"app\" "
            "password=\"kafka-s3cr3t-inventado\";\n", thread="scheduling-3"),
        ecs("2026-09-24T12:00:00.700Z", "INFO", "order-service", "com.zaxxer.hikari.HikariDataSource",
            "HikariPool-1 - url=jdbc:postgresql://app:pg-s3cr3t-inventado@postgres:5432/orders peer=10.0.3.7 edge=8.8.4.4"),
        ecs("2026-09-24T12:00:00.800Z", "DEBUG", "order-service", "org.apache.coyote.http11.Http11Processor",
            "headers={authorization=[Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbmEifQ.c2lnbmF0dXJh], x-request-id=[r-1]} "
            "customerName=\"Ana Ficticia Souza\" cpf=529.982.247-25 card=4111 1111 1111 1111"),
        # tentativa de XSS no texto do log (CA-17: a UI mostra como texto)
        ecs("2026-09-24T12:00:00.900Z", "WARN", "order-service", "com.checkout.order.api.OrderController",
            "valor recebido <img src=x onerror=\"window.__xss=1\"> ignorado"),
    ]


def compose_output(trace_id: str = TRACE_ID) -> str:
    """Saída de `docker compose -p checkout-saga logs --no-color ...` (prefixo do compose + JSON)."""
    out = []
    for ln in lines():
        svc = json.loads(ln)["service.name"]
        out.append(f"{svc}-1  | {ln.replace(TRACE_ID, trace_id)}")
    out.append('order-service-1  | {"@timestamp":"2026-09-24T12:00:01Z","log.level":"INFO","message":"outro trace",'
               '"trace_id":"ffffffffffffffffffffffffffffffff"}')
    return "\n".join(out) + "\n"
