package com.checkout.saga.domain;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.Topics;
import com.checkout.common.messaging.Topics.Types;
import com.checkout.saga.domain.Transition.Metric;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/** Testes unitários da máquina de estados da Saga (transições, compensações, timeouts, respostas tardias). */
class SagaStateMachineTest {

    static final class MutableClock extends Clock {
        Instant now = Instant.parse("2026-09-23T14:00:00Z");

        void advance(long ms) {
            now = now.plusMillis(ms);
        }

        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
    }

    private final ObjectMapper mapper = new ObjectMapper();
    private final SagaSettings settings = SagaSettings.defaults(); // 5000 ms, 2 retries, 1000 backoff, 30000 max, alerta 5
    private MutableClock clock;
    private SagaStateMachine machine;

    @BeforeEach
    void setUp() {
        clock = new MutableClock();
        machine = new SagaStateMachine(settings, clock);
    }

    // ------------------------------------------------------------------ fixtures

    private SagaInstance newSaga(String deliveryType, JsonNode simulate) {
        OrderSnapshot snap = new OrderSnapshot("c-123", deliveryType,
                List.of(new OrderSnapshot.Item("SKU-BOOK-001", 2, new BigDecimal("49.90"))), new BigDecimal("99.80"),
                "BRL", "PHYSICAL".equals(deliveryType) ? mapper.createObjectNode().put("street", "Av. Paulista") : null,
                simulate);
        return SagaInstance.create(UUID.randomUUID(), UUID.randomUUID(), snap, UUID.randomUUID(), null, clock.now);
    }

    private MessageEnvelope reply(SagaInstance s, String type, Map<String, Object> payload) {
        return replyWithCausation(s, type, s.lastCommandId, payload);
    }

    private MessageEnvelope replyWithCausation(SagaInstance s, String type, UUID causation, Map<String, Object> payload) {
        ObjectNode p = mapper.valueToTree(payload);
        return new MessageEnvelope(UUID.randomUUID(), type, 1, "test", clock.now, s.sagaId, s.orderId,
                s.correlationId, causation, p);
    }

    private static Transition.Command onlyCommand(Transition t) {
        assertThat(t.commands).hasSize(1);
        return t.commands.get(0);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> payload(Transition.Command c) {
        return (Map<String, Object>) c.payload();
    }

    private static long count(Transition t, Class<? extends Metric> type) {
        return t.metrics.stream().filter(type::isInstance).count();
    }

    // ------------------------------------------------------------------ caminhos felizes

    @Test
    void happyPathPhysicalGoesThroughAllStepsAndCompletesAsConfirmed() {
        SagaInstance s = newSaga("PHYSICAL", null);
        UUID orderCreatedId = UUID.randomUUID();

        Transition t = machine.start(s, orderCreatedId);
        assertThat(s.status).isEqualTo(SagaStatus.RESERVING_INVENTORY);
        Transition.Command reserve = onlyCommand(t);
        assertThat(reserve.topic()).isEqualTo(Topics.INVENTORY_COMMANDS);
        assertThat(reserve.type()).isEqualTo(Types.INVENTORY_RESERVE);
        assertThat(reserve.messageId()).isEqualTo(s.lastCommandId);
        assertThat(reserve.causationId()).isEqualTo(orderCreatedId);
        assertThat(payload(reserve)).containsKeys("items", "simulate");
        assertThat(s.deadlineAt).isEqualTo(clock.now.plusMillis(5000));
        assertThat(count(t, Metric.Started.class)).isEqualTo(1);

        clock.advance(100);
        t = machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of("reservationId", UUID.randomUUID().toString())));
        assertThat(t.accepted).isTrue();
        assertThat(s.status).isEqualTo(SagaStatus.AUTHORIZING_PAYMENT);
        Transition.Command authorize = onlyCommand(t);
        assertThat(authorize.type()).isEqualTo(Types.PAYMENT_AUTHORIZE);
        assertThat(payload(authorize)).containsEntry("amount", new BigDecimal("99.80")).containsEntry("currency", "BRL")
                .containsEntry("customerId", "c-123");
        assertThat(t.metrics).contains(new Metric.StepDuration(Step.INVENTORY, "OK", Duration.ofMillis(100)));

