package com.checkout.payment.web;

import com.checkout.payment.domain.PaymentRepository;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.UUID;

/** Endpoint de diagnóstico (api.md §3). 404 em problem+json quando não há registro. */
@RestController
@RequestMapping("/payments")
public class PaymentController {

    public record PaymentView(UUID orderId, UUID paymentId, String status, BigDecimal amount, String currency,
                              String authorizationCode, boolean noop) {}

    private final PaymentRepository repo;

    public PaymentController(PaymentRepository repo) {
        this.repo = repo;
    }

    @GetMapping("/{orderId}")
    public PaymentView payment(@PathVariable UUID orderId) {
        return repo.find(orderId)
                .map(p -> new PaymentView(p.orderId(), p.paymentId(), p.status(), p.amount(), p.currency(),
                        p.authorizationCode(), p.noop()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "Pagamento do pedido " + orderId + " não encontrado"));
    }
}
