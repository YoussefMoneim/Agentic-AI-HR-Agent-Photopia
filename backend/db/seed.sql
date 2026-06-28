-- CTE creates the tenant and employees in one atomic statement.
WITH fotopia AS (
    INSERT INTO tenants (name, slug)
    VALUES ('Fotopia Technologies', 'fotopia')
    RETURNING id
)
INSERT INTO employees (
    tenant_id, employee_code, full_name, arabic_name,
    position, department, employment_type, start_date,
    basic_salary, housing_allowance, transport_allowance, total_salary,
    currency, annual_leave_balance, email, manager_name
)
SELECT
    fotopia.id,
    emp.employee_code, emp.full_name, emp.arabic_name,
    emp.position, emp.department, emp.employment_type, emp.start_date::DATE,
    emp.basic_salary, emp.housing_allowance, emp.transport_allowance, emp.total_salary,
    'EGP', emp.annual_leave_balance, emp.email, emp.manager_name
FROM fotopia, (VALUES
    ('EMP001', 'Saif Ahmed Hassan',  'سيف أحمد حسن',    'Software Engineer',  'R&D',  'Full-time', '2022-03-15', 20000, 2500, 1500, 24000, 8,  'saif.hassan@fotopia.ai',    'Dr. Ahmed El-Yazbi'),
    ('EMP002', 'Nourhan Hosny',      'نورهان حسني',      'HR Project Lead',    'HR',   'Full-time', '2021-06-01', 24000, 3000, 2000, 29000, 12, 'hr.agent.fotopia@gmail.com',  'Raef Eid'),
    ('EMP003', 'Omar Alsayed',       'عمر السيد',        'ML Engineer',        'R&D',  'Full-time', '2023-01-10', 21500, 2500, 2000, 26000, 5,  'omar.alsayed@fotopia.ai',   'Dr. Ahmed El-Yazbi')
) AS emp(employee_code, full_name, arabic_name, position, department, employment_type, start_date, basic_salary, housing_allowance, transport_allowance, total_salary, annual_leave_balance, email, manager_name);

-- Set manager_id FK. EMP001 and EMP003 (R&D) report to EMP002 (Nourhan, HR Lead) for
-- leave approvals in the demo. In production, Dr. Ahmed El-Yazbi and Raef Eid would be
-- added as employee records and linked here.
UPDATE employees e
SET manager_id = mgr.id
FROM employees mgr
WHERE e.employee_code IN ('EMP001', 'EMP003')
  AND mgr.employee_code = 'EMP002'
  AND e.tenant_id = mgr.tenant_id;

-- ─── Leave types — sourced from Leaves Policy EG Ref: HR/BTE 001/7-2025 ──────
-- Columns: code, name_en, name_ar, requires_approval, requires_documentation,
--          deducts_balance, is_time_based, requires_hr_review,
--          max_days_per_year, max_consecutive_days

-- Annual: 21 days/year (15 in hire year, 30 for age 50+ or 10+ SI years). Balance-tracked.
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'annual', 'Annual Leave', 'إجازة سنوية', TRUE, FALSE, TRUE, FALSE, TRUE, 21, NULL
FROM tenants WHERE slug = 'fotopia';

-- Sick: requires medical report from company network provider
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'sick', 'Sick Leave', 'إجازة مرضية', TRUE, TRUE, TRUE, FALSE, TRUE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- Emergency: kept for backward compatibility; Funeral/Bereavement now has its own type below
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'emergency', 'Emergency Leave', 'إجازة طارئة', TRUE, FALSE, FALSE, FALSE, TRUE, NULL, 6
FROM tenants WHERE slug = 'fotopia';

