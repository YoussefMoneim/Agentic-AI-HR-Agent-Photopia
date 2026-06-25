-- Migration 004: tenant settings column
-- Adds a JSONB settings column to tenants for per-tenant configurable behaviour.
-- Initial use: approval_routing policy (top_of_hierarchy_action, default_deadline_hours).
-- Idempotent: safe to run multiple times.

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}';

-- Seed the Fotopia tenant with the default routing policy if not already set.
UPDATE tenants
SET settings = jsonb_build_object(
    'approval_routing', jsonb_build_object(
        'top_of_hierarchy_action', 'self_approve_flagged',
        'default_deadline_hours', 72
    )
)
WHERE slug = 'fotopia'
  AND (settings = '{}' OR settings -> 'approval_routing' IS NULL);
