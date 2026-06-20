CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- One row per customer company. Everything else is scoped to a tenant_id.
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Login identity. Role here drives what tools the person can call.
-- employee_id links to employees when the user is also an employee (for row-level checks).
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'employee',
    employee_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);

-- Core HR record. Almost every tool reads from this table.
CREATE TABLE employees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    employee_code TEXT NOT NULL,
    full_name TEXT NOT NULL,
    arabic_name TEXT,
    position TEXT,
    department TEXT,
    employment_type TEXT,
    start_date DATE,
    basic_salary NUMERIC(12,2),
    housing_allowance NUMERIC(12,2) DEFAULT 0,
    transport_allowance NUMERIC(12,2) DEFAULT 0,
    total_salary NUMERIC(12,2),
    currency TEXT DEFAULT 'EGP',
    annual_leave_balance INTEGER DEFAULT 0,  -- deprecated: superseded by leave_balances table
    email TEXT,
    manager_name TEXT,       -- legacy free-text; manager_id FK is authoritative
    manager_id UUID REFERENCES employees(id),  -- direct manager; self-referential FK
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, employee_code)
);

-- Append-only log of every tool call. Never updated or deleted.
-- Also used by get_employee_documents: filter by tool_name + tool_input->>'employee_code'.
-- tool_input is JSONB (not TEXT) so we can query inside it with the ->> operator.
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL,
    actor_user_id TEXT,
    actor_role TEXT,
    tool_name TEXT NOT NULL,
    tool_input JSONB,
    outcome TEXT NOT NULL,
    authz_decision TEXT,
    result_summary TEXT,
    latency_ms INTEGER,
    data_fields_accessed JSONB DEFAULT NULL,  -- list of sensitive field names read, e.g. ["annual_leave_balance"]
    action TEXT NOT NULL DEFAULT 'tool_executed',
        -- tool_executed | data_read | data_write | decision_denied
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Leave types ──────────────────────────────────────────────────────────────
-- 8 supported types: annual, sick, emergency, permission, business_trip,
--                    wfh, outside_duty, compensatory  (+ unpaid legacy)
CREATE TABLE leave_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    requires_approval BOOLEAN NOT NULL DEFAULT TRUE,
    requires_documentation BOOLEAN NOT NULL DEFAULT FALSE,
    deducts_balance BOOLEAN NOT NULL DEFAULT TRUE,      -- FALSE: emergency, permission, business_trip, wfh, outside_duty
    is_time_based BOOLEAN NOT NULL DEFAULT FALSE,       -- TRUE only for Permission (hours, not days)
    requires_hr_review BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE: annual, sick, emergency, business_trip, compensatory, unpaid
    max_days_per_year INTEGER,    -- NULL = no annual cap
    max_consecutive_days INTEGER, -- NULL = no per-request limit
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (tenant_id, code)
);

-- ─── Leave balances ───────────────────────────────────────────────────────────
-- Per-employee, per-leave-type, per-year balance.
-- Only populated for types where deducts_balance = TRUE.
CREATE TABLE leave_balances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    employee_id UUID NOT NULL REFERENCES employees(id),
    leave_type_id UUID NOT NULL REFERENCES leave_types(id),
    year INTEGER NOT NULL,
    allocated_days NUMERIC(5,1) NOT NULL DEFAULT 0,   -- prorated at hire for hire year; full in subsequent years
    used_days NUMERIC(5,1) NOT NULL DEFAULT 0,        -- approved and completed requests
    pending_days NUMERIC(5,1) NOT NULL DEFAULT 0,     -- in-flight: submitted but not yet resolved
    carry_over_days NUMERIC(5,1) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, employee_id, leave_type_id, year)
);