-- Permission: hours-based, not days
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'permission', 'Permission', 'إذن خروج', TRUE, FALSE, FALSE, TRUE, FALSE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- Business trip
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'business_trip', 'Business Trip', 'رحلة عمل', TRUE, FALSE, FALSE, FALSE, TRUE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- WFH: max 2 days/week, 8 days/month (enforced via leave_policies)
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'wfh', 'Work From Home', 'عمل من المنزل', TRUE, FALSE, FALSE, FALSE, FALSE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- Outside duty
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'outside_duty', 'Outside Duty', 'مهمة خارجية', TRUE, FALSE, FALSE, FALSE, FALSE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- Compensatory: earned by working 4+ hours on holiday/weekend; added to vacation balance
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'compensatory', 'Compensatory Off', 'إجازة تعويضية', TRUE, FALSE, TRUE, FALSE, TRUE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- Unpaid
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'unpaid', 'Unpaid Leave', 'إجازة بدون مرتب', TRUE, FALSE, FALSE, FALSE, TRUE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- Marriage: 5 days paid, once per service life, 1+ year service required
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'marriage', 'Marriage Leave', 'إجازة زواج', TRUE, TRUE, FALSE, FALSE, TRUE, 5, 5
FROM tenants WHERE slug = 'fotopia';

-- Hajj: up to 30 days, 5+ years service, once per service life
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'hajj', 'Hajj Leave', 'إجازة حج', TRUE, TRUE, FALSE, FALSE, TRUE, 30, 30
FROM tenants WHERE slug = 'fotopia';

-- Umrah: 5 days paid, once per service life, 1+ year service required
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'umrah', 'Umrah Leave', 'إجازة عمرة', TRUE, TRUE, FALSE, FALSE, TRUE, 5, 5
FROM tenants WHERE slug = 'fotopia';

-- Funeral/Bereavement: 3 days 1st-degree relatives, 1 day 2nd-degree (enforced in tool logic)
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'funeral', 'Funeral/Bereavement Leave', 'إجازة وفاة', TRUE, FALSE, FALSE, FALSE, TRUE, 3, 3
FROM tenants WHERE slug = 'fotopia';

-- Maternity: 4 months (120 days) full pay, 1+ year service, max 3 times during service
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'maternity', 'Maternity Leave', 'إجازة أمومة', TRUE, TRUE, FALSE, FALSE, TRUE, 120, 120
FROM tenants WHERE slug = 'fotopia';

-- Paternity: 1 day on delivery surgery day only, max 3 times during service
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'paternity', 'Paternity Leave', 'إجازة أبوة', TRUE, TRUE, FALSE, FALSE, TRUE, 1, 1
FROM tenants WHERE slug = 'fotopia';

-- Educational: restricted to exam days only, schedule must be shared with HR in advance
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'educational', 'Educational Leave', 'إجازة دراسية', TRUE, TRUE, FALSE, FALSE, TRUE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- Military service: full paid, duration per official military authority letter
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
SELECT id, 'military', 'Military Service Leave', 'إجازة خدمة عسكرية', FALSE, TRUE, FALSE, FALSE, TRUE, NULL, NULL
FROM tenants WHERE slug = 'fotopia';

-- ─── Leave balances for 2026 ──────────────────────────────────────────────────
-- Annual leave: all three employees were hired before 2026 → full 21-day allocation.
-- Proration applies only in the hire year; subsequent years are always full.
INSERT INTO leave_balances (tenant_id, employee_id, leave_type_id, year, allocated_days, used_days, pending_days)
SELECT e.tenant_id, e.id, lt.id, 2026, 21.0, 0.0, 0.0
FROM employees e
JOIN leave_types lt ON lt.tenant_id = e.tenant_id AND lt.code = 'annual'
JOIN tenants t ON t.id = e.tenant_id
WHERE t.slug = 'fotopia';

-- Sick leave: 90 days allocated per year (Egyptian Labor Law — 90 days fully/partially paid).
INSERT INTO leave_balances (tenant_id, employee_id, leave_type_id, year, allocated_days, used_days, pending_days)
SELECT e.tenant_id, e.id, lt.id, 2026, 90.0, 0.0, 0.0
FROM employees e
JOIN leave_types lt ON lt.tenant_id = e.tenant_id AND lt.code = 'sick'
JOIN tenants t ON t.id = e.tenant_id
WHERE t.slug = 'fotopia';

