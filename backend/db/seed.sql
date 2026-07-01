-- CTE creates the tenant and all 26 employees in one atomic statement.
WITH fotopia AS (
    INSERT INTO tenants (name, slug)
    VALUES ('Fotopia Technologies', 'fotopia')
    RETURNING id
)
INSERT INTO employees (
    tenant_id, employee_code, full_name, position, department,
    start_date,
    basic_salary, housing_allowance, transport_allowance, total_salary,
    currency, annual_leave_balance, email, employment_type
)
SELECT
    fotopia.id,
    emp.employee_code, emp.full_name, emp.position, emp.department,
    emp.start_date::DATE,
    emp.basic_salary::NUMERIC, 0, 0, emp.basic_salary::NUMERIC,
    'EGP', 0, emp.email, 'Full-time'
FROM fotopia, (VALUES
    ('FT-2021-001','Mohammed Al Nuaimi',        'Chief Executive Officer',         'Executive',       '2021-01-01', 95000, 'mohammed.nuaimi@fotopiatech.com'),
    ('FT-2021-002','Khalid Al Hashmi',          'Engineering Director',            'Engineering',     '2021-01-10', 45000, 'khalid.hashmi@fotopiatech.com'),
    ('FT-2021-003','Noura Al Rashidi',          'HR Director',                     'Human Resources', '2021-02-01', 42000, 'noura.rashidi@fotopiatech.com'),
    ('FT-2021-004','Ahmed Al Mansouri',         'Senior Software Engineer',        'Engineering',     '2021-03-15', 28000, 'ahmed.mansouri@fotopiatech.com'),
    ('FT-2021-005','Sara Al Zaabi',             'HR Business Partner',             'Human Resources', '2021-05-01', 22000, 'sara.zaabi@fotopiatech.com'),
    ('FT-2022-001','Reem Al Ketbi',             'Product Director',                'Product',         '2022-02-01', 44000, 'reem.ketbi@fotopiatech.com'),
    ('FT-2022-002','Saeed Al Marri',            'Finance Director',                'Finance',         '2022-03-15', 43000, 'saeed.marri@fotopiatech.com'),
    ('FT-2022-003','Tariq Al Ameri',            'Sales Director',                  'Sales',           '2022-04-01', 41000, 'tariq.ameri@fotopiatech.com'),
    ('FT-2022-004','Jaber Al Kindi',            'Marketing Director',              'Marketing',       '2022-05-10', 40000, 'jaber.kindi@fotopiatech.com'),
    ('FT-2022-005','Hessa Al Mazrouei',         'Product Manager',                 'Product',         '2022-09-01', 32000, 'hessa.mazrouei@fotopiatech.com'),
    ('FT-2022-006','Omar Al Shehhi',            'Backend Engineer',                'Engineering',     '2022-04-11', 26000, 'omar.shehhi@fotopiatech.com'),
    ('FT-2022-007','Maryam Al Falasi',          'Senior Finance Analyst',          'Finance',         '2022-06-01', 24000, 'maryam.falasi@fotopiatech.com'),
    ('FT-2022-008','Rashed Al Blooshi',         'DevOps Lead',                     'Engineering',     '2022-07-15', 29000, 'rashed.blooshi@fotopiatech.com'),
    ('FT-2022-009','Fatima Al Suwaidi',         'Senior UI/UX Designer',           'Product',         '2022-02-20', 25000, 'fatima.suwaidi@fotopiatech.com'),
    ('FT-2022-010','Saif Ahmed',                'Mobile Engineer',                 'Engineering',     '2022-11-01', 24000, 'saif.ahmed@fotopiatech.com'),
    ('FT-2022-011','Saif Al Ahmed',             'Mobile Engineer',                 'Engineering',     '2022-11-01', 24000, 'i-saif.ahmed@fotopiatech.com'),
    ('FT-2023-001','Layla Al Qassimi',          'Data Analyst',                    'Engineering',     '2023-01-15', 22000, 'layla.qassimi@fotopiatech.com'),
    ('FT-2023-002','Hamdan Al Nuaimi',          'Sales Executive',                 'Sales',           '2023-03-01', 19000, 'hamdan.nuaimi@fotopiatech.com'),
    ('FT-2023-003','Shaikha Al Ketbi',          'Graphic Designer',                'Product',         '2023-04-10', 18000, 'shaikha.ketbi@fotopiatech.com'),
    ('FT-2023-004','Amna Al Muhairi',           'Content Strategist',              'Marketing',       '2023-06-15', 17000, 'amna.muhairi@fotopiatech.com'),
    ('FT-2023-005','Mansoor Al Dhaheri',        'IT Administrator',                'IT',              '2023-05-20', 21000, 'mansoor.dhaheri@fotopiatech.com'),
    ('FT-2023-006','Wadima Al Hosani',          'Talent Acquisition Specialist',   'Human Resources', '2023-07-01', 18000, 'wadima.hosani@fotopiatech.com'),
    ('FT-2024-001','Maitha Al Romaithi',        'QA Engineer',                     'Engineering',     '2024-02-20', 20000, 'maitha.romaithi@fotopiatech.com'),
    ('FT-2024-002','Zayed Al Kaabi',            'Junior Software Developer',        'Engineering',     '2024-04-01', 18000, 'zayed.kaabi@fotopiatech.com'),
    ('FT-2024-003','Nadia Al Shamsi',           'Junior Sales Associate',           'Sales',           '2024-06-01', 16000, 'nadia.shamsi@fotopiatech.com'),
    ('FT-2026-001','Lina Al Rashidi',           'Junior Data Scientist',            'Engineering',     '2026-03-01', 15000, 'lina.rashidi@fotopiatech.com')
) AS emp(employee_code, full_name, position, department, start_date, basic_salary, email);

