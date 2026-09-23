package com.checkout.inventory.domain;

/** Saldo de um SKU (api.md §3). */
public record StockLevel(String sku, int available, int reserved) {}
