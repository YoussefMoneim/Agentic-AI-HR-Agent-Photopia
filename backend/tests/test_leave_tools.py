"""
Integration tests for all 9 leave tools (Phase 1).

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_leave_tools.py -v --tb=short

All tests hit the real seeded PostgreSQL DB. The autouse `reset_leave_data` fixture
in conftest.py deletes all leave_requests / workflow_instances / pending_actions and
resets pending_days/used_days to 0 before and after every test, so each test starts
from a known-clean state.

Seeded employees (relevant):
    EMP001 – Saif Ahmed Hassan, R&D, hired 2022-03-15, manager = EMP002
    EMP002 – Nourhan Hosny,     HR,  hired 2021-06-01, NO MANAGER (top of hierarchy)
    EMP003 – Omar Alsayed,      R&D, hired 2023-01-10, manager = EMP002

Annual leave balance (2026): 21 allocated days for all three employees.
Annual leave policy: 90-day probation restriction, 2-day minimum advance notice.
WFH policy: max 2 days/week, max 8 days/month.
"""

import pytest

from tests.conftest import get_pending_days, get_used_days
from tools.leave import (
    ApproveLeaveRequestTool,
    CancelLeaveRequestTool,
    CheckLeaveBalanceTool,
    CheckLeaveEligibilityTool,
    GetLeaveRequestsTool,
    GetLeaveWaitingStatusTool,
    GetPendingApprovalsTool,
    RejectLeaveRequestTool,
    SubmitLeaveRequestTool,
)

# ─── date constants ───────────────────────────────────────────────────────────
# All dates are far enough in the future to pass the 2-day advance-notice rule.
# Aug 3, 2026 is a Monday; Aug 31, 2026 is a Monday.

ANNUAL_START = "2026-08-18"
ANNUAL_END   = "2026-08-20"   # 3 days
ANNUAL_DAYS  = 3

OVERLAP_START = "2026-07-08"
OVERLAP_END   = "2026-07-10"  # 3 days – used for overlap detection test
OVERLAP_LATER_START = "2026-07-09"
OVERLAP_LATER_END   = "2026-07-12"  # overlaps the first request

WFH_WEEK1_START = "2026-08-03"  # Monday
WFH_WEEK1_END   = "2026-08-04"  # Tuesday – 2 days (reaches weekly limit)
WFH_WEEK1_3RD   = "2026-08-05"  # Wednesday – would exceed weekly limit

WFH_WEEK2_START = "2026-08-10"
WFH_WEEK2_END   = "2026-08-11"
WFH_WEEK3_START = "2026-08-17"
WFH_WEEK3_END   = "2026-08-18"
WFH_WEEK4_START = "2026-08-24"
WFH_WEEK4_END   = "2026-08-25"
WFH_MONTH_9TH   = "2026-08-31"  # Monday of week 5 – triggers monthly limit (8 → 9)

