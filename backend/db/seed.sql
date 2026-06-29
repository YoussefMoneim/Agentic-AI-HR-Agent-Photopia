-- CTE creates the tenant and all 25 employees in one atomic statement.
WITH fotopia AS (
    INSERT INTO tenants (name, slug)
    VALUES ('Fotopia Technologies', 'fotopia')
    RETURNING id
)
INSERT INTO employees (
    tenant_id, employee_code, full_name, position, department,
    gender, birth_date, start_date, national_id,
    basic_salary, housing_allowance, transport_allowance, total_salary,
    currency, annual_leave_balance, email, employment_type, employment_status, phone_number
)
SELECT
    fotopia.id,
    emp.employee_code, emp.full_name, emp.position, emp.department,
    emp.gender, emp.birth_date::DATE, emp.start_date::DATE, emp.national_id,
    emp.basic_salary::NUMERIC, 0, 0, emp.basic_salary::NUMERIC,
    'EGP', 0, emp.email, 'Full-time', 'active', emp.phone_number
FROM fotopia, (VALUES
    ('FT-2021-001','Mohammed Al Nuaimi','Chief Executive Officer','Executive','M','1972-03-15','2021-01-01','27203150123456',95000,'mohammed.nuaimi@fotopiatech.com','+20-100-001-0001'),
    ('FT-2021-002','Khalid Al Hashmi','Engineering Director','Engineering','M','1978-07-22','2021-01-10','27807220234567',45000,'khalid.hashmi@fotopiatech.com','+20-100-001-0002'),
    ('FT-2021-003','Noura Al Rashidi','HR Director','Human Resources','F','1980-11-05','2021-02-01','28011050345678',42000,'noura.rashidi@fotopiatech.com','+20-100-001-0003'),
    ('FT-2021-004','Ahmed Al Mansouri','Senior Software Engineer','Engineering','M','1990-06-14','2021-03-15','29006140456789',28000,'ahmed.mansouri@fotopiatech.com','+20-100-001-0004'),
    ('FT-2021-005','Sara Al Zaabi','HR Business Partner','Human Resources','F','1993-09-28','2021-05-01','29309280567890',22000,'sara.zaabi@fotopiatech.com','+20-100-001-0005'),
    ('FT-2022-001','Reem Al Ketbi','Product Director','Product','F','1982-04-17','2022-02-01','28204170678901',44000,'reem.ketbi@fotopiatech.com','+20-100-001-0006'),
    ('FT-2022-002','Saeed Al Marri','Finance Director','Finance','M','1979-12-03','2022-03-15','27912030789012',43000,'saeed.marri@fotopiatech.com','+20-100-001-0007'),
    ('FT-2022-003','Tariq Al Ameri','Sales Director','Sales','M','1981-08-19','2022-04-01','28108190890123',41000,'tariq.ameri@fotopiatech.com','+20-100-001-0008'),
    ('FT-2022-004','Jaber Al Kindi','Marketing Director','Marketing','M','1983-02-25','2022-05-10','28302250901234',40000,'jaber.kindi@fotopiatech.com','+20-100-001-0009'),
    ('FT-2022-005','Hessa Al Mazrouei','Product Manager','Product','F','1988-10-11','2022-09-01','28810111012345',32000,'hessa.mazrouei@fotopiatech.com','+20-100-001-0010'),
    ('FT-2022-006','Omar Al Shehhi','Backend Engineer','Engineering','M','1994-03-07','2022-04-11','29403071123456',26000,'omar.shehhi@fotopiatech.com','+20-100-001-0011'),
    ('FT-2022-007','Maryam Al Falasi','Senior Finance Analyst','Finance','F','1991-07-30','2022-06-01','29107301234567',24000,'maryam.falasi@fotopiatech.com','+20-100-001-0012'),
    ('FT-2022-008','Rashed Al Blooshi','DevOps Lead','Engineering','M','1989-05-16','2022-07-15','28905161345678',29000,'rashed.blooshi@fotopiatech.com','+20-100-001-0013'),
    ('FT-2022-009','Fatima Al Suwaidi','Senior UI/UX Designer','Product','F','1992-01-24','2022-02-20','29201241456789',25000,'fatima.suwaidi@fotopiatech.com','+20-100-001-0014'),
    ('FT-2022-010','Saif Ahmed','Mobile Engineer','Engineering','M','1995-08-09','2022-11-01','29508091567890',24000,'saif.ahmed@fotopiatech.com','+20-100-001-0015'),
    ('FT-2023-001','Layla Al Qassimi','Data Analyst','Engineering','F','1996-04-22','2023-01-15','29604221678901',22000,'layla.qassimi@fotopiatech.com','+20-100-001-0016'),
    ('FT-2023-002','Hamdan Al Nuaimi','Sales Executive','Sales','M','1997-11-13','2023-03-01','29711131789012',19000,'hamdan.nuaimi@fotopiatech.com','+20-100-001-0017'),
    ('FT-2023-003','Shaikha Al Ketbi','Graphic Designer','Product','F','1998-06-30','2023-04-10','29806301890123',18000,'shaikha.ketbi@fotopiatech.com','+20-100-001-0018'),
    ('FT-2023-004','Amna Al Muhairi','Content Strategist','Marketing','F','1997-02-18','2023-06-15','29702181901234',17000,'amna.muhairi@fotopiatech.com','+20-100-001-0019'),
    ('FT-2023-005','Mansoor Al Dhaheri','IT Administrator','IT','M','1993-09-05','2023-05-20','29309052012345',21000,'mansoor.dhaheri@fotopiatech.com','+20-100-001-0020'),
    ('FT-2023-006','Wadima Al Hosani','Talent Acquisition Specialist','Human Resources','F','1998-12-27','2023-07-01','29812272123456',18000,'wadima.hosani@fotopiatech.com','+20-100-001-0021'),
    ('FT-2024-001','Maitha Al Romaithi','QA Engineer','Engineering','F','1999-03-14','2024-02-20','29903142234567',20000,'maitha.romaithi@fotopiatech.com','+20-100-001-0022'),
    ('FT-2024-002','Zayed Al Kaabi','Junior Software Developer','Engineering','M','2000-07-08','2024-04-01','30007082345678',18000,'zayed.kaabi@fotopiatech.com','+20-100-001-0023'),
    ('FT-2024-003','Nadia Al Shamsi','Junior Sales Associate','Sales','F','2001-01-19','2024-06-01','30101192456789',16000,'nadia.shamsi@fotopiatech.com','+20-100-001-0024'),
    ('FT-2026-001','Lina Al Rashidi','Junior Data Scientist','Engineering','F','2002-05-10','2026-03-01','30205101234567',15000,'lina.rashidi@fotopiatech.com','+20-100-001-0025')
) AS emp(employee_code, full_name, position, department, gender, birth_date, start_date, national_id, basic_salary, email, phone_number);

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
WHERE e.employee_code IN ('FT-2021-004','FT-2022-006','FT-2022-008','FT-2022-010','FT-2023-001','FT-2024-001','FT-2024-002','FT-2026-001')
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
-- All 25 accounts share password 'demo123' (bcrypt hash). Never ship to production.
-- Roles: admin (1), hr_manager (8), hr_staff (2), employee (14)
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

