package com.checkout.saga.api;

import com.checkout.common.web.ApiException;
import com.checkout.saga.app.SagaRepository;
import com.checkout.saga.domain.SagaInstance;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** Diagnóstico (api.md §2). */
@RestController
@RequestMapping("/sagas")
public class SagaController {

    public record LogView(String step, String action, String messageType, UUID messageId, Integer attempt,
                          String detail, Instant at) {}

    public record SagaView(UUID sagaId, UUID orderId, String status, String outcome, String currentStep, int attempt,
                           Instant deadlineAt, Instant nextRetryAt, String failureReason, Instant createdAt,
                           Instant updatedAt, List<LogView> log) {}

    private final SagaRepository repo;

    public SagaController(SagaRepository repo) {
        this.repo = repo;
    }

    @GetMapping("/{sagaId}")
    public SagaView get(@PathVariable UUID sagaId) {
        return view(repo.findById(sagaId).orElseThrow(() -> ApiException.notFound("Saga " + sagaId + " não encontrada")));
    }

    @GetMapping
    public SagaView byOrder(@RequestParam(required = false) UUID orderId) {
        if (orderId == null) {
            throw ApiException.badRequest("Parâmetro orderId obrigatório",
                    List.of(new ApiException.FieldError("orderId", "obrigatório")));
        }
        return view(repo.findByOrderId(orderId)
                .orElseThrow(() -> ApiException.notFound("Saga do pedido " + orderId + " não encontrada")));
    }

    private SagaView view(SagaInstance s) {
        List<LogView> log = repo.logs(s.sagaId).stream()
                .map(l -> new LogView(l.step() == null ? null : l.step().name(), l.action(), l.messageType(),
                        l.messageId(), l.attempt(), l.detail(), l.at()))
                .toList();
        return new SagaView(s.sagaId, s.orderId, s.status.name(), s.status.outcome(),
                s.currentStep == null ? null : s.currentStep.name(), s.attempt, s.deadlineAt, s.nextRetryAt,
                s.failureReason, s.createdAt, s.updatedAt, log);
    }
}
