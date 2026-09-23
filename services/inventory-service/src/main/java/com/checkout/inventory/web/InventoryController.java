package com.checkout.inventory.web;

import com.checkout.inventory.domain.InventoryRepository;
import com.checkout.inventory.domain.Item;
import com.checkout.inventory.domain.StockLevel;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.UUID;

/** Endpoints de diagnóstico (api.md §3). 404 em problem+json quando não há registro. */
@RestController
@RequestMapping("/inventory")
public class InventoryController {

    public record ReservationView(UUID orderId, UUID reservationId, String status, List<Item> items, boolean noop) {}

    private final InventoryRepository repo;

    public InventoryController(InventoryRepository repo) {
        this.repo = repo;
    }

    @GetMapping("/stock/{sku}")
    public StockLevel stock(@PathVariable String sku) {
        return repo.findStock(sku)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "SKU " + sku + " não encontrado"));
    }

    @GetMapping("/reservations/{orderId}")
    public ReservationView reservation(@PathVariable UUID orderId) {
        return repo.findReservation(orderId)
                .map(r -> new ReservationView(r.orderId(), r.reservationId(), r.status(), r.items(), r.noop()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "Reserva do pedido " + orderId + " não encontrada"));
    }
}
