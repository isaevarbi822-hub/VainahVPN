-- Execute once in the VainahVPN PostgreSQL database before exposing webhook.
CREATE TABLE IF NOT EXISTS rollypay_webhook_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payment_id VARCHAR(128) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL,
    is_test BOOLEAN NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    UNIQUE (payment_id, payload_sha256)
);
CREATE INDEX IF NOT EXISTS idx_rollypay_events_pending
    ON rollypay_webhook_events (received_at)
    WHERE processed_at IS NULL;