-- ─── Demo documents (pre-loaded for the Documents tab demo) ──────────────────
DO $$
DECLARE
    v_tenant_id UUID;
    v_uploader  TEXT;
    v_content_1 TEXT;
    v_content_2 TEXT;
BEGIN
    SELECT id INTO v_tenant_id FROM tenants WHERE slug = 'fotopia';
    SELECT u.id::text INTO v_uploader
    FROM users u JOIN employees e ON e.id = u.employee_id
    WHERE e.employee_code = 'FT-2021-003' AND u.tenant_id = v_tenant_id;

    PERFORM set_config('app.current_tenant_id', v_tenant_id::text, true);

    v_content_1 := $doc1$SALARY CERTIFICATE

Date: 15 March 2025
Reference: SC-2025-0847

TO WHOM IT MAY CONCERN

This is to certify that Mr. Ahmed Hassan (National ID: 29901011234567) is a full-time
employee of Fotopia Technologies, holding the position of Senior Software Engineer in
the Research & Development department.

Employment Details:
- Employee Code: EMP001
- Date of Joining: 12 January 2021
- Employment Type: Full-time, Permanent

Compensation Details (Monthly):
- Basic Salary: EGP 45,000
- Housing Allowance: EGP 8,000
- Transportation Allowance: EGP 2,500
- Total Monthly Compensation: EGP 55,500

