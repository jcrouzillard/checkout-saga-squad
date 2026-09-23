package com.checkout.inventory.domain;

import java.util.List;
import java.util.UUID;

/**
 * Reserva de um pedido (no máximo uma por {@code orderId}). {@code RELEASED} com {@code noop=true} é o
 * tombstone gravado quando a liberação chega antes/no lugar da reserva (events.md §5.4).
 */
public record Reservation(UUID orderId, UUID reservationId, String status, List<Item> items, boolean noop,
                          String reason, String message, List<RejectionDetail> details, int attempts) {

    public static final String RESERVED = "RESERVED";
    public static final String RELEASED = "RELEASED";
    public static final String REJECTED = "REJECTED";

    public static Reservation reserved(UUID orderId, UUID reservationId, List<Item> items) {
        return new Reservation(orderId, reservationId, RESERVED, items, false, null, null, null, 0);
    }

    public static Reservation rejected(UUID orderId, List<Item> items, Rejection rejection) {
        return new Reservation(orderId, null, REJECTED, items, false, rejection.reason(), rejection.message(),
                rejection.details(), 0);
    }

    public static Reservation tombstone(UUID orderId) {
        return new Reservation(orderId, null, RELEASED, List.of(), true, null, null, null, 0);
    }

    public boolean isReserved() {
        return RESERVED.equals(status);
    }

    public boolean isReleased() {
        return RELEASED.equals(status);
    }

    public boolean isRejected() {
        return REJECTED.equals(status);
    }

    public Rejection rejection() {
        return new Rejection(reason, message, details == null ? List.of() : details);
    }
}
