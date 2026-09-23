package com.checkout.shipping.messaging;

import com.checkout.common.messaging.Simulate;
import com.checkout.shipping.domain.Address;
import com.checkout.shipping.domain.Item;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

/** Payloads de {@code shipping.commands} / {@code shipping.events} — nomes idênticos a events.md §4.5. */
public final class ShippingMessages {
    private ShippingMessages() {}

    public record CreateCommand(Address address, List<Item> items, Simulate simulate) {
        public String simulateMode() {
            return simulate == null ? null : simulate.shipping();
        }
    }

    public record CancelCommand(String reason) {}

    public record Created(UUID shipmentId, String trackingCode, String carrier, LocalDate estimatedDeliveryDate) {}

    public record Failed(String reason, String message) {}

    public record Canceled(UUID shipmentId, boolean noop) {}
}
