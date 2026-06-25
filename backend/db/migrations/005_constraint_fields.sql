-- Migration 005 — Constraint engine fields
-- Idempotent: safe to re-run.

-- Add medical certificate flag to leave_requests
ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS
    has_medical_certificate BOOLEAN NOT NULL DEFAULT FALSE;

-- Extend tenants.settings with constraint thresholds (only if not already set)
UPDATE tenants
SET settings = settings || jsonb_build_object(
    'constraints', jsonb_build_object(
        'max_concurrent_leave_pct', 0.25,
        'allow_balance_override_roles', ARRAY['hr_manager', 'admin']
    )
)
WHERE slug = 'fotopia'
  AND (settings -> 'constraints' IS NULL);
