package com.checkout.shipping.web;

import com.checkout.shipping.domain.ShipmentRepository;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.UUID;

/** Endpoint de diagnóstico (api.md §3). 404 em problem+json quando não há registro. */
@RestController
@RequestMapping("/shipments")
public class ShipmentController {

    public record ShipmentView(UUID orderId, UUID shipmentId, String status, String trackingCode, boolean noop) {}

    private final ShipmentRepository repo;

    public ShipmentController(ShipmentRepository repo) {
        this.repo = repo;
    }

    @GetMapping("/{orderId}")
    public ShipmentView shipment(@PathVariable UUID orderId) {
        return repo.find(orderId)
                .map(s -> new ShipmentView(s.orderId(), s.shipmentId(), s.status(), s.trackingCode(), s.noop()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "Envio do pedido " + orderId + " não encontrado"));
    }
}
