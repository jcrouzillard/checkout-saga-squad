package com.checkout.saga.domain;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.Topics.Types;
import com.checkout.saga.domain.Transition.Metric;
import com.fasterxml.jackson.databind.JsonNode;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * Máquina de estados da Saga (docs/architecture/saga.md §1–§3). Lógica pura: muta o {@link SagaInstance} e devolve
 * os efeitos ({@link Transition}); persistência/outbox/métricas ficam no serviço. Sem I/O → testável em unidade.
 */
public class SagaStateMachine {

    private final SagaSettings settings;
    private final Clock clock;

    public SagaStateMachine(SagaSettings settings, Clock clock) {
        this.settings = settings;
        this.clock = clock;
    }

    // ------------------------------------------------------------------ início

    /** order.created → RESERVING_INVENTORY + inventory.reserve. */
    public Transition start(SagaInstance s, UUID orderCreatedMessageId) {
        Transition t = new Transition();
        t.metrics.add(new Metric.Started());
        enter(t, s, SagaStatus.RESERVING_INVENTORY, orderCreatedMessageId, now());
        return t;
    }

    // ------------------------------------------------------------------ respostas

    public Transition onReply(SagaInstance s, MessageEnvelope reply) {
        Transition t = new Transition();
        if (s.status.isTerminal() || !Objects.equals(reply.causationId(), s.lastCommandId)
                || !s.status.expects(reply.type())) {
            t.logs.add(new Transition.LogEntry(s.currentStep, Transition.IGNORED_LATE_REPLY, reply.type(),
                    reply.messageId(), s.attempt, "estado=" + s.status + " causationId=" + reply.causationId()
                    + " lastCommandId=" + s.lastCommandId));
            return t;
        }
        Instant now = now();
        JsonNode p = reply.payload();
        t.accepted = true;
        t.logs.add(new Transition.LogEntry(s.currentStep, Transition.REPLY_RECEIVED, reply.type(), reply.messageId(),
                s.attempt, null));
        UUID cause = reply.messageId();
        switch (reply.type()) {
            case Types.INVENTORY_RESERVED -> {
                succeeded(t, s, now);
                enter(t, s, SagaStatus.AUTHORIZING_PAYMENT, cause, now);
            }
            case Types.INVENTORY_REJECTED -> {
                String reason = text(p, "reason", "OUT_OF_STOCK");
                failed(t, s, now, reason, reason, text(p, "message", "Reserva de estoque rejeitada"));
                enter(t, s, SagaStatus.CANCELING_ORDER, cause, now);
            }
            case Types.PAYMENT_AUTHORIZED -> {
                s.paymentId = uuid(p, "paymentId");
                succeeded(t, s, now);
                enter(t, s, s.snapshot.isPhysical() ? SagaStatus.CREATING_SHIPMENT : SagaStatus.CONFIRMING_ORDER,
                        cause, now);
            }
            case Types.PAYMENT_FAILED -> {
                String reason = text(p, "reason", "DECLINED");
                failed(t, s, now, reason, "DECLINED".equals(reason) ? "PAYMENT_DECLINED" : reason,
                        text(p, "message", "Pagamento recusado"));
                enter(t, s, SagaStatus.RELEASING_INVENTORY, cause, now);
            }
            case Types.SHIPMENT_CREATED -> {
                s.shipmentId = uuid(p, "shipmentId");
                s.trackingCode = text(p, "trackingCode", null);
                succeeded(t, s, now);
                enter(t, s, SagaStatus.CONFIRMING_ORDER, cause, now);
            }
            case Types.SHIPMENT_FAILED -> {
                String reason = text(p, "reason", "CARRIER_REJECTED");
                failed(t, s, now, reason, "ALREADY_COMPENSATED".equals(reason) ? reason : "SHIPMENT_FAILED",
                        text(p, "message", "Falha na criação do envio"));
                enter(t, s, SagaStatus.REFUNDING_PAYMENT, cause, now);
            }
            case Types.SHIPMENT_CANCELED -> {
                compensated(t, s, reply.type());
                enter(t, s, SagaStatus.REFUNDING_PAYMENT, cause, now);
            }
            case Types.PAYMENT_REFUNDED -> {
                compensated(t, s, reply.type());
                enter(t, s, SagaStatus.RELEASING_INVENTORY, cause, now);
            }
            case Types.INVENTORY_RELEASED -> {
                compensated(t, s, reply.type());
                enter(t, s, SagaStatus.CANCELING_ORDER, cause, now);
            }
            case Types.ORDER_CONFIRMED -> finish(t, s, SagaStatus.COMPLETED, now);
            case Types.ORDER_CANCELED -> finish(t, s, SagaStatus.CANCELED, now);
            default -> throw new IllegalStateException("Tipo esperado sem tratamento: " + reply.type());
        }
        return t;
    }

