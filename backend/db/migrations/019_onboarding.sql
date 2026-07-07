-- Migration 019: Onboarding module
-- Creates onboarding_templates, onboarding_template_steps,
-- onboarding_cases, onboarding_case_steps with full RLS and fotopia_app grants.

-- ─── Onboarding templates ─────────────────────────────────────────────────────
-- One template per tenant; multiple allowed. is_default=TRUE → used when no
-- template_id is supplied to create_onboarding.
CREATE TABLE IF NOT EXISTS onboarding_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- ─── Onboarding template steps ────────────────────────────────────────────────
-- Ordered list of steps in a template. Copied (snapshotted) to onboarding_case_steps
-- when a case is created, so template edits never affect in-progress onboardings.
CREATE TABLE IF NOT EXISTS onboarding_template_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    template_id UUID NOT NULL REFERENCES onboarding_templates(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL DEFAULT 'documentation'
        CHECK (category IN ('documentation', 'it_access', 'policies', 'training', 'team_intro', 'compliance')),
    owner TEXT NOT NULL DEFAULT 'hr'
        CHECK (owner IN ('hr', 'it', 'manager', 'employee')),
    due_offset_days INTEGER NOT NULL DEFAULT 1,  -- calendar days from employee start_date
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_template_steps_template
    ON onboarding_template_steps(tenant_id, template_id, sort_order);

-- ─── Onboarding cases ─────────────────────────────────────────────────────────
-- One active onboarding case per employee.
CREATE TABLE IF NOT EXISTS onboarding_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    employee_id UUID NOT NULL REFERENCES employees(id),
    template_id UUID REFERENCES onboarding_templates(id),
    status TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'completed', 'cancelled')),
    created_by_user_id TEXT,  -- ToolContext.user_id
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, employee_id)
);
CREATE INDEX IF NOT EXISTS idx_onboarding_cases_tenant_status
    ON onboarding_cases(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_onboarding_cases_employee
    ON onboarding_cases(tenant_id, employee_id);

-- ─── Onboarding case steps ────────────────────────────────────────────────────
-- Snapshot of template steps taken at case creation time. Independent of the
-- template so that later template customisations don't mutate live onboardings.
CREATE TABLE IF NOT EXISTS onboarding_case_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    case_id UUID NOT NULL REFERENCES onboarding_cases(id) ON DELETE CASCADE,
    template_step_id UUID REFERENCES onboarding_template_steps(id),  -- soft ref
    sort_order INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL DEFAULT 'documentation'
        CHECK (category IN ('documentation', 'it_access', 'policies', 'training', 'team_intro', 'compliance')),
    owner TEXT NOT NULL DEFAULT 'hr'
        CHECK (owner IN ('hr', 'it', 'manager', 'employee')),
    due_date DATE,           -- employee.start_date + due_offset_days; NULL if start_date unknown
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed', 'skipped', 'blocked')),
    notes TEXT,
    completed_at TIMESTAMPTZ,
    completed_by_user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_case_steps_case
    ON onboarding_case_steps(tenant_id, case_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_onboarding_case_steps_status
    ON onboarding_case_steps(tenant_id, case_id, status);

-- ─── Row Level Security ────────────────────────────────────────────────────────
ALTER TABLE onboarding_templates       ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_templates       FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON onboarding_templates FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

ALTER TABLE onboarding_template_steps  ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_template_steps  FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON onboarding_template_steps FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

ALTER TABLE onboarding_cases           ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_cases           FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON onboarding_cases FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

ALTER TABLE onboarding_case_steps      ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_case_steps      FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON onboarding_case_steps FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ─── Grants ───────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_templates       TO fotopia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_template_steps  TO fotopia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_cases           TO fotopia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_case_steps      TO fotopia_app;

DO $$ BEGIN RAISE NOTICE 'Migration 019 complete: onboarding tables created with RLS'; END $$;
