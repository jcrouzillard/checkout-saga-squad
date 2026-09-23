package com.checkout.order.messaging;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Topics;
import com.checkout.common.observability.SagaMdc;
import com.checkout.order.domain.OrderRepository;
import com.checkout.order.domain.OrderService;
import com.checkout.order.messaging.OrderPayloads.CancelCommand;
import com.checkout.order.messaging.OrderPayloads.ConfirmCommand;
import com.checkout.order.messaging.OrderPayloads.StepChanged;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * Consumidores do order-service (group id = order-service). Cada mensagem: dedupe + efeito + outbox numa transação;
 * offset confirmado após o commit (AckMode RECORD).
 */
@Component
public class OrderMessageListener {

    private static final Logger log = LoggerFactory.getLogger(OrderMessageListener.class);

    private final MessageFactory messages;
    private final IdempotencyGuard idempotency;
    private final OrderService service;
    private final OrderRepository repo;

    public OrderMessageListener(MessageFactory messages, IdempotencyGuard idempotency, OrderService service,
                                OrderRepository repo) {
        this.messages = messages;
        this.idempotency = idempotency;
        this.service = service;
        this.repo = repo;
    }

    /** order.confirm / order.cancel — idempotentes: duplicata re-publica o evento a partir do estado persistido. */
    @KafkaListener(topics = Topics.ORDER_COMMANDS)
    @Transactional
    public void onOrderCommand(String value) {
        MessageEnvelope cmd = messages.read(value);
        try (var mdc = SagaMdc.of(cmd)) {
            boolean first = idempotency.tryMarkProcessed(cmd.messageId());
            if (!first) {
                log.info("Comando duplicado {} messageId={}; re-publicando resposta", cmd.type(), cmd.messageId());
            }
            switch (cmd.type()) {
                case Topics.Types.ORDER_CONFIRM -> {
                    ConfirmCommand c = messages.payload(cmd, ConfirmCommand.class);
                    service.confirm(cmd, c.paymentId(), c.shipmentId(), c.trackingCode());
                }
                case Topics.Types.ORDER_CANCEL -> {
                    CancelCommand c = messages.payload(cmd, CancelCommand.class);
                    service.cancel(cmd, c.reason(), c.failedStep(), c.message());
                }
                default -> log.warn("Tipo desconhecido ignorado em {}: {}", Topics.ORDER_COMMANDS, cmd.type());
            }
        }
    }

    /** saga.step-changed → order_status_history (histórico exibido em GET /orders/{orderId}). */
    @KafkaListener(topics = Topics.SAGA_EVENTS)
    @Transactional
    public void onSagaEvent(String value) {
        MessageEnvelope evt = messages.read(value);
        try (var mdc = SagaMdc.of(evt)) {
            if (!Topics.Types.SAGA_STEP_CHANGED.equals(evt.type())) {
                log.warn("Tipo desconhecido ignorado em {}: {}", Topics.SAGA_EVENTS, evt.type());
                return;
            }
            if (!idempotency.tryMarkProcessed(evt.messageId())) {
                return;
            }
            if (!repo.exists(evt.orderId())) {
                log.warn("saga.step-changed para pedido inexistente orderId={}", evt.orderId());
                return;
            }
            StepChanged s = messages.payload(evt, StepChanged.class);
            repo.addHistory(evt.orderId(), s.step(), s.stepStatus(), s.attempt() == null ? 1 : s.attempt(),
                    s.detail(), evt.occurredAt());
        }
    }
}
