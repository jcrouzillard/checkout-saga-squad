package com.checkout.payment.messaging;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Simulate;
import com.checkout.common.messaging.Topics;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.payment.domain.Payment;
import com.checkout.payment.domain.PaymentRepository;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.time.Clock;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PaymentCommandHandlerTest {

    private static final BigDecimal AMOUNT = new BigDecimal("99.80");

    private final ObjectMapper mapper = JsonMapper.builder().findAndAddModules()
            .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS).build();
    private final MessageFactory messages = new MessageFactory(mapper, "saga-orchestrator", Clock.systemUTC());
    private PaymentRepository repo;
    private IdempotencyGuard idempotency;
    private OutboxWriter outbox;
    private DelayedReplies delayed;
    private PaymentCommandHandler handler;
    private final UUID orderId = UUID.randomUUID();

    @BeforeEach
    void setUp() {
        repo = mock(PaymentRepository.class);
        idempotency = mock(IdempotencyGuard.class);
        outbox = mock(OutboxWriter.class);
        delayed = mock(DelayedReplies.class);
        when(idempotency.tryMarkProcessed(any())).thenReturn(true);
        handler = new PaymentCommandHandler(repo, idempotency, outbox, delayed, messages, 2000);
    }

    private MessageEnvelope authorizeCmd(String simulatePayment) {
        return messages.create(Topics.Types.PAYMENT_AUTHORIZE, UUID.randomUUID(), orderId, UUID.randomUUID(), null,
                new PaymentMessages.AuthorizeCommand("c-123", AMOUNT, "BRL",
                        simulatePayment == null ? null : new Simulate(null, simulatePayment, null)));
    }

    private MessageEnvelope refundCmd() {
        return messages.create(Topics.Types.PAYMENT_REFUND, UUID.randomUUID(), orderId, UUID.randomUUID(), null,
                new PaymentMessages.RefundCommand(AMOUNT, "BRL", "SHIPMENT_FAILED"));
    }

    private Payment authorized(UUID paymentId) {
        return new Payment(orderId, paymentId, Payment.AUTHORIZED, "c-123", AMOUNT, "BRL", "AUTH-8F3K2", false, 1);
    }

    private MessageEnvelope published() {
        ArgumentCaptor<MessageEnvelope> captor = ArgumentCaptor.forClass(MessageEnvelope.class);
        verify(outbox).publish(eq(Topics.PAYMENT_EVENTS), captor.capture());
        return captor.getValue();
    }

    @Test
    void autorizaEPublicaAuthorizedComValorExato() {
        MessageEnvelope cmd = authorizeCmd(null);
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(cmd);

        ArgumentCaptor<Payment> saved = ArgumentCaptor.forClass(Payment.class);
        verify(repo).insert(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(Payment.AUTHORIZED);
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.PAYMENT_AUTHORIZED);
        assertThat(reply.causationId()).isEqualTo(cmd.messageId());
        assertThat(reply.payload().get("amount").decimalValue()).isEqualByComparingTo("99.80");
        assertThat(reply.payload().get("authorizationCode").asText()).startsWith("AUTH-");
        assertThat(reply.payload().get("paymentId").asText()).isEqualTo(saved.getValue().paymentId().toString());
    }

    @Test
    void autorizacaoDuplicadaRepublicaMesmoPaymentIdSemReexecutar() {
        UUID paymentId = UUID.randomUUID();
        MessageEnvelope cmd = authorizeCmd(null);
        when(idempotency.tryMarkProcessed(cmd.messageId())).thenReturn(false);
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(authorized(paymentId)));
        when(repo.incrementAttempts(orderId)).thenReturn(2);

        handler.handle(cmd);

        verify(repo, never()).insert(any());
        assertThat(published().payload().get("paymentId").asText()).isEqualTo(paymentId.toString());
    }

    @Test
    void declinePersisteDeclinedEPublicaFailed() {
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(authorizeCmd("DECLINE"));

        ArgumentCaptor<Payment> saved = ArgumentCaptor.forClass(Payment.class);
        verify(repo).insert(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(Payment.DECLINED);
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.PAYMENT_FAILED);
        assertThat(reply.payload().get("reason").asText()).isEqualTo("DECLINED");
    }

    @Test
    void timeoutAutorizaDeFatoENuncaResponde() {
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);
        handler.handle(authorizeCmd("TIMEOUT"));

        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(authorized(UUID.randomUUID())));
        when(repo.incrementAttempts(orderId)).thenReturn(2);
        handler.handle(authorizeCmd("TIMEOUT"));

        verify(repo).insert(any());
        verify(outbox, never()).publish(anyString(), any());
    }

    @Test
    void timeoutOnceSilenciaPrimeiraTentativaERespondeNoRetry() {
        MessageEnvelope cmd = authorizeCmd("TIMEOUT_ONCE");
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);
        handler.handle(cmd);
        verify(outbox, never()).publish(anyString(), any());

        when(idempotency.tryMarkProcessed(cmd.messageId())).thenReturn(false);   // retry = mesmo messageId
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(authorized(UUID.randomUUID())));
        when(repo.incrementAttempts(orderId)).thenReturn(2);
        handler.handle(cmd);

        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.PAYMENT_AUTHORIZED);
        assertThat(reply.causationId()).isEqualTo(cmd.messageId());
    }

    @Test
    void slowAgendaRespostaAtrasadaEmVezDeBloquear() {
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(authorizeCmd("SLOW"));

        ArgumentCaptor<MessageEnvelope> captor = ArgumentCaptor.forClass(MessageEnvelope.class);
        verify(delayed).schedule(eq(Topics.PAYMENT_EVENTS), captor.capture(), eq(2000L));
        assertThat(captor.getValue().type()).isEqualTo(Topics.Types.PAYMENT_AUTHORIZED);
        verify(outbox, never()).publish(anyString(), any());
    }

    @Test
    void refundEstornaAutorizacaoReal() {
        UUID paymentId = UUID.randomUUID();
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(authorized(paymentId)));

        handler.handle(refundCmd());

        verify(repo).markRefunded(orderId);
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.PAYMENT_REFUNDED);
        assertThat(reply.payload().get("paymentId").asText()).isEqualTo(paymentId.toString());
        assertThat(reply.payload().get("noop").asBoolean()).isFalse();
    }

    @Test
    void refundDuplicadoEIdempotente() {
        UUID paymentId = UUID.randomUUID();
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(
                new Payment(orderId, paymentId, Payment.REFUNDED, "c-123", AMOUNT, "BRL", "AUTH-8F3K2", false, 1)));

        handler.handle(refundCmd());

        verify(repo, never()).markRefunded(any());
        verify(repo, never()).insert(any());
        MessageEnvelope reply = published();
        assertThat(reply.payload().get("paymentId").asText()).isEqualTo(paymentId.toString());
        assertThat(reply.payload().get("noop").asBoolean()).isFalse();
    }

    @Test
    void refundSemAutorizacaoGravaTombstoneEAutorizacaoTardiaFalha() {
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        handler.handle(refundCmd());

        ArgumentCaptor<Payment> saved = ArgumentCaptor.forClass(Payment.class);
        verify(repo).insert(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(Payment.REFUNDED);
        assertThat(saved.getValue().noop()).isTrue();
        MessageEnvelope refunded = published();
        assertThat(refunded.payload().get("noop").asBoolean()).isTrue();
        assertThat(refunded.payload().get("paymentId").isNull()).isTrue();
        assertThat(refunded.payload().get("amount").decimalValue()).isEqualByComparingTo("99.80");

        outbox = mock(OutboxWriter.class);
        handler = new PaymentCommandHandler(repo, idempotency, outbox, delayed, messages, 2000);
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(saved.getValue()));
        handler.handle(authorizeCmd(null));

        verify(repo, never()).incrementAttempts(any());
        verify(delayed, never()).schedule(anyString(), any(), anyLong());
        MessageEnvelope failed = published();
        assertThat(failed.type()).isEqualTo(Topics.Types.PAYMENT_FAILED);
        assertThat(failed.payload().get("reason").asText()).isEqualTo("ALREADY_COMPENSATED");
    }
}
