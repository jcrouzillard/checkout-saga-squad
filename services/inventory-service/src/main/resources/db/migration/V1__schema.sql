-- inventory-service: saldo por SKU e reservas (saga.md §3.1, events.md §4.3/§5)
CREATE TABLE stock (
    sku        VARCHAR(64) PRIMARY KEY,
    available  INT         NOT NULL CHECK (available >= 0),
    reserved   INT         NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    version    BIGINT      NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- No máximo uma reserva por pedido (events.md §5.3). Também guarda tombstones de compensação (§5.4).
CREATE TABLE reservations (
    order_id       UUID        PRIMARY KEY,
    reservation_id UUID,                          -- null em REJECTED e em tombstone
    status         VARCHAR(16) NOT NULL,          -- RESERVED | RELEASED | REJECTED
    items          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    noop           BOOLEAN     NOT NULL DEFAULT FALSE,
    reason         VARCHAR(32),                   -- motivo da rejeição (OUT_OF_STOCK | UNKNOWN_SKU)
    message        VARCHAR(255),
    details        JSONB,                         -- detalhes da rejeição (re-publicação idêntica)
    attempts       INT         NOT NULL DEFAULT 0, -- nº de comandos inventory.reserve recebidos (simulate)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_reservations_reservation_id UNIQUE (reservation_id)
);
