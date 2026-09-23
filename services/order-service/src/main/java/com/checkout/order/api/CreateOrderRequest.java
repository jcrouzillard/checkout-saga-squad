package com.checkout.order.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;
import java.util.List;

/** Corpo do POST /orders (api.md §1). {@code simulate} fica como JSON e é validado à parte (events.md §3). */
public record CreateOrderRequest(
        @NotBlank @Size(max = 100) String customerId,
        @NotNull @Size(min = 1, max = 50) List<@NotNull @Valid Item> items,
        @NotBlank String deliveryType,
        @Valid Address shippingAddress,
        JsonNode simulate) {

    public record Item(
            @NotBlank @Size(max = 64) String sku,
            @NotNull @Min(1) @Max(1000) Integer quantity,
            @NotNull @DecimalMin(value = "0.00", inclusive = false) @Digits(integer = 10, fraction = 2) BigDecimal unitPrice) {}

    public record Address(
            String street, String number, String complement, String city, String state, String zipCode,
            String country) {}
}
