package com.checkout.shipping.domain;

import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

class CarrierTest {

    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-09-23T14:05:12Z"), ZoneOffset.UTC);
    private static final Address ADDRESS =
            new Address("Av. Paulista", "1000", null, "São Paulo", "SP", "01310-100", "BR");
    private static final List<Item> ITEMS = List.of(new Item("SKU-BOOK-001", 2));

    @Test
    void criaEnvioComTrackingCodeEPrevisao() {
        Shipment s = Carrier.create(UUID.randomUUID(), ADDRESS, ITEMS, null, CLOCK);
        assertThat(s.status()).isEqualTo(Shipment.CREATED);
        assertThat(s.shipmentId()).isNotNull();
        assertThat(s.trackingCode()).matches("BR\\d{9}");
        assertThat(s.carrier()).isEqualTo("LOCAL-EXPRESS");
        assertThat(s.estimatedDeliveryDate()).isEqualTo(LocalDate.parse("2026-09-30"));
    }

    @Test
    void simulateFailRecusaNaTransportadora() {
        Shipment s = Carrier.create(UUID.randomUUID(), ADDRESS, ITEMS, "FAIL", CLOCK);
        assertThat(s.status()).isEqualTo(Shipment.FAILED);
        assertThat(s.reason()).isEqualTo("CARRIER_REJECTED");
        assertThat(s.shipmentId()).isNull();
    }

    @Test
    void enderecoInvalidoFalhaComInvalidAddress() {
        Shipment s = Carrier.create(UUID.randomUUID(),
                new Address("Av. Paulista", "1000", null, "São Paulo", "SP", " ", "BR"), ITEMS, null, CLOCK);
        assertThat(s.status()).isEqualTo(Shipment.FAILED);
        assertThat(s.reason()).isEqualTo("INVALID_ADDRESS");
    }
}
