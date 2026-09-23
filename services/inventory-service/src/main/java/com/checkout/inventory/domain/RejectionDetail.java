package com.checkout.inventory.domain;

/** Detalhe de {@code inventory.rejected}: {@code { "sku", "requested", "available" }}. */
public record RejectionDetail(String sku, int requested, int available) {}
