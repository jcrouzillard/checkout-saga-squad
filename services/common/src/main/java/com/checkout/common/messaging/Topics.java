package com.checkout.common.messaging;

import java.util.List;

/** Nomes de tópicos e tipos de mensagem exatamente como em docs/contracts/events.md §1/§4. */
public final class Topics {
    private Topics() {}

    public static final int PARTITIONS = 3;

    public static final String ORDER_EVENTS = "order.events";
    public static final String ORDER_COMMANDS = "order.commands";
    public static final String INVENTORY_COMMANDS = "inventory.commands";
    public static final String INVENTORY_EVENTS = "inventory.events";
    public static final String PAYMENT_COMMANDS = "payment.commands";
    public static final String PAYMENT_EVENTS = "payment.events";
    public static final String SHIPPING_COMMANDS = "shipping.commands";
    public static final String SHIPPING_EVENTS = "shipping.events";
    public static final String SAGA_EVENTS = "saga.events";

    public static final List<String> ALL = List.of(ORDER_EVENTS, ORDER_COMMANDS, INVENTORY_COMMANDS, INVENTORY_EVENTS,
            PAYMENT_COMMANDS, PAYMENT_EVENTS, SHIPPING_COMMANDS, SHIPPING_EVENTS, SAGA_EVENTS);

    /** Valores do campo {@code type} do envelope. */
    public static final class Types {
        private Types() {}

        public static final String ORDER_CREATED = "order.created";
        public static final String ORDER_CONFIRMED = "order.confirmed";
        public static final String ORDER_CANCELED = "order.canceled";
        public static final String ORDER_CONFIRM = "order.confirm";
        public static final String ORDER_CANCEL = "order.cancel";

        public static final String INVENTORY_RESERVE = "inventory.reserve";
        public static final String INVENTORY_RELEASE = "inventory.release";
        public static final String INVENTORY_RESERVED = "inventory.reserved";
        public static final String INVENTORY_REJECTED = "inventory.rejected";
        public static final String INVENTORY_RELEASED = "inventory.released";

        public static final String PAYMENT_AUTHORIZE = "payment.authorize";
        public static final String PAYMENT_REFUND = "payment.refund";
        public static final String PAYMENT_AUTHORIZED = "payment.authorized";
        public static final String PAYMENT_FAILED = "payment.failed";
        public static final String PAYMENT_REFUNDED = "payment.refunded";

        public static final String SHIPMENT_CREATE = "shipment.create";
        public static final String SHIPMENT_CANCEL = "shipment.cancel";
        public static final String SHIPMENT_CREATED = "shipment.created";
        public static final String SHIPMENT_FAILED = "shipment.failed";
        public static final String SHIPMENT_CANCELED = "shipment.canceled";

        public static final String SAGA_STEP_CHANGED = "saga.step-changed";
    }
}
