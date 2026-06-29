"""
Constraint engine tests — Step 5.

Covers all three rule classes:
  Hard rules   — sick leave with cert → BLOCK rejection (no state change)
  Soft rules   — 25% dept cap, balance exceeded → REQUIRES_OVERRIDE or BLOCKED
  Advisory flags — sick leave without cert (long) → action proceeds, flag returned

All seeded data is from conftest:
  EMP001: Saif Ahmed Hassan, R&D, manager=EMP002
  EMP002: Nourhan Hosny,     HR,  no manager
  EMP003: Omar Alsayed,      R&D, manager=EMP002
  R&D department has exactly 2 employees (EMP001, EMP003)

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_constraints.py -v --tb=short
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2
import pytest

import config


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _set_has_medical_cert(conn, tenant_id: str, request_id: str, value: bool) -> None:
    with conn:
        with conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                "UPDATE leave_requests SET has_medical_certificate = %s WHERE id = %s::uuid AND tenant_id = %s",
                (value, request_id, tenant_id),
            )


def _submit_sick_leave(registry, ctx, start: str, end: str, days: int):
    """Submit a sick leave request for EMP001."""
    return registry.execute(
        "submit_leave_request",
        {"leave_type_code": "sick", "start_date": start, "end_date": end,
         "days_requested": days, "reason": "not feeling well"},
        ctx(role="employee", employee_code="EMP001"),
    )


def _submit_annual_leave(registry, ctx, employee_code: str, start: str, end: str, days: int = 2):
    """Submit an annual leave request for the given employee."""
    return registry.execute(
        "submit_leave_request",
        {"leave_type_code": "annual", "start_date": start, "end_date": end,
         "days_requested": days, "reason": "vacation"},
        ctx(role="employee", employee_code=employee_code),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Hard rules — sick leave with medical certificate
# ═══════════════════════════════════════════════════════════════════════════════

class TestHardRules:

    def test_reject_sick_with_cert_is_blocked(self, registry, ctx, db_conn, tenant_id):
        """Attempting to reject sick leave that has a medical certificate must be BLOCKED.
        No state change should occur — leave_request remains 'pending_approval'."""
        # Submit a 5-day sick leave (> 3-day cert threshold)
        submit = _submit_sick_leave(registry, ctx, "2026-08-04", "2026-08-08", 5)
        assert submit.success, f"Submit failed: {submit.error}"
        lr_id = submit.data["request_id"]

        # Mark the request as having a medical certificate
        _set_has_medical_cert(db_conn, tenant_id, lr_id, True)

        # Try to reject — must be blocked
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = registry.execute(
            "reject_leave_request",
            {"request_id": lr_id, "comment": "budget constraints"},
            mgr_ctx,
        )
        assert not result.success, "Expected rejection to be blocked but it succeeded"
        assert "Labour Law" in (result.error or ""), (
            f"Expected Labour Law reference in error, got: {result.error}"
        )
        assert "Art. 68" in (result.error or "") or "Art" in (result.error or ""), (
            f"Expected article reference in error, got: {result.error}"
        )

        # Confirm no state change — leave is still pending_approval
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM leave_requests WHERE id = %s::uuid AND tenant_id = %s",
                (lr_id, tenant_id),
            )
            assert cur.fetchone()[0] == "pending_approval", "Status changed despite hard block"

    def test_reject_sick_with_cert_produces_no_workflow_event(self, registry, ctx, db_conn, tenant_id):
        """A hard-blocked rejection must not write a manager_rejected workflow_events row."""
        submit = _submit_sick_leave(registry, ctx, "2026-08-04", "2026-08-08", 5)
        assert submit.success
        lr_id = submit.data["request_id"]
        _set_has_medical_cert(db_conn, tenant_id, lr_id, True)

        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        registry.execute("reject_leave_request", {"request_id": lr_id, "comment": "no"}, mgr_ctx)

        with db_conn.cursor() as cur:
            cur.execute(
                """SELECT we.event_type FROM workflow_events we
                   JOIN workflow_instances wi ON wi.id = we.workflow_instance_id
                   WHERE wi.leave_request_id = %s::uuid AND we.tenant_id = %s
                     AND we.event_type = 'manager_rejected'""",
                (lr_id, tenant_id),
            )
            assert cur.fetchone() is None, "manager_rejected event must not be written for hard-blocked rejection"

    def test_reject_sick_without_cert_is_allowed(self, registry, ctx, db_conn, tenant_id):
        """Rejecting sick leave WITHOUT a certificate must succeed (hard rule does not apply)."""
        submit = _submit_sick_leave(registry, ctx, "2026-08-04", "2026-08-08", 5)
        assert submit.success
        lr_id = submit.data["request_id"]
        # has_medical_certificate defaults to FALSE — no need to set it

        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = registry.execute(
            "reject_leave_request",
            {"request_id": lr_id, "comment": "no cert on file"},
            mgr_ctx,
        )
        assert result.success, f"Expected success but got: {result.error}"


# ═══════════════════════════════════════════════════════════════════════════════
# Soft rules — 25% concurrent department cap
# ═══════════════════════════════════════════════════════════════════════════════

class TestSoftRulesDeptCap:
    """
    R&D has 2 employees (EMP001, EMP003). The cap applies when active_count >= 1
    and (active+1)/total > threshold. After EMP003 is approved, active=1,
    so approving EMP001 gives (1+1)/2 = 100% > 25% → requires_override.
    """

    def _setup_rd_cap_breach(self, registry, ctx, database_url, tenant_id):
        """Approve EMP003 so R&D is at 50% (1/2). Returns EMP001's pending request_id."""
        # Approve EMP003's leave first (active=0 → cap guard skipped → succeeds)
        emp3_submit = _submit_annual_leave(registry, ctx, "EMP003", "2026-08-11", "2026-08-12")
        assert emp3_submit.success, f"EMP003 submit failed: {emp3_submit.error}"
        emp3_lr_id = emp3_submit.data["request_id"]

        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        approve3 = registry.execute("approve_leave_request", {"request_id": emp3_lr_id}, mgr_ctx)
        assert approve3.success, f"EMP003 approve failed: {approve3.error}"

        # Submit EMP001 leave overlapping the same dates
        emp1_submit = _submit_annual_leave(registry, ctx, "EMP001", "2026-08-11", "2026-08-12")
        assert emp1_submit.success, f"EMP001 submit failed: {emp1_submit.error}"
        return emp1_submit.data["request_id"]

    def test_approve_over_dept_cap_no_override_returns_requires_override(
        self, registry, ctx, database_url, tenant_id
    ):
        """Approving when dept cap is exceeded without override_reason → requires_override."""
        lr_id = self._setup_rd_cap_breach(registry, ctx, database_url, tenant_id)
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")

        result = registry.execute("approve_leave_request", {"request_id": lr_id}, mgr_ctx)
        assert not result.success
        assert result.data and result.data.get("override_reason_required"), (
            "Expected override_reason_required=True in response data"
        )
        assert "dept_cap_exceeded" in (result.data.get("flags") or [])

    def test_approve_over_dept_cap_with_hr_manager_override_succeeds(
        self, registry, ctx, database_url, tenant_id, db_conn
    ):
        """hr_manager can override the cap with an override_reason; policy_exception event written."""
        lr_id = self._setup_rd_cap_breach(registry, ctx, database_url, tenant_id)
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")

        result = registry.execute(
            "approve_leave_request",
            {"request_id": lr_id, "override_reason": "critical project deadline"},
            mgr_ctx,
        )
        assert result.success, f"Override should succeed for hr_manager but got: {result.error}"

        # Confirm policy_exception workflow_event was written
        with db_conn.cursor() as cur:
            cur.execute(
                """SELECT we.event_type, we.data FROM workflow_events we
                   JOIN workflow_instances wi ON wi.id = we.workflow_instance_id
                   WHERE wi.leave_request_id = %s::uuid AND we.tenant_id = %s
                     AND we.event_type = 'policy_exception'
                   ORDER BY we.created_at DESC LIMIT 1""",
                (lr_id, tenant_id),
            )
            row = cur.fetchone()
            assert row is not None, "policy_exception workflow_event was not written"
            event_data = row[1]
            assert event_data.get("override_reason") == "critical project deadline"
            assert event_data.get("rule") == "dept_cap_exceeded"

    def test_approve_over_dept_cap_override_denied_for_hr_staff(
        self, registry, ctx, database_url, tenant_id
    ):
        """hr_staff cannot override the department cap — denied by role gate."""
        lr_id = self._setup_rd_cap_breach(registry, ctx, database_url, tenant_id)
        staff_ctx = ctx(role="hr_staff", employee_code="EMP002")

        result = registry.execute(
            "approve_leave_request",
            {"request_id": lr_id, "override_reason": "trying anyway"},
            staff_ctx,
        )
        assert not result.success
        assert "hr_staff" in (result.error or "").lower() or "role" in (result.error or "").lower(), (
            f"Expected role-denial message, got: {result.error}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Advisory flags — sick leave without certificate
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdvisoryFlags:

    def test_reject_long_sick_no_cert_returns_advisory_flag(
        self, registry, ctx, db_conn, tenant_id
    ):
        """Rejecting long sick leave (> 3 days) without cert → success with advisory_flags."""
        # 5-day sick leave, no medical certificate (default FALSE)
        submit = _submit_sick_leave(registry, ctx, "2026-08-04", "2026-08-08", 5)
        assert submit.success
        lr_id = submit.data["request_id"]

        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = registry.execute(
            "reject_leave_request",
            {"request_id": lr_id, "comment": "not approved"},
            mgr_ctx,
        )
        assert result.success, f"Expected success (advisory only) but got: {result.error}"
        flags = (result.data or {}).get("advisory_flags", [])
        assert "no_medical_certificate" in flags, (
            f"Expected 'no_medical_certificate' advisory flag, got: {flags}"
        )

    def test_reject_long_sick_no_cert_writes_advisory_shown_event(
        self, registry, ctx, db_conn, tenant_id
    ):
        """advisory_shown workflow_events row must be written before the state change."""
        submit = _submit_sick_leave(registry, ctx, "2026-08-04", "2026-08-08", 5)
        assert submit.success
        lr_id = submit.data["request_id"]

        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        registry.execute("reject_leave_request", {"request_id": lr_id, "comment": "no cert"}, mgr_ctx)

        with db_conn.cursor() as cur:
            cur.execute(
                """SELECT we.event_type, we.data FROM workflow_events we
                   JOIN workflow_instances wi ON wi.id = we.workflow_instance_id
                   WHERE wi.leave_request_id = %s::uuid AND we.tenant_id = %s
                     AND we.event_type = 'advisory_shown'
                   ORDER BY we.created_at DESC LIMIT 1""",
                (lr_id, tenant_id),
            )
            row = cur.fetchone()
            assert row is not None, "advisory_shown event not written"
            assert row[1].get("flag") == "no_medical_certificate"

    def test_reject_short_sick_no_cert_no_advisory(self, registry, ctx, tenant_id):
        """Rejecting short sick leave (≤ 3 days cert threshold) → no advisory flag."""
        # 2-day sick leave — below the 3-day cert threshold
        submit = registry.execute(
            "submit_leave_request",
            {"leave_type_code": "sick", "start_date": "2026-08-04", "end_date": "2026-08-05",
             "days_requested": 2, "reason": "mild cold"},
            ctx(role="employee", employee_code="EMP001"),
        )
        assert submit.success
        lr_id = submit.data["request_id"]

        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = registry.execute(
            "reject_leave_request",
            {"request_id": lr_id, "comment": "staffing needs"},
            mgr_ctx,
        )
        assert result.success
        flags = (result.data or {}).get("advisory_flags", [])
        assert "no_medical_certificate" not in flags, (
            "Short sick leave should not trigger advisory flag"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Constraint settings — thresholds are read from tenants.settings
# ═══════════════════════════════════════════════════════════════════════════════

class TestConstraintSettings:

    def test_tenant_settings_have_constraints_key(self, ds, tenant_id):
        """Migration 005 must have added the constraints key to tenants.settings."""
        settings = ds.get_tenant_settings(tenant_id)
        assert "constraints" in settings, (
            "constraints key missing from tenant settings. "
            "Run migration 005_constraint_fields.sql."
        )
        cfg = settings["constraints"]
        assert "max_concurrent_leave_pct" in cfg
        assert "allow_balance_override_roles" in cfg

    def test_override_role_gate_excludes_hr_staff(self, ds, tenant_id):
        """allow_balance_override_roles must not include hr_staff by default."""
        settings = ds.get_tenant_settings(tenant_id)
        roles = settings.get("constraints", {}).get("allow_balance_override_roles", [])
        assert "hr_staff" not in roles, (
            "hr_staff should not be in allow_balance_override_roles"
        )
        assert "hr_manager" in roles

    def test_count_active_leaves_in_department_zero_when_no_approved(
        self, ds, tenant_id
    ):
        """count_active_leaves_in_department returns 0 active_count when no approved leaves."""
        result = ds.count_active_leaves_in_department(
            tenant_id, "R&D", "2026-08-11", "2026-08-12"
        )
        assert result["active_count"] == 0
        assert result["total_employees"] == 2  # EMP001 + EMP003

    def test_count_active_leaves_in_department_counts_after_approval(
        self, registry, ctx, ds, tenant_id
    ):
        """active_count increases after an approval."""
        # Approve EMP003 first
        emp3 = _submit_annual_leave(registry, ctx, "EMP003", "2026-08-11", "2026-08-12")
        assert emp3.success
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        registry.execute("approve_leave_request", {"request_id": emp3.data["request_id"]}, mgr_ctx)

        result = ds.count_active_leaves_in_department(
            tenant_id, "R&D", "2026-08-11", "2026-08-12"
        )
        assert result["active_count"] == 1
        assert result["total_employees"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — Email link respects constraint engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmailLinkConstraint:

    def test_email_link_approval_blocked_by_constraint(
        self, ctx, ds, db_conn, tenant_id, registry, client
    ):
        """Email-link approval is blocked when it would breach the 25% concurrent cap.
        No state change should occur — leave remains pending_approval."""
        start, end = "2026-09-08", "2026-09-10"  # dates clear of other test windows

        # Approve EMP003 for same dates → active_count=1 in R&D (1/2 = 50% > 25% cap)
        r3 = _submit_annual_leave(registry, ctx, "EMP003", start, end)
        assert r3.success, r3.error
        registry.execute(
            "approve_leave_request",
            {"request_id": r3.data["request_id"]},
            ctx(role="hr_manager", employee_code="EMP002"),
        )

        # Submit EMP001 for same dates — approving would push R&D to 2/2 = 100%
        r1 = _submit_annual_leave(registry, ctx, "EMP001", start, end)
        assert r1.success, r1.error
        request_id = r1.data["request_id"]

        # Look up the correlation token from the pending_action created at submission
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT pa.correlation_token
                FROM pending_actions pa
                JOIN workflow_instances wi ON wi.id = pa.workflow_instance_id
                WHERE wi.leave_request_id = %s::uuid
                  AND pa.tenant_id = %s
                  AND pa.status = 'pending'
                """,
                (request_id, tenant_id),
            )
            row = cur.fetchone()
        assert row is not None, "No pending_action found for the submitted leave request"
        token = row[0]

        # Hit the email-link resolve endpoint as if the manager clicked Approve
        resp = client.get(f"/api/leave/resolve/{token}?decision=approved")

        # Constraint must have fired — response signals blocked/requires-override, not success
        assert resp.status_code == 200
        body = resp.text.lower()
        assert "requires" in body or "not permitted" in body, (
            f"Expected constraint message in response, got: {resp.text[:400]}"
        )

        # Leave status must be unchanged — no state change occurred
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM leave_requests WHERE id = %s::uuid",
                (request_id,),
            )
            status_row = cur.fetchone()
        assert status_row[0] == "pending_approval", (
            f"Expected pending_approval after blocked email-link approval, got {status_row[0]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Working day calculation and weekend submission blocking
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkingDayCalculation:
    """
    Tests for count_working_days() utility and submission-time weekend validation.
    Monday–Friday are working days; Saturday (5) and Sunday (6) are excluded.
    """

    def test_working_day_calculation_monday_to_friday(self):
        """Mon–Fri inclusive = 5 working days."""
        from datetime import date as d
        from workflow.constraints import count_working_days
        assert count_working_days(d(2026, 7, 13), d(2026, 7, 17)) == 5  # Mon–Fri

    def test_request_spanning_weekend_counts_correctly(self):
        """Fri to Wed spans a weekend: Fri + Mon + Tue + Wed = 4, not 6 calendar days."""
        from datetime import date as d
        from workflow.constraints import count_working_days
        # July 17 = Friday, July 18–19 = weekend, July 20–22 = Mon–Wed
        assert count_working_days(d(2026, 7, 17), d(2026, 7, 22)) == 4

    def test_weekend_only_request_blocked(self, registry, ctx):
        """Submitting leave for Sat–Sun must be rejected with a working-days error."""
        result = registry.execute(
            "submit_leave_request",
            {
                "leave_type_code": "sick",
                "start_date": "2026-07-18",  # Saturday
                "end_date": "2026-07-19",    # Sunday
                "reason": "not feeling well",
            },
            ctx(role="employee", employee_code="EMP001"),
        )
        assert not result.success
        error = (result.error or "").lower()
        assert "weekend" in error or "working day" in error

    def test_single_weekend_day_blocked(self, registry, ctx):
        """A single Saturday produces zero working days and must be rejected."""
        from datetime import date as d
        from workflow.constraints import count_working_days
        assert count_working_days(d(2026, 7, 18), d(2026, 7, 18)) == 0  # Saturday

        result = registry.execute(
            "submit_leave_request",
            {
                "leave_type_code": "sick",
                "start_date": "2026-07-18",  # Saturday
                "end_date": "2026-07-18",
                "reason": "sick",
            },
            ctx(role="employee", employee_code="EMP001"),
        )
        assert not result.success
        error = (result.error or "").lower()
        assert "weekend" in error or "working day" in error
