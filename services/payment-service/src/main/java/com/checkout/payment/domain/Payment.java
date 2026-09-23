package com.checkout.payment.domain;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * Pagamento de um pedido (no máximo um por {@code orderId}). {@code REFUNDED} com {@code noop=true} é o tombstone
 * gravado quando o estorno chega antes/no lugar da autorização (events.md §5.4).
 */
public record Payment(UUID orderId, UUID paymentId, String status, String customerId, BigDecimal amount,
                      String currency, String authorizationCode, boolean noop, int attempts) {

    public static final String AUTHORIZED = "AUTHORIZED";
    public static final String DECLINED = "DECLINED";
    public static final String REFUNDED = "REFUNDED";

    public boolean isAuthorized() {
        return AUTHORIZED.equals(status);
    }

    public boolean isDeclined() {
        return DECLINED.equals(status);
    }

    public boolean isRefunded() {
        return REFUNDED.equals(status);
    }
}