-- Compensatory off: starts at 0; earned by working weekends/holidays (future integration).
INSERT INTO leave_balances (tenant_id, employee_id, leave_type_id, year, allocated_days, used_days, pending_days)
SELECT e.tenant_id, e.id, lt.id, 2026, 0.0, 0.0, 0.0
FROM employees e
JOIN leave_types lt ON lt.tenant_id = e.tenant_id AND lt.code = 'compensatory'
JOIN tenants t ON t.id = e.tenant_id
WHERE t.slug = 'fotopia';

-- ─── Leave policies (flat model — one row per leave type) ─────────────────────

-- annual: 21 days/year, 90-day probation block, 2 days minimum notice
INSERT INTO leave_policies (tenant_id, leave_type_id, probation_restriction_days, annual_allowance_days, min_notice_days)
SELECT t.id, lt.id, 90, 21, 2
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'annual'
WHERE t.slug = 'fotopia';

-- sick: medical certificate required after 3 consecutive days; no probation restriction
INSERT INTO leave_policies (tenant_id, leave_type_id, requires_medical_cert_after_days)
SELECT t.id, lt.id, 3
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'sick'
WHERE t.slug = 'fotopia';

-- emergency: max 6 days per request; no probation restriction (genuine emergencies)
INSERT INTO leave_policies (tenant_id, leave_type_id, max_consecutive_days)
SELECT t.id, lt.id, 6
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'emergency'
WHERE t.slug = 'fotopia';

-- permission: 1 hour minimum (enforced in tool logic); no day-based limits
INSERT INTO leave_policies (tenant_id, leave_type_id)
SELECT t.id, lt.id
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'permission'
WHERE t.slug = 'fotopia';

-- business_trip: no special policy limits
INSERT INTO leave_policies (tenant_id, leave_type_id)
SELECT t.id, lt.id
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'business_trip'
WHERE t.slug = 'fotopia';

-- wfh: max 2 days per week, max 8 days per month
INSERT INTO leave_policies (tenant_id, leave_type_id, wfh_max_days_per_week, wfh_max_days_per_month)
SELECT t.id, lt.id, 2, 8
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'wfh'
WHERE t.slug = 'fotopia';

-- outside_duty: no special policy limits
INSERT INTO leave_policies (tenant_id, leave_type_id)
SELECT t.id, lt.id
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'outside_duty'
WHERE t.slug = 'fotopia';

-- compensatory: must have earned balance; no other restrictions
INSERT INTO leave_policies (tenant_id, leave_type_id)
SELECT t.id, lt.id
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'compensatory'
WHERE t.slug = 'fotopia';

-- unpaid: 90-day probation restriction
INSERT INTO leave_policies (tenant_id, leave_type_id, probation_restriction_days)
SELECT t.id, lt.id, 90
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = 'unpaid'
WHERE t.slug = 'fotopia';

-- ─── WIN Holding leave types (migration 010 + 011) ──────────────────────────
-- These cover the full HR/BTE 001/7-2025 leave type set beyond the base 9.

INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'marriage', 'Marriage Leave', 'إجازة زواج', TRUE, FALSE, FALSE, FALSE, TRUE, 5, 5, 1, 365
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'hajj', 'Hajj Leave', 'إجازة حج', TRUE, FALSE, FALSE, FALSE, TRUE, 30, 30, 1, 1825
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'umrah', 'Umrah Leave', 'إجازة عمرة', TRUE, FALSE, FALSE, FALSE, TRUE, 5, 5, 1, 365
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_times_in_career, service_min_days)
SELECT id, 'military_summon', 'Military Service Summon', 'إجازة التجنيد', TRUE, TRUE, FALSE, FALSE, TRUE, NULL, 0
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_times_in_career, service_min_days)
SELECT id, 'educational', 'Educational Exam Leave', 'إجازة الامتحانات', TRUE, TRUE, FALSE, FALSE, FALSE, NULL, 0
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

-- funeral (generic — inserted then immediately deactivated; degree-split types below are the active ones)
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'funeral', 'Funeral Leave', 'إجازة الوفاة', TRUE, FALSE, FALSE, FALSE, TRUE, 3, NULL, 0
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

