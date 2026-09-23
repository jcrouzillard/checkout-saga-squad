-- Migração COMPARTILHADA (lib common) — aplicada em todos os serviços.
-- Versão 0.1 para nunca colidir com as migrações do serviço (classpath:db/migration, V1__, V2__, ...).
-- Colunas conforme docs/architecture/saga.md §3.1 (coluna do traceparent = trace_parent, parecer G1 do Jev).

CREATE TABLE IF NOT EXISTS outbox (
    id               BIGSERIAL PRIMARY KEY,
    message_id       UUID         NOT NULL,          -- NÃO é único: retry de comando reutiliza o message_id
    topic            VARCHAR(64)  NOT NULL,
    message_key      VARCHAR(64)  NOT NULL,          -- orderId (chave de partição)
    type             VARCHAR(40)  NOT NULL,
    payload          JSONB        NOT NULL,          -- envelope completo
    trace_parent     VARCHAR(64),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    published_at     TIMESTAMPTZ,
    publish_attempts INT          NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_outbox_pending ON outbox (id) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_outbox_message_id ON outbox (message_id);

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id   UUID        NOT NULL,
    consumer     VARCHAR(64) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, consumer)
);