-- ─── Leave requests ───────────────────────────────────────────────────────────
-- One row per submitted leave request. Tracks the full approval lifecycle.
CREATE TABLE leave_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    employee_id UUID NOT NULL REFERENCES employees(id),
    leave_type_id UUID NOT NULL REFERENCES leave_types(id),

    -- Date fields — NULL for Permission type (use datetime fields below instead)
    start_date DATE,
    end_date DATE,
    days_requested NUMERIC(5,1),  -- stored at submission; immutable. NULL for pure hours-based.

    -- Time fields — only populated for Permission type
    start_datetime TIMESTAMPTZ,
    end_datetime TIMESTAMPTZ,
    duration_hours NUMERIC(4,1),  -- e.g. 2.0 hours

    reason TEXT,
    attachment_path TEXT,  -- path to uploaded medical cert, etc.

    -- Approval chain — manager stored at submission from DB, never from user input
    manager_id UUID REFERENCES employees(id),
    manager_decision_at TIMESTAMPTZ,
    manager_comment TEXT,
    hr_reviewer_id UUID REFERENCES employees(id),
    hr_decision_at TIMESTAMPTZ,
    hr_comment TEXT,

    -- External sync flags (all FALSE until real integrations land)
    odoo_synced BOOLEAN NOT NULL DEFAULT FALSE,
    timelog_synced BOOLEAN NOT NULL DEFAULT FALSE,
    excel_synced BOOLEAN NOT NULL DEFAULT FALSE,

    -- Full approval chain status
    status TEXT NOT NULL DEFAULT 'pending_approval'
        CHECK (status IN (
            'pending_approval',
            'manager_approved', 'manager_rejected',
            'hr_approved', 'hr_rejected',
            'cancelled', 'withdrawn', 'completed'
        )),

    -- Legacy fields — kept for resolve_pending_action compatibility
    resolved_by UUID REFERENCES employees(id),
    resolved_at TIMESTAMPTZ,
    rejection_reason TEXT,

    workflow_instance_id UUID,  -- soft FK; set after workflow_instances row is created

    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT valid_date_range CHECK (start_date IS NULL OR end_date >= start_date),
    CONSTRAINT valid_datetime_range CHECK (start_datetime IS NULL OR end_datetime >= start_datetime),
    CONSTRAINT valid_request CHECK (
        (days_requested IS NOT NULL AND days_requested > 0)
        OR (duration_hours IS NOT NULL AND duration_hours > 0)
    )
);
CREATE INDEX idx_leave_requests_tenant ON leave_requests(tenant_id, status, submitted_at DESC);
CREATE INDEX idx_leave_requests_employee ON leave_requests(tenant_id, employee_id, status);
CREATE INDEX idx_leave_requests_manager ON leave_requests(tenant_id, manager_id, status);
CREATE INDEX ON leave_requests(workflow_instance_id) WHERE workflow_instance_id IS NOT NULL;

-- ─── Leave policies ───────────────────────────────────────────────────────────
-- One row per (tenant, leave_type). Flat model — no JSONB rules.
-- Absence of a row = all defaults apply (no extra restrictions).
CREATE TABLE leave_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    leave_type_id UUID NOT NULL REFERENCES leave_types(id),
    probation_restriction_days INTEGER NOT NULL DEFAULT 0,  -- 0 = no probation restriction
    annual_allowance_days NUMERIC(5,1),   -- NULL = use leave_types.max_days_per_year
    wfh_max_days_per_week INTEGER,        -- NULL = no weekly cap (used for wfh type)
    wfh_max_days_per_month INTEGER,       -- NULL = no monthly cap (used for wfh type)
    max_consecutive_days INTEGER,         -- NULL = use leave_types.max_consecutive_days
    requires_medical_cert_after_days INTEGER,  -- NULL = never; sick leave: typically 3
    min_notice_days INTEGER NOT NULL DEFAULT 0,  -- calendar days advance notice before start_date
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, leave_type_id)
);

-- ─── Workflow state ───────────────────────────────────────────────────────────
-- One row per active workflow instance (leave approval, onboarding, etc.).
-- state_snapshot is a JSONB blob the orchestrator reads to resume.
CREATE TABLE workflow_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workflow_type TEXT NOT NULL DEFAULT 'leave_approval',
    status TEXT NOT NULL DEFAULT 'running',
        -- running | waiting_human | completed | failed | timed_out
    subject_employee_id UUID REFERENCES employees(id),
    triggered_by_user_id TEXT,   -- ToolContext.user_id; TEXT until JWT lands in Phase 2
    leave_request_id UUID,       -- soft FK to leave_requests
    current_step TEXT NOT NULL,
    state_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX ON workflow_instances(tenant_id, status);
CREATE INDEX ON workflow_instances(leave_request_id);

-- ─── Pending actions ─────────────────────────────────────────────────────────
-- One row per outstanding human approval gate.
-- Manager clicks the approval link → /api/leave/resolve/{correlation_token} resolves this row.
CREATE TABLE pending_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workflow_instance_id UUID NOT NULL REFERENCES workflow_instances(id),
    action_type TEXT NOT NULL DEFAULT 'email_approval',
    status TEXT NOT NULL DEFAULT 'pending',
        -- pending | approved | rejected | timed_out | cancelled
    assigned_to_employee_id UUID REFERENCES employees(id),
    assigned_to_email TEXT NOT NULL,
    outbound_message_id TEXT UNIQUE,    -- SMTP Message-ID header; for future reply-chain parsing
    correlation_token TEXT UNIQUE NOT NULL,  -- UUID embedded in the approval URL
    context_snapshot JSONB NOT NULL,    -- immutable snapshot of what the approver was shown
    prompt_text TEXT NOT NULL,          -- text of the approval request / email body
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolved_by_employee_id UUID REFERENCES employees(id),
    resolution_note TEXT,
    idempotency_key TEXT UNIQUE NOT NULL,  -- sha256(workflow_id||step||attempt); prevents re-send
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON pending_actions(tenant_id, status, deadline_at);
CREATE INDEX ON pending_actions(correlation_token);
