package com.checkout.inventory.domain;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.SortedMap;
import java.util.TreeMap;

/**
 * Regras puras da reserva tudo-ou-nada (events.md §4.3). Os SKUs são tratados em ordem alfabética
 * (TreeMap) para que os locks de linha em {@code stock} sejam sempre adquiridos na mesma ordem (sem deadlock).
 */
public final class StockAllocator {
    private StockAllocator() {}

    /** Agrupa itens repetidos por SKU, em ordem de SKU. Itens inválidos → IllegalArgumentException. */
    public static SortedMap<String, Integer> normalize(List<Item> items) {
        if (items == null || items.isEmpty()) {
            throw new IllegalArgumentException("inventory.reserve sem itens");
        }
        SortedMap<String, Integer> bySku = new TreeMap<>();
        for (Item item : items) {
            if (item == null || item.sku() == null || item.sku().isBlank() || item.quantity() <= 0) {
                throw new IllegalArgumentException("Item inválido em inventory.reserve: " + item);
            }
            bySku.merge(item.sku(), item.quantity(), Integer::sum);
        }
        return bySku;
    }

    public static List<Item> toItems(SortedMap<String, Integer> bySku) {
        List<Item> items = new ArrayList<>(bySku.size());
        bySku.forEach((sku, qty) -> items.add(new Item(sku, qty)));
        return items;
    }

    /**
     * @param requested quantidades por SKU (normalizadas)
     * @param available saldo disponível por SKU (SKU ausente = inexistente)
     * @return rejeição (UNKNOWN_SKU tem precedência sobre OUT_OF_STOCK) ou vazio se tudo pode ser reservado
     */
    public static Optional<Rejection> check(SortedMap<String, Integer> requested, Map<String, Integer> available) {
        List<RejectionDetail> unknown = new ArrayList<>();
        List<RejectionDetail> insufficient = new ArrayList<>();
        requested.forEach((sku, qty) -> {
            Integer avail = available.get(sku);
            if (avail == null) {
                unknown.add(new RejectionDetail(sku, qty, 0));
            } else if (avail < qty) {
                insufficient.add(new RejectionDetail(sku, qty, avail));
            }
        });
        if (!unknown.isEmpty()) {
            return Optional.of(Rejection.unknownSku(unknown));
        }
        if (!insufficient.isEmpty()) {
            return Optional.of(Rejection.outOfStock(insufficient));
        }
        return Optional.empty();
    }

    /** Detalhes para {@code simulate.inventory=OUT_OF_STOCK} (rejeita sem reservar, informando o saldo atual). */
    public static List<RejectionDetail> simulatedDetails(SortedMap<String, Integer> requested,
                                                         Map<String, Integer> available) {
        List<RejectionDetail> details = new ArrayList<>();
        requested.forEach((sku, qty) -> details.add(new RejectionDetail(sku, qty, available.getOrDefault(sku, 0))));
        return details;
    }
}
