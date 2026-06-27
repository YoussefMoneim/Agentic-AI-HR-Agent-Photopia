-- Migration 011: WIN Holding Leave Policy — Phase 2 Corrections
-- Ref: HR/BTE 001/7-2025
--
-- Adds: birth_date on employees (age ≥50 → 30-day allocation advisory)
--       is_casual on leave_requests (casual vs regular annual leave flag)
--       carry_over_expiry_date on leave_balances (Q1 expiry enforcement)
--       funeral_1st_degree (3 working days) and funeral_2nd_degree (1 working day)
--       Deactivates generic 'funeral' type (too imprecise — degree determines entitlement)

-- ─── 1. birth_date on employees ───────────────────────────────────────────────
ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS birth_date DATE;

-- ─── 2. is_casual on leave_requests ──────────────────────────────────────────
-- Marks whether an annual leave request is casual (max 2 consecutive days) vs regular.
ALTER TABLE leave_requests
    ADD COLUMN IF NOT EXISTS is_casual BOOLEAN NOT NULL DEFAULT FALSE;

-- ─── 3. carry_over_expiry_date on leave_balances ─────────────────────────────
-- Carry-over days expire on March 31 of the following year (Q1 only).
ALTER TABLE leave_balances
    ADD COLUMN IF NOT EXISTS carry_over_expiry_date DATE;

-- ─── 4. Seed carry_over_expiry_date for existing annual balances ──────────────
-- Set to March 31 of the balance year for all existing annual leave_balances.
UPDATE leave_balances lb
SET carry_over_expiry_date = make_date(lb.year, 3, 31)
FROM leave_types lt, tenants t
WHERE lb.leave_type_id = lt.id
  AND lb.tenant_id = t.id
  AND t.slug = 'fotopia'
  AND lt.code = 'annual'
  AND lb.carry_over_expiry_date IS NULL;

-- ─── 5. Deactivate generic funeral type ──────────────────────────────────────
-- The generic type is too imprecise: degree determines entitlement (3 vs 1 day).
UPDATE leave_types
SET is_active = FALSE
FROM tenants
WHERE tenants.id = leave_types.tenant_id
  AND tenants.slug = 'fotopia'
  AND leave_types.code = 'funeral';

-- ─── 6. Add funeral_1st_degree leave type ────────────────────────────────────
-- Father, Mother, Son, Daughter, Husband, Wife: 3 working days
INSERT INTO leave_types (
    tenant_id, code, name_en, name_ar,
    requires_approval, requires_documentation, deducts_balance,
    is_time_based, requires_hr_review,
    max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days
)
SELECT
    t.id,
    'funeral_1st_degree',
    'Funeral Leave (1st Degree)',
    'إجازة وفاة (درجة أولى)',
    TRUE, FALSE, FALSE,
    FALSE, TRUE,
    3, 3, NULL, 0
FROM tenants t
WHERE t.slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- ─── 7. Add funeral_2nd_degree leave type ────────────────────────────────────
-- Grandfather, Grandmother, Brother, Sister, Grandsons: 1 working day
INSERT INTO leave_types (
    tenant_id, code, name_en, name_ar,
    requires_approval, requires_documentation, deducts_balance,
    is_time_based, requires_hr_review,
    max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days
)
SELECT
    t.id,
    'funeral_2nd_degree',
    'Funeral Leave (2nd Degree)',
    'إجازة وفاة (درجة ثانية)',
    TRUE, FALSE, FALSE,
    FALSE, TRUE,
    1, 1, NULL, 0
FROM tenants t
WHERE t.slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- ─── 8. Leave policies for new funeral types ──────────────────────────────────
INSERT INTO leave_policies (tenant_id, leave_type_id)
SELECT t.id, lt.id
FROM tenants t
JOIN leave_types lt
    ON lt.tenant_id = t.id
    AND lt.code IN ('funeral_1st_degree', 'funeral_2nd_degree')
WHERE t.slug = 'fotopia'
ON CONFLICT (tenant_id, leave_type_id) DO NOTHING;
