package com.checkout.saga.domain;

import java.time.Instant;
import java.util.UUID;

/** Estado persistido de uma saga (tabela saga_instance). Nada de estado vive só em memória. */
public class SagaInstance {
    public UUID sagaId;
    public UUID orderId;
    public SagaStatus status;
    public Step currentStep;
    public String deliveryType;
    public OrderSnapshot snapshot;
    public UUID paymentId;
    public UUID shipmentId;
    public String trackingCode;
    public UUID lastCommandId;
    public String lastCommandType;
    public UUID lastCausationId;
    public int attempt;
    public Instant deadlineAt;
    public Instant nextRetryAt;
    public Instant stepStartedAt;
    public String failureReason;
    public Step failedStep;
    public String failureMessage;
    public UUID correlationId;
    public String traceParent;
    public long version;
    public Instant createdAt;
    public Instant updatedAt;

    public static SagaInstance create(UUID sagaId, UUID orderId, OrderSnapshot snapshot, UUID correlationId,
                                      String traceParent, Instant now) {
        SagaInstance s = new SagaInstance();
        s.sagaId = sagaId;
        s.orderId = orderId;
        s.snapshot = snapshot;
        s.deliveryType = snapshot.deliveryType();
        s.correlationId = correlationId;
        s.traceParent = traceParent;
        s.createdAt = now;
        s.updatedAt = now;
        return s;
    }
}
