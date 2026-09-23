package com.checkout.common.observability;

import com.checkout.common.messaging.MessageEnvelope;
import org.slf4j.MDC;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * MDC de domínio ({@code orderId}, {@code sagaId}, {@code messageId}) — docs/observability.md §2.
 * {@code trace_id}/{@code span_id} vêm do agente OTel; não coloque aqui.
 * <pre>try (var mdc = SagaMdc.of(envelope)) { ... }</pre>
 */
public final class SagaMdc implements AutoCloseable {

    public static final String ORDER_ID = "orderId";
    public static final String SAGA_ID = "sagaId";
    public static final String MESSAGE_ID = "messageId";

    private final Map<String, String> previous = new LinkedHashMap<>();

    private SagaMdc() {}

    public static SagaMdc of(MessageEnvelope env) {
        return of(env.orderId(), env.sagaId()).with(MESSAGE_ID, env.messageId());
    }

    public static SagaMdc of(UUID orderId, UUID sagaId) {
        return new SagaMdc().with(ORDER_ID, orderId).with(SAGA_ID, sagaId);
    }

    public SagaMdc with(String key, Object value) {
        if (!previous.containsKey(key)) {
            previous.put(key, MDC.get(key));
        }
        if (value == null) {
            MDC.remove(key);
        } else {
            MDC.put(key, value.toString());
        }
        return this;
    }

    @Override
    public void close() {
        previous.forEach((k, v) -> {
            if (v == null) {
                MDC.remove(k);
            } else {
                MDC.put(k, v);
            }
        });
    }
}
