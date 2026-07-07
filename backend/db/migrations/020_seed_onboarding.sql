-- Migration 020: Seed onboarding templates for fotopia tenant
-- Idempotent: ON CONFLICT DO NOTHING guards prevent duplicates on re-run.
-- Run AFTER migration 019 (tables must already exist).

DO $$
DECLARE
    v_tenant_id UUID;
    v_generic_id UUID;
    v_fotopia_id UUID;
BEGIN
    SELECT id INTO v_tenant_id FROM tenants WHERE slug = 'fotopia';
    IF v_tenant_id IS NULL THEN
        RAISE EXCEPTION 'fotopia tenant not found — run seed.sql first';
    END IF;

    -- RLS requires this before any DML
    PERFORM set_config('app.current_tenant_id', v_tenant_id::text, true);

    -- ── Generic Employee Onboarding (is_default=TRUE) ─────────────────────────
    -- Used as the fallback template for any tenant that has not yet created
    -- a custom template. Seeded into fotopia; new-tenant provisioning should
    -- copy these steps (future: tenant provisioning tool).
    INSERT INTO onboarding_templates (tenant_id, name, description, is_default)
    VALUES (
        v_tenant_id,
        'Generic Employee Onboarding',
        'Standard 10-step onboarding checklist suitable for any company.',
        TRUE
    )
    ON CONFLICT (tenant_id, name) DO NOTHING
    RETURNING id INTO v_generic_id;

    IF v_generic_id IS NOT NULL THEN
        INSERT INTO onboarding_template_steps
            (tenant_id, template_id, sort_order, title, description, category, owner, due_offset_days, is_required)
        VALUES
            (v_tenant_id, v_generic_id,  1,
             'Collect signed offer letter / contract',
             'Obtain wet or e-signature on the employment contract and file in HRIS.',
             'documentation', 'hr', 1, TRUE),
            (v_tenant_id, v_generic_id,  2,
             'Collect ID, tax forms, and bank details for payroll',
             'National ID, tax card, and bank account number needed for payroll setup.',
             'documentation', 'hr', 1, TRUE),
            (v_tenant_id, v_generic_id,  3,
             'Create company email and core accounts',
             'Set up work email, Slack/Teams, HRIS login, and all standard access accounts.',
             'it_access', 'it', 1, TRUE),
            (v_tenant_id, v_generic_id,  4,
             'Provision hardware / laptop and required software',
             'Issue laptop, install required software, and verify VPN access.',
             'it_access', 'it', 3, TRUE),
            (v_tenant_id, v_generic_id,  5,
             'Assign buddy / mentor and schedule manager 1:1',
             'Pair the new hire with a buddy and book the first 1:1 with their direct manager.',
             'team_intro', 'manager', 1, TRUE),
            (v_tenant_id, v_generic_id,  6,
             'Share and acknowledge employee handbook / code of conduct',
             'New hire reads and signs the handbook, code of conduct, and data-handling policy.',
             'policies', 'hr', 3, TRUE),
            (v_tenant_id, v_generic_id,  7,
             'Complete mandatory compliance / security training',
             'Information security, data privacy, and any role-required compliance modules.',
             'compliance', 'employee', 7, TRUE),
            (v_tenant_id, v_generic_id,  8,
             'Benefits enrollment (if applicable)',
             'Walk through available benefits and complete enrollment forms within the election window.',
             'documentation', 'hr', 7, FALSE),
            (v_tenant_id, v_generic_id,  9,
             'Set 30/60/90-day goals with manager',
             'Align on short-term deliverables and success criteria for the first three months.',
             'training', 'manager', 7, TRUE),
            (v_tenant_id, v_generic_id, 10,
             'Add to relevant team channels / distribution lists',
             'Add to project channels, mailing lists, and meeting invites appropriate to the role.',
             'team_intro', 'it', 3, TRUE);
    END IF;

    -- ── Fotopia Technologies Onboarding ───────────────────────────────────────
    -- Reflects Fotopia's actual process for interns and full-time hires:
    -- company + product orientation, Claude Code / AI tooling intro,
    -- supervisor kickoff, project-track assignment, end-of-week verification.
    INSERT INTO onboarding_templates (tenant_id, name, description, is_default)
    VALUES (
        v_tenant_id,
        'Fotopia Technologies Onboarding',
        'Fotopia-specific onboarding for interns and full-time employees joining the AI / document-management team.',
        FALSE
    )
    ON CONFLICT (tenant_id, name) DO NOTHING
    RETURNING id INTO v_fotopia_id;

    IF v_fotopia_id IS NOT NULL THEN
        INSERT INTO onboarding_template_steps
            (tenant_id, template_id, sort_order, title, description, category, owner, due_offset_days, is_required)
        VALUES
            (v_tenant_id, v_fotopia_id,  1,
             'Sign employment / internship contract and NDA',
             'Complete contract signing via HR. Intern agreement includes NDA and IP assignment clause.',
             'documentation', 'hr', 1, TRUE),
            (v_tenant_id, v_fotopia_id,  2,
             'Submit ID documents and bank details',
             'Provide national ID, passport copy (if applicable), and bank account details to HR for payroll.',
             'documentation', 'hr', 1, TRUE),
            (v_tenant_id, v_fotopia_id,  3,
             'Receive company email and Fotopia system access',
             'IT provisions @fotopiatech.com email, VPN credentials, and access to Odoo, GitHub, and Jira.',
             'it_access', 'it', 1, TRUE),
            (v_tenant_id, v_fotopia_id,  4,
             'Day 1 company and program orientation',
             'Attend overview session: Fotopia mission, DigitizeMe product, WIN Holding context, and team structure.',
             'team_intro', 'hr', 1, TRUE),
            (v_tenant_id, v_fotopia_id,  5,
             'Introduction to Claude Code, Agent Skills, and AI tooling',
             'Hands-on walkthrough of Claude Code CLI, Agent SDK, tool-use patterns, and the HR Agent prototype.',
             'training', 'manager', 2, TRUE),
            (v_tenant_id, v_fotopia_id,  6,
             'Supervisor kickoff: project track and expectations meeting',
             'Direct supervisor sets project assignment, deliverables, communication norms, and first-week priorities.',
             'team_intro', 'manager', 1, TRUE),
            (v_tenant_id, v_fotopia_id,  7,
             'Review and acknowledge HR policies (leave, conduct, etc.)',
             'Read WIN Holding Leave Policy, code of conduct, and IT Acceptable Use policy. Acknowledge in HRIS.',
             'policies', 'hr', 3, TRUE),
            (v_tenant_id, v_fotopia_id,  8,
             'Complete information security and data-privacy training',
             'Mandatory e-learning: data classification, phishing awareness, and PDPL basics (Egypt Personal Data Protection Law).',
             'compliance', 'employee', 5, TRUE),
            (v_tenant_id, v_fotopia_id,  9,
             'Project track assignment confirmed and first task scoped',
             'Manager assigns first concrete deliverable; new hire acknowledges scope and timeline in writing.',
             'training', 'manager', 3, TRUE),
            (v_tenant_id, v_fotopia_id, 10,
             'End-of-week check-in: progress and training hours verified',
             'Supervisor reviews Week 1 progress, confirms training hours logged, and sets Week 2 priorities.',
             'training', 'manager', 7, TRUE),
            (v_tenant_id, v_fotopia_id, 11,
             'Set 30/60/90-day goals (full-time) or internship-period milestones (intern)',
             'Full-time employees align with manager on 30/60/90-day OKRs. Interns set internship-period milestones.',
             'training', 'manager', 7, FALSE),
            (v_tenant_id, v_fotopia_id, 12,
             'Add to DigitizeMe project channels and meeting invites',
             'Add to relevant Slack channels, Jira project boards, sprint ceremonies, and product demo invites.',
             'team_intro', 'it', 2, TRUE);
    END IF;

    RAISE NOTICE 'Migration 020 complete: onboarding templates seeded for fotopia tenant';
END;
$$;
