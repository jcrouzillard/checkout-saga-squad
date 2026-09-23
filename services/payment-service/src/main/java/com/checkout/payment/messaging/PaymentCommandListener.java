package com.checkout.payment.messaging;

import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Topics;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/** Consumidor de {@code payment.commands} (group id = spring.application.name). Offset confirmado após o commit. */
@Component
public class PaymentCommandListener {

    private final MessageFactory messages;
    private final PaymentCommandHandler handler;

    public PaymentCommandListener(MessageFactory messages, PaymentCommandHandler handler) {
        this.messages = messages;
        this.handler = handler;
    }

    @KafkaListener(topics = Topics.PAYMENT_COMMANDS)
    public void onCommand(String value) {
        handler.handle(messages.read(value));
    }
}