-- ─── Manager hierarchy ────────────────────────────────────────────────────────
-- Resolved in post-INSERT UPDATEs (self-referencing FK cannot be set inline).

-- Reporting to CEO (FT-2021-001 — Mohammed Al Nuaimi)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2021-001' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2021-002','FT-2021-003','FT-2022-001','FT-2022-002','FT-2022-003','FT-2022-004')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to Engineering Director (FT-2021-002 — Khalid Al Hashmi)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2021-002' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2021-004','FT-2022-006','FT-2022-008','FT-2022-010','FT-2022-011','FT-2023-001','FT-2024-001','FT-2024-002','FT-2026-001')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to HR Director (FT-2021-003 — Noura Al Rashidi)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2021-003' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2021-005','FT-2023-006')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to Product Director (FT-2022-001 — Reem Al Ketbi)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2022-001' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2022-005')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to Finance Director (FT-2022-002 — Saeed Al Marri)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2022-002' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2022-007')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to Sales Director (FT-2022-003 — Tariq Al Ameri)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2022-003' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2023-002','FT-2024-003')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to Marketing Director (FT-2022-004 — Jaber Al Kindi)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2022-004' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2023-004')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to Product Manager (FT-2022-005 — Hessa Al Mazrouei)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2022-005' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2022-009','FT-2023-003')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Reporting to DevOps Lead (FT-2022-008 — Rashed Al Blooshi)
UPDATE employees e
SET manager_id = (SELECT id FROM employees WHERE employee_code = 'FT-2022-008' AND tenant_id = e.tenant_id)
WHERE e.employee_code IN ('FT-2023-005')
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Denormalized manager_name for display tools (set once after all manager_ids are resolved)
UPDATE employees e
SET manager_name = mgr.full_name
FROM employees mgr
WHERE e.manager_id = mgr.id
  AND e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

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
-- Annual leave: CASE-based allocation per employee.
--   FT-2021-001 (Mohammed Al Nuaimi, born 1972, age 53) → 30 days (age ≥50 enhanced entitlement)
--   FT-2026-001 (Lina Al Rashidi, hired 2026-03-01) → 15 days (first calendar year entitlement)
--   All others → 21 days (standard full-year allocation)
INSERT INTO leave_balances (tenant_id, employee_id, leave_type_id, year, allocated_days, used_days, pending_days)
SELECT e.tenant_id, e.id, lt.id, 2026,
    CASE e.employee_code
        WHEN 'FT-2021-001' THEN 30.0
        WHEN 'FT-2026-001' THEN 15.0
        ELSE 21.0
    END,
    0.0, 0.0
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

-- ─── Tenant settings ──────────────────────────────────────────────────────────
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
-- All 26 accounts share password 'demo123' (bcrypt hash). Never ship to production.
-- Roles: admin (1), hr_manager (8), hr_staff (2), employee (15)
INSERT INTO users (tenant_id, email, full_name, role, employee_id, password_hash)
SELECT
    e.tenant_id,
    e.email,
    e.full_name,
    CASE e.employee_code
        WHEN 'FT-2021-001' THEN 'admin'
        WHEN 'FT-2021-002' THEN 'hr_manager'
        WHEN 'FT-2021-003' THEN 'hr_manager'
        WHEN 'FT-2022-001' THEN 'hr_manager'
        WHEN 'FT-2022-002' THEN 'hr_manager'
        WHEN 'FT-2022-003' THEN 'hr_manager'
        WHEN 'FT-2022-004' THEN 'hr_manager'
        WHEN 'FT-2022-005' THEN 'hr_manager'
        WHEN 'FT-2022-008' THEN 'hr_manager'
        WHEN 'FT-2021-005' THEN 'hr_staff'
        WHEN 'FT-2023-006' THEN 'hr_staff'
        ELSE 'employee'
    END,
    e.id,
    '$2b$12$4qFSJ1YZ.CoCCX/TPUU2E.J/gcu4v5wiQz42fxPlwJCI6U7rxjfZO'
FROM employees e
JOIN tenants t ON t.id = e.tenant_id
WHERE t.slug = 'fotopia';

-- Developer login alias: Youssef can sign in as i-youssef.abdelmoneim@fotopiatech.com
-- (FT-2022-010's employee.email is saif.ahmed for the demo persona; this alias gives
-- the developer their own login without touching the Odoo sync key.)
INSERT INTO users (tenant_id, email, full_name, role, employee_id, password_hash)
SELECT
    e.tenant_id,
    'i-youssef.abdelmoneim@fotopiatech.com',
    e.full_name,
    'employee',
    e.id,
    '$2b$12$4qFSJ1YZ.CoCCX/TPUU2E.J/gcu4v5wiQz42fxPlwJCI6U7rxjfZO'
FROM employees e
JOIN tenants t ON t.id = e.tenant_id
WHERE t.slug = 'fotopia' AND e.employee_code = 'FT-2022-010';
