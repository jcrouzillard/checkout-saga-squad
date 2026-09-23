# common — lib compartilhada (`com.checkout:common`)

Auto-configurada (`CheckoutCommonAutoConfiguration` + `CommonEnvironmentPostProcessor`): basta a dependência
`<dependency><groupId>com.checkout</groupId><artifactId>common</artifactId></dependency>` (versão gerida pelo pom raiz).
Traz transitivamente web, actuator, jdbc (**JdbcClient**), validation, spring-kafka, flyway(+postgresql), driver, prometheus, OTel API.

## application.yml mínimo do serviço
```yaml
spring.application.name: payment-service   # = group id Kafka, source do envelope, consumer do dedupe
server.port: ${SERVER_PORT:8083}
checkout.simulate.slow-ms: ${SIMULATE_SLOW_MS:2000}   # (participantes) exemplo de env var própria
```
Já vêm como default (sobrescrevíveis): Kafka `enable-auto-commit=false`, `ack-mode=record`, `auto-offset-reset=earliest`,
String (de)serializers, producer `acks=all` + idempotência; `management.*` e `logging.structured.format.console=ecs`
(docs/observability.md); `OUTBOX_POLL_INTERVAL_MS`/`OUTBOX_BATCH_SIZE`; `spring.flyway.locations=classpath:db/common,classpath:db/migration`.
Datasource/Kafka: só `SPRING_DATASOURCE_*`/`SPRING_KAFKA_BOOTSTRAP_SERVERS` (compose). Todos os 9 tópicos são criados (3 partições).

## Flyway
A lib fornece `db/common/V0_1__outbox_and_processed_messages.sql` (`outbox` + `processed_messages`, saga.md §3.1).
O serviço coloca as suas em `src/main/resources/db/migration/` começando em **`V1__`** (ex.: `V1__schema.sql`,
`V2__seed_stock.sql` como pede api.md §4). Não use a versão 0.1.

## API
- `MessageEnvelope` (record, events.md §2), `Simulate` (§3, constantes + `ALLOWED`), `Topics` / `Topics.Types` (nomes exatos).
- `MessageFactory`: `read(String)` (JSON inválido → `MalformedMessageException` → DLT após 3 tentativas),
  `payload(env, Record.class)`, `create(...)`, `replyTo(cmd, type, payload)` (novo messageId, `causationId = cmd.messageId`).
- `OutboxWriter.publish(topic, envelope)` — exige transação ativa (`MANDATORY`); grava `trace_parent`. O `OutboxRelay`
  (@Scheduled) publica com key=orderId e header `traceparent`. **Nunca** use `KafkaTemplate.send` no negócio.
- `IdempotencyGuard.tryMarkProcessed(messageId)` — `INSERT ... ON CONFLICT DO NOTHING`; `false` = duplicata. Exige transação.
- `SagaMdc.of(envelope)` (try-with-resources: orderId/sagaId/messageId). `TraceContext` (captura/restaura traceparent).
- `ApiException.notFound("...")`/`badRequest(...)` → problem+json via `ProblemDetailsAdvice` (auto-registrado).
- `CorrelationIdFilter.current(request)` — `X-Correlation-Id` (gerado se ausente, ecoado na resposta).
- Error handler: exceções transitórias (ex.: banco) → retry exponencial sem limite; venenosas → `<tópico>.DLT`.

## Handler de comando idempotente (re-publica a resposta em duplicata — events.md §5.2)
```java
@KafkaListener(topics = Topics.PAYMENT_COMMANDS)
@Transactional   // offset só é confirmado após o commit (ack RECORD)
public void onCommand(String value) {
    MessageEnvelope cmd = messages.read(value);
    try (var mdc = SagaMdc.of(cmd)) {
        boolean first = idempotency.tryMarkProcessed(cmd.messageId());
        switch (cmd.type()) {
            case Topics.Types.PAYMENT_AUTHORIZE -> {
                var p = messages.payload(cmd, AuthorizeCommand.class);
                Payment pay = repo.findByOrderId(cmd.orderId())            // UNIQUE(order_id): 1 por pedido
                        .orElseGet(() -> repo.authorize(cmd.orderId(), p));  // executa só se não existir
                pay = repo.incrementAttempts(pay);                           // p/ TIMEOUT_ONCE
                if (shouldReply(p.simulate(), pay.attempts()))               // TIMEOUT: nunca; TIMEOUT_ONCE: a partir da 2ª
                    outbox.publish(Topics.PAYMENT_EVENTS, messages.replyTo(cmd, resultType(pay), resultPayload(pay)));
            }
            case Topics.Types.PAYMENT_REFUND -> { /* tombstone se não houver pagamento; noop=true */ }
            default -> log.warn("Tipo desconhecido ignorado: {}", cmd.type());
        }
    }
}
```
`first=false` (retry com o mesmo messageId) ⇒ não reexecuta o efeito, apenas re-publica a partir do estado persistido.
Compensações e simulações nunca se misturam (events.md §3). `SLOW`: use `checkout.simulate.slow-ms`.