    // ------------------------------------------------------------------ timeouts / retries (scheduler)

    /** Chamado pelo scheduler para sagas com deadline_at ou next_retry_at vencidos (saga.md §3.2). */
    public Transition onTick(SagaInstance s) {
        Transition t = new Transition();
        if (s.status == null || s.status.isTerminal()) {
            return t;
        }
        Instant now = now();
        Step step = s.status.step();
        if (s.nextRetryAt != null && !s.nextRetryAt.isAfter(now)) {
            // Reenvia o MESMO comando com o MESMO messageId.
            s.attempt++;
            s.nextRetryAt = null;
            s.deadlineAt = now.plusMillis(settings.stepTimeoutMs());
            t.stateChanged = true;
            t.commands.add(buildCommand(s));
            t.logs.add(new Transition.LogEntry(step, Transition.RETRY, s.lastCommandType, s.lastCommandId, s.attempt,
                    null));
            if (step.isParticipant()) {
                t.metrics.add(new Metric.Retry(step));
            }
            t.stepEvents.add(new Transition.StepEvent(step, "RETRYING", s.attempt, s.status,
                    "Reenviando " + s.lastCommandType + " (tentativa " + s.attempt + ")"));
            return t;
        }
        if (s.deadlineAt == null || s.deadlineAt.isAfter(now)) {
            return t;
        }
        t.stateChanged = true;
        s.deadlineAt = null;
        t.logs.add(new Transition.LogEntry(step, Transition.TIMEOUT, s.lastCommandType, s.lastCommandId, s.attempt,
                "Sem resposta em " + settings.stepTimeoutMs() + " ms"));
        if (step.isParticipant()) {
            t.metrics.add(new Metric.Timeout(step));
        }
        if (s.status.isAction()) {
            if (s.attempt <= settings.stepMaxRetries()) {
                s.nextRetryAt = now.plusMillis(backoff(s.attempt, Long.MAX_VALUE));
                t.stepEvents.add(new Transition.StepEvent(step, "TIMED_OUT", s.attempt, s.status,
                        "Sem resposta em " + settings.stepTimeoutMs() + " ms; reenviando " + s.lastCommandType));
            } else {
                t.stepEvents.add(new Transition.StepEvent(step, "TIMED_OUT", s.attempt, s.status,
                        "Sem resposta após " + s.attempt + " tentativas; compensando"));
                t.metrics.add(new Metric.StepDuration(step, "TIMEOUT", elapsed(s, now)));
                s.failureReason = "STEP_TIMEOUT";
                s.failedStep = step;
                s.failureMessage = "Sem resposta de " + step + " após " + s.attempt + " tentativas";
                enter(t, s, s.status.compensationOnTimeout(), s.lastCommandId, now);
            }
        } else {
            s.nextRetryAt = now.plusMillis(backoff(s.attempt, settings.compensationBackoffMaxMs()));
            t.stepEvents.add(new Transition.StepEvent(step, "TIMED_OUT", s.attempt, s.status,
                    "Sem resposta em " + settings.stepTimeoutMs() + " ms; reenviando " + s.lastCommandType));
            if (s.attempt >= settings.compensationAlertAfter()) {
                t.logs.add(new Transition.LogEntry(step, Transition.COMPENSATION_STUCK, s.lastCommandType,
                        s.lastCommandId, s.attempt, "Compensação/finalização sem resposta após " + s.attempt
                        + " tentativas"));
                t.metrics.add(new Metric.CompensationStuck(step));
            }
        }
        return t;
    }

    // ------------------------------------------------------------------ helpers

    private void enter(Transition t, SagaInstance s, SagaStatus next, UUID causationId, Instant now) {
        s.status = next;
        s.currentStep = next.step();
        s.lastCommandId = UUID.randomUUID();
        s.lastCommandType = next.commandType();
        s.lastCausationId = causationId;
        s.attempt = 1;
        s.deadlineAt = now.plusMillis(settings.stepTimeoutMs());
        s.nextRetryAt = null;
        s.stepStartedAt = now;
        t.stateChanged = true;
        t.commands.add(buildCommand(s));
        t.logs.add(new Transition.LogEntry(next.step(), Transition.COMMAND_SENT, next.commandType(), s.lastCommandId,
                1, null));
        switch (next.kind()) {
            case ACTION -> t.stepEvents.add(new Transition.StepEvent(next.step(), "STARTED", 1, next,
                    next.commandType()));
            case COMPENSATION -> {
                t.logs.add(new Transition.LogEntry(next.step(), Transition.COMPENSATION_STARTED, next.commandType(),
                        s.lastCommandId, 1, s.failureReason));
                t.metrics.add(new Metric.Compensation(next.step()));
                t.stepEvents.add(new Transition.StepEvent(next.step(), "COMPENSATING", 1, next, next.commandType()));
            }
            default -> { /* order.confirm/cancel: o order-service registra CONFIRMED/CANCELED no histórico */ }
        }
    }

