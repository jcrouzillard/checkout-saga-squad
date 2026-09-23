package com.checkout.saga.app;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Topics;
import com.checkout.common.observability.SagaMdc;
import com.checkout.common.observability.TraceContext;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.saga.domain.OrderSnapshot;
import com.checkout.saga.domain.SagaInstance;
import com.checkout.saga.domain.SagaStateMachine;
import com.checkout.saga.domain.Transition;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Aplica a máquina de estados. Cada chamada = UMA transação: dedupe (processed_messages) + saga_instance +
 * saga_step_log + outbox (comando e saga.step-changed). Métricas só após o commit.
 */
@Service
public class SagaService {

    private static final Logger log = LoggerFactory.getLogger(SagaService.class);

    private final SagaRepository repo;
    private final SagaStateMachine machine;
    private final OutboxWriter outbox;
    private final MessageFactory messages;
    private final IdempotencyGuard idempotency;
    private final SagaMetrics metrics;
    private final Clock clock;

    public SagaService(SagaRepository repo, SagaStateMachine machine, OutboxWriter outbox, MessageFactory messages,
                       IdempotencyGuard idempotency, SagaMetrics metrics, Clock clock) {
        this.repo = repo;
        this.machine = machine;
        this.outbox = outbox;
        this.messages = messages;
        this.idempotency = idempotency;
        this.metrics = metrics;
        this.clock = clock;
    }

    /** Entrada do consumidor Kafka (order.events e *.events dos participantes). */
    @Transactional
    public void handle(MessageEnvelope env) {
        if (!idempotency.tryMarkProcessed(env.messageId())) {
            log.info("Mensagem duplicada ignorada type={} messageId={}", env.type(), env.messageId());
            return;
        }
        switch (env.type()) {
            case Topics.Types.ORDER_CREATED -> start(env);
            case Topics.Types.INVENTORY_RESERVED, Topics.Types.INVENTORY_REJECTED, Topics.Types.INVENTORY_RELEASED,
                 Topics.Types.PAYMENT_AUTHORIZED, Topics.Types.PAYMENT_FAILED, Topics.Types.PAYMENT_REFUNDED,
                 Topics.Types.SHIPMENT_CREATED, Topics.Types.SHIPMENT_FAILED, Topics.Types.SHIPMENT_CANCELED,
                 Topics.Types.ORDER_CONFIRMED, Topics.Types.ORDER_CANCELED -> reply(env);
            default -> log.warn("Tipo desconhecido ignorado: {}", env.type());
        }
    }

    private void start(MessageEnvelope env) {
        if (repo.existsByOrderId(env.orderId())) {
            log.warn("Saga já existe para orderId={}; order.created ignorado", env.orderId());
            return;
        }
        OrderSnapshot snapshot = messages.payload(env, OrderSnapshot.class);
        Instant now = Instant.now(clock);
        SagaInstance s = SagaInstance.create(env.sagaId(), env.orderId(), snapshot, env.correlationId(),
                TraceContext.currentTraceparent(), now);
        Transition t = machine.start(s, env.messageId());
        repo.insert(s);
        apply(s, t, env.messageId(), now);
        log.info("Saga iniciada status={} deliveryType={} comando={}", s.status, s.deliveryType, s.lastCommandType);
    }

    private void reply(MessageEnvelope env) {
        SagaInstance s = repo.lockById(env.sagaId()).orElse(null);
        if (s == null) {
            log.warn("Resposta {} para saga inexistente sagaId={}", env.type(), env.sagaId());
            return;
        }
        var before = s.status;
        Transition t = machine.onReply(s, env);
        Instant now = Instant.now(clock);
        if (t.stateChanged) {
            s.updatedAt = now;
            repo.update(s);
        }
        apply(s, t, env.messageId(), now);
        if (t.accepted) {
            log.info("Transição {} -> {} por {}{}", before, s.status, env.type(),
                    s.lastCommandType != null && !s.status.isTerminal() ? " (enviado " + s.lastCommandType + ")" : "");
        } else {
            log.info("IGNORED_LATE_REPLY type={} causationId={} estado={} lastCommandId={}", env.type(),
                    env.causationId(), s.status, s.lastCommandId);
        }
    }

