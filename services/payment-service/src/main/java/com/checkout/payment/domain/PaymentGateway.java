package com.checkout.payment.domain;

import com.checkout.common.messaging.Simulate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

/** Emissor simulado: aprova tudo, exceto {@code simulate.payment=DECLINE}. */
public final class PaymentGateway {
    private PaymentGateway() {}

    private static final String ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

    public static Payment authorize(UUID orderId, String customerId, BigDecimal amount, String currency,
                                    String simulateMode) {
        BigDecimal money = money(amount);
        if (Simulate.DECLINE.equals(simulateMode)) {
            return new Payment(orderId, UUID.randomUUID(), Payment.DECLINED, customerId, money, currency, null, false, 0);
        }
        return new Payment(orderId, UUID.randomUUID(), Payment.AUTHORIZED, customerId, money, currency,
                authorizationCode(), false, 0);
    }

    public static Payment refundTombstone(UUID orderId, BigDecimal amount, String currency) {
        return new Payment(orderId, null, Payment.REFUNDED, null, money(amount), currency == null ? "BRL" : currency,
                null, true, 0);
    }

    public static BigDecimal money(BigDecimal amount) {
        return amount == null ? BigDecimal.ZERO.setScale(2) : amount.setScale(2, RoundingMode.HALF_UP);
    }

    static String authorizationCode() {
        ThreadLocalRandom rnd = ThreadLocalRandom.current();
        StringBuilder sb = new StringBuilder("AUTH-");
        for (int i = 0; i < 5; i++) {
            sb.append(ALPHABET.charAt(rnd.nextInt(ALPHABET.length())));
        }
        return sb.toString();
    }
}
