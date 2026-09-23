package com.checkout.shipping.domain;

import com.checkout.common.messaging.Simulate;

import java.time.Clock;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

/** Transportadora simulada: cria o envio, exceto com {@code simulate.shipping=FAIL} ou endereço inválido. */
public final class Carrier {
    private Carrier() {}

    public static final String NAME = "LOCAL-EXPRESS";
    public static final int DELIVERY_DAYS = 7;
    public static final String CARRIER_REJECTED = "CARRIER_REJECTED";
    public static final String INVALID_ADDRESS = "INVALID_ADDRESS";
    public static final String ALREADY_COMPENSATED = "ALREADY_COMPENSATED";

    public static Shipment create(UUID orderId, Address address, List<Item> items, String simulateMode, Clock clock) {
        List<Item> safeItems = items == null ? List.of() : items;
        if (Simulate.FAIL.equals(simulateMode)) {
            return failed(orderId, address, safeItems, CARRIER_REJECTED, "Transportadora indisponível");
        }
        if (address == null || !address.isValid()) {
            return failed(orderId, address, safeItems, INVALID_ADDRESS, "Endereço de entrega inválido");
        }
        return new Shipment(orderId, UUID.randomUUID(), Shipment.CREATED, trackingCode(), NAME,
                LocalDate.now(clock).plusDays(DELIVERY_DAYS), address, safeItems, false, null, null, 0);
    }

    private static Shipment failed(UUID orderId, Address address, List<Item> items, String reason, String message) {
        return new Shipment(orderId, null, Shipment.FAILED, null, null, null, address, items, false, reason, message, 0);
    }

    /** Formato {@code BR} + 9 dígitos (ex.: BR123456789). */
    static String trackingCode() {
        return "BR" + String.format("%09d", ThreadLocalRandom.current().nextInt(1_000_000_000));
    }
}