    /** Chamado pelo scheduler (já dentro do contexto de trace restaurado). */
    @Transactional
    public void tick(UUID sagaId) {
        Instant now = Instant.now(clock);
        SagaInstance s = repo.lockDue(sagaId, now).orElse(null);
        if (s == null) {
            return; // outra instância pegou ou não está mais vencida
        }
        try (var mdc = SagaMdc.of(s.orderId, s.sagaId)) {
            var before = s.status;
            Transition t = machine.onTick(s);
            if (t.stateChanged) {
                s.updatedAt = now;
                repo.update(s);
            }
            apply(s, t, s.lastCommandId, now);
            for (Transition.LogEntry l : t.logs) {
                switch (l.action()) {
                    case Transition.TIMEOUT -> log.warn("TIMEOUT step={} comando={} tentativa={} -> estado={}",
                            l.step(), l.messageType(), l.attempt(), s.status);
                    case Transition.RETRY -> log.info("RETRY step={} comando={} messageId={} tentativa={}",
                            l.step(), l.messageType(), l.messageId(), l.attempt());
                    case Transition.COMPENSATION_STUCK -> log.error(
                            "COMPENSATION_STUCK step={} comando={} tentativa={} estado={} — intervenção necessária",
                            l.step(), l.messageType(), l.attempt(), s.status);
                    default -> { }
                }
            }
            if (before != s.status) {
                log.info("Transição {} -> {} por timeout (enviado {})", before, s.status, s.lastCommandType);
            }
        }
    }

    /** Carência no startup (ver {@link SagaStateMachine#resumeAfterRestart}). Retorna quantas sagas foram re-armadas. */
    @Transactional
    public int resumeAfterRestart(long stepTimeoutMs) {
        Instant now = Instant.now(clock);
        int n = 0;
        for (SagaInstance s : repo.lockResumable(now.plusMillis(stepTimeoutMs))) {
            try (var mdc = SagaMdc.of(s.orderId, s.sagaId)) {
                Transition t = machine.resumeAfterRestart(s);
                if (!t.stateChanged) {
                    continue;
                }
                s.updatedAt = now;
                repo.update(s);
                apply(s, t, s.lastCommandId, now);
                n++;
                log.info("RESUMED_AFTER_RESTART estado={} comando={} tentativa={} novo deadline={}", s.status,
                        s.lastCommandType, s.attempt, s.deadlineAt);
            }
        }
        return n;
    }

    private void apply(SagaInstance s, Transition t, UUID causationId, Instant now) {
        for (Transition.LogEntry l : t.logs) {
            repo.insertLog(s.sagaId, l, now);
        }
        for (Transition.Command c : t.commands) {
            outbox.publish(c.topic(), messages.create(c.messageId(), c.type(), s.sagaId, s.orderId, s.correlationId,
                    c.causationId(), c.payload()));
        }
        for (Transition.StepEvent e : t.stepEvents) {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("step", e.step().name());
            p.put("stepStatus", e.stepStatus());
            p.put("attempt", e.attempt());
            p.put("sagaStatus", e.sagaStatus().name());
            p.put("detail", e.detail());
            outbox.publish(Topics.SAGA_EVENTS, messages.create(Topics.Types.SAGA_STEP_CHANGED, s.sagaId, s.orderId,
                    s.correlationId, causationId, p));
        }
        List<Transition.Metric> ms = List.copyOf(t.metrics);
        if (!ms.isEmpty()) {
            if (TransactionSynchronizationManager.isSynchronizationActive()) {
                TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                    @Override
                    public void afterCommit() {
                        ms.forEach(metrics::record);
                    }
                });
            } else {
                ms.forEach(metrics::record);
            }
        }
    }
}
