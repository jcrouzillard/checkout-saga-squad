package com.checkout.inventory.domain;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.SortedMap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class StockAllocatorTest {

    @Test
    void normalizeAgrupaSkusRepetidosEmOrdemDeSku() {
        SortedMap<String, Integer> bySku = StockAllocator.normalize(List.of(
                new Item("SKU-PHONE-001", 1), new Item("SKU-BOOK-001", 2), new Item("SKU-PHONE-001", 3)));
        assertThat(bySku).containsExactly(Map.entry("SKU-BOOK-001", 2), Map.entry("SKU-PHONE-001", 4));
    }

    @Test
    void normalizeRejeitaItensInvalidos() {
        assertThatThrownBy(() -> StockAllocator.normalize(List.of())).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> StockAllocator.normalize(List.of(new Item("SKU-BOOK-001", 0))))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void checkAceitaQuandoTodosOsSkusTemSaldo() {
        var requested = StockAllocator.normalize(List.of(new Item("SKU-BOOK-001", 2), new Item("SKU-LIMITED-001", 1)));
        assertThat(StockAllocator.check(requested, Map.of("SKU-BOOK-001", 1000, "SKU-LIMITED-001", 1))).isEmpty();
    }

    @Test
    void checkRejeitaTudoSeUmSkuNaoTemSaldo() {
        var requested = StockAllocator.normalize(List.of(new Item("SKU-BOOK-001", 2), new Item("SKU-LIMITED-001", 2)));
        Rejection r = StockAllocator.check(requested, Map.of("SKU-BOOK-001", 1000, "SKU-LIMITED-001", 1)).orElseThrow();
        assertThat(r.reason()).isEqualTo("OUT_OF_STOCK");
        assertThat(r.details()).containsExactly(new RejectionDetail("SKU-LIMITED-001", 2, 1));
    }

    @Test
    void skuInexistenteTemPrecedenciaSobreFaltaDeEstoque() {
        var requested = StockAllocator.normalize(List.of(new Item("SKU-NOPE", 1), new Item("SKU-LIMITED-001", 5)));
        Rejection r = StockAllocator.check(requested, Map.of("SKU-LIMITED-001", 1)).orElseThrow();
        assertThat(r.reason()).isEqualTo("UNKNOWN_SKU");
        assertThat(r.details()).containsExactly(new RejectionDetail("SKU-NOPE", 1, 0));
    }
}
