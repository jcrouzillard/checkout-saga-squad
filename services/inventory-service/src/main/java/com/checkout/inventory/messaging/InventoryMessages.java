package com.checkout.inventory.messaging;

import com.checkout.common.messaging.Simulate;
import com.checkout.inventory.domain.Item;
import com.checkout.inventory.domain.RejectionDetail;

import java.util.List;
import java.util.UUID;

/** Payloads de {@code inventory.commands} / {@code inventory.events} — nomes idênticos a events.md §4.3. */
public final class InventoryMessages {
    private InventoryMessages() {}

    public record ReserveCommand(List<Item> items, Simulate simulate) {
        public String simulateMode() {
            return simulate == null ? null : simulate.inventory();
        }
    }

    public record ReleaseCommand(String reason) {}

    public record Reserved(UUID reservationId, List<Item> items) {}

    public record Rejected(String reason, String message, List<RejectionDetail> details) {}

    public record Released(UUID reservationId, boolean noop) {}
}
