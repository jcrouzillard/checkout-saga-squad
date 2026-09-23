package com.checkout.inventory.messaging;

import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Topics;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/** Consumidor de {@code inventory.commands} (group id = spring.application.name). Offset confirmado após o commit. */
@Component
public class InventoryCommandListener {

    private final MessageFactory messages;
    private final InventoryCommandHandler handler;

    public InventoryCommandListener(MessageFactory messages, InventoryCommandHandler handler) {
        this.messages = messages;
        this.handler = handler;
    }

    @KafkaListener(topics = Topics.INVENTORY_COMMANDS)
    public void onCommand(String value) {
        handler.handle(messages.read(value));
    }
}