        UUID paymentId = UUID.randomUUID();
        t = machine.onReply(s, reply(s, Types.PAYMENT_AUTHORIZED, Map.of("paymentId", paymentId.toString())));
        assertThat(s.status).isEqualTo(SagaStatus.CREATING_SHIPMENT);
        assertThat(onlyCommand(t).type()).isEqualTo(Types.SHIPMENT_CREATE);
        assertThat(s.paymentId).isEqualTo(paymentId);

        UUID shipmentId = UUID.randomUUID();
        t = machine.onReply(s, reply(s, Types.SHIPMENT_CREATED,
                Map.of("shipmentId", shipmentId.toString(), "trackingCode", "BR123456789")));
        assertThat(s.status).isEqualTo(SagaStatus.CONFIRMING_ORDER);
        Transition.Command confirm = onlyCommand(t);
        assertThat(confirm.topic()).isEqualTo(Topics.ORDER_COMMANDS);
        assertThat(confirm.type()).isEqualTo(Types.ORDER_CONFIRM);
        assertThat(payload(confirm)).containsEntry("paymentId", paymentId).containsEntry("shipmentId", shipmentId)
                .containsEntry("trackingCode", "BR123456789");

        t = machine.onReply(s, reply(s, Types.ORDER_CONFIRMED, Map.of("status", "CONFIRMED")));
        assertThat(s.status).isEqualTo(SagaStatus.COMPLETED);
        assertThat(s.status.outcome()).isEqualTo("CONFIRMED");
        assertThat(t.commands).isEmpty();
        assertThat(t.metrics).contains(new Metric.Completed("CONFIRMED"));
        assertThat(s.deadlineAt).isNull();
        assertThat(s.nextRetryAt).isNull();
    }

    @Test
    void digitalOrderSkipsShipping() {
        SagaInstance s = newSaga("DIGITAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        Transition t = machine.onReply(s, reply(s, Types.PAYMENT_AUTHORIZED, Map.of("paymentId", UUID.randomUUID().toString())));
        assertThat(s.status).isEqualTo(SagaStatus.CONFIRMING_ORDER);
        assertThat(onlyCommand(t).type()).isEqualTo(Types.ORDER_CONFIRM);
        assertThat(payload(t.commands.get(0))).containsEntry("shipmentId", null).containsEntry("trackingCode", null);
    }

    @Test
    void simulateIsPropagatedUnchangedToActionCommands() {
        JsonNode simulate = mapper.createObjectNode().put("payment", "DECLINE");
        SagaInstance s = newSaga("PHYSICAL", simulate);
        Transition t = machine.start(s, UUID.randomUUID());
        assertThat(payload(onlyCommand(t)).get("simulate")).isEqualTo(simulate);
        t = machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        assertThat(payload(onlyCommand(t)).get("simulate")).isEqualTo(simulate);
    }

    // ------------------------------------------------------------------ falhas de negócio e compensações

    @Test
    void paymentDeclinedReleasesInventoryThenCancelsOrder() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));

        Transition t = machine.onReply(s, reply(s, Types.PAYMENT_FAILED, Map.of("reason", "DECLINED")));
        assertThat(s.status).isEqualTo(SagaStatus.RELEASING_INVENTORY);
        Transition.Command release = onlyCommand(t);
        assertThat(release.type()).isEqualTo(Types.INVENTORY_RELEASE);
        assertThat(payload(release)).containsEntry("reason", "PAYMENT_DECLINED");
        assertThat(t.metrics).contains(new Metric.Compensation(Step.INVENTORY));
        assertThat(t.hasLog(Transition.COMPENSATION_STARTED)).isTrue();
        assertThat(t.stepEvents).extracting(Transition.StepEvent::stepStatus).containsExactly("FAILED", "COMPENSATING");

        t = machine.onReply(s, reply(s, Types.INVENTORY_RELEASED, Map.of("noop", false)));
        assertThat(s.status).isEqualTo(SagaStatus.CANCELING_ORDER);
        Transition.Command cancel = onlyCommand(t);
        assertThat(cancel.type()).isEqualTo(Types.ORDER_CANCEL);
        assertThat(payload(cancel)).containsEntry("reason", "PAYMENT_DECLINED").containsEntry("failedStep", "PAYMENT");

        t = machine.onReply(s, reply(s, Types.ORDER_CANCELED, Map.of("status", "CANCELED")));
        assertThat(s.status).isEqualTo(SagaStatus.CANCELED);
        assertThat(t.metrics).contains(new Metric.Completed("CANCELED"));
    }

    @Test
    void shipmentFailedRefundsPaymentReleasesInventoryAndCancels() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        machine.onReply(s, reply(s, Types.PAYMENT_AUTHORIZED, Map.of("paymentId", UUID.randomUUID().toString())));

        Transition t = machine.onReply(s, reply(s, Types.SHIPMENT_FAILED, Map.of("reason", "CARRIER_REJECTED")));
        assertThat(s.status).isEqualTo(SagaStatus.REFUNDING_PAYMENT);
        assertThat(payload(onlyCommand(t))).containsEntry("reason", "SHIPMENT_FAILED")
                .containsEntry("amount", new BigDecimal("99.80"));
        assertThat(t.metrics).contains(new Metric.Compensation(Step.PAYMENT));

        t = machine.onReply(s, reply(s, Types.PAYMENT_REFUNDED, Map.of("noop", false)));
        assertThat(s.status).isEqualTo(SagaStatus.RELEASING_INVENTORY);
        assertThat(onlyCommand(t).type()).isEqualTo(Types.INVENTORY_RELEASE);

        t = machine.onReply(s, reply(s, Types.INVENTORY_RELEASED, Map.of()));
        assertThat(s.status).isEqualTo(SagaStatus.CANCELING_ORDER);
        assertThat(payload(onlyCommand(t))).containsEntry("reason", "SHIPMENT_FAILED").containsEntry("failedStep", "SHIPPING");
    }

    @Test
    void inventoryRejectedCancelsOrderWithoutCompensation() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        Transition t = machine.onReply(s, reply(s, Types.INVENTORY_REJECTED, Map.of("reason", "OUT_OF_STOCK")));
        assertThat(s.status).isEqualTo(SagaStatus.CANCELING_ORDER);
        assertThat(payload(onlyCommand(t))).containsEntry("reason", "OUT_OF_STOCK").containsEntry("failedStep", "INVENTORY");
        assertThat(count(t, Metric.Compensation.class)).isZero();
    }

    // ------------------------------------------------------------------ correlação / respostas tardias

    @Test
    void replyWithStaleCausationIdIsIgnored() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        UUID reserveId = s.lastCommandId;
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        UUID authorizeId = s.lastCommandId;

        Transition t = machine.onReply(s, replyWithCausation(s, Types.PAYMENT_AUTHORIZED, UUID.randomUUID(), Map.of()));
        assertThat(t.accepted).isFalse();
        assertThat(t.stateChanged).isFalse();
        assertThat(t.commands).isEmpty();
        assertThat(t.hasLog(Transition.IGNORED_LATE_REPLY)).isTrue();
        assertThat(s.status).isEqualTo(SagaStatus.AUTHORIZING_PAYMENT);
        assertThat(s.lastCommandId).isEqualTo(authorizeId);

        // resposta duplicada/tardia ao passo anterior (causation = reserve, tipo não esperado no estado atual)
        t = machine.onReply(s, replyWithCausation(s, Types.INVENTORY_RESERVED, reserveId, Map.of()));
        assertThat(t.accepted).isFalse();
        assertThat(t.hasLog(Transition.IGNORED_LATE_REPLY)).isTrue();
        assertThat(s.status).isEqualTo(SagaStatus.AUTHORIZING_PAYMENT);
    }

    @Test
    void unexpectedTypeWithMatchingCausationIsIgnored() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        Transition t = machine.onReply(s, reply(s, Types.PAYMENT_AUTHORIZED, Map.of()));
        assertThat(t.accepted).isFalse();
        assertThat(s.status).isEqualTo(SagaStatus.RESERVING_INVENTORY);
    }

    @Test
    void lateReplyAfterTimeoutCompensationIsIgnored() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        UUID authorizeId = s.lastCommandId;
        exhaustRetries(s);
        assertThat(s.status).isEqualTo(SagaStatus.REFUNDING_PAYMENT);

        Transition t = machine.onReply(s, replyWithCausation(s, Types.PAYMENT_AUTHORIZED, authorizeId,
                Map.of("paymentId", UUID.randomUUID().toString())));
        assertThat(t.accepted).isFalse();
        assertThat(t.hasLog(Transition.IGNORED_LATE_REPLY)).isTrue();
        assertThat(s.status).isEqualTo(SagaStatus.REFUNDING_PAYMENT);
    }

    @Test
    void terminalSagaIgnoresRepliesAndTicks() {
        SagaInstance s = newSaga("DIGITAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_REJECTED, Map.of("reason", "UNKNOWN_SKU")));
        machine.onReply(s, reply(s, Types.ORDER_CANCELED, Map.of()));
        assertThat(s.status).isEqualTo(SagaStatus.CANCELED);

        assertThat(machine.onReply(s, reply(s, Types.ORDER_CANCELED, Map.of())).accepted).isFalse();
        clock.advance(60_000);
        Transition tick = machine.onTick(s);
        assertThat(tick.commands).isEmpty();
        assertThat(tick.stateChanged).isFalse();
    }

    // ------------------------------------------------------------------ timeouts e retries

    private void exhaustRetries(SagaInstance s) {
        // tentativa 1 expira → retry em 1 s; tentativa 2 expira → retry em 2 s; tentativa 3 expira → compensa
        for (int i = 0; i < 3; i++) {
            clock.advance(5001);
            machine.onTick(s);
            if (i < 2) {
                clock.advance(2000);
                machine.onTick(s);
            }
        }
    }

    @Test
    void actionTimeoutRetriesWithSameMessageIdThenCompensatesOwnStep() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        UUID authorizeId = s.lastCommandId;

        // antes do prazo: nada
        clock.advance(4999);
        assertThat(machine.onTick(s).stateChanged).isFalse();

        // prazo vencido (tentativa 1) → TIMED_OUT e agenda retry com backoff 1000 ms
        clock.advance(2);
        Transition t = machine.onTick(s);
        assertThat(t.hasLog(Transition.TIMEOUT)).isTrue();
        assertThat(t.metrics).contains(new Metric.Timeout(Step.PAYMENT));
        assertThat(t.commands).isEmpty();
        assertThat(s.deadlineAt).isNull();
        assertThat(s.nextRetryAt).isEqualTo(clock.now.plusMillis(1000));
        assertThat(t.stepEvents.get(0).stepStatus()).isEqualTo("TIMED_OUT");

        // retry: mesmo messageId, attempt 2, novo deadline
        clock.advance(1000);
        t = machine.onTick(s);
        Transition.Command retry = onlyCommand(t);
        assertThat(retry.type()).isEqualTo(Types.PAYMENT_AUTHORIZE);
        assertThat(retry.messageId()).isEqualTo(authorizeId);
        assertThat(s.attempt).isEqualTo(2);
        assertThat(s.deadlineAt).isEqualTo(clock.now.plusMillis(5000));
        assertThat(t.metrics).contains(new Metric.Retry(Step.PAYMENT));
        assertThat(t.hasLog(Transition.RETRY)).isTrue();

        // tentativa 2 expira → backoff 2000 ms
        clock.advance(5000);
        machine.onTick(s);
        assertThat(s.nextRetryAt).isEqualTo(clock.now.plusMillis(2000));
        clock.advance(2000);
        t = machine.onTick(s);
        assertThat(onlyCommand(t).messageId()).isEqualTo(authorizeId);
        assertThat(s.attempt).isEqualTo(3);

        // tentativa 3 expira → retries esgotados → compensa o próprio passo (payment.refund), STEP_TIMEOUT
        clock.advance(5000);
        t = machine.onTick(s);
        assertThat(s.status).isEqualTo(SagaStatus.REFUNDING_PAYMENT);
        assertThat(s.failureReason).isEqualTo("STEP_TIMEOUT");
        assertThat(s.failedStep).isEqualTo(Step.PAYMENT);
        Transition.Command refund = onlyCommand(t);
        assertThat(refund.type()).isEqualTo(Types.PAYMENT_REFUND);
        assertThat(refund.messageId()).isNotEqualTo(authorizeId);
        assertThat(payload(refund)).containsEntry("reason", "STEP_TIMEOUT");
        assertThat(t.metrics).contains(new Metric.Compensation(Step.PAYMENT));
        assertThat(t.metrics).anyMatch(m -> m instanceof Metric.StepDuration d && d.result().equals("TIMEOUT"));

        // compensação segue a ordem reversa até order.cancel(STEP_TIMEOUT)
        machine.onReply(s, reply(s, Types.PAYMENT_REFUNDED, Map.of("noop", false)));
        assertThat(s.status).isEqualTo(SagaStatus.RELEASING_INVENTORY);
        t = machine.onReply(s, reply(s, Types.INVENTORY_RELEASED, Map.of()));
        assertThat(payload(onlyCommand(t))).containsEntry("reason", "STEP_TIMEOUT").containsEntry("failedStep", "PAYMENT");
    }

    @Test
    void timeoutOnceThenReplyToRetryIsAccepted() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        clock.advance(5001);
        machine.onTick(s);
        clock.advance(1000);
        machine.onTick(s);
        assertThat(s.attempt).isEqualTo(2);

        Transition t = machine.onReply(s, reply(s, Types.PAYMENT_AUTHORIZED, Map.of("paymentId", UUID.randomUUID().toString())));
        assertThat(t.accepted).isTrue();
        assertThat(s.status).isEqualTo(SagaStatus.CREATING_SHIPMENT);
        assertThat(s.attempt).isEqualTo(1);
    }

    @Test
    void shippingTimeoutCompensatesWithShipmentCancelFirst() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        machine.onReply(s, reply(s, Types.PAYMENT_AUTHORIZED, Map.of("paymentId", UUID.randomUUID().toString())));
        exhaustRetries(s);
        assertThat(s.status).isEqualTo(SagaStatus.CANCELING_SHIPMENT);
        Transition t = machine.onReply(s, reply(s, Types.SHIPMENT_CANCELED, Map.of("noop", true)));
        assertThat(s.status).isEqualTo(SagaStatus.REFUNDING_PAYMENT);
        assertThat(onlyCommand(t).type()).isEqualTo(Types.PAYMENT_REFUND);
    }

    @Test
    void inventoryTimeoutReleasesInventory() {
        SagaInstance s = newSaga("DIGITAL", null);
        machine.start(s, UUID.randomUUID());
        exhaustRetries(s);
        assertThat(s.status).isEqualTo(SagaStatus.RELEASING_INVENTORY);
        assertThat(s.failedStep).isEqualTo(Step.INVENTORY);
    }

    @Test
    void compensationRetriesForeverWithCappedBackoffAndRaisesStuckAlert() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        machine.onReply(s, reply(s, Types.PAYMENT_FAILED, Map.of("reason", "DECLINED")));
        assertThat(s.status).isEqualTo(SagaStatus.RELEASING_INVENTORY);
        UUID releaseId = s.lastCommandId;

        boolean stuckRaised = false;
        for (int attempt = 1; attempt <= 12; attempt++) {
            clock.advance(5000);
            Transition timeout = machine.onTick(s);
            assertThat(timeout.hasLog(Transition.TIMEOUT)).isTrue();
            assertThat(s.status).isEqualTo(SagaStatus.RELEASING_INVENTORY); // nunca desiste
            long delay = Duration.between(clock.now, s.nextRetryAt).toMillis();
            assertThat(delay).isLessThanOrEqualTo(30_000);
            if (attempt >= 5) {
                assertThat(timeout.hasLog(Transition.COMPENSATION_STUCK)).isTrue();
                stuckRaised = true;
            } else {
                assertThat(timeout.hasLog(Transition.COMPENSATION_STUCK)).isFalse();
            }
            clock.advance(delay);
            Transition retry = machine.onTick(s);
            assertThat(onlyCommand(retry).messageId()).isEqualTo(releaseId);
        }
        assertThat(stuckRaised).isTrue();
        assertThat(Duration.between(clock.now, clock.now.plusMillis(machine.backoff(40, 30_000))).toMillis())
                .isEqualTo(30_000);
    }

    // ------------------------------------------------------------------ carência pós-reinício

    @Test
    void resumeAfterRestartRearmsExpiredDeadlineWithoutConsumingAttempt() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        machine.onReply(s, reply(s, Types.INVENTORY_RESERVED, Map.of()));
        UUID authorizeId = s.lastCommandId;

        clock.advance(20_000); // coordenador fora por 20 s: deadline de 5 s venceu na queda
        Transition t = machine.resumeAfterRestart(s);
        assertThat(t.stateChanged).isTrue();
        assertThat(t.hasLog(Transition.RESUMED_AFTER_RESTART)).isTrue();
        assertThat(t.metrics).contains(new Metric.Resumed());
        assertThat(t.commands).isEmpty();
        assertThat(t.stepEvents).isEmpty();
        assertThat(s.attempt).isEqualTo(1);
        assertThat(s.lastCommandId).isEqualTo(authorizeId);
        assertThat(s.status).isEqualTo(SagaStatus.AUTHORIZING_PAYMENT);
        assertThat(s.deadlineAt).isEqualTo(clock.now.plusMillis(5000));

        // o scheduler não cobra timeout durante a carência
        clock.advance(4999);
        assertThat(machine.onTick(s).hasLog(Transition.TIMEOUT)).isFalse();

        // a resposta ao comando original (mesmo causationId) é aceita
        Transition r = machine.onReply(s, reply(s, Types.PAYMENT_AUTHORIZED, Map.of("paymentId", UUID.randomUUID().toString())));
        assertThat(r.accepted).isTrue();
        assertThat(s.status).isEqualTo(SagaStatus.CREATING_SHIPMENT);
    }

    @Test
    void resumeAfterRestartExtendsDeadlineAboutToExpire() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        clock.advance(4000); // restam 1 s
        Transition t = machine.resumeAfterRestart(s);
        assertThat(t.stateChanged).isTrue();
        assertThat(s.deadlineAt).isEqualTo(clock.now.plusMillis(5000));
    }

    @Test
    void resumeAfterRestartKeepsAttemptCountOnRetriedStep() {
        SagaInstance s = newSaga("PHYSICAL", null);
        machine.start(s, UUID.randomUUID());
        clock.advance(5001);
        machine.onTick(s);
        clock.advance(1000);
        machine.onTick(s); // tentativa 2 em voo
        clock.advance(30_000);
        machine.resumeAfterRestart(s);
        assertThat(s.attempt).isEqualTo(2);
        assertThat(s.deadlineAt).isEqualTo(clock.now.plusMillis(5000));
    }

    @Test
    void resumeAfterRestartIgnoresTerminalPendingRetryAndFreshDeadlines() {
        SagaInstance waitingRetry = newSaga("PHYSICAL", null);
        machine.start(waitingRetry, UUID.randomUUID());
        clock.advance(5001);
        machine.onTick(waitingRetry); // deadline_at = null, next_retry_at agendado
        assertThat(machine.resumeAfterRestart(waitingRetry).stateChanged).isFalse();

        SagaInstance fresh = newSaga("PHYSICAL", null);
        machine.start(fresh, UUID.randomUUID()); // deadline = now + 5 s (prazo completo)
        assertThat(machine.resumeAfterRestart(fresh).stateChanged).isFalse();

        SagaInstance done = newSaga("DIGITAL", null);
        machine.start(done, UUID.randomUUID());
        machine.onReply(done, reply(done, Types.INVENTORY_REJECTED, Map.of("reason", "OUT_OF_STOCK")));
        machine.onReply(done, reply(done, Types.ORDER_CANCELED, Map.of()));
        clock.advance(60_000);
        assertThat(machine.resumeAfterRestart(done).stateChanged).isFalse();
    }

    @Test
    void outcomeTagMapsCompletedToConfirmed() {
        assertThat(SagaStatus.COMPLETED.outcome()).isEqualTo("CONFIRMED");
        assertThat(SagaStatus.CANCELED.outcome()).isEqualTo("CANCELED");
        assertThat(SagaStatus.AUTHORIZING_PAYMENT.outcome()).isNull();
    }
}