This certificate is issued upon the employee's request for the purpose of bank account
opening and financial verification.

Authorized Signatory:
Nourhan Hosny
HR Manager, Fotopia Technologies
$doc1$;

    v_content_2 := $doc2$Q3 2025 PLANNING MEETING — AGENDA

Date: Monday, 7 July 2025
Time: 10:00 AM – 12:00 PM (Cairo time)
Location: Conference Room B / Google Meet (link TBD)
Facilitator: Raef Eid

ATTENDEES
- Raef Eid (Founder)
- Dr. Ahmed El-Yazbi (R&D AI Director)
- Youssef Abdelmoneim (AI/ML)
- Nourhan Hosny (HR)
- Finance representative (TBC)

AGENDA ITEMS

1. Q2 Retrospective (20 min)
   - Delivery milestones hit / missed
   - Budget vs actual spend
   - Team feedback summary

2. Q3 OKRs and Priorities (30 min)
   - HR Agent: Phase 2 scope and go-live targets
   - DigitizeMe integration milestone
   - Hiring plan: 2 backend engineers, 1 UX designer

3. Risk Review (15 min)
   - PDPL cross-border transfer status
   - ZDR agreement timeline with Anthropic
   - Pilot client readiness (Nourhan to update)

4. Resource Allocation (20 min)
   - Sprint assignments for July–September
   - Tooling budget requests

5. AOB / Open Floor (15 min)

ACTION ITEMS FROM LAST MEETING
- [Youssef] Complete leave workflow engine — DONE
- [Nourhan] Confirm pilot user list — IN PROGRESS
- [Dr. Ahmed] PDPL legal review — PENDING

Next meeting: Monday, 11 August 2025
$doc2$;

    INSERT INTO demo_documents
        (id, tenant_id, uploaded_by, filename, content_text,
         file_size_bytes, sensitivity_scan, is_sensitive, is_demo)
    VALUES
    (
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'::uuid,
        v_tenant_id,
        v_uploader,
        'salary_certificate_ahmed_hassan.pdf',
        v_content_1,
        octet_length(v_content_1),
        '{"salary":{"examples":["basic salary","EGP 45,000","housing allowance"],"llm_verdict":{"is_sensitive":true,"confidence":"high","reason":"Document contains personal compensation data including salary figures and allowances for a named individual."}},"national_id":{"examples":["29901011234567"],"llm_verdict":{"is_sensitive":true,"confidence":"high","reason":"Document contains a 14-digit Egyptian national ID number."}}}'::jsonb,
        true,
        true
    ),
    (
        'b2c3d4e5-f6a7-8901-bcde-fa2345678901'::uuid,
        v_tenant_id,
        v_uploader,
        'q3_planning_meeting_agenda.txt',
        v_content_2,
        octet_length(v_content_2),
        '{}'::jsonb,
        false,
        true
    )
    ON CONFLICT (id) DO NOTHING;
END $$;

-- Route approval-request notifications for managers/admin to the shared HR Gmail inbox.
-- employees.email stays as @fotopiatech.com (real work email — used by Odoo sync for matching).
-- notification_email is the override destination for outgoing HR notification emails only.
UPDATE employees
SET notification_email = 'hr.agent.fotopia@gmail.com'
WHERE employee_code IN (
    'FT-2021-001', 'FT-2021-002', 'FT-2021-003',
    'FT-2022-001', 'FT-2022-002', 'FT-2022-003',
    'FT-2022-004', 'FT-2022-005', 'FT-2022-008'
)
  AND tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');
