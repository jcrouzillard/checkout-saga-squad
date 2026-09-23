package com.checkout.saga.domain;

import com.fasterxml.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.util.List;

/** Cópia do payload de order.created guardada em saga_instance.order_snapshot. simulate propagado sem alteração. */
public record OrderSnapshot(String customerId, String deliveryType, List<Item> items, BigDecimal totalAmount,
                            String currency, JsonNode shippingAddress, JsonNode simulate) {

    public record Item(String sku, int quantity, BigDecimal unitPrice) {}

    public boolean isPhysical() {
        return "PHYSICAL".equals(deliveryType);
    }
}
