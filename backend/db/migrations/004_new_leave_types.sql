-- Migration 004: Add missing leave types from Fotopia Leaves Policy HR/BTE 001/7-2025
-- Run this against a running DB that already has the original 9 leave types.
-- Idempotent: INSERT ... WHERE NOT EXISTS guards prevent duplicates.
--
-- Apply:
--   docker cp backend/db/migrations/004_new_leave_types.sql fotopia-hr-agent-db-1:/tmp/
--   docker exec fotopia-hr-agent-db-1 psql -U fotopia -d fotopia_hr -f /tmp/004_new_leave_types.sql

DO $$
DECLARE v_tenant_id UUID;
BEGIN
    SELECT id INTO v_tenant_id FROM tenants WHERE slug = 'fotopia';
    IF v_tenant_id IS NULL THEN RAISE EXCEPTION 'Tenant fotopia not found'; END IF;

    -- Marriage
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'marriage', 'Marriage Leave', 'إجازة زواج', TRUE, TRUE, FALSE, FALSE, TRUE, 5, 5
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'marriage');

    -- Hajj
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'hajj', 'Hajj Leave', 'إجازة حج', TRUE, TRUE, FALSE, FALSE, TRUE, 30, 30
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'hajj');

    -- Umrah
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'umrah', 'Umrah Leave', 'إجازة عمرة', TRUE, TRUE, FALSE, FALSE, TRUE, 5, 5
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'umrah');

    -- Funeral/Bereavement
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'funeral', 'Funeral/Bereavement Leave', 'إجازة وفاة', TRUE, FALSE, FALSE, FALSE, TRUE, 3, 3
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'funeral');

    -- Maternity
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'maternity', 'Maternity Leave', 'إجازة أمومة', TRUE, TRUE, FALSE, FALSE, TRUE, 120, 120
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'maternity');

    -- Paternity
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'paternity', 'Paternity Leave', 'إجازة أبوة', TRUE, TRUE, FALSE, FALSE, TRUE, 1, 1
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'paternity');

    -- Educational
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'educational', 'Educational Leave', 'إجازة دراسية', TRUE, TRUE, FALSE, FALSE, TRUE, NULL, NULL
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'educational');

    -- Military service
    INSERT INTO leave_types (tenant_id, code, name_en, name_ar, requires_approval, requires_documentation, deducts_balance, is_time_based, requires_hr_review, max_days_per_year, max_consecutive_days)
    SELECT v_tenant_id, 'military', 'Military Service Leave', 'إجازة خدمة عسكرية', FALSE, TRUE, FALSE, FALSE, TRUE, NULL, NULL
    WHERE NOT EXISTS (SELECT 1 FROM leave_types WHERE tenant_id = v_tenant_id AND code = 'military');

    RAISE NOTICE 'Migration 004 complete for tenant fotopia';
END $$;
