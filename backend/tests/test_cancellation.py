"""
Integration tests for the approved leave cancellation feature.

These tests cover the full flow: employee requests cancellation of an already-approved
leave → HR approves → balance restored (full, partial, or zero).

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_cancellation.py -v --tb=short

Policy decisions (from Nourhan Hosny, HR):
    P-01: No manager re-approval. HR cancels directly.
    P-02: In-progress cancellation allowed. Only unconsumed days restored.
    P-03: Leave proceeds if HR hasn't processed before start date.
    P-04: Full cancellation only — employee resubmits for actual days needed.
"""

import pytest

from tests.conftest import get_used_days
from tools.leave import (
    ApproveLeaveCancellationTool,
    ApproveLeaveRequestTool,
    CancelLeaveRequestTool,
    GetPendingCancellationsTool,
    RequestLeaveCancellationTool,
    SubmitLeaveRequestTool,
)

# ── Date constants ─────────────────────────────────────────────────────────────
# All future dates — far enough past the 2-day advance-notice policy requirement.

FUTURE_START = "2026-08-18"   # Tuesday
FUTURE_END   = "2026-08-20"   # Thursday  →  3 working days
FUTURE_DAYS  = 3

# A second non-overlapping window for partial-restore test
ALT_START = "2026-09-01"
ALT_END   = "2026-09-03"   # 3 working days


# ── Setup helpers ──────────────────────────────────────────────────────────────

def _submit_annual(ds, ctx, employee_code="EMP001", start=FUTURE_START, end=FUTURE_END):
    """Submit an annual leave request and return its request_id."""
    role = "hr_manager" if employee_code == "EMP002" else "employee"
    emp_ctx = ctx(role=role, employee_code=employee_code)
    result = SubmitLeaveRequestTool(ds).execute(
        {"leave_type_code": "annual", "start_date": start, "end_date": end},
        emp_ctx,
    )
    assert result.success, f"Submit failed: {result.error}"
    return result.data["request_id"]


def _approve(ds, ctx, request_id):
    """Approve leave as EMP002 (hr_manager)."""
    hr_ctx = ctx(role="hr_manager", employee_code="EMP002")
    result = ApproveLeaveRequestTool(ds).execute({"request_id": request_id}, hr_ctx)
    assert result.success, f"Approval failed: {result.error}"


def _submit_and_approve(ds, ctx, start=FUTURE_START, end=FUTURE_END):
    """Submit annual leave for EMP001 and approve it. Returns request_id."""
    rid = _submit_annual(ds, ctx, start=start, end=end)
    _approve(ds, ctx, rid)
    return rid


def _request_cancellation(ds, ctx, request_id, reason="Plans changed"):
    """Request cancellation as EMP001 (default ctx). Asserts success."""
    result = RequestLeaveCancellationTool(ds).execute(
        {"request_id": request_id, "reason": reason},
        ctx(),
    )
    assert result.success, f"Cancellation request failed: {result.error}"


def _backdate_leave(db_conn, request_id, start="2026-05-01", end="2026-05-03"):
    """Directly update start/end dates in the DB to simulate a past leave."""
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE leave_requests SET start_date = %s, end_date = %s WHERE id = %s::uuid",
            (start, end, request_id),
        )
    db_conn.commit()


