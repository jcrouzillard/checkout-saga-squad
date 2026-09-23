-- docs/architecture/saga.md §3.1 (+ colunas auxiliares: failed_step, failure_message, last_causation_id, step_started_at)
CREATE TABLE saga_instance (
    saga_id           UUID PRIMARY KEY,
    order_id          UUID        NOT NULL UNIQUE,
    status            VARCHAR(32) NOT NULL,
    current_step      VARCHAR(16),
    delivery_type     VARCHAR(16) NOT NULL,
    order_snapshot    JSONB       NOT NULL,
    payment_id        UUID,
    shipment_id       UUID,
    tracking_code     VARCHAR(64),
    last_command_id   UUID,
    last_command_type VARCHAR(40),
    last_causation_id UUID,
    attempt           INT         NOT NULL DEFAULT 0,
    deadline_at       TIMESTAMPTZ,
    next_retry_at     TIMESTAMPTZ,
    step_started_at   TIMESTAMPTZ,
    failure_reason    VARCHAR(32),
    failed_step       VARCHAR(16),
    failure_message   TEXT,
    correlation_id    UUID,
    trace_parent      VARCHAR(64),
    version           BIGINT      NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_saga_deadline ON saga_instance (deadline_at) WHERE status NOT IN ('COMPLETED', 'CANCELED');
CREATE INDEX ix_saga_next_retry ON saga_instance (next_retry_at) WHERE status NOT IN ('COMPLETED', 'CANCELED');

CREATE TABLE saga_step_log (
    id           BIGSERIAL PRIMARY KEY,
    saga_id      UUID        NOT NULL REFERENCES saga_instance(saga_id),
    step         VARCHAR(16),
    action       VARCHAR(32) NOT NULL, -- COMMAND_SENT | REPLY_RECEIVED | TIMEOUT | RETRY | COMPENSATION_STARTED | IGNORED_LATE_REPLY | COMPENSATION_STUCK
    message_type VARCHAR(40),
    message_id   UUID,
    attempt      INT,
    detail       TEXT,
    created_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_saga_step_log_saga ON saga_step_log (saga_id, id);
