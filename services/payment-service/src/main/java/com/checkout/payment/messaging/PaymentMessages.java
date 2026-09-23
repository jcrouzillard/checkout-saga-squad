package com.checkout.payment.messaging;

import com.checkout.common.messaging.Simulate;

import java.math.BigDecimal;
import java.util.UUID;

/** Payloads de {@code payment.commands} / {@code payment.events} — nomes idênticos a events.md §4.4. */
public final class PaymentMessages {
    private PaymentMessages() {}

    public record AuthorizeCommand(String customerId, BigDecimal amount, String currency, Simulate simulate) {
        public String simulateMode() {
            return simulate == null ? null : simulate.payment();
        }
    }

    public record RefundCommand(BigDecimal amount, String currency, String reason) {}

    public record Authorized(UUID paymentId, String authorizationCode, BigDecimal amount, String currency) {}

    public record Failed(String reason, String message) {
        public static final String DECLINED = "DECLINED";
        public static final String ALREADY_COMPENSATED = "ALREADY_COMPENSATED";

        public static Failed declined() {
            return new Failed(DECLINED, "Pagamento recusado pelo emissor");
        }

        public static Failed alreadyCompensated() {
            return new Failed(ALREADY_COMPENSATED, "Pagamento já estornado/compensado para este pedido");
        }
    }

    public record Refunded(UUID paymentId, BigDecimal amount, boolean noop) {}
}