def _zero_used_days(db_conn, tenant_id):
    """Set used_days = 0 for EMP001's annual balance (forces underflow scenario)."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE leave_balances
            SET used_days = 0
            WHERE tenant_id = %s
              AND year = 2026
              AND employee_id = (
                  SELECT id FROM employees
                  WHERE employee_code = 'EMP001' AND tenant_id = %s
              )
              AND leave_type_id = (
                  SELECT id FROM leave_types
                  WHERE code = 'annual' AND tenant_id = %s
              )
            """,
            (tenant_id, tenant_id, tenant_id),
        )
    db_conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — Requesting cancellation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRequestCancellation:

    def test_employee_can_request_cancellation_of_approved_leave(self, ctx, ds):
        """EMP001 can request cancellation of their manager_approved leave."""
        request_id = _submit_and_approve(ds, ctx)

        result = RequestLeaveCancellationTool(ds).execute(
            {"request_id": request_id, "reason": "Plans changed"},
            ctx(),
        )

        assert result.success
        assert result.data["leave_request_id"] == request_id

    def test_cancellation_request_sets_status_to_cancellation_pending(self, ctx, ds, db_conn, tenant_id):
        """After requesting cancellation, DB status must be cancellation_pending."""
        request_id = _submit_and_approve(ds, ctx)
        _request_cancellation(ds, ctx, request_id)

        db_conn.rollback()
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM leave_requests WHERE id = %s::uuid",
                (request_id,),
            )
            row = cur.fetchone()

        assert row is not None
        assert row[0] == "cancellation_pending"

    def test_employee_cannot_cancel_pending_leave_via_new_tool(self, ctx, ds):
        """RequestLeaveCancellationTool requires the leave to be already approved."""
        rid = _submit_annual(ds, ctx)  # still pending_approval

        result = RequestLeaveCancellationTool(ds).execute({"request_id": rid}, ctx())

        assert not result.success
        assert "approved" in result.error.lower() or "status" in result.error.lower()

    def test_employee_cannot_cancel_others_approved_leave(self, ctx, ds):
        """EMP003 cannot request cancellation of EMP001's approved leave."""
        request_id = _submit_and_approve(ds, ctx)
        emp003_ctx = ctx(role="employee", employee_code="EMP003")

        result = RequestLeaveCancellationTool(ds).execute(
            {"request_id": request_id, "reason": "Not my leave"},
            emp003_ctx,
        )

        assert not result.success

    def test_old_cancel_tool_redirects_for_approved_leaves(self, ctx, ds):
        """CancelLeaveRequestTool returns a redirect message for already-approved requests."""
        request_id = _submit_and_approve(ds, ctx)

        result = CancelLeaveRequestTool(ds).execute({"request_id": request_id}, ctx())

        assert not result.success
        assert "request_leave_cancellation" in result.error

    def test_old_cancel_tool_still_handles_pending_approval(self, ctx, ds):
        """CancelLeaveRequestTool still cancels pending_approval requests as before."""
        rid = _submit_annual(ds, ctx)

        result = CancelLeaveRequestTool(ds).execute({"request_id": rid}, ctx())

        assert result.success


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — HR approval of cancellation
# ═══════════════════════════════════════════════════════════════════════════════

