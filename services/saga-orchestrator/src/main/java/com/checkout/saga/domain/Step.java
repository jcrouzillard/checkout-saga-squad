package com.checkout.saga.domain;

/** Passo da saga (tag {@code step} das métricas e campo {@code step} de saga.step-changed). */
public enum Step {
    INVENTORY, PAYMENT, SHIPPING, ORDER;

    /** Métricas só usam INVENTORY|PAYMENT|SHIPPING (docs/observability.md). */
    public boolean isParticipant() {
        return this != ORDER;
    }
}