TOMORROW        = "2026-06-22"  # 1 day notice (annual needs 2) → blocked
YESTERDAY       = "2026-06-20"  # past date


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — Balance checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckLeaveBalance:

    def test_employee_reads_own_balance(self, ctx, ds):
        """EMP001 can read their own balance with no employee_code supplied."""
        tool = CheckLeaveBalanceTool(ds)
        result = tool.execute({}, ctx())
        assert result.success
        assert result.data["employee_code"] == "EMP001"
        assert isinstance(result.data["balances"], list)
        assert len(result.data["balances"]) > 0

    def test_employee_cannot_read_others_balance(self, ctx, ds):
        """Employee role row-level check: cannot request another employee's balance."""
        tool = CheckLeaveBalanceTool(ds)
        result = tool.execute({"employee_code": "EMP002"}, ctx())
        assert not result.success
        assert "only check your own" in result.error.lower()

    def test_hr_manager_reads_any_balance(self, ctx, ds):
        """HR manager can read any employee's balance."""
        tool = CheckLeaveBalanceTool(ds)
        result = tool.execute({"employee_code": "EMP001"}, ctx(role="hr_manager", employee_code="EMP002"))
        assert result.success
        assert result.data["employee_code"] == "EMP001"

    def test_balance_includes_expected_leave_types(self, ctx, ds):
        """Annual and sick leave types must appear in EMP001's 2026 balance."""
        tool = CheckLeaveBalanceTool(ds)
        result = tool.execute({}, ctx())
        assert result.success
        codes = {b["leave_type_code"] for b in result.data["balances"]}
        assert "annual" in codes
        assert "sick" in codes

    def test_unknown_employee_code_returns_error(self, ctx, ds):
        """Non-existent employee code returns a clear error."""
        tool = CheckLeaveBalanceTool(ds)
        result = tool.execute({"employee_code": "EMP999"}, ctx(role="hr_manager", employee_code="EMP002"))
        assert not result.success
        assert "EMP999" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — Eligibility checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckLeaveEligibility:

    def test_annual_eligible_with_sufficient_balance_and_notice(self, ctx, ds):
        """EMP001 has 21 days available, 3 requested, well within notice period."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            ctx(),
        )
        assert result.success
        assert result.data["eligible"] is True

    def test_annual_blocked_insufficient_balance(self, ctx, ds):
        """25 days requested but only 21 allocated → insufficient balance."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "annual", "start_date": "2026-08-01", "end_date": "2026-08-25"},
            ctx(),
        )
        assert result.success
        assert result.data["eligible"] is False
        assert "insufficient balance" in result.data["reason"].lower()

    def test_annual_blocked_min_notice_too_short(self, ctx, ds):
        """Annual leave requires 2-day advance notice; tomorrow (1 day away) is blocked."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "annual", "start_date": TOMORROW, "end_date": TOMORROW},
            ctx(),
        )
        assert result.success
        assert result.data["eligible"] is False
        assert "notice" in result.data["reason"].lower()

    def test_annual_blocked_during_probation(self, ctx, ds, recently_hired_employee):
        """Employee hired today is still in 90-day probation — annual leave is blocked."""
        new_emp = recently_hired_employee
        tool = CheckLeaveEligibilityTool(ds)
        # Use HR manager to check eligibility of the new employee
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = tool.execute(
            {
                "employee_code": new_emp,
                "leave_type_code": "annual",
                "start_date": "2026-07-01",
                "end_date": "2026-07-01",
            },
            mgr_ctx,
        )
        assert result.success
        assert result.data["eligible"] is False
        assert "probation" in result.data["reason"].lower()

    def test_emergency_leave_within_max_consecutive_days(self, ctx, ds):
        """6 consecutive emergency days — at the maximum, should be eligible."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "emergency", "start_date": "2026-08-01", "end_date": "2026-08-06"},
            ctx(),
        )
        assert result.success
        assert result.data["eligible"] is True

    def test_emergency_leave_exceeds_max_consecutive_days(self, ctx, ds):
        """7 consecutive emergency days — exceeds max (6) → blocked."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "emergency", "start_date": "2026-08-01", "end_date": "2026-08-07"},
            ctx(),
        )
        assert result.success
        assert result.data["eligible"] is False
        assert "maximum" in result.data["reason"].lower()

    def test_wfh_blocked_by_weekly_limit(self, ctx, ds):
        """Submit 2 WFH days (Mon-Tue) to reach weekly limit, then check Wed → blocked."""
        submit = SubmitLeaveRequestTool(ds)
        emp_ctx = ctx()
        # Fill the week (2 days = weekly limit)
        r = submit.execute(
            {"leave_type_code": "wfh", "start_date": WFH_WEEK1_START, "end_date": WFH_WEEK1_END},
            emp_ctx,
        )
        assert r.success, f"WFH setup submit failed: {r.error}"

        # A 3rd day in the same week should be blocked
        check = CheckLeaveEligibilityTool(ds)
        result = check.execute(
            {"leave_type_code": "wfh", "start_date": WFH_WEEK1_3RD, "end_date": WFH_WEEK1_3RD},
            emp_ctx,
        )
        assert result.success
        assert result.data["eligible"] is False
        assert "weekly" in result.data["reason"].lower()

    def test_wfh_blocked_by_monthly_limit(self, ctx, ds):
        """Submit 8 WFH days across 4 weeks in August → 9th day (Aug 31) is blocked."""
        submit = SubmitLeaveRequestTool(ds)
        emp_ctx = ctx()
        for (s, e) in [
            (WFH_WEEK1_START, WFH_WEEK1_END),   # week 1: Aug 3-4 (2 days, total 2)
            (WFH_WEEK2_START, WFH_WEEK2_END),   # week 2: Aug 10-11 (total 4)
            (WFH_WEEK3_START, WFH_WEEK3_END),   # week 3: Aug 17-18 (total 6)
            (WFH_WEEK4_START, WFH_WEEK4_END),   # week 4: Aug 24-25 (total 8)
        ]:
            r = submit.execute({"leave_type_code": "wfh", "start_date": s, "end_date": e}, emp_ctx)
            assert r.success, f"WFH setup failed for {s}–{e}: {r.error}"

        # 9th day in August — new week (week 5, Aug 31), so weekly is fine,
        # but monthly total becomes 9 > 8 → blocked
        check = CheckLeaveEligibilityTool(ds)
        result = check.execute(
            {"leave_type_code": "wfh", "start_date": WFH_MONTH_9TH, "end_date": WFH_MONTH_9TH},
            emp_ctx,
        )
        assert result.success
        assert result.data["eligible"] is False
        assert "monthly" in result.data["reason"].lower()

    def test_permission_requires_duration_hours(self, ctx, ds):
        """Permission (time-based) needs duration_hours > 0."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({"leave_type_code": "permission", "duration_hours": 2}, ctx())
        assert result.success
        assert result.data["eligible"] is True

    def test_permission_duration_hours_zero_blocked(self, ctx, ds):
        """duration_hours = 0 for permission type is rejected."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({"leave_type_code": "permission", "duration_hours": 0}, ctx())
        assert not result.success
        assert "duration_hours" in result.error.lower()

    def test_business_trip_always_eligible(self, ctx, ds):
        """Business trip does not deduct balance; no balance check required."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "business_trip", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            ctx(),
        )
        assert result.success
        assert result.data["eligible"] is True

    def test_unknown_leave_type_returns_error(self, ctx, ds):
        """'vacation' is not a valid leave type code — tool returns success=False with valid types list."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "vacation", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            ctx(),
        )
        assert not result.success
        assert "vacation" in result.error

    def test_leave_type_uppercase_accepted(self, ctx, ds):
        """Input 'ANNUAL' should be lowercased internally and treated as 'annual'."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "ANNUAL", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            ctx(),
        )
        assert result.success
        assert result.data["eligible"] is True

    def test_end_date_before_start_date_returns_error(self, ctx, ds):
        """end_date < start_date is invalid — tool should return success=False."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute(
            {"leave_type_code": "annual", "start_date": "2026-08-20", "end_date": "2026-08-18"},
            ctx(),
        )
        assert not result.success
        assert "end_date" in result.error.lower() or "after" in result.error.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — Submit
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubmitLeaveRequest:

    def test_submit_annual_leave_success(self, ctx, ds):
        """EMP001 submits 3-day annual leave — request_id returned, status=pending_approval."""
        tool = SubmitLeaveRequestTool(ds)
        result = tool.execute(
            {
                "leave_type_code": "annual",
                "start_date": ANNUAL_START,
                "end_date": ANNUAL_END,
                "reason": "vacation",
            },
            ctx(),
        )
        assert result.success
        assert result.data["request_id"]
        assert result.data["status"] == "pending_approval"
        assert result.data["days_requested"] == ANNUAL_DAYS

    def test_submit_permission_success(self, ctx, ds):
        """EMP001 submits a 2-hour permission (time-based) — request_id returned.
        Note: submit_leave_request requires start_date even for time-based types
        (eligibility check needs it; duration_hours alone is not sufficient)."""
        tool = SubmitLeaveRequestTool(ds)
        result = tool.execute(
            {
                "leave_type_code": "permission",
                "duration_hours": 2,
                "start_date": "2026-08-18",
                "reason": "dentist",
            },
            ctx(),
        )
        assert result.success
        assert result.data["request_id"]

    def test_submit_without_manager_fails(self, ctx, ds):
        """EMP002 (Nourhan) has no manager → cannot submit leave."""
        tool = SubmitLeaveRequestTool(ds)
        emp002_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = tool.execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            emp002_ctx,
        )
        assert not result.success
        assert "manager" in result.error.lower()

    def test_submit_always_uses_ctx_employee_code(self, ctx, ds):
        """Submit tool uses ctx.employee_code — the resulting request belongs to EMP001."""
        tool = SubmitLeaveRequestTool(ds)
        result = tool.execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            ctx(),
        )
        assert result.success
        # Confirm the request's employee is EMP001, not any other
        from tools.leave import GetLeaveRequestsTool
        requests_result = GetLeaveRequestsTool(ds).execute({}, ctx())
        assert requests_result.success
        assert requests_result.data["count"] == 1
        assert requests_result.data["requests"][0]["id"] == result.data["request_id"]

    def test_submit_blocked_by_overlap(self, ctx, ds):
        """
        Submit a request, then try to submit an overlapping request.
        The second submit calls check_leave_eligibility internally and
        is blocked because the dates overlap an existing pending request.
        """
        submit = SubmitLeaveRequestTool(ds)
        emp_ctx = ctx()

        first = submit.execute(
            {"leave_type_code": "annual", "start_date": OVERLAP_START, "end_date": OVERLAP_END},
            emp_ctx,
        )
        assert first.success, f"First submit failed: {first.error}"

        second = submit.execute(
            {
                "leave_type_code": "annual",
                "start_date": OVERLAP_LATER_START,
                "end_date": OVERLAP_LATER_END,
            },
            emp_ctx,
        )
        assert not second.success
        assert "overlap" in second.error.lower()

    def test_submit_increments_pending_days(self, ctx, ds, db_conn, tenant_id):
        """Submitting annual leave reserves days as pending_days in leave_balances."""
        before = get_pending_days(db_conn, tenant_id, "EMP001", "annual")
        assert before == 0.0, "Test precondition failed: pending_days should be 0 before submit"

        SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            ctx(),
        )

        db_conn.rollback()  # Re-read committed data
        after = get_pending_days(db_conn, tenant_id, "EMP001", "annual")
        assert after == float(ANNUAL_DAYS)

    def test_idempotency_key_unique_constraint_exists(self, db_conn):
        """Verify the DB has a UNIQUE index on pending_actions.idempotency_key."""
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE tablename = 'pending_actions'
                  AND indexdef ILIKE '%idempotency_key%'
                """,
            )
            rows = cur.fetchall()
        assert rows, "No index on pending_actions.idempotency_key found"
        assert any("unique" in row[0].lower() for row in rows), (
            "pending_actions.idempotency_key must have a UNIQUE index"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — Approval flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestApprovalFlow:
    """Tests require a submitted leave request as setup."""

    def _submit_annual(self, ds, emp_ctx):
        """Helper: submit a standard 3-day annual leave for EMP001."""
        result = SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            emp_ctx,
        )
        assert result.success, f"Test setup submit failed: {result.error}"
        return result.data["request_id"]

    def test_manager_can_approve_pending_request(self, ctx, ds):
        """EMP002 (assigned manager) approves EMP001's request → status = manager_approved."""
        emp_ctx = ctx()
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        request_id = self._submit_annual(ds, emp_ctx)

        result = ApproveLeaveRequestTool(ds).execute({"request_id": request_id}, mgr_ctx)
        assert result.success
        assert result.data["new_status"] == "manager_approved"

    def test_reject_with_comment_releases_pending_days(self, ctx, ds, db_conn, tenant_id):
        """Rejecting a request releases the reserved pending_days."""
        emp_ctx = ctx()
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        request_id = self._submit_annual(ds, emp_ctx)

        # Pending days should be reserved now
        db_conn.rollback()
        pending_before = get_pending_days(db_conn, tenant_id, "EMP001", "annual")
        assert pending_before == float(ANNUAL_DAYS), "pending_days not incremented on submit"

        RejectLeaveRequestTool(ds).execute(
            {"request_id": request_id, "comment": "Team capacity issue"},
            mgr_ctx,
        )

        db_conn.rollback()
        pending_after = get_pending_days(db_conn, tenant_id, "EMP001", "annual")
        assert pending_after == 0.0, "pending_days not released after rejection"

    def test_reject_requires_comment(self, ctx, ds):
        """Reject without a comment returns an error."""
        emp_ctx = ctx()
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        request_id = self._submit_annual(ds, emp_ctx)

        result = RejectLeaveRequestTool(ds).execute(
            {"request_id": request_id, "comment": ""},
            mgr_ctx,
        )
        assert not result.success
        assert "comment" in result.error.lower() or "reason" in result.error.lower()

    def test_cancel_pending_request_releases_pending_days(self, ctx, ds, db_conn, tenant_id):
        """Employee cancels their own pending request → status=cancelled, pending_days released."""
        emp_ctx = ctx()
        request_id = self._submit_annual(ds, emp_ctx)

        db_conn.rollback()
        pending_before = get_pending_days(db_conn, tenant_id, "EMP001", "annual")
        assert pending_before == float(ANNUAL_DAYS)

        result = CancelLeaveRequestTool(ds).execute({"request_id": request_id}, emp_ctx)
        assert result.success
        assert result.data["new_status"] == "cancelled"

        db_conn.rollback()
        pending_after = get_pending_days(db_conn, tenant_id, "EMP001", "annual")
        assert pending_after == 0.0

    def test_cannot_cancel_already_approved_request(self, ctx, ds):
        """Cancelling an already-approved request is blocked (only pending_approval is cancellable)."""
        emp_ctx = ctx()
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        request_id = self._submit_annual(ds, emp_ctx)

        ApproveLeaveRequestTool(ds).execute({"request_id": request_id}, mgr_ctx)

        result = CancelLeaveRequestTool(ds).execute({"request_id": request_id}, emp_ctx)
        assert not result.success
        assert "manager_approved" in result.error or "pending_approval" in result.error

    def test_cannot_approve_already_approved_request(self, ctx, ds):
        """Double-approving a request returns an error."""
        emp_ctx = ctx()
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        request_id = self._submit_annual(ds, emp_ctx)

        ApproveLeaveRequestTool(ds).execute({"request_id": request_id}, mgr_ctx)

        result = ApproveLeaveRequestTool(ds).execute({"request_id": request_id}, mgr_ctx)
        assert not result.success
        assert "manager_approved" in result.error

    def test_wrong_manager_cannot_approve(self, ctx, ds):
        """EMP003 is not the assigned manager for EMP001's request (EMP002 is) → denied."""
        emp_ctx = ctx()
        emp003_mgr_ctx = ctx(role="hr_manager", employee_code="EMP003")
        request_id = self._submit_annual(ds, emp_ctx)

        result = ApproveLeaveRequestTool(ds).execute({"request_id": request_id}, emp003_mgr_ctx)
        assert not result.success
        assert "assigned approver" in result.error.lower() or "not the assigned" in result.error.lower()

    def test_employee_cannot_cancel_others_request(self, ctx, ds):
        """EMP003 (employee role) cannot cancel EMP001's leave request."""
        emp001_ctx = ctx()
        emp003_ctx = ctx(role="employee", employee_code="EMP003")
        request_id = self._submit_annual(ds, emp001_ctx)

        result = CancelLeaveRequestTool(ds).execute({"request_id": request_id}, emp003_ctx)
        assert not result.success
        assert "only cancel your own" in result.error.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — Security & access control (tool-level, not registry-level)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccessControl:

    def test_employee_balance_row_level_isolation(self, ctx, ds):
        """Employee cannot see another employee's balance via employee_code input."""
        result = CheckLeaveBalanceTool(ds).execute(
            {"employee_code": "EMP003"}, ctx(role="employee", employee_code="EMP001")
        )
        assert not result.success

    def test_cross_tenant_employee_not_found(self, ds):
        """Wrong tenant_id means the employee is simply not found — application-level isolation."""
        from tools.base import ToolContext
        fake_ctx = ToolContext(
            tenant_id="00000000-0000-0000-0000-000000000000",
            user_id="attacker",
            role="employee",
            employee_code="EMP001",
        )
        result = CheckLeaveBalanceTool(ds).execute({}, fake_ctx)
        assert not result.success
        assert "not found" in result.error.lower()

    def test_employee_cannot_access_pending_approvals(self, ctx, ds):
        """GetPendingApprovalsTool.allowed_roles excludes 'employee' — direct call denied by role check."""
        emp_ctx = ctx()
        tool = GetPendingApprovalsTool(ds)
        # allowed_roles = ["hr_staff", "hr_manager", "admin"] — employee not in list
        # Direct execute bypasses registry role check; test at tool level via the registry in test_security.py
        # Here we just verify the tool spec excludes employee
        assert "employee" not in tool.spec.allowed_roles

    def test_approve_tool_spec_excludes_employee_role(self, ds):
        """approve_leave_request.allowed_roles does not include 'employee'."""
        assert "employee" not in ApproveLeaveRequestTool(ds).spec.allowed_roles

    def test_reject_tool_spec_excludes_employee_role(self, ds):
        """reject_leave_request.allowed_roles does not include 'employee'."""
        assert "employee" not in RejectLeaveRequestTool(ds).spec.allowed_roles

    def test_submit_tool_includes_employee_role(self, ds):
        """submit_leave_request is available to employees (they need to submit their own requests)."""
        assert "employee" in SubmitLeaveRequestTool(ds).spec.allowed_roles


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6 — Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_exactly_one_day_leave(self, ctx, ds):
        """start_date == end_date should create a 1-day request."""
        result = SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_START},
            ctx(),
        )
        assert result.success
        assert result.data["days_requested"] == 1.0

    def test_very_long_leave_blocked_by_balance(self, ctx, ds):
        """Requesting 100 annual days (balance = 21) is blocked by eligibility check inside submit."""
        result = SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": "2026-07-01", "end_date": "2026-10-08"},
            ctx(),
        )
        assert not result.success
        assert "balance" in result.error.lower() or "insufficient" in result.error.lower()

    @pytest.mark.xfail(
        strict=False,
        reason="Past date blocking not implemented — all leave types currently allow past start_date. Phase 2 TODO.",
    )
    def test_sick_leave_in_the_past_should_be_blocked(self, ctx, ds):
        """
        Sick leave for yesterday should be blocked (no min_notice for sick).
        Currently the code does NOT block past dates — this test documents the gap.
        Phase 2 should add a universal 'start_date >= today' guard.
        """
        result = CheckLeaveEligibilityTool(ds).execute(
            {"leave_type_code": "sick", "start_date": YESTERDAY, "end_date": YESTERDAY},
            ctx(),
        )
        assert result.success
        # Phase 2 expectation: eligible=False. Current behavior: eligible=True (no past-date guard).
        assert result.data["eligible"] is False

    def test_employee_sees_only_own_requests(self, ctx, ds):
        """After submitting as EMP001, get_leave_requests as EMP001 returns exactly that request."""
        emp_ctx = ctx()
        submit_result = SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            emp_ctx,
        )
        assert submit_result.success

        result = GetLeaveRequestsTool(ds).execute({}, emp_ctx)
        assert result.success
        assert result.data["count"] == 1
        assert result.data["requests"][0]["id"] == submit_result.data["request_id"]

    def test_hr_manager_sees_all_requests(self, ctx, ds):
        """HR manager with no filter sees all employees' requests."""
        emp_ctx = ctx()
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")

        SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            emp_ctx,
        )

        result = GetLeaveRequestsTool(ds).execute({}, mgr_ctx)
        assert result.success
        assert result.data["count"] >= 1

    def test_get_waiting_status_shows_pending_request(self, ctx, ds):
        """After submitting, get_leave_waiting_status shows the pending request for the employee."""
        emp_ctx = ctx()
        SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            emp_ctx,
        )

        result = GetLeaveWaitingStatusTool(ds).execute({}, emp_ctx)
        assert result.success
        assert result.data["count"] == 1

    def test_approve_sets_status_and_updates_balance(self, ctx, ds, db_conn, tenant_id):
        """Chat-tool approval sets status=manager_approved AND moves days pending→used."""
        emp_ctx = ctx()
        mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")

        request_id = SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            emp_ctx,
        ).data["request_id"]

        db_conn.rollback()
        assert get_pending_days(db_conn, tenant_id, "EMP001", "annual") == float(ANNUAL_DAYS)

        approve_result = ApproveLeaveRequestTool(ds).execute({"request_id": request_id}, mgr_ctx)
        assert approve_result.success
        assert approve_result.data["new_status"] == "manager_approved"

        db_conn.rollback()
        assert get_pending_days(db_conn, tenant_id, "EMP001", "annual") == 0.0
        assert get_used_days(db_conn, tenant_id, "EMP001", "annual") == float(ANNUAL_DAYS)

    def test_action_type_data_read_on_balance_check(self, ctx, ds):
        """Balance check tool sets action_type='data_read' for correct audit logging."""
        result = CheckLeaveBalanceTool(ds).execute({}, ctx())
        assert result.action_type == "data_read"

    def test_action_type_data_write_on_submit(self, ctx, ds):
        """Submit tool sets action_type='data_write' for correct audit logging."""
        result = SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": ANNUAL_START, "end_date": ANNUAL_END},
            ctx(),
        )
        assert result.success
        assert result.action_type == "data_write"
