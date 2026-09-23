package com.checkout.order.domain;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/** Linha da tabela orders. */
public record OrderRecord(UUID orderId, UUID sagaId, String idempotencyKey, String requestHash, String customerId,
                          String status, String deliveryType, BigDecimal totalAmount, String currency,
                          String shippingAddressJson, UUID paymentId, UUID shipmentId, String trackingCode,
                          String cancellationReason, String failedStep, String cancellationMessage,
                          UUID correlationId, Instant createdAt, Instant updatedAt) {

    public static final String PENDING = "PENDING";
    public static final String CONFIRMED = "CONFIRMED";
    public static final String CANCELED = "CANCELED";
}
