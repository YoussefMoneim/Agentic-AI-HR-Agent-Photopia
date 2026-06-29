"""
Integration tests for the team leave calendar feature.

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_calendar.py -v --tb=short

Role behaviour:
    employee   — own leave events only; daily_summary counts all team members (anonymous)
    hr_manager — all employees; full details; optional department filter
    (no "manager" role in the current 4-role system; future addition)

Seeded employees:
    EMP001 (Saif)    — R&D,  employee role,   manager = EMP002
    EMP002 (Nourhan) — HR,   hr_manager role, no manager (top of hierarchy)
    EMP003 (Omar)    — R&D,  employee role,   manager = EMP002
"""

import pytest

from tools.calendar import GetTeamCalendarTool
from tools.leave import (
    ApproveLeaveRequestTool,
    RequestLeaveCancellationTool,
    CancelLeaveRequestTool,
    SubmitLeaveRequestTool,
)

# ── Date constants ─────────────────────────────────────────────────────────────
# Both windows are in August 2026 — well clear of the 2-day advance-notice rule.

YEAR  = 2026
MONTH = 8

CAL_START = "2026-08-18"   # Tuesday
CAL_END   = "2026-08-20"   # Thursday  — 3 working days

EMP002_START = "2026-08-19"  # overlaps with CAL_START-CAL_END on the 19th and 20th
EMP002_END   = "2026-08-21"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _submit(ds, ctx, employee_code=None, start=CAL_START, end=CAL_END):
    """Submit annual leave; returns request_id. Defaults to EMP001."""
    if employee_code is None:
        employee_code = "EMP001"
    role = "hr_manager" if employee_code == "EMP002" else "employee"
    result = SubmitLeaveRequestTool(ds).execute(
        {"leave_type_code": "annual", "start_date": start, "end_date": end},
        ctx(role=role, employee_code=employee_code),
    )
    assert result.success, f"Submit failed for {employee_code}: {result.error}"
    return result.data["request_id"]


def _calendar(ds, ctx, role="employee", employee_code="EMP001", year=YEAR, month=MONTH, department=None):
    """Call GetTeamCalendarTool and return ToolResult."""
    inp = {"year": year, "month": month}
    if department:
        inp["department"] = department
    return GetTeamCalendarTool(ds).execute(inp, ctx(role=role, employee_code=employee_code))


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — Employee view
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmployeeCalendarView:

    def test_employee_sees_own_leave_event(self, ctx, ds):
        """EMP001 sees their own annual leave event with full details."""
        _submit(ds, ctx, "EMP001")

        result = _calendar(ds, ctx)

        assert result.success
        events = result.data["events"]
        own = [e for e in events if e["is_own"]]
        assert len(own) == 1
        assert own[0]["employee_name"] is not None
        assert own[0]["employee_code"] == "EMP001"
        assert own[0]["leave_type_code"] == "annual"

    def test_employee_events_list_contains_only_own(self, ctx, ds):
        """Employee events list contains only their own leave — no other employees' events."""
        _submit(ds, ctx, "EMP001", start=CAL_START, end=CAL_END)
        _submit(ds, ctx, "EMP002", start=EMP002_START, end=EMP002_END)

        result = _calendar(ds, ctx)

        assert result.success
        events = result.data["events"]
        # Every event in the list must be the caller's own
        for ev in events:
            assert ev["is_own"] is True
            assert ev["employee_code"] == "EMP001"
        # EMP002's leave is NOT in the events list (only counted in daily_summary)
        assert all(ev["employee_code"] != "EMP002" for ev in events)

    def test_employee_daily_summary_counts_all_team(self, ctx, ds):
        """daily_summary on-leave count includes all team members, not just the caller."""
        _submit(ds, ctx, "EMP001", start=CAL_START, end=CAL_END)
        _submit(ds, ctx, "EMP002", start=EMP002_START, end=EMP002_END)

        result = _calendar(ds, ctx)

        assert result.success
        # Aug 19 and 20 are covered by both employees' leaves
        summary_aug19 = result.data["daily_summary"].get("2026-08-19")
        assert summary_aug19 is not None
        assert summary_aug19["on_leave_count"] >= 2, (
            "Both EMP001 and EMP002 are on leave on Aug 19 — count should be at least 2"
        )

    def test_daily_summary_covers_every_day_of_month(self, ctx, ds):
        """daily_summary must include an entry for every calendar day in the month."""
        result = _calendar(ds, ctx)

        assert result.success
        from calendar import monthrange
        _, days_in_month = monthrange(YEAR, MONTH)
        assert len(result.data["daily_summary"]) == days_in_month


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — HR view
# ═══════════════════════════════════════════════════════════════════════════════

