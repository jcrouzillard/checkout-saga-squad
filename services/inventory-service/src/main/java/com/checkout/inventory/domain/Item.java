package com.checkout.inventory.domain;

/** Item de reserva (events.md §4.3): {@code { "sku": "SKU-BOOK-001", "quantity": 2 }}. */
public record Item(String sku, int quantity) {}
