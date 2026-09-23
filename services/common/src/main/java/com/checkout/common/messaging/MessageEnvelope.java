package com.checkout.common.messaging;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.Instant;
import java.util.UUID;

/**
 * Envelope padrão de toda mensagem Kafka (docs/contracts/events.md §2).
 * O payload fica como {@link JsonNode}; use {@link MessageFactory#payload(MessageEnvelope, Class)} para tipá-lo.
 */
public record MessageEnvelope(
        UUID messageId,
        String type,
        int version,
        String source,
        Instant occurredAt,
        UUID sagaId,
        UUID orderId,
        UUID correlationId,
        UUID causationId,
        JsonNode payload) {

    public static final int CURRENT_VERSION = 1;

    /** Chave de partição Kafka (= orderId). */
    public String key() {
        return orderId.toString();
    }
}