UPDATE leave_types SET is_active = FALSE
FROM tenants WHERE tenants.id = leave_types.tenant_id AND tenants.slug = 'fotopia' AND leave_types.code = 'funeral';

INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'maternity', 'Maternity Leave', 'إجازة الأمومة', TRUE, FALSE, FALSE, FALSE, TRUE, 120, 120, 3, 365
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'paternity', 'Paternity Leave', 'إجازة الأبوة', TRUE, FALSE, FALSE, FALSE, FALSE, 1, 1, 3, 0
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

-- funeral_1st_degree: Father/Mother/Son/Daughter/Husband/Wife — 3 working days
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'funeral_1st_degree', 'Funeral Leave (1st Degree)', 'إجازة وفاة (درجة أولى)', TRUE, FALSE, FALSE, FALSE, TRUE, 3, 3, NULL, 0
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

-- funeral_2nd_degree: Grandfather/Grandmother/Brother/Sister/Grandsons — 1 working day
INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days, max_times_in_career, service_min_days)
SELECT id, 'funeral_2nd_degree', 'Funeral Leave (2nd Degree)', 'إجازة وفاة (درجة ثانية)', TRUE, FALSE, FALSE, FALSE, TRUE, 1, 1, NULL, 0
FROM tenants WHERE slug = 'fotopia' ON CONFLICT (tenant_id, code) DO NOTHING;

-- Leave policies for all new types (all defaults; constraints enforced in application code)
INSERT INTO leave_policies (tenant_id, leave_type_id)
SELECT t.id, lt.id
FROM tenants t JOIN leave_types lt ON lt.tenant_id = t.id
    AND lt.code IN ('marriage', 'hajj', 'umrah', 'military_summon', 'educational',
                    'funeral', 'maternity', 'paternity', 'funeral_1st_degree', 'funeral_2nd_degree')
WHERE t.slug = 'fotopia' ON CONFLICT (tenant_id, leave_type_id) DO NOTHING;

-- Reset annual leave min_notice to 0 — split notice logic (1-day/<7-working-days) is in application code
UPDATE leave_policies lp SET min_notice_days = 0
FROM leave_types lt, tenants t
WHERE lp.leave_type_id = lt.id AND lt.tenant_id = t.id AND t.slug = 'fotopia' AND lt.code = 'annual';

-- Seed carry_over_expiry_date for annual leave balances (Q1 — March 31 of the balance year)
UPDATE leave_balances lb SET carry_over_expiry_date = make_date(lb.year, 3, 31)
FROM leave_types lt, tenants t
WHERE lb.leave_type_id = lt.id AND lb.tenant_id = t.id AND t.slug = 'fotopia'
  AND lt.code = 'annual' AND lb.carry_over_expiry_date IS NULL;

-- ─── Tenant settings (migrations 004 + 005) ──────────────────────────────────
UPDATE tenants
SET settings = jsonb_build_object(
    'approval_routing', jsonb_build_object(
        'top_of_hierarchy_action', 'self_approve_flagged',
        'default_deadline_hours', 72
    ),
    'constraints', jsonb_build_object(
        'max_concurrent_leave_pct', 0.25,
        'allow_balance_override_roles', ARRAY['hr_manager', 'admin']
    )
)
WHERE slug = 'fotopia';

-- ─── Demo users (login credentials for testing / demo) ───────────────────────
-- All demo accounts share password 'demo123' (bcrypt hash). Never ship to production.
INSERT INTO users (tenant_id, email, full_name, role, employee_id, password_hash)
SELECT
    t.id,
    e.email,
    e.full_name,
    CASE e.employee_code
        WHEN 'EMP001' THEN 'employee'
        WHEN 'EMP002' THEN 'hr_manager'
        WHEN 'EMP003' THEN 'employee'
    END,
    e.id,
    '$2b$12$4qFSJ1YZ.CoCCX/TPUU2E.J/gcu4v5wiQz42fxPlwJCI6U7rxjfZO'
FROM tenants t
JOIN employees e ON e.tenant_id = t.id AND e.employee_code IN ('EMP001', 'EMP002', 'EMP003')
WHERE t.slug = 'fotopia';