class TestApproveCancellation:

    def test_hr_can_approve_cancellation_full_restore(self, ctx, ds, db_conn, tenant_id):
        """Future leave: all days restored when no consumed_days provided."""
        request_id = _submit_and_approve(ds, ctx)

        db_conn.rollback()
        used_after_approval = get_used_days(db_conn, tenant_id, "EMP001", "annual")
        assert used_after_approval == float(FUTURE_DAYS), "used_days must reflect approved leave"

        _request_cancellation(ds, ctx, request_id)

        hr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = ApproveLeaveCancellationTool(ds).execute({"request_id": request_id}, hr_ctx)

        assert result.success
        assert result.data["days_restored"] == float(FUTURE_DAYS)

        db_conn.rollback()
        used_final = get_used_days(db_conn, tenant_id, "EMP001", "annual")
        assert used_final == 0.0, "All days should be restored for a future leave"

    def test_hr_can_approve_cancellation_partial_restore(self, ctx, ds, db_conn, tenant_id):
        """Partial restore: consumed_days=1 on a 3-day leave → 2 days restored."""
        request_id = _submit_and_approve(ds, ctx, start=ALT_START, end=ALT_END)

        db_conn.rollback()
        used_after_approval = get_used_days(db_conn, tenant_id, "EMP001", "annual")
        assert used_after_approval == 3.0

        _request_cancellation(ds, ctx, request_id)

        hr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = ApproveLeaveCancellationTool(ds).execute(
            {"request_id": request_id, "consumed_days": 1},
            hr_ctx,
        )

        assert result.success
        assert result.data["days_restored"] == 2.0

        db_conn.rollback()
        used_final = get_used_days(db_conn, tenant_id, "EMP001", "annual")
        assert used_final == 1.0, "Only consumed day should remain in used_days"

    def test_hr_can_approve_cancellation_zero_restore(self, ctx, ds, db_conn, tenant_id):
        """Past leave (end_date before today): 0 days restored when approved."""
        request_id = _submit_and_approve(ds, ctx)

        # Backdate to simulate a leave that has fully passed
        _backdate_leave(db_conn, request_id, start="2026-05-01", end="2026-05-03")

        _request_cancellation(ds, ctx, request_id)

        hr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = ApproveLeaveCancellationTool(ds).execute({"request_id": request_id}, hr_ctx)

        assert result.success
        assert result.data["days_restored"] == 0.0

        db_conn.rollback()
        used_final = get_used_days(db_conn, tenant_id, "EMP001", "annual")
        assert used_final == float(FUTURE_DAYS), "No days should be restored for a fully consumed leave"

    def test_employee_cannot_approve_own_cancellation(self, ctx, ds):
        """Employees cannot call approve_leave_cancellation — role blocked at tool level."""
        request_id = _submit_and_approve(ds, ctx)
        _request_cancellation(ds, ctx, request_id)

        result = ApproveLeaveCancellationTool(ds).execute(
            {"request_id": request_id},
            ctx(),  # employee role
        )

        assert not result.success

    def test_balance_never_goes_below_zero_on_restore(self, ctx, ds, db_conn, tenant_id):
        """GREATEST(0, used_days - restore) guard prevents negative used_days."""
        request_id = _submit_and_approve(ds, ctx)

        # Simulate an inconsistent state: used_days already at 0 despite approved leave
        _zero_used_days(db_conn, tenant_id)

        _request_cancellation(ds, ctx, request_id)

        hr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = ApproveLeaveCancellationTool(ds).execute(
            {"request_id": request_id},  # no consumed_days → tries full restore
            hr_ctx,
        )

        assert result.success

        db_conn.rollback()
        used_final = get_used_days(db_conn, tenant_id, "EMP001", "annual")
        assert used_final >= 0.0, f"used_days must never go negative, got {used_final}"


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — Visibility and side effects
# ═══════════════════════════════════════════════════════════════════════════════

class TestCancellationVisibility:

    def test_get_pending_cancellations_shows_request(self, ctx, ds):
        """After requesting cancellation, it appears in get_pending_cancellations."""
        request_id = _submit_and_approve(ds, ctx)
        _request_cancellation(ds, ctx, request_id)

        hr_ctx = ctx(role="hr_manager", employee_code="EMP002")
        result = GetPendingCancellationsTool(ds).execute({}, hr_ctx)

        assert result.success
        ids = [item["id"] for item in result.data["pending_cancellations"]]
        assert request_id in ids

    def test_employee_cannot_view_pending_cancellations(self, ctx, ds):
        """Employees cannot call get_pending_cancellations."""
        result = GetPendingCancellationsTool(ds).execute({}, ctx())
        assert not result.success

    def test_cancelled_leave_excluded_from_overlap_check(self, ctx, ds):
        """A cancelled leave must not block a new request for the same dates."""
        request_id = _submit_and_approve(ds, ctx)
        emp_ctx = ctx()
        hr_ctx = ctx(role="hr_manager", employee_code="EMP002")

        _request_cancellation(ds, ctx, request_id, reason="Overlap test setup")
        ApproveLeaveCancellationTool(ds).execute({"request_id": request_id}, hr_ctx)

        # Resubmit for the same dates — overlap check must not block this
        result = SubmitLeaveRequestTool(ds).execute(
            {"leave_type_code": "annual", "start_date": FUTURE_START, "end_date": FUTURE_END},
            emp_ctx,
        )

        assert result.success, f"Resubmit after cancellation should succeed, got: {result.error}"
