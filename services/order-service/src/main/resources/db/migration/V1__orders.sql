CREATE TABLE orders (
    order_id             UUID PRIMARY KEY,
    saga_id              UUID          NOT NULL UNIQUE,
    idempotency_key      VARCHAR(100)  NOT NULL UNIQUE,
    request_hash         VARCHAR(64)   NOT NULL,
    customer_id          VARCHAR(100)  NOT NULL,
    status               VARCHAR(16)   NOT NULL,           -- PENDING | CONFIRMED | CANCELED
    delivery_type        VARCHAR(16)   NOT NULL,           -- PHYSICAL | DIGITAL
    total_amount         NUMERIC(14,2) NOT NULL,
    currency             VARCHAR(3)    NOT NULL,
    shipping_address     JSONB,
    simulate             JSONB,
    payment_id           UUID,
    shipment_id          UUID,
    tracking_code        VARCHAR(64),
    cancellation_reason  VARCHAR(32),
    failed_step          VARCHAR(16),
    cancellation_message TEXT,
    correlation_id       UUID          NOT NULL,
    created_at           TIMESTAMPTZ   NOT NULL,
    updated_at           TIMESTAMPTZ   NOT NULL
);

CREATE TABLE order_items (
    id         BIGSERIAL PRIMARY KEY,
    order_id   UUID          NOT NULL REFERENCES orders(order_id),
    line_no    INT           NOT NULL,
    sku        VARCHAR(64)   NOT NULL,
    quantity   INT           NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL
);
CREATE INDEX ix_order_items_order ON order_items(order_id);

CREATE TABLE order_status_history (
    id         BIGSERIAL PRIMARY KEY,
    order_id   UUID        NOT NULL REFERENCES orders(order_id),
    step       VARCHAR(16) NOT NULL,
    status     VARCHAR(32) NOT NULL,
    attempt    INT         NOT NULL DEFAULT 1,
    detail     TEXT,
    at         TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_order_history_order ON order_status_history(order_id, at, id);
