package com.checkout.saga.messaging;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Topics;
import com.checkout.common.observability.SagaMdc;
import com.checkout.saga.app.SagaService;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/**
 * Consome order.events e as respostas dos participantes (group id = saga-orchestrator). O SagaService abre a
 * transação; o offset é confirmado só após o commit (AckMode RECORD).
 */
@Component
public class SagaEventListener {

    private final MessageFactory messages;
    private final SagaService service;

    public SagaEventListener(MessageFactory messages, SagaService service) {
        this.messages = messages;
        this.service = service;
    }

    @KafkaListener(topics = {Topics.ORDER_EVENTS, Topics.INVENTORY_EVENTS, Topics.PAYMENT_EVENTS,
            Topics.SHIPPING_EVENTS})
    public void onEvent(String value) {
        MessageEnvelope env = messages.read(value);
        try (var mdc = SagaMdc.of(env)) {
            service.handle(env);
        }
    }
}
