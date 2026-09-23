package com.checkout.order.messaging;

import com.checkout.common.messaging.Simulate;
import com.checkout.order.api.CreateOrderRequest.Address;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** Payloads de order.events / order.commands / saga.events exatamente como events.md §4.1, §4.2, §4.6. */
public final class OrderPayloads {
    private OrderPayloads() {}

    public record Line(String sku, int quantity, BigDecimal unitPrice) {}

    public record OrderCreated(String customerId, String deliveryType, List<Line> items, BigDecimal totalAmount,
                               String currency, Address shippingAddress, Simulate simulate, Instant createdAt) {}

    public record OrderConfirmed(String status, UUID paymentId, UUID shipmentId, String trackingCode,
                                 Instant confirmedAt) {}

    public record OrderCanceled(String status, String reason, String failedStep, String message, Instant canceledAt) {}

    public record ConfirmCommand(UUID paymentId, UUID shipmentId, String trackingCode) {}

    public record CancelCommand(String reason, String failedStep, String message) {}

    public record StepChanged(String step, String stepStatus, Integer attempt, String sagaStatus, String detail) {}
}
