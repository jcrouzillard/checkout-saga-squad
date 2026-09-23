package com.checkout.payment.messaging;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Simulate;
import com.checkout.common.messaging.Topics;
import com.checkout.common.observability.SagaMdc;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.payment.domain.Payment;
import com.checkout.payment.domain.PaymentGateway;
import com.checkout.payment.domain.PaymentRepository;
import com.checkout.payment.domain.ReplyPolicy;
import com.checkout.payment.messaging.PaymentMessages.AuthorizeCommand;
import com.checkout.payment.messaging.PaymentMessages.Authorized;
import com.checkout.payment.messaging.PaymentMessages.Failed;
import com.checkout.payment.messaging.PaymentMessages.RefundCommand;
import com.checkout.payment.messaging.PaymentMessages.Refunded;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;
import java.util.UUID;

/**
 * Processa {@code payment.authorize} / {@code payment.refund} numa única transação:
 * dedupe ({@code processed_messages}) + efeito + resposta no outbox (events.md §5, ADR-002).
 * <p>Comando duplicado ou nova autorização para o mesmo pedido NÃO reexecuta: a resposta é re-publicada a partir
 * do estado persistido em {@code payments}.
 */
@Service
public class PaymentCommandHandler {

    private static final Logger log = LoggerFactory.getLogger(PaymentCommandHandler.class);

    private final PaymentRepository repo;
    private final IdempotencyGuard idempotency;
    private final OutboxWriter outbox;
    private final DelayedReplies delayedReplies;
    private final MessageFactory messages;
    private final long slowMs;

    public PaymentCommandHandler(PaymentRepository repo, IdempotencyGuard idempotency, OutboxWriter outbox,
                                 DelayedReplies delayedReplies, MessageFactory messages,
                                 @Value("${checkout.simulate.slow-ms:2000}") long slowMs) {
        this.repo = repo;
        this.idempotency = idempotency;
        this.outbox = outbox;
        this.delayedReplies = delayedReplies;
        this.messages = messages;
        this.slowMs = slowMs;
    }

    @Transactional
    public void handle(MessageEnvelope cmd) {
        try (var mdc = SagaMdc.of(cmd)) {
            boolean first = idempotency.tryMarkProcessed(cmd.messageId());
            switch (cmd.type()) {
                case Topics.Types.PAYMENT_AUTHORIZE -> authorize(cmd, first);
                case Topics.Types.PAYMENT_REFUND -> refund(cmd, first);
                default -> log.warn("Tipo desconhecido ignorado em {}: {}", Topics.PAYMENT_COMMANDS, cmd.type());
            }
        }
    }

    // ------------------------------------------------------------------ payment.authorize (ação)

    private void authorize(MessageEnvelope cmd, boolean first) {
        AuthorizeCommand p = messages.payload(cmd, AuthorizeCommand.class);
        String mode = simulateMode(p);
        UUID orderId = cmd.orderId();

        Optional<Payment> existing = repo.findForUpdate(orderId);
        if (existing.isPresent() && existing.get().isRefunded()) {
            log.info("payment.authorize após estorno (noop={}) → payment.failed ALREADY_COMPENSATED",
                    existing.get().noop());
            publish(cmd, Topics.Types.PAYMENT_FAILED, Failed.alreadyCompensated());
            return;
        }

        Payment payment;
        if (existing.isPresent()) {
            payment = existing.get();
            log.info("payment.authorize {} para pedido já processado (status={}); re-publicando resposta do estado",
                    first ? "novo" : "duplicado", payment.status());
        } else {
            payment = PaymentGateway.authorize(orderId, p.customerId(), p.amount(), p.currency(), mode);
            repo.insert(payment);
            log.info("Pagamento {} paymentId={} amount={} {}{}", payment.status(), payment.paymentId(),
                    payment.amount(), payment.currency(), mode != null ? " (simulate.payment=" + mode + ")" : "");
        }

        int attempts = repo.incrementAttempts(orderId);
        if (!ReplyPolicy.shouldReply(mode, attempts)) {
            log.warn("simulate.payment={} → resposta suprimida (tentativa {})", mode, attempts);
            return;
        }
        MessageEnvelope reply = payment.isAuthorized()
                ? messages.replyTo(cmd, Topics.Types.PAYMENT_AUTHORIZED, new Authorized(payment.paymentId(),
                        payment.authorizationCode(), payment.amount(), payment.currency()))
                : messages.replyTo(cmd, Topics.Types.PAYMENT_FAILED, Failed.declined());
        if (Simulate.SLOW.equals(mode)) {
            delayedReplies.schedule(Topics.PAYMENT_EVENTS, reply, slowMs);
            log.info("simulate.payment=SLOW → resposta {} agendada para daqui a {} ms", reply.type(), slowMs);
        } else {
            outbox.publish(Topics.PAYMENT_EVENTS, reply);
        }
    }

    // ------------------------------------------------------------------ payment.refund (compensação)

    /** Compensação: sempre executa (simulate nunca se aplica) e sempre responde a partir do estado. */
    private void refund(MessageEnvelope cmd, boolean first) {
        RefundCommand p = messages.payload(cmd, RefundCommand.class);
        UUID orderId = cmd.orderId();
        Optional<Payment> existing = repo.findForUpdate(orderId);

        if (existing.isEmpty()) {
            Payment tombstone = PaymentGateway.refundTombstone(orderId, p.amount(), p.currency());
            repo.insert(tombstone);
            log.info("payment.refund sem autorização (reason={}) → tombstone REFUNDED noop=true", p.reason());
            publish(cmd, Topics.Types.PAYMENT_REFUNDED, new Refunded(null, tombstone.amount(), true));
            return;
        }

        Payment pay = existing.get();
        switch (pay.status()) {
            case Payment.AUTHORIZED -> {
                repo.markRefunded(orderId);
                log.info("Pagamento estornado paymentId={} amount={} (reason={})", pay.paymentId(), pay.amount(),
                        p.reason());
                publish(cmd, Topics.Types.PAYMENT_REFUNDED, new Refunded(pay.paymentId(), pay.amount(), false));
            }
            case Payment.REFUNDED -> {
                log.info("payment.refund {} para pagamento já estornado; re-publicando", first ? "novo" : "duplicado");
                publish(cmd, Topics.Types.PAYMENT_REFUNDED, new Refunded(pay.paymentId(), pay.amount(), pay.noop()));
            }
            default -> { // DECLINED: nada foi capturado → estorno é no-op
                log.info("payment.refund para pagamento DECLINED → noop");
                publish(cmd, Topics.Types.PAYMENT_REFUNDED, new Refunded(pay.paymentId(), pay.amount(), true));
            }
        }
    }

    // ------------------------------------------------------------------ helpers

    private static String simulateMode(AuthorizeCommand p) {
        String mode = p.simulateMode();
        if (mode != null && !Simulate.ALLOWED.get("payment").contains(mode)) {
            log.warn("simulate.payment desconhecido ignorado: {}", mode);
            return null;
        }
        return mode;
    }

    private void publish(MessageEnvelope cmd, String type, Object payload) {
        outbox.publish(Topics.PAYMENT_EVENTS, messages.replyTo(cmd, type, payload));
    }
}
