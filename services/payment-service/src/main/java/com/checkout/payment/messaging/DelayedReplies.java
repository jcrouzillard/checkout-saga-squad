package com.checkout.payment.messaging;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.observability.SagaMdc;
import com.checkout.common.observability.TraceContext;
import com.checkout.common.outbox.OutboxWriter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.List;

/**
 * Resposta atrasada de {@code simulate.payment=SLOW} (events.md §3) sem {@code Thread.sleep}: o handler grava a
 * resposta em {@code delayed_replies} com {@code due_at = now() + slow-ms} (mesma transação do efeito) e este
 * agendador a move para o outbox quando vence, restaurando o {@code traceparent} original.
 */
@Component
public class DelayedReplies {

    private static final Logger log = LoggerFactory.getLogger(DelayedReplies.class);

    record Row(long id, String topic, String envelope, String traceParent) {}

    private final JdbcClient jdbc;
    private final OutboxWriter outbox;
    private final MessageFactory messages;
    private final TransactionTemplate tx;

    public DelayedReplies(JdbcClient jdbc, OutboxWriter outbox, MessageFactory messages, TransactionTemplate tx) {
        this.jdbc = jdbc;
        this.outbox = outbox;
        this.messages = messages;
        this.tx = tx;
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public void schedule(String topic, MessageEnvelope envelope, long delayMs) {
        jdbc.sql("""
                INSERT INTO delayed_replies (topic, envelope, trace_parent, due_at)
                VALUES (:topic, :envelope, :traceParent, now() + (:ms * INTERVAL '1 millisecond'))
                """)
                .param("topic", topic)
                .param("envelope", messages.write(envelope))
                .param("traceParent", TraceContext.currentTraceparent())
                .param("ms", delayMs)
                .update();
    }

    @Scheduled(fixedDelayString = "${checkout.simulate.delayed-reply-poll-ms:100}")
    public void publishDue() {
        try {
            tx.executeWithoutResult(status -> {
                List<Row> due = jdbc.sql("""
                        SELECT id, topic, envelope, trace_parent FROM delayed_replies
                        WHERE due_at <= now() ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED
                        """)
                        .query((rs, n) -> new Row(rs.getLong("id"), rs.getString("topic"), rs.getString("envelope"),
                                rs.getString("trace_parent")))
                        .list();
                for (Row row : due) {
                    MessageEnvelope env = messages.read(row.envelope());
                    try (var mdc = SagaMdc.of(env)) {
                        TraceContext.runWith(row.traceParent(), () -> outbox.publish(row.topic(), env));
                        log.info("simulate.payment=SLOW → resposta {} liberada para o outbox", env.type());
                    }
                    jdbc.sql("DELETE FROM delayed_replies WHERE id = :id").param("id", row.id()).update();
                }
            });
        } catch (Exception e) {
            log.warn("Falha ao liberar respostas atrasadas; nova tentativa no próximo ciclo: {}", e.toString());
        }
    }
}
