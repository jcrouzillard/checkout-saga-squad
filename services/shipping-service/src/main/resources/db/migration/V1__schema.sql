-- shipping-service: um envio por pedido (events.md §4.5/§5.3) + tombstone de cancelamento (§5.4)
CREATE TABLE shipments (
    order_id                UUID        PRIMARY KEY,
    shipment_id             UUID,                    -- null em FAILED e no tombstone
    status                  VARCHAR(16) NOT NULL,    -- CREATED | FAILED | CANCELED
    tracking_code           VARCHAR(64),
    carrier                 VARCHAR(32),
    estimated_delivery_date DATE,
    address                 JSONB,
    items                   JSONB       NOT NULL DEFAULT '[]'::jsonb,
    noop                    BOOLEAN     NOT NULL DEFAULT FALSE,
    reason                  VARCHAR(32),             -- motivo da falha (CARRIER_REJECTED | INVALID_ADDRESS)
    message                 VARCHAR(255),
    attempts                INT         NOT NULL DEFAULT 0, -- nº de shipment.create recebidos (TIMEOUT_ONCE)
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_shipments_shipment_id UNIQUE (shipment_id),
    CONSTRAINT uq_shipments_tracking_code UNIQUE (tracking_code)
);
