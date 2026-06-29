-- Migration 016: add notification_email override column to employees.
-- When set, outgoing approval-request emails go to this address instead of email.
-- Allows routing HR notifications to a shared inbox without overwriting the real work email.
-- Odoo sync always uses email (the real work email) — never notification_email.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS notification_email TEXT;
