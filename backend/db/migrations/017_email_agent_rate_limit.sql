-- Migration 017: Email agent rate-limit table
-- Tracks inbound email volume per sender to prevent abuse.
-- Loop detection and identity checks happen BEFORE this table is touched.

CREATE TABLE IF NOT EXISTS email_agent_rate_limit (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    sender_email    TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    request_count   INT NOT NULL DEFAULT 1,
    blocked_until   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, sender_email)
);

CREATE INDEX IF NOT EXISTS idx_earl_tenant_sender
    ON email_agent_rate_limit(tenant_id, sender_email);

GRANT SELECT, INSERT, UPDATE ON email_agent_rate_limit TO fotopia_app;
GRANT USAGE, SELECT ON SEQUENCE email_agent_rate_limit_id_seq TO fotopia_app;
