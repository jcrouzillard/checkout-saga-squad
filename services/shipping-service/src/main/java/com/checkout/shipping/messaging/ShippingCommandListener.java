package com.checkout.shipping.messaging;

import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Topics;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/** Consumidor de {@code shipping.commands} (group id = spring.application.name). Offset confirmado após o commit. */
@Component
public class ShippingCommandListener {

    private final MessageFactory messages;
    private final ShippingCommandHandler handler;

    public ShippingCommandListener(MessageFactory messages, ShippingCommandHandler handler) {
        this.messages = messages;
        this.handler = handler;
    }

    @KafkaListener(topics = Topics.SHIPPING_COMMANDS)
    public void onCommand(String value) {
        handler.handle(messages.read(value));
    }
}
