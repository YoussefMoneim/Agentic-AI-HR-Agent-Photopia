"""
Integration tests for the onboarding module (4 tools).

Run inside Docker:
    docker exec agentic-ai-hr-agent-photopia-backend-1 python -m pytest tests/test_onboarding.py -v --tb=short

All tests hit the real PostgreSQL database. Each test class cleans up after itself.
Seeded employees (from conftest.py):
    EMP001 — Saif Ahmed Hassan, R&D, employee role
    EMP002 — Nourhan Hosny,     HR,  hr_manager role
    EMP003 — Omar Alsayed,      R&D, employee role
"""

import psycopg2
import pytest

import config
from tests.conftest import get_pending_days  # noqa: F401 (unused here but keeps conftest loaded)
from tools.onboarding import (
    CreateOnboardingTool,
    CustomizeOnboardingTemplateTool,
    GetOnboardingStatusTool,
    UpdateOnboardingStepTool,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixture: clean onboarding data before and after every test
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_onboarding(database_url, tenant_id):
    """Delete all onboarding cases (and their cascade-deleted steps) before and after each test."""
    def _cleanup():
        conn = psycopg2.connect(database_url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                    cur.execute("DELETE FROM onboarding_cases WHERE tenant_id = %s", (tenant_id,))
        finally:
            conn.close()

    _cleanup()
    yield
    _cleanup()


@pytest.fixture(autouse=True)
def clean_custom_templates(database_url, tenant_id):
    """Remove templates created during tests and restore the seeded default flag."""
    yield
    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                # Remove any test-created templates
                cur.execute(
                    """
                    DELETE FROM onboarding_templates
                    WHERE tenant_id = %s
                      AND name NOT IN ('Generic Employee Onboarding', 'Fotopia Technologies Onboarding')
                    """,
                    (tenant_id,),
                )
                # Restore the correct is_default state for seeded templates
                cur.execute(
                    "UPDATE onboarding_templates SET is_default = TRUE  WHERE tenant_id = %s AND name = 'Generic Employee Onboarding'",
                    (tenant_id,),
                )
                cur.execute(
                    "UPDATE onboarding_templates SET is_default = FALSE WHERE tenant_id = %s AND name = 'Fotopia Technologies Onboarding'",
                    (tenant_id,),
                )
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# Group 1 — Template seeding
# ══════════════════════════════════════════════════════════════════════════════

class TestTemplateSeeding:

    def test_generic_template_exists(self, ds, tenant_id):
        """Migration 020 must have seeded the generic default template."""
        templates = ds.get_onboarding_templates(tenant_id)
        defaults = [t for t in templates if t["is_default"]]
        assert len(defaults) == 1, "Exactly one default template must exist"
        assert defaults[0]["name"] == "Generic Employee Onboarding"

    def test_generic_template_has_ten_steps(self, ds, tenant_id):
        templates = ds.get_onboarding_templates(tenant_id)
        generic = next(t for t in templates if t["name"] == "Generic Employee Onboarding")
        steps = ds.get_onboarding_template_steps(tenant_id, generic["id"])
        assert len(steps) == 10

    def test_fotopia_template_exists(self, ds, tenant_id):
        templates = ds.get_onboarding_templates(tenant_id)
        names = [t["name"] for t in templates]
        assert "Fotopia Technologies Onboarding" in names

    def test_fotopia_template_has_twelve_steps(self, ds, tenant_id):
        templates = ds.get_onboarding_templates(tenant_id)
        fotopia = next(t for t in templates if t["name"] == "Fotopia Technologies Onboarding")
        steps = ds.get_onboarding_template_steps(tenant_id, fotopia["id"])
        assert len(steps) == 12

    def test_step_fields_present(self, ds, tenant_id):
        """Each step must have required structural fields."""
        templates = ds.get_onboarding_templates(tenant_id)
        generic = next(t for t in templates if t["name"] == "Generic Employee Onboarding")
        steps = ds.get_onboarding_template_steps(tenant_id, generic["id"])
        for step in steps:
            assert "title" in step
            assert step["category"] in {"documentation", "it_access", "policies", "training", "team_intro", "compliance"}
            assert step["owner"] in {"hr", "it", "manager", "employee"}
            assert isinstance(step["due_offset_days"], int)
            assert isinstance(step["is_required"], bool)


# ══════════════════════════════════════════════════════════════════════════════
# Group 2 — create_onboarding
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateOnboarding:

    def test_hr_can_create_onboarding_for_employee(self, ctx, ds):
        """HR manager can start an onboarding for any employee."""
        tool = CreateOnboardingTool(ds)
        result = tool.execute({"employee_code": "EMP001"}, ctx(role="hr_manager", employee_code="EMP002"))
        assert result.success, result.error
        assert result.data["employee_code"] == "EMP001"
        assert result.data["steps_created"] > 0
        assert "case_id" in result.data

    def test_creates_steps_in_db(self, ctx, ds, db_conn, tenant_id):
        """Steps are written to onboarding_case_steps after create."""
        tool = CreateOnboardingTool(ds)
        result = tool.execute({"employee_code": "EMP001"}, ctx(role="hr_manager", employee_code="EMP002"))
        assert result.success
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM onboarding_case_steps WHERE tenant_id = %s AND case_id = %s",
                (tenant_id, result.data["case_id"]),
            )
            count = cur.fetchone()[0]
        assert count == result.data["steps_created"]

    def test_employee_cannot_create_onboarding(self, ctx, ds):
        """Employees are not allowed to call create_onboarding."""
        tool = CreateOnboardingTool(ds)
        # ToolRegistry enforces this at the registry level; we test the allowed_roles list
        assert "employee" not in tool.spec.allowed_roles

    def test_duplicate_creates_raises(self, ctx, ds):
        """Creating a second onboarding for the same employee raises an error (UNIQUE constraint)."""
        tool = CreateOnboardingTool(ds)
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        r1 = tool.execute({"employee_code": "EMP001"}, mgr_ctx)
        assert r1.success
        r2 = tool.execute({"employee_code": "EMP001"}, mgr_ctx)
        assert not r2.success

    def test_unknown_employee_returns_error(self, ctx, ds):
        result = CreateOnboardingTool(ds).execute(
            {"employee_code": "DOES-NOT-EXIST"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert not result.success
        assert "not found" in result.error.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Group 3 — get_onboarding_status
# ══════════════════════════════════════════════════════════════════════════════

class TestGetOnboardingStatus:

    def _start(self, ds, ctx):
        """Helper: create an onboarding case for EMP001."""
        return CreateOnboardingTool(ds).execute(
            {"employee_code": "EMP001"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )

    def test_hr_can_view_any_employee(self, ctx, ds):
        self._start(ds, ctx)
        result = GetOnboardingStatusTool(ds).execute(
            {"employee_code": "EMP001"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert result.success
        assert result.data["onboarding_started"] is True
        assert "steps" in result.data
        assert result.data["progress"]["percent_complete"] == 0

    def test_employee_reads_own(self, ctx, ds):
        self._start(ds, ctx)
        result = GetOnboardingStatusTool(ds).execute(
            {},
            ctx(role="employee", employee_code="EMP001"),
        )
        assert result.success
        assert result.data["employee_code"] == "EMP001"

    def test_employee_blocked_from_reading_other(self, ctx, ds):
        self._start(ds, ctx)
        result = GetOnboardingStatusTool(ds).execute(
            {"employee_code": "EMP002"},
            ctx(role="employee", employee_code="EMP001"),
        )
        assert not result.success
        assert "only view your own" in result.error

    def test_no_onboarding_returns_clear_message(self, ctx, ds):
        result = GetOnboardingStatusTool(ds).execute(
            {"employee_code": "EMP001"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert result.success
        assert result.data["onboarding_started"] is False
        assert "create_onboarding" in result.data["message"]


# ══════════════════════════════════════════════════════════════════════════════
# Group 4 — update_onboarding_step
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateOnboardingStep:

    def _setup(self, ds, ctx):
        """Create case and return (case_data, steps list)."""
        CreateOnboardingTool(ds).execute(
            {"employee_code": "EMP001"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        status = GetOnboardingStatusTool(ds).execute(
            {"employee_code": "EMP001"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        return status.data

    def test_hr_marks_step_completed(self, ctx, ds):
        data = self._setup(ds, ctx)
        step = data["steps"][0]
        result = UpdateOnboardingStepTool(ds).execute(
            {"employee_code": "EMP001", "step_id": step["id"], "status": "completed"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert result.success
        assert result.data["new_status"] == "completed"

    def test_step_status_persists_in_db(self, ctx, ds, db_conn, tenant_id):
        data = self._setup(ds, ctx)
        step = data["steps"][0]
        UpdateOnboardingStepTool(ds).execute(
            {"employee_code": "EMP001", "step_id": step["id"], "status": "completed", "notes": "done"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status, notes FROM onboarding_case_steps WHERE tenant_id = %s AND id = %s",
                (tenant_id, step["id"]),
            )
            row = cur.fetchone()
        assert row[0] == "completed"
        assert row[1] == "done"

    def test_employee_can_update_own_employee_owned_step(self, ctx, ds):
        """Employees can mark steps where owner='employee' on their own case."""
        data = self._setup(ds, ctx)
        employee_steps = [s for s in data["steps"] if s["owner"] == "employee"]
        if not employee_steps:
            pytest.skip("No employee-owned steps in default template")
        step = employee_steps[0]
        result = UpdateOnboardingStepTool(ds).execute(
            {"employee_code": "EMP001", "step_id": step["id"], "status": "completed"},
            ctx(role="employee", employee_code="EMP001"),
        )
        assert result.success

    def test_employee_blocked_from_updating_hr_step(self, ctx, ds):
        """Employees cannot update steps where owner != 'employee'."""
        data = self._setup(ds, ctx)
        hr_steps = [s for s in data["steps"] if s["owner"] != "employee"]
        if not hr_steps:
            pytest.skip("All steps are employee-owned in this template")
        step = hr_steps[0]
        result = UpdateOnboardingStepTool(ds).execute(
            {"employee_code": "EMP001", "step_id": step["id"], "status": "completed"},
            ctx(role="employee", employee_code="EMP001"),
        )
        assert not result.success
        assert "not permitted" in result.error

    def test_employee_blocked_from_updating_other_employees_step(self, ctx, ds):
        data = self._setup(ds, ctx)
        step = data["steps"][0]
        result = UpdateOnboardingStepTool(ds).execute(
            {"employee_code": "EMP001", "step_id": step["id"], "status": "completed"},
            ctx(role="employee", employee_code="EMP003"),
        )
        assert not result.success

    def test_case_auto_completes_when_all_required_done(self, ctx, ds, db_conn, tenant_id):
        """When all required steps are completed/skipped, case status becomes 'completed'."""
        data = self._setup(ds, ctx)
        update_tool = UpdateOnboardingStepTool(ds)
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")

        last_result = None
        for step in data["steps"]:
            last_result = update_tool.execute(
                {"employee_code": "EMP001", "step_id": step["id"], "status": "completed"},
                mgr_ctx,
            )
            assert last_result.success, last_result.error

        assert last_result.data["case_auto_completed"] is True
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM onboarding_cases WHERE tenant_id = %s AND id = %s",
                (tenant_id, data["case_id"]),
            )
            assert cur.fetchone()[0] == "completed"


# ══════════════════════════════════════════════════════════════════════════════
# Group 5 — customize_onboarding_template
# ══════════════════════════════════════════════════════════════════════════════

class TestCustomizeOnboardingTemplate:

    _SAMPLE_STEPS = [
        {"title": "Sign NDA", "category": "documentation", "owner": "hr", "due_offset_days": 1, "is_required": True},
        {"title": "Setup laptop", "category": "it_access", "owner": "it", "due_offset_days": 1, "is_required": True},
        {"title": "Meet the team", "category": "team_intro", "owner": "manager", "due_offset_days": 2, "is_required": False},
    ]

    def test_hr_manager_creates_new_template(self, ctx, ds):
        result = CustomizeOnboardingTemplateTool(ds).execute(
            {"name": "Test Template", "steps": self._SAMPLE_STEPS},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert result.success, result.error
        assert result.data["steps_count"] == 3
        assert "template_id" in result.data

    def test_employee_cannot_customize_template(self, ctx, ds):
        assert "employee" not in CustomizeOnboardingTemplateTool(ds).spec.allowed_roles
        assert "hr_staff" not in CustomizeOnboardingTemplateTool(ds).spec.allowed_roles

    def test_set_as_default_flips_default_flag(self, ctx, ds, tenant_id):
        result = CustomizeOnboardingTemplateTool(ds).execute(
            {"name": "New Default", "steps": self._SAMPLE_STEPS, "set_as_default": True},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert result.success
        templates = ds.get_onboarding_templates(tenant_id)
        defaults = [t for t in templates if t["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["name"] == "New Default"

    def test_update_existing_template_replaces_steps(self, ctx, ds, tenant_id):
        tool = CustomizeOnboardingTemplateTool(ds)
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")

        # Create template with 3 steps
        r1 = tool.execute({"name": "Editable Template", "steps": self._SAMPLE_STEPS}, mgr_ctx)
        assert r1.success
        template_id = r1.data["template_id"]

        # Update with 1 step
        r2 = tool.execute(
            {"name": "Editable Template", "template_id": template_id, "steps": [self._SAMPLE_STEPS[0]]},
            mgr_ctx,
        )
        assert r2.success
        assert r2.data["steps_count"] == 1

        steps = ds.get_onboarding_template_steps(tenant_id, template_id)
        assert len(steps) == 1

    def test_missing_name_returns_error(self, ctx, ds):
        result = CustomizeOnboardingTemplateTool(ds).execute(
            {"name": "", "steps": self._SAMPLE_STEPS},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert not result.success

    def test_empty_steps_returns_error(self, ctx, ds):
        result = CustomizeOnboardingTemplateTool(ds).execute(
            {"name": "Empty", "steps": []},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        assert not result.success


# ══════════════════════════════════════════════════════════════════════════════
# Group 6 — Tenant isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestTenantIsolation:

    def test_second_tenant_cannot_see_first_tenant_cases(self, ctx, ds, database_url, tenant_id):
        """Cases created for fotopia tenant are not visible under a different tenant_id."""
        # Create an onboarding case for EMP001 under fotopia
        CreateOnboardingTool(ds).execute(
            {"employee_code": "EMP001"},
            ctx(role="hr_manager", employee_code="EMP002"),
        )

        # Probe with a fake tenant_id — RLS returns None
        import uuid
        fake_tenant = str(uuid.uuid4())
        employee = ds.get_employee_by_code(tenant_id, "EMP001")
        case = ds.get_onboarding_case(fake_tenant, employee["id"])
        assert case is None, "Cross-tenant case lookup must return None"

    def test_second_tenant_cannot_see_first_tenant_templates(self, ds, tenant_id):
        """Templates are not visible under a different tenant_id."""
        import uuid
        fake_tenant = str(uuid.uuid4())
        templates = ds.get_onboarding_templates(fake_tenant)
        assert templates == [], "Cross-tenant template lookup must return an empty list"
