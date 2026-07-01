"""
Integration tests for WIN Holding Leave Policy (HR/BTE 001/7-2025) — Phase 2.

Tests cover:
  - Funeral degree split (funeral_1st_degree / funeral_2nd_degree)
  - Casual leave consecutive-day limit (≤2 days)
  - Carry-over expiry after Q1 (March 31)
  - Service minimum enforcement (marriage 1yr, hajj 5yrs, maternity 1yr)
  - Career usage cap (marriage 1×, maternity 3×, paternity 3×)
  - AddCompensatoryDayTool (credit mechanism)
  - is_casual flag stored on leave_requests at submission

Seeded employees:
    EMP001 – Saif Hassan,   R&D, hired 2022-03-15 (~4.3 yrs service, ~1564 days)
    EMP002 – Nourhan Hosny, HR,  hired 2021-06-01 (~5.1 yrs service, ~1851 days)
    EMP003 – Omar Alsayed,  R&D, hired 2023-01-10 (~3.5 yrs service, ~1263 days)
    recently_hired_employee – hired TODAY (0 days service)

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_win_policy.py -v --tb=short
"""

import psycopg2
import pytest
from datetime import date, timedelta

from tools.leave import (
    AddCompensatoryDayTool,
    CheckLeaveEligibilityTool,
    SubmitLeaveRequestTool,
)

# ─── Date constants ────────────────────────────────────────────────────────────
# Today = 2026-06-26 (Friday). Egypt weekend = Fri (4) + Sat (5).
# 2026-06-27 = Saturday (weekday 5), 2026-06-28 = Sunday (working day).
# Min start for ≤3-day annual leave = today + 1 day = 2026-06-27.
# Min start for >3-day annual leave = 7 working days from today ≈ 2026-07-07.

FUNERAL_START   = "2026-06-28"   # Sunday — no notice requirement for funeral
FUNERAL_END_1   = "2026-06-28"   # 1 calendar day
FUNERAL_END_3   = "2026-06-30"   # 3 calendar days (max for 1st degree)
FUNERAL_END_4   = "2026-07-01"   # 4 calendar days (exceeds 1st-degree max)
FUNERAL_END_2   = "2026-06-29"   # 2 calendar days (exceeds 2nd-degree max of 1)

def _working_days_from_today(n: int) -> str:
    d = date.today()
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return str(d)

CASUAL_START = _working_days_from_today(3)  # 3rd working day — passes ≤3-day notice
CASUAL_END_2 = _working_days_from_today(4)  # 4th working day — 2-day span from CASUAL_START
CASUAL_END_3 = _working_days_from_today(5)  # 5th working day — 3-day span from CASUAL_START

# Dates far enough ahead to pass 7-working-day notice requirement (>3-day annual)
AHEAD_START     = "2026-08-10"   # Monday well past July 7 notice deadline
AHEAD_END_22    = "2026-08-31"   # 22 calendar days from Aug 10 (22 > 21)
AHEAD_END_5     = "2026-08-14"   # 5 calendar days from Aug 10

HAJJ_START      = "2026-09-01"
HAJJ_END        = "2026-09-30"   # 30 days

HOLIDAY_SATURDAY = "2026-06-27"  # Saturday — valid Egypt weekend day
WEEKDAY_MONDAY   = "2026-06-29"  # Monday — NOT a holiday or weekend


# ─── Helper ───────────────────────────────────────────────────────────────────