class TestHRCalendarView:

    def test_hr_sees_all_employees(self, ctx, ds):
        """HR manager sees all 3 seeded employees' events with names."""
        _submit(ds, ctx, "EMP001")
        _submit(ds, ctx, "EMP002", start=EMP002_START, end=EMP002_END)
        _submit(ds, ctx, "EMP003", start="2026-08-25", end="2026-08-27")

        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002")

        assert result.success
        codes = {e["employee_code"] for e in result.data["events"]}
        assert "EMP001" in codes
        assert "EMP002" in codes
        assert "EMP003" in codes
        # All events have names visible to HR
        for ev in result.data["events"]:
            assert ev["employee_name"] is not None

    def test_hr_department_filter_includes_matching_dept(self, ctx, ds):
        """HR calendar with department=R&D includes EMP001 (R&D) events."""
        _submit(ds, ctx, "EMP001")   # R&D

        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002", department="R&D")

        assert result.success
        codes = {e["employee_code"] for e in result.data["events"]}
        assert "EMP001" in codes

    def test_hr_department_filter_excludes_other_dept(self, ctx, ds):
        """HR calendar with department=R&D does not include EMP002 (HR dept) events."""
        _submit(ds, ctx, "EMP001")                                         # R&D
        _submit(ds, ctx, "EMP002", start=EMP002_START, end=EMP002_END)    # HR

        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002", department="R&D")

        assert result.success
        codes = {e["employee_code"] for e in result.data["events"]}
        assert "EMP001" in codes
        assert "EMP002" not in codes

    def test_employee_department_filter_silently_ignored(self, ctx, ds):
        """department filter is silently ignored for employee role (security guard)."""
        _submit(ds, ctx, "EMP001")

        result = _calendar(ds, ctx, role="employee", employee_code="EMP001", department="R&D")

        assert result.success
        # Employee still sees their own event regardless of the ignored dept filter
        own = [e for e in result.data["events"] if e["is_own"]]
        assert len(own) == 1

    def test_departments_list_returned(self, ctx, ds):
        """departments list contains at least the seeded departments."""
        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002")

        assert result.success
        depts = result.data["departments"]
        assert "R&D" in depts
        assert "HR" in depts


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — Daily summary threshold and status inclusion
# ═══════════════════════════════════════════════════════════════════════════════

class TestDailySummary:

    def test_over_threshold_false_when_no_leaves(self, ctx, ds):
        """No leaves in month → on_leave_count=0, over_threshold=False for all days."""
        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002")

        assert result.success
        for day_data in result.data["daily_summary"].values():
            assert day_data["on_leave_count"] == 0
            assert day_data["over_threshold"] is False

    def test_over_threshold_true_above_25_percent(self, ctx, ds):
        """1 of 2 R&D employees on leave = 50% > 25% → over_threshold=True for those days.
        Filters to department='R&D' so only EMP001 and EMP003 are in scope (2 employees)."""
        _submit(ds, ctx, "EMP001", start=CAL_START, end=CAL_END)

        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002", department="R&D")

        assert result.success
        aug18 = result.data["daily_summary"]["2026-08-18"]
        assert aug18["on_leave_count"] == 1
        assert aug18["percentage"] > 25.0
        assert aug18["over_threshold"] is True

    def test_cancelled_leave_excluded_from_summary(self, ctx, ds):
        """Cancelled leave is not counted in daily_summary or events list."""
        rid = _submit(ds, ctx, "EMP001")
        CancelLeaveRequestTool(ds).execute({"request_id": rid}, ctx())

        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002")

        assert result.success
        assert len(result.data["events"]) == 0
        aug18 = result.data["daily_summary"]["2026-08-18"]
        assert aug18["on_leave_count"] == 0

    def test_cancellation_pending_included_in_summary(self, ctx, ds):
        """Leave in cancellation_pending status is still active — must appear in calendar."""
        rid = _submit(ds, ctx, "EMP001")
        # Approve it to manager_approved
        ApproveLeaveRequestTool(ds).execute(
            {"request_id": rid},
            ctx(role="hr_manager", employee_code="EMP002"),
        )
        # Request cancellation → status = cancellation_pending
        RequestLeaveCancellationTool(ds).execute(
            {"request_id": rid, "reason": "Test"},
            ctx(),
        )

        result = _calendar(ds, ctx, role="hr_manager", employee_code="EMP002")

        assert result.success
        statuses = {e["status"] for e in result.data["events"]}
        assert "cancellation_pending" in statuses
        aug18 = result.data["daily_summary"]["2026-08-18"]
        assert aug18["on_leave_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — API endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalendarAPI:

    def test_endpoint_rejects_invalid_jwt(self, client):
        """GET /api/calendar/leave with a malformed token → 401."""
        resp = client.get(
            "/api/calendar/leave",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert resp.status_code == 401

    def test_endpoint_invalid_month(self, client, make_jwt):
        """month=13 → 400."""
        token = make_jwt(employee_code="EMP001", role="employee")
        resp = client.get(
            "/api/calendar/leave?month=13",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_endpoint_valid_returns_correct_shape(self, client, make_jwt):
        """Valid JWT returns response with all expected top-level keys."""
        token = make_jwt(employee_code="EMP002", role="hr_manager")
        resp = client.get(
            f"/api/calendar/leave?year={YEAR}&month={MONTH}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in ("events", "daily_summary", "departments", "total_employees_in_scope", "viewer_role"):
            assert key in body, f"Missing key '{key}' in response"
        assert body["viewer_role"] == "hr_manager"
