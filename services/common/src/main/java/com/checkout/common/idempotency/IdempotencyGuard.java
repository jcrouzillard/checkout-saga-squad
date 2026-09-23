package com.checkout.common.idempotency;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/**
 * Consumo idempotente (events.md §5.1): {@code INSERT INTO processed_messages ... ON CONFLICT DO NOTHING}
 * na MESMA transação do handler. {@code false} ⇒ mensagem já processada (duplicata).
 */
public class IdempotencyGuard {

    private final JdbcClient jdbc;
    private final String defaultConsumer;

    public IdempotencyGuard(JdbcClient jdbc, String defaultConsumer) {
        this.jdbc = jdbc;
        this.defaultConsumer = defaultConsumer;
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public boolean tryMarkProcessed(UUID messageId) {
        return tryMarkProcessed(messageId, defaultConsumer);
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public boolean tryMarkProcessed(UUID messageId, String consumer) {
        return jdbc.sql("""
                INSERT INTO processed_messages (message_id, consumer, processed_at) VALUES (:id, :consumer, now())
                ON CONFLICT DO NOTHING
                """)
                .param("id", messageId)
                .param("consumer", consumer)
                .update() == 1;
    }
}
