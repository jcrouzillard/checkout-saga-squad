package com.checkout.shipping.domain;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

/**
 * Envio de um pedido (no máximo um por {@code orderId}). {@code CANCELED} com {@code noop=true} é o tombstone
 * gravado quando o cancelamento chega antes/no lugar da criação (events.md §5.4).
 */
public record Shipment(UUID orderId, UUID shipmentId, String status, String trackingCode, String carrier,
                       LocalDate estimatedDeliveryDate, Address address, List<Item> items, boolean noop,
                       String reason, String message, int attempts) {

    public static final String CREATED = "CREATED";
    public static final String FAILED = "FAILED";
    public static final String CANCELED = "CANCELED";

    public static Shipment tombstone(UUID orderId) {
        return new Shipment(orderId, null, CANCELED, null, null, null, null, List.of(), true, null, null, 0);
    }

    public boolean isCreated() {
        return CREATED.equals(status);
    }

    public boolean isCanceled() {
        return CANCELED.equals(status);
    }
}
