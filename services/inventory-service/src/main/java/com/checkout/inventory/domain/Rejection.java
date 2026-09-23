package com.checkout.inventory.domain;

import java.util.List;

/** Resultado negativo da reserva (events.md §4.3). */
public record Rejection(String reason, String message, List<RejectionDetail> details) {

    public static final String OUT_OF_STOCK = "OUT_OF_STOCK";
    public static final String UNKNOWN_SKU = "UNKNOWN_SKU";
    public static final String ALREADY_COMPENSATED = "ALREADY_COMPENSATED";

    public static Rejection outOfStock(List<RejectionDetail> details) {
        return new Rejection(OUT_OF_STOCK, "Estoque insuficiente", details);
    }

    public static Rejection unknownSku(List<RejectionDetail> details) {
        return new Rejection(UNKNOWN_SKU, "SKU inexistente", details);
    }

    public static Rejection alreadyCompensated() {
        return new Rejection(ALREADY_COMPENSATED, "Reserva já compensada para este pedido", List.of());
    }
}
