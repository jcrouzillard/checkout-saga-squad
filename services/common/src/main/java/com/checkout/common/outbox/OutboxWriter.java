package com.checkout.common.outbox;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.observability.TraceContext;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Grava a mensagem na tabela {@code outbox} na MESMA transação do chamador (ADR-002).
 * Nunca chame {@code kafkaTemplate.send} em código de negócio — use este writer.
 * Captura o {@code traceparent} do span atual na coluna {@code trace_parent} (reaplicado pelo relay).
 */
public class OutboxWriter {

    private final JdbcClient jdbc;
    private final MessageFactory messages;

    public OutboxWriter(JdbcClient jdbc, MessageFactory messages) {
        this.jdbc = jdbc;
        this.messages = messages;
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public void publish(String topic, MessageEnvelope envelope) {
        jdbc.sql("""
                INSERT INTO outbox (message_id, topic, message_key, type, payload, trace_parent, created_at)
                VALUES (:messageId, :topic, :key, :type, CAST(:payload AS jsonb), :traceParent, now())
                """)
                .param("messageId", envelope.messageId())
                .param("topic", topic)
                .param("key", envelope.key())
                .param("type", envelope.type())
                .param("payload", messages.write(envelope))
                .param("traceParent", TraceContext.currentTraceparent())
                .update();
    }
}
