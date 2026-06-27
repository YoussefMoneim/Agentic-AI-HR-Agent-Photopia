-- Migration 010: WIN Holding Leave Policy (HR/BTE 001/7-2025)
--
-- Adds 8 missing leave types, two new columns on leave_types for career-cap
-- enforcement, casual sub-quota tracking on leave_balances, and corrects the
-- annual leave notice period (flat 2-day → split 1-day/7-working-day rule,
-- enforced in application code; policy row is reset to 0).

-- ─── 1. New columns on leave_types ───────────────────────────────────────────
ALTER TABLE leave_types
    ADD COLUMN IF NOT EXISTS max_times_in_career INTEGER,       -- NULL = no career cap
    ADD COLUMN IF NOT EXISTS service_min_days     INTEGER NOT NULL DEFAULT 0;  -- min employment days before eligible

-- ─── 2. Casual sub-quota tracking on leave_balances ──────────────────────────
ALTER TABLE leave_balances
    ADD COLUMN IF NOT EXISTS casual_used_days NUMERIC(5,1) NOT NULL DEFAULT 0;

-- ─── 3. Fix annual leave min_notice ──────────────────────────────────────────
-- WIN policy: 24h for 2-3 day requests; 7 working days for >3 day requests.
-- Split logic is enforced in tools/leave.py. The flat value is cleared here.
UPDATE leave_policies lp
SET min_notice_days = 0
FROM leave_types lt, tenants t
WHERE lp.leave_type_id = lt.id
  AND lt.tenant_id = t.id
  AND t.slug = 'fotopia'
  AND lt.code = 'annual';

-- ─── 4. Eight new leave types ─────────────────────────────────────────────────

-- marriage: 5 days paid, once per career, 1-year service minimum
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'marriage', 'Marriage Leave', 'إجازة زواج', TRUE,
    FALSE, FALSE, FALSE, TRUE,
    5, 5, 1, 365
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- hajj: 1 month paid (~30 days), once per career, 5-year service minimum
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'hajj', 'Hajj Leave', 'إجازة حج', TRUE,
    FALSE, FALSE, FALSE, TRUE,
    30, 30, 1, 1825
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- umrah: 5 days paid, once per career, 1-year service minimum
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'umrah', 'Umrah Leave', 'إجازة عمرة', TRUE,
    FALSE, FALSE, FALSE, TRUE,
    5, 5, 1, 365
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- military_summon: duration per official letter, full pay, no cap, no service minimum
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_times_in_career, service_min_days)
SELECT id, 'military_summon', 'Military Service Summon', 'إجازة التجنيد', TRUE,
    TRUE, FALSE, FALSE, TRUE,
    NULL, 0
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- educational: exam days only, must share exam schedule with HR in advance
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_times_in_career, service_min_days)
SELECT id, 'educational', 'Educational Exam Leave', 'إجازة الامتحانات', TRUE,
    TRUE, FALSE, FALSE, FALSE,
    NULL, 0
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- funeral: 3 days (1st-degree relatives) or 1 day (2nd-degree); HR verifies relationship
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'funeral', 'Funeral Leave', 'إجازة الوفاة', TRUE,
    FALSE, FALSE, FALSE, TRUE,
    3, NULL, 0
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- maternity: 4 months (~120 days) full pay, 3 times in career, 1-year service minimum
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'maternity', 'Maternity Leave', 'إجازة الأمومة', TRUE,
    FALSE, FALSE, FALSE, TRUE,
    120, 120, 3, 365
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- paternity: 1 day on delivery/surgery date, 3 times in career
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval,
    requires_documentation, deducts_balance, is_time_based, requires_hr_review,
    max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'paternity', 'Paternity Leave', 'إجازة الأبوة', TRUE,
    FALSE, FALSE, FALSE, FALSE,
    1, 1, 3, 0
FROM tenants WHERE slug = 'fotopia'
ON CONFLICT (tenant_id, code) DO NOTHING;

-- ─── 5. Leave policies for new types (all defaults; constraints enforced in code) ──
INSERT INTO leave_policies (tenant_id, leave_type_id)
SELECT t.id, lt.id
FROM tenants t
JOIN leave_types lt
    ON lt.tenant_id = t.id
    AND lt.code IN ('marriage', 'hajj', 'umrah', 'military_summon',
                    'educational', 'funeral', 'maternity', 'paternity')
WHERE t.slug = 'fotopia'
ON CONFLICT (tenant_id, leave_type_id) DO NOTHING;