def _insert_leave_request(conn, tenant_id: str, employee_code: str,
                           leave_type_code: str, start_date: str, end_date: str):
    """Insert a bare leave_request row to simulate prior usage for career-cap tests.
    Status is 'pending_approval' (counted by count_leave_type_usage)."""
    with conn.cursor() as cur:
        cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
        cur.execute(
            """
            INSERT INTO leave_requests
                (tenant_id, employee_id, leave_type_id,
                 start_date, end_date, days_requested, status)
            SELECT t.id, e.id, lt.id,
                   %s::date, %s::date, 1, 'pending_approval'
            FROM tenants t
            JOIN employees e   ON e.tenant_id  = t.id AND e.employee_code = %s
            JOIN leave_types lt ON lt.tenant_id = t.id AND lt.code = %s
            WHERE t.id = %s
            """,
            (start_date, end_date, employee_code, leave_type_code, tenant_id),
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# Funeral degree split
# ═══════════════════════════════════════════════════════════════════════════════

class TestFuneralDegreeSplit:
    """After migration 011: two typed funeral leave types replace the generic one."""

    def test_funeral_1st_degree_3_days_allowed(self, ctx, ds):
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "funeral_1st_degree",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_3,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is True
        assert result.data["days_requested"] == 3

    def test_funeral_1st_degree_4_days_blocked(self, ctx, ds):
        """4 days exceeds max_consecutive_days=3 for 1st-degree funeral."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "funeral_1st_degree",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_4,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        assert "maximum" in result.data["reason"].lower()

    def test_funeral_2nd_degree_1_day_allowed(self, ctx, ds):
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "funeral_2nd_degree",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_1,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is True
        assert result.data["days_requested"] == 1

    def test_funeral_2nd_degree_2_days_blocked(self, ctx, ds):
        """2 days exceeds max_consecutive_days=1 for 2nd-degree funeral."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "funeral_2nd_degree",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_2,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        assert "maximum" in result.data["reason"].lower()

    def test_funeral_generic_type_inactive(self, ctx, ds):
        """Generic 'funeral' code is inactive after migration 011 — not available."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "funeral",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_1,
        }, ctx())
        # Not active → tool returns success=False (type not found)
        assert not result.success
        assert "not available" in result.error.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Casual leave consecutive limit
# ═══════════════════════════════════════════════════════════════════════════════

class TestCasualLeave:
    """WIN policy: casual annual leave is limited to ≤2 consecutive days per request."""

    def test_casual_2_days_allowed(self, ctx, ds):
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "annual",
            "start_date": CASUAL_START,
            "end_date": CASUAL_END_2,
            "is_casual": True,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is True
        assert result.data.get("is_casual") is True

    def test_casual_3_days_blocked(self, ctx, ds):
        """3 consecutive casual days exceeds the 2-day limit."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "annual",
            "start_date": CASUAL_START,
            "end_date": CASUAL_END_3,
            "is_casual": True,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        assert "casual" in result.data["reason"].lower()
        assert "2 consecutive" in result.data["reason"]

    def test_regular_3_days_not_blocked_by_casual_rule(self, ctx, ds):
        """is_casual=False (or omitted): the 2-day casual cap does not apply."""
        tool = CheckLeaveEligibilityTool(ds)
        # 3-day regular annual, starts Monday CASUAL_START — passes ≤3-day notice (1 day)
        result = tool.execute({
            "leave_type_code": "annual",
            "start_date": CASUAL_START,
            "end_date": CASUAL_END_3,
        }, ctx())
        assert result.success
        # Should be eligible (no casual restriction applies; balance 21 ≥ 3)
        assert result.data["eligible"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Carry-over expiry
# ═══════════════════════════════════════════════════════════════════════════════

class TestCarryOverExpiry:
    """Carry-over days expire on March 31 of the balance year (Q1 only)."""

    def test_carry_over_expired_after_q1_blocks_request(
        self, ctx, ds, db_conn, tenant_id
    ):
        """Today = June (month 6 > 3): carry-over is expired.
        Request 22 days, which is > 21 (allocated) but ≤ 26 (with carry-over).
        Without expired carry-over, available = 21 < 22 → blocked."""
        # Set carry_over_days=5 for EMP001 annual 2026
        with db_conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                """
                UPDATE leave_balances
                SET carry_over_days = 5
                WHERE tenant_id = %s
                  AND employee_id = (
                      SELECT id FROM employees
                      WHERE tenant_id = %s AND employee_code = 'EMP001'
                  )
                  AND leave_type_id = (
                      SELECT id FROM leave_types
                      WHERE tenant_id = %s AND code = 'annual'
                  )
                  AND year = 2026
                """,
                (tenant_id, tenant_id, tenant_id),
            )
        db_conn.commit()

        try:
            tool = CheckLeaveEligibilityTool(ds)
            result = tool.execute({
                "leave_type_code": "annual",
                "start_date": AHEAD_START,
                "end_date": AHEAD_END_22,  # 22 calendar days
            }, ctx())

            assert result.success
            assert result.data["eligible"] is False
            reason = result.data["reason"].lower()
            assert "carry-over" in reason or "carry_over" in reason
        finally:
            # Restore carry_over_days to 0
            with db_conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                cur.execute(
                    """
                    UPDATE leave_balances
                    SET carry_over_days = 0
                    WHERE tenant_id = %s
                      AND employee_id = (
                          SELECT id FROM employees
                          WHERE tenant_id = %s AND employee_code = 'EMP001'
                      )
                      AND leave_type_id = (
                          SELECT id FROM leave_types
                          WHERE tenant_id = %s AND code = 'annual'
                      )
                      AND year = 2026
                    """,
                    (tenant_id, tenant_id, tenant_id),
                )
            db_conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# Service minimum
# ═══════════════════════════════════════════════════════════════════════════════

class TestServiceMinimum:
    """WIN policy: hajj needs 5 years (1825 days), marriage/maternity need 1 year (365 days)."""

    def test_hajj_blocked_below_5_year_service_emp001(self, ctx, ds):
        """EMP001 (hired 2022-03-15) has ~1564 days service < 1825 (5 years)."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "hajj",
            "start_date": HAJJ_START,
            "end_date": HAJJ_END,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        reason = result.data["reason"]
        assert "5 year" in reason or "1825" in reason

    def test_hajj_blocked_below_5_year_service_emp003(self, ctx, ds):
        """EMP003 (hired 2023-01-10) has ~1263 days < 1825."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "hajj",
            "start_date": HAJJ_START,
            "end_date": HAJJ_END,
        }, ctx(role="employee", employee_code="EMP003"))
        assert result.success
        assert result.data["eligible"] is False

    def test_marriage_blocked_for_new_hire(self, ctx, ds, recently_hired_employee):
        """Employee hired today has 0 days service < 365 (1 year) for marriage."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "marriage",
            "start_date": AHEAD_START,
            "end_date": AHEAD_END_5,
        }, ctx(role="employee", employee_code=recently_hired_employee))
        assert result.success
        assert result.data["eligible"] is False
        reason = result.data["reason"]
        assert "1 year" in reason or "365" in reason

    def test_maternity_blocked_for_new_hire(self, ctx, ds, recently_hired_employee):
        """Employee hired today has 0 days service < 365 (1 year) for maternity."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "maternity",
            "start_date": AHEAD_START,
            "end_date": "2026-12-07",  # 120 days
        }, ctx(role="employee", employee_code=recently_hired_employee))
        assert result.success
        assert result.data["eligible"] is False
        reason = result.data["reason"]
        assert "1 year" in reason or "365" in reason

    def test_hajj_allowed_after_5_years_emp002(self, ctx, ds):
        """EMP002 (hired 2021-06-01) has ~1851 days > 1825 → passes service min.
        Career cap: first use (max_times_in_career=1) → eligible."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "hajj",
            "start_date": HAJJ_START,
            "end_date": HAJJ_END,
        }, ctx(role="hr_manager", employee_code="EMP002"))
        assert result.success
        # Eligible (no prior uses, service passes)
        assert result.data["eligible"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Career usage cap
# ═══════════════════════════════════════════════════════════════════════════════

class TestCareerUsageCap:
    """WIN policy: marriage=1×, maternity=3×, paternity=3× during career."""

    def test_marriage_once_per_career_blocked(self, ctx, ds, db_conn, tenant_id):
        """After 1 prior marriage leave, a second request is blocked."""
        _insert_leave_request(
            db_conn, tenant_id, "EMP001", "marriage",
            "2025-01-01", "2025-01-05",
        )
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "marriage",
            "start_date": AHEAD_START,
            "end_date": AHEAD_END_5,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        reason = result.data["reason"]
        assert "once" in reason.lower() or "1 prior" in reason.lower()

    def test_maternity_max_3_times_blocked(self, ctx, ds, db_conn, tenant_id):
        """After 3 prior maternity requests, a 4th is blocked."""
        for i in range(3):
            month = str(i + 1).zfill(2)
            _insert_leave_request(
                db_conn, tenant_id, "EMP001", "maternity",
                f"2024-{month}-01", f"2024-{month}-28",
            )
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "maternity",
            "start_date": AHEAD_START,
            "end_date": "2026-12-07",
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        reason = result.data["reason"]
        assert "3 times" in reason.lower() or "3 prior" in reason.lower()

    def test_paternity_max_1_day_per_request(self, ctx, ds):
        """max_consecutive_days=1 for paternity: requesting 2 days is blocked."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "paternity",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_2,   # 2 days > max_consecutive_days=1
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        assert "maximum" in result.data["reason"].lower()

    def test_paternity_1_day_allowed(self, ctx, ds):
        """Exactly 1 day paternity is allowed (first use, service_min_days=0)."""
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "paternity",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_1,  # 1 day
        }, ctx())
        assert result.success
        assert result.data["eligible"] is True

    def test_paternity_max_3_times_blocked(self, ctx, ds, db_conn, tenant_id):
        """After 3 prior paternity requests, a 4th is blocked."""
        for i in range(3):
            _insert_leave_request(
                db_conn, tenant_id, "EMP001", "paternity",
                f"2024-0{i+1}-01", f"2024-0{i+1}-01",
            )
        tool = CheckLeaveEligibilityTool(ds)
        result = tool.execute({
            "leave_type_code": "paternity",
            "start_date": FUNERAL_START,
            "end_date": FUNERAL_END_1,
        }, ctx())
        assert result.success
        assert result.data["eligible"] is False
        reason = result.data["reason"]
        assert "3 times" in reason.lower() or "3 prior" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# AddCompensatoryDayTool
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompensatoryDayTool:
    """HR tool: credit 1 compensatory day to annual leave balance."""

    def test_add_compensatory_day_requires_manager_approval(self, ctx, ds):
        """approved_by_manager=False → error, no balance change."""
        tool = AddCompensatoryDayTool(ds)
        result = tool.execute({
            "employee_code": "EMP001",
            "holiday_date": HOLIDAY_SATURDAY,
            "approved_by_manager": False,
        }, ctx(role="hr_manager", employee_code="EMP002"))
        assert not result.success
        assert "prior manager approval" in result.error.lower() or "approved_by_manager" in result.error.lower()

    def test_add_compensatory_day_non_weekend_blocked(self, ctx, ds):
        """A regular working day is not eligible for compensatory credit."""
        tool = AddCompensatoryDayTool(ds)
        result = tool.execute({
            "employee_code": "EMP001",
            "holiday_date": WEEKDAY_MONDAY,
            "approved_by_manager": True,
        }, ctx(role="hr_manager", employee_code="EMP002"))
        assert not result.success
        assert "not a public holiday" in result.error.lower() or "weekend" in result.error.lower()

    def test_add_compensatory_day_credits_balance(self, ctx, ds, db_conn, tenant_id):
        """Credits 1 day to annual leave allocated_days for EMP001."""
        # Read initial allocated_days
        with db_conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                """
                SELECT lb.allocated_days
                FROM leave_balances lb
                JOIN employees e ON e.id = lb.employee_id
                JOIN leave_types lt ON lt.id = lb.leave_type_id
                WHERE lb.tenant_id = %s
                  AND e.employee_code = 'EMP001'
                  AND lt.code = 'annual'
                  AND lb.year = 2026
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
        initial_allocated = float(row[0]) if row else 21.0

        tool = AddCompensatoryDayTool(ds)
        result = tool.execute({
            "employee_code": "EMP001",
            "holiday_date": HOLIDAY_SATURDAY,
            "approved_by_manager": True,
        }, ctx(role="hr_manager", employee_code="EMP002"))

        assert result.success
        assert result.data["new_annual_leave_allocated_days"] == initial_allocated + 1
        assert "EMP001" in result.data.get("employee_code", "")

        # Cleanup: restore allocated_days
        with db_conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                """
                UPDATE leave_balances
                SET allocated_days = %s
                WHERE tenant_id = %s
                  AND employee_id = (
                      SELECT id FROM employees WHERE tenant_id = %s AND employee_code = 'EMP001'
                  )
                  AND leave_type_id = (
                      SELECT id FROM leave_types WHERE tenant_id = %s AND code = 'annual'
                  )
                  AND year = 2026
                """,
                (initial_allocated, tenant_id, tenant_id, tenant_id),
            )
        db_conn.commit()

    def test_add_compensatory_day_hr_only(self, ctx, ds):
        """Employee role cannot call add_compensatory_day (hr_staff+ only)."""
        tool = AddCompensatoryDayTool(ds)
        assert "employee" not in tool.spec.allowed_roles
        assert "hr_staff" in tool.spec.allowed_roles
        assert "hr_manager" in tool.spec.allowed_roles


# ═══════════════════════════════════════════════════════════════════════════════
# is_casual stored on leave_request at submission
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsCasualFlag:
    """is_casual=True must be stored in leave_requests.is_casual when submitted."""

    def test_submit_casual_leave_stores_flag(self, ctx, ds, db_conn, tenant_id):
        """Submitting annual leave with is_casual=True stores the flag in the DB row."""
        tool = SubmitLeaveRequestTool(ds)
        result = tool.execute({
            "leave_type_code": "annual",
            "start_date": CASUAL_START,
            "end_date": CASUAL_END_2,  # 2 days — valid casual
            "is_casual": True,
        }, ctx())
        assert result.success, result.error
        request_id = result.data["request_id"]

        # Verify is_casual is stored in the DB
        with db_conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                "SELECT is_casual FROM leave_requests WHERE id = %s::uuid",
                (request_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] is True

    def test_submit_regular_leave_is_casual_false_by_default(self, ctx, ds, db_conn, tenant_id):
        """Submitting without is_casual stores False (the default)."""
        tool = SubmitLeaveRequestTool(ds)
        result = tool.execute({
            "leave_type_code": "annual",
            "start_date": CASUAL_START,
            "end_date": CASUAL_END_2,
        }, ctx())
        assert result.success, result.error
        request_id = result.data["request_id"]

        with db_conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                "SELECT is_casual FROM leave_requests WHERE id = %s::uuid",
                (request_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Allocation advisory (first-year / age-50)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAllocationAdvisory:
    """Advisory flags on eligibility response for mis-allocated balances."""

    def test_first_year_employee_gets_advisory_flag(self, ctx, ds, db_conn, tenant_id):
        """Employee hired in 2026 → 'first_hire_year_allocation' advisory flag.
        We create a temp employee hired 2026-01-01 (past 90-day probation) with
        a 21-day annual balance (should be 15) to trigger the advisory."""
        emp_code = "TEST_2026_HIRE"
        with db_conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                """
                INSERT INTO employees
                    (tenant_id, employee_code, full_name, department,
                     employment_type, start_date, currency)
                VALUES (%s, %s, 'Test 2026 Hire', 'R&D', 'Full-time', '2026-01-01', 'EGP')
                ON CONFLICT (tenant_id, employee_code) DO NOTHING
                """,
                (tenant_id, emp_code),
            )
            # Link to EMP002 as manager
            cur.execute(
                """
                UPDATE employees
                SET manager_id = (SELECT id FROM employees WHERE tenant_id = %s AND employee_code = 'EMP002')
                WHERE tenant_id = %s AND employee_code = %s
                """,
                (tenant_id, tenant_id, emp_code),
            )
            # Add annual leave balance of 21 days (should be 15 per WIN policy)
            cur.execute(
                """
                INSERT INTO leave_balances (tenant_id, employee_id, leave_type_id, year, allocated_days)
                SELECT %s, e.id, lt.id, 2026, 21.0
                FROM employees e, leave_types lt
                WHERE e.tenant_id = %s AND e.employee_code = %s
                  AND lt.tenant_id = %s AND lt.code = 'annual'
                ON CONFLICT DO NOTHING
                """,
                (tenant_id, tenant_id, emp_code, tenant_id),
            )
        db_conn.commit()

        try:
            tool = CheckLeaveEligibilityTool(ds)
            result = tool.execute({
                "leave_type_code": "annual",
                "start_date": AHEAD_START,
                "end_date": AHEAD_END_5,  # 5 days
            }, ctx(role="employee", employee_code=emp_code))
            assert result.success
            assert result.data["eligible"] is True
            flags = result.data.get("advisory_flags", [])
            assert "first_hire_year_allocation" in flags
            assert "15 days" in result.data.get("advisory", "")
        finally:
            with db_conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                cur.execute(
                    "DELETE FROM leave_balances WHERE tenant_id = %s AND employee_id = "
                    "(SELECT id FROM employees WHERE tenant_id = %s AND employee_code = %s)",
                    (tenant_id, tenant_id, emp_code),
                )
                cur.execute(
                    "DELETE FROM employees WHERE tenant_id = %s AND employee_code = %s",
                    (tenant_id, emp_code),
                )
            db_conn.commit()

    def test_age_50_employee_gets_enhanced_advisory(self, ctx, ds, db_conn, tenant_id):
        """Employee born in 1975 is 51 years old → 'enhanced_allocation_30_days' advisory."""
        with db_conn.cursor() as cur:
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
            cur.execute(
                """
                UPDATE employees
                SET birth_date = '1975-01-01'
                WHERE tenant_id = %s AND employee_code = 'EMP001'
                """,
                (tenant_id,),
            )
        db_conn.commit()

        try:
            tool = CheckLeaveEligibilityTool(ds)
            result = tool.execute({
                "leave_type_code": "annual",
                "start_date": AHEAD_START,
                "end_date": AHEAD_END_5,
            }, ctx())
            assert result.success
            assert result.data["eligible"] is True
            flags = result.data.get("advisory_flags", [])
            assert "enhanced_allocation_30_days" in flags
            assert "30 days" in result.data.get("advisory", "")
        finally:
            with db_conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                cur.execute(
                    "UPDATE employees SET birth_date = NULL WHERE tenant_id = %s AND employee_code = 'EMP001'",
                    (tenant_id,),
                )
            db_conn.commit()
