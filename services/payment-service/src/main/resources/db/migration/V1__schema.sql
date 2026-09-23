-- payment-service: um pagamento por pedido (events.md §4.4/§5.3) + tombstone de estorno (§5.4)
CREATE TABLE payments (
    order_id           UUID          PRIMARY KEY,
    payment_id         UUID,                            -- null no tombstone (refund sem autorização)
    status             VARCHAR(16)   NOT NULL,          -- AUTHORIZED | DECLINED | REFUNDED
    customer_id        VARCHAR(100),
    amount             NUMERIC(12,2) NOT NULL,
    currency           VARCHAR(3)    NOT NULL,
    authorization_code VARCHAR(32),
    noop               BOOLEAN       NOT NULL DEFAULT FALSE,
    attempts           INT           NOT NULL DEFAULT 0, -- nº de payment.authorize recebidos (TIMEOUT_ONCE)
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_payments_payment_id UNIQUE (payment_id)
);

-- Respostas atrasadas de simulate.payment=SLOW: persistidas com prazo e movidas para o outbox por um agendador
-- (sem Thread.sleep no consumidor; sobrevive a reinício do serviço).
CREATE TABLE delayed_replies (
    id           BIGSERIAL    PRIMARY KEY,
    topic        VARCHAR(64)  NOT NULL,
    envelope     TEXT         NOT NULL,
    trace_parent VARCHAR(64),
    due_at       TIMESTAMPTZ  NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_delayed_replies_due ON delayed_replies (due_at);
