package com.checkout.saga.domain;

import com.checkout.common.messaging.Topics;
import com.checkout.common.messaging.Topics.Types;

import java.util.Set;

/** Estados da máquina (docs/architecture/saga.md §1) com o comando enviado ao entrar e as respostas esperadas. */
public enum SagaStatus {
    RESERVING_INVENTORY(Step.INVENTORY, Kind.ACTION, Topics.INVENTORY_COMMANDS, Types.INVENTORY_RESERVE,
            Set.of(Types.INVENTORY_RESERVED, Types.INVENTORY_REJECTED)),
    AUTHORIZING_PAYMENT(Step.PAYMENT, Kind.ACTION, Topics.PAYMENT_COMMANDS, Types.PAYMENT_AUTHORIZE,
            Set.of(Types.PAYMENT_AUTHORIZED, Types.PAYMENT_FAILED)),
    CREATING_SHIPMENT(Step.SHIPPING, Kind.ACTION, Topics.SHIPPING_COMMANDS, Types.SHIPMENT_CREATE,
            Set.of(Types.SHIPMENT_CREATED, Types.SHIPMENT_FAILED)),
    CANCELING_SHIPMENT(Step.SHIPPING, Kind.COMPENSATION, Topics.SHIPPING_COMMANDS, Types.SHIPMENT_CANCEL,
            Set.of(Types.SHIPMENT_CANCELED)),
    REFUNDING_PAYMENT(Step.PAYMENT, Kind.COMPENSATION, Topics.PAYMENT_COMMANDS, Types.PAYMENT_REFUND,
            Set.of(Types.PAYMENT_REFUNDED)),
    RELEASING_INVENTORY(Step.INVENTORY, Kind.COMPENSATION, Topics.INVENTORY_COMMANDS, Types.INVENTORY_RELEASE,
            Set.of(Types.INVENTORY_RELEASED)),
    CONFIRMING_ORDER(Step.ORDER, Kind.FINALIZATION, Topics.ORDER_COMMANDS, Types.ORDER_CONFIRM,
            Set.of(Types.ORDER_CONFIRMED)),
    CANCELING_ORDER(Step.ORDER, Kind.FINALIZATION, Topics.ORDER_COMMANDS, Types.ORDER_CANCEL,
            Set.of(Types.ORDER_CANCELED)),
    COMPLETED(Step.ORDER, Kind.TERMINAL, null, null, Set.of()),
    CANCELED(Step.ORDER, Kind.TERMINAL, null, null, Set.of());

    public enum Kind { ACTION, COMPENSATION, FINALIZATION, TERMINAL }

    private final Step step;
    private final Kind kind;
    private final String commandTopic;
    private final String commandType;
    private final Set<String> expectedReplies;

    SagaStatus(Step step, Kind kind, String commandTopic, String commandType, Set<String> expectedReplies) {
        this.step = step;
        this.kind = kind;
        this.commandTopic = commandTopic;
        this.commandType = commandType;
        this.expectedReplies = expectedReplies;
    }

    public Step step() { return step; }
    public Kind kind() { return kind; }
    public String commandTopic() { return commandTopic; }
    public String commandType() { return commandType; }
    public boolean isTerminal() { return kind == Kind.TERMINAL; }
    public boolean isAction() { return kind == Kind.ACTION; }
    /** Compensações e order.confirm/cancel: retry infinito com backoff limitado. */
    public boolean retriesForever() { return kind == Kind.COMPENSATION || kind == Kind.FINALIZATION; }
    public boolean expects(String replyType) { return expectedReplies.contains(replyType); }

    /** Compensação do próprio passo quando os retries de uma ação se esgotam (saga.md §2). */
    public SagaStatus compensationOnTimeout() {
        return switch (this) {
            case RESERVING_INVENTORY -> RELEASING_INVENTORY;
            case AUTHORIZING_PAYMENT -> REFUNDING_PAYMENT;
            case CREATING_SHIPMENT -> CANCELING_SHIPMENT;
            default -> throw new IllegalStateException("Sem compensação por timeout para " + this);
        };
    }

    /** Valor da tag {@code outcome} (CONFIRMED|CANCELED — parecer G1: COMPLETED é mapeado para CONFIRMED). */
    public String outcome() {
        return switch (this) {
            case COMPLETED -> "CONFIRMED";
            case CANCELED -> "CANCELED";
            default -> null;
        };
    }
}
