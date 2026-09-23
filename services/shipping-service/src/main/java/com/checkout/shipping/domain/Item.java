package com.checkout.shipping.domain;

/** Item do envio: {@code { "sku", "quantity" }}. */
public record Item(String sku, int quantity) {}
