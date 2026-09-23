package com.checkout.common.messaging;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.Map;
import java.util.Set;

/**
 * Objeto de injeção de falha (events.md §3). Propagado sem alteração do POST /orders até os comandos.
 * Campos ausentes/null = comportamento normal.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record Simulate(String inventory, String payment, String shipping) {

    public static final String OUT_OF_STOCK = "OUT_OF_STOCK";
    public static final String DECLINE = "DECLINE";
    public static final String FAIL = "FAIL";
    public static final String TIMEOUT = "TIMEOUT";
    public static final String TIMEOUT_ONCE = "TIMEOUT_ONCE";
    public static final String SLOW = "SLOW";

    /** Valores aceitos por chave (valor desconhecido → 400 no order-service). */
    public static final Map<String, Set<String>> ALLOWED = Map.of(
            "inventory", Set.of(OUT_OF_STOCK, TIMEOUT),
            "payment", Set.of(DECLINE, TIMEOUT, TIMEOUT_ONCE, SLOW),
            "shipping", Set.of(FAIL, TIMEOUT, TIMEOUT_ONCE));
}
