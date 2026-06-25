-- Migration 008: Index for IMAP listener hot path.
-- The email listener looks up pending_actions by outbound_message_id on every
-- inbound email. Without an index this is a full-table scan.
CREATE INDEX IF NOT EXISTS pending_actions_outbound_message_id_idx
    ON pending_actions (tenant_id, outbound_message_id)
    WHERE outbound_message_id IS NOT NULL;