    private void finish(Transition t, SagaInstance s, SagaStatus terminal, Instant now) {
        s.status = terminal;
        s.deadlineAt = null;
        s.nextRetryAt = null;
        t.stateChanged = true;
        t.metrics.add(new Metric.Completed(terminal.outcome()));
    }

    private void succeeded(Transition t, SagaInstance s, Instant now) {
        t.metrics.add(new Metric.StepDuration(s.currentStep, "OK", elapsed(s, now)));
        t.stepEvents.add(new Transition.StepEvent(s.currentStep, "SUCCEEDED", s.attempt, s.status, null));
    }

    private void failed(Transition t, SagaInstance s, Instant now, String replyReason, String failureReason,
                        String message) {
        t.metrics.add(new Metric.StepDuration(s.currentStep, "FAILED", elapsed(s, now)));
        t.stepEvents.add(new Transition.StepEvent(s.currentStep, "FAILED", s.attempt, s.status, replyReason));
        s.failureReason = failureReason;
        s.failedStep = s.currentStep;
        s.failureMessage = message;
    }

    private void compensated(Transition t, SagaInstance s, String replyType) {
        t.stepEvents.add(new Transition.StepEvent(s.currentStep, "COMPENSATED", s.attempt, s.status, replyType));
    }

    /** Monta o comando do estado corrente (determinístico → retry reenvia o mesmo conteúdo com o mesmo messageId). */
    Transition.Command buildCommand(SagaInstance s) {
        OrderSnapshot o = s.snapshot;
        Map<String, Object> p = new LinkedHashMap<>();
        switch (s.status) {
            case RESERVING_INVENTORY -> {
                p.put("items", skuQuantities(o));
                p.put("simulate", simulateOrNull(o));
            }
            case AUTHORIZING_PAYMENT -> {
                p.put("customerId", o.customerId());
                p.put("amount", o.totalAmount());
                p.put("currency", o.currency());
                p.put("simulate", simulateOrNull(o));
            }
            case CREATING_SHIPMENT -> {
                p.put("address", o.shippingAddress());
                p.put("items", skuQuantities(o));
                p.put("simulate", simulateOrNull(o));
            }
            case CANCELING_SHIPMENT -> p.put("reason", s.failureReason);
            case REFUNDING_PAYMENT -> {
                p.put("amount", o.totalAmount());
                p.put("currency", o.currency());
                p.put("reason", s.failureReason);
            }
            case RELEASING_INVENTORY -> p.put("reason", s.failureReason);
            case CONFIRMING_ORDER -> {
                p.put("paymentId", s.paymentId);
                p.put("shipmentId", s.shipmentId);
                p.put("trackingCode", s.trackingCode);
            }
            case CANCELING_ORDER -> {
                p.put("reason", s.failureReason);
                p.put("failedStep", s.failedStep == null ? null : s.failedStep.name());
                p.put("message", s.failureMessage);
            }
            default -> throw new IllegalStateException("Estado sem comando: " + s.status);
        }
        return new Transition.Command(s.status.commandTopic(), s.status.commandType(), s.lastCommandId,
                s.lastCausationId, p);
    }

    private static List<Map<String, Object>> skuQuantities(OrderSnapshot o) {
        return o.items().stream().map(i -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("sku", i.sku());
            m.put("quantity", i.quantity());
            return m;
        }).toList();
    }

    private static JsonNode simulateOrNull(OrderSnapshot o) {
        return o.simulate() == null || o.simulate().isNull() || o.simulate().isMissingNode() ? null : o.simulate();
    }

    /** backoff × 2^(attempt-1), limitado a {@code max}. */
    long backoff(int attempt, long max) {
        int exp = Math.max(0, Math.min(attempt - 1, 20));
        long value = settings.retryBackoffMs() * (1L << exp);
        return Math.min(value, max);
    }

    private static Duration elapsed(SagaInstance s, Instant now) {
        return s.stepStartedAt == null ? Duration.ZERO : Duration.between(s.stepStartedAt, now);
    }

    private static String text(JsonNode p, String field, String fallback) {
        JsonNode v = p == null ? null : p.get(field);
        return v == null || v.isNull() ? fallback : v.asText();
    }

    private static UUID uuid(JsonNode p, String field) {
        String v = text(p, field, null);
        return v == null ? null : UUID.fromString(v);
    }

    private Instant now() {
        return Instant.now(clock);
    }
}
