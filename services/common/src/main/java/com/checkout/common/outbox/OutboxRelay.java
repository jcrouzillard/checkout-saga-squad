package com.checkout.common.outbox;

import com.checkout.common.observability.SagaMdc;
import com.checkout.common.observability.TraceContext;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Relay por polling (saga.md §3.3): lê linhas pendentes em ordem ({@code FOR UPDATE SKIP LOCKED}), publica no Kafka
 * com key = orderId e header {@code traceparent} restaurado da linha, e marca {@code published_at}.
 * Falha de envio interrompe o lote (preserva ordem) e a linha é retentada no próximo ciclo. At-least-once.
 */
public class OutboxRelay {

    private static final Logger log = LoggerFactory.getLogger(OutboxRelay.class);

    private final JdbcClient jdbc;
    private final KafkaTemplate<String, String> kafka;
    private final TransactionTemplate tx;
    private final int batchSize;

    public OutboxRelay(JdbcClient jdbc, KafkaTemplate<String, String> kafka, TransactionTemplate tx, int batchSize) {
        this.jdbc = jdbc;
        this.kafka = kafka;
        this.tx = tx;
        this.batchSize = batchSize;
    }

    record Row(long id, String messageId, String topic, String messageKey, String type, String payload,
               String traceParent) {}

    @Scheduled(fixedDelayString = "${checkout.outbox.poll-interval-ms:200}")
    public void relay() {
        try {
            Integer published;
            do {
                published = tx.execute(status -> publishBatch());
            } while (published != null && published == batchSize);
        } catch (Exception e) {
            log.warn("Relay do outbox falhou; nova tentativa no próximo ciclo: {}", e.toString());
        }
    }

    private int publishBatch() {
        List<Row> rows = jdbc.sql("""
                SELECT id, message_id::text AS message_id, topic, message_key, type, payload::text AS payload, trace_parent
                FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED
                """)
                .param("limit", batchSize)
                .query((rs, n) -> new Row(rs.getLong("id"), rs.getString("message_id"), rs.getString("topic"),
                        rs.getString("message_key"), rs.getString("type"), rs.getString("payload"),
                        rs.getString("trace_parent")))
                .list();
        int ok = 0;
        for (Row row : rows) {
            try {
                send(row);
            } catch (Exception e) {
                jdbc.sql("UPDATE outbox SET publish_attempts = publish_attempts + 1 WHERE id = :id")
                        .param("id", row.id()).update();
                log.warn("Falha ao publicar outbox id={} type={} topic={}: {}", row.id(), row.type(), row.topic(),
                        e.toString());
                return -1; // interrompe o lote para preservar a ordem
            }
            jdbc.sql("UPDATE outbox SET published_at = now(), publish_attempts = publish_attempts + 1 WHERE id = :id")
                    .param("id", row.id()).update();
            ok++;
        }
        return ok;
    }

    private void send(Row row) throws Exception {
        ProducerRecord<String, String> record = new ProducerRecord<>(row.topic(), row.messageKey(), row.payload());
        record.headers().add("type", row.type().getBytes(StandardCharsets.UTF_8));
        if (row.traceParent() != null) {
            record.headers().add("traceparent", row.traceParent().getBytes(StandardCharsets.UTF_8));
        }
        try (var mdc = new SagaMdcScope(row)) {
            // O contexto restaurado torna o span de "publish" do agente OTel filho do span que gravou a linha.
            TraceContext.callWith(row.traceParent(), () -> {
                try {
                    return kafka.send(record).get(10, TimeUnit.SECONDS);
                } catch (Exception e) {
                    throw new IllegalStateException(e);
                }
            });
            log.debug("Outbox publicado id={} type={} topic={} traceparent={}", row.id(), row.type(), row.topic(),
                    row.traceParent());
        }
    }

    /** MDC mínimo (orderId = key) para correlacionar logs do relay. */
    private static final class SagaMdcScope implements AutoCloseable {
        private final SagaMdc mdc;

        SagaMdcScope(Row row) {
            this.mdc = SagaMdc.of(null, null).with(SagaMdc.ORDER_ID, row.messageKey())
                    .with(SagaMdc.MESSAGE_ID, row.messageId());
        }

        @Override
        public void close() {
            mdc.close();
        }
    }
}
