import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone

import config
from core.access import can_access
from data.base import DataSource
from services import email as email_svc
from tools.base import Tool, ToolContext, ToolResult, ToolSpec
from utils.prompt_security import sanitize_for_html_email, wrap_untrusted_content
from workflow.constraints import evaluate_constraints
from workflow.routing import get_routing_policy

# SECURITY NOTE: Any user-provided text (reason, comment fields) that goes into
# LLM context must be wrapped with wrap_untrusted_content() from utils.prompt_security.
# Any user-provided text that goes into HTML email bodies must be passed through
# sanitize_for_html_email(). This prevents indirect prompt injection (Rule 13 in CLAUDE.md).
# Raw values are stored in the database as-is — protection applies at USE, not storage.


def _today() -> date:
    return date.today()


def _parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def _calendar_days(start: date, end: date) -> float:
    return float((end - start).days + 1)


def _add_working_days(from_date: date, n: int) -> date:
    """Return the date that is n working days after from_date.
    Uses Egypt weekend (Friday=4, Saturday=5) and EGYPT_PUBLIC_HOLIDAYS_2026 from config."""
    holidays = {date.fromisoformat(d) for d in getattr(config, "EGYPT_PUBLIC_HOLIDAYS_2026", [])}
    weekend = set(getattr(config, "EGYPT_WEEKEND_DAYS", [4, 5]))
    count = 0
    current = from_date
    while count < n:
        current += timedelta(days=1)
        if current.weekday() not in weekend and current not in holidays:
            count += 1
    return current


def _months_employed(start_date: date, reference_date: date) -> int:
    return (reference_date.year - start_date.year) * 12 + (reference_date.month - start_date.month)


def _week_start(d: date) -> date:
    """Return the Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


_LEAVE_FIELD_REQUIREMENTS: dict[str, dict] = {
    "annual":        {"reason_required": False},
    "sick":          {"reason_required": False,
                      "attachment_note": "A medical report from a company network provider must be submitted to HR."},
    "emergency":     {"reason_required": False},
    "permission":    {"reason_required": False},
    "wfh":           {"reason_required": False},
    "compensatory":  {"reason_required": False},
    "business_trip": {"reason_required": True,
                      "reason_prompt": "What is the purpose of the business trip?",
                      "attachment_prompt": "Do you have a travel authorisation or itinerary to attach? (optional)"},
    "outside_duty":  {"reason_required": True,
                      "reason_prompt": "What is the purpose of the outside duty assignment?"},
    "unpaid":        {"reason_required": True,
                      "reason_prompt": "What is the reason for the unpaid leave request?"},
    "marriage":      {"reason_required": False,
                      "attachment_note": "Marriage certificate documentation required. Leave is available once per service life after 1+ year of service."},
    "hajj":          {"reason_required": False,
                      "attachment_note": "Hajj registration documentation required. Requires 5+ consecutive years of full-time service. Available once per service life."},
    "umrah":         {"reason_required": False,
                      "attachment_note": "Supporting documentation required. Available once per service life after 1+ year of service."},
    "funeral":       {"reason_required": True,
                      "reason_prompt": "Please specify the relationship to the deceased (e.g. father, mother, spouse — 3 days; or grandparent, sibling — 1 day)."},
    "maternity":     {"reason_required": False,
                      "attachment_note": "Medical documentation required. Available up to 3 times during service. Requires 1+ year of service."},
    "paternity":     {"reason_required": False,
                      "attachment_note": "Hospital or birth documentation required. Must be taken on the delivery/surgery day. Available up to 3 times during service."},
    "educational":   {"reason_required": False,
                      "attachment_note": "Exam schedule and enrolment confirmation must be shared with HR and direct manager in advance."},
    "military":      {"reason_required": False,
                      "attachment_note": "Official military authority summons letter required."},
}


# ─── Tool 0: check_request_completeness ──────────────────────────────────────

class CheckRequestCompletenessTool(Tool):
    spec = ToolSpec(
        name="check_request_completeness",
        description=(
            "Check whether all required fields are present before submitting a leave request. "
            "Call this FIRST, before check_leave_eligibility. "
            "Returns complete=true/false, missing_fields list, prompts to show the user, and any warnings."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "leave_type_code": {
                    "type": "string",
                    "description": "annual, sick, emergency, permission, business_trip, wfh, outside_duty, compensatory, unpaid",
                },
                "start_date":     {"type": "string", "description": "Start date YYYY-MM-DD (not for permission)."},
                "end_date":       {"type": "string", "description": "End date YYYY-MM-DD (not for permission)."},
                "start_datetime": {"type": "string", "description": "Start datetime ISO 8601 (permission only)."},
                "end_datetime":   {"type": "string", "description": "End datetime ISO 8601 (permission only)."},
                "duration_hours": {"type": "number",  "description": "Duration in hours (permission only)."},
                "reason":         {"type": "string",  "description": "Reason/note for types that require one."},
            },
            "required": ["leave_type_code"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        leave_type_code = input.get("leave_type_code", "").lower()

        leave_type = self._ds.get_leave_type_by_code(ctx.tenant_id, leave_type_code)
        if not leave_type:
            return ToolResult(
                success=False,
                error=f"Unknown leave type '{leave_type_code}'. Check valid active leave types with your HR administrator.",
            )

        rules = _LEAVE_FIELD_REQUIREMENTS.get(leave_type_code, {"reason_required": False})
        is_time_based = leave_type.get("is_time_based", False)

        missing_fields: list[str] = []
        prompts: list[str] = []
        warnings: list[str] = []

        if is_time_based:
            has_duration = float(input.get("duration_hours") or 0) > 0
            has_datetimes = bool(input.get("start_datetime")) and bool(input.get("end_datetime"))
            if not has_duration and not has_datetimes:
                missing_fields.append("duration_hours or start_datetime+end_datetime")
                prompts.append(
                    "Please provide the start and end time for the permission (e.g. '2 PM to 4 PM') or total hours."
                )
        else:
            if not input.get("start_date"):
                missing_fields.append("start_date")
                prompts.append("What is the start date? (YYYY-MM-DD)")
            if not input.get("end_date"):
                missing_fields.append("end_date")
                prompts.append("What is the end date? (YYYY-MM-DD)")

        if rules.get("reason_required") and not input.get("reason"):
            missing_fields.append("reason")
            prompts.append(rules.get("reason_prompt", "Please provide a reason for this leave request."))

        if rules.get("attachment_prompt"):
            prompts.append(rules["attachment_prompt"])

        if leave_type_code == "sick" and input.get("start_date") and input.get("end_date"):
            try:
                days = _calendar_days(_parse_date(input["start_date"]), _parse_date(input["end_date"]))
                if days > 3:
                    warnings.append(rules.get("attachment_note", ""))
            except ValueError:
                pass

        complete = len(missing_fields) == 0

        result_data: dict = {
            "complete": complete,
            "leave_type_name": leave_type["name_en"],
            "missing_fields": missing_fields,
            "prompts": prompts,
            "warnings": [w for w in warnings if w],
        }
        if rules.get("attachment_note") and leave_type_code == "sick":
            result_data["attachment_note"] = rules["attachment_note"]

        return ToolResult(
            success=True,
            data=result_data,
            action_type="data_read",
        )


# ─── Tool 1: check_leave_balance ─────────────────────────────────────────────

class CheckLeaveBalanceTool(Tool):
    spec = ToolSpec(
        name="check_leave_balance",
        description=(
            "Show the current leave balance for an employee. "
            "Returns all leave types with their allocated, used, pending, and available days for the current year. "
            "Employee role can only check their own balance."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "Employee code to check (optional — defaults to the calling employee's own code).",
                },
            },
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = input.get("employee_code") or ctx.employee_code
        decision = can_access(ctx, "read_leave_balance", {"employee_code": employee_code})
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error=f"Employee {employee_code} not found.")

        year = _today().year
        balances = self._ds.get_leave_balance_detail(ctx.tenant_id, employee_code, year)

        return ToolResult(
            success=True,
            data={
                "employee_name": employee["full_name"],
                "employee_code": employee_code,
                "year": year,
                "balances": balances,
            },
            data_fields_accessed=["leave_balance", "allocated_days", "used_days", "pending_days"],
            action_type="data_read",
        )


# ─── Tool 2: check_leave_eligibility ─────────────────────────────────────────

class CheckLeaveEligibilityTool(Tool):
    spec = ToolSpec(
        name="check_leave_eligibility",
        description=(
            "Check whether an employee is eligible to take a specific type of leave. "
            "Run this BEFORE calling submit_leave_request. "
            "For Permission (time-off within a day), provide duration_hours instead of start_date/end_date. "
            "Returns eligible=true/false with a reason if blocked."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "Employee code (defaults to the calling employee).",
                },
                "leave_type_code": {
                    "type": "string",
                    "description": "Leave type: annual, sick, emergency, permission, business_trip, wfh, outside_duty, compensatory, unpaid.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date ISO format YYYY-MM-DD (not required for permission type).",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date ISO format YYYY-MM-DD (not required for permission type).",
                },
                "duration_hours": {
                    "type": "number",
                    "description": "Duration in hours (only for permission type).",
                },
                "is_casual": {
                    "type": "boolean",
                    "description": "Annual leave only: true = casual leave (max 2 consecutive days). Omit or false for regular annual leave.",
                },
            },
            "required": ["leave_type_code"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = input.get("employee_code") or ctx.employee_code
        decision = can_access(ctx, "read_leave_eligibility", {"employee_code": employee_code})
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        leave_type_code = input.get("leave_type_code", "").lower()

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error=f"Employee {employee_code} not found.")

        leave_type = self._ds.get_leave_type_by_code(ctx.tenant_id, leave_type_code)
        if not leave_type:
            return ToolResult(
                success=False,
                error=f"Leave type '{leave_type_code}' is not available or not active for this tenant.",
            )

        policy = self._ds.get_leave_policy(ctx.tenant_id, leave_type["id"]) or {}

        today = _today()
        is_time_based = leave_type.get("is_time_based", False)

        # Parse dates for non-Permission types
        start_date: date | None = None
        end_date: date | None = None
        days_requested: float = 0.0
        duration_hours: float | None = None

        if is_time_based:
            duration_hours = float(input.get("duration_hours") or 0)
            if duration_hours <= 0:
                return ToolResult(
                    success=False,
                    error="Permission type requires duration_hours > 0 (e.g., 2 for 2 hours).",
                )
        else:
            if not input.get("start_date") or not input.get("end_date"):
                return ToolResult(
                    success=False,
                    error="start_date and end_date are required for this leave type.",
                )
            try:
                start_date = _parse_date(input["start_date"])
                end_date = _parse_date(input["end_date"])
            except ValueError:
                return ToolResult(success=False, error="Invalid date format. Use YYYY-MM-DD.")

            if end_date < start_date:
                return ToolResult(success=False, error="end_date must be on or after start_date.")
            days_requested = _calendar_days(start_date, end_date)

        # 1. Probation check
        probation_days = policy.get("probation_restriction_days", 0) or 0
        if probation_days > 0 and employee.get("start_date"):
            hire_date = _parse_date(employee["start_date"])
            probation_end = hire_date + timedelta(days=probation_days)
            ref = start_date or today
            if ref < probation_end:
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": f"Probation restriction: leave is not allowed during the first {probation_days} days of employment (until {probation_end.isoformat()}).",
                        "leave_type_name": leave_type["name_en"],
                    },
                    action_type="data_read",
                )

        # 2. Notice period check
        if start_date and not is_time_based:
            if leave_type_code == "annual":
                # WIN policy HR/BTE 001/7-2025: 24h notice for 2-3 day requests;
                # 7 working days notice for requests longer than 3 days.
                if days_requested <= 3:
                    min_start = today + timedelta(days=1)
                    notice_desc = "1 calendar day (24h)"
                else:
                    min_start = _add_working_days(today, 7)
                    notice_desc = "7 working days"
                if start_date < min_start:
                    return ToolResult(
                        success=True,
                        data={
                            "eligible": False,
                            "reason": (
                                f"Annual leave ({int(days_requested)} days) requires {notice_desc} advance notice. "
                                f"Earliest allowed start: {min_start.isoformat()}."
                            ),
                            "leave_type_name": leave_type["name_en"],
                        },
                        action_type="data_read",
                    )
            else:
                min_notice = policy.get("min_notice_days", 0) or 0
                if min_notice > 0:
                    earliest_allowed = today + timedelta(days=min_notice)
                    if start_date < earliest_allowed:
                        return ToolResult(
                            success=True,
                            data={
                                "eligible": False,
                                "reason": f"This leave type requires at least {min_notice} days advance notice. Earliest allowed start: {earliest_allowed.isoformat()}.",
                                "leave_type_name": leave_type["name_en"],
                            },
                            action_type="data_read",
                        )

        # 3. Max consecutive days
        max_consec = policy.get("max_consecutive_days") or leave_type.get("max_consecutive_days")
        if max_consec and not is_time_based and days_requested > max_consec:
            return ToolResult(
                success=True,
                data={
                    "eligible": False,
                    "reason": f"This leave type allows a maximum of {max_consec} consecutive days per request. You requested {days_requested:.0f} days.",
                    "leave_type_name": leave_type["name_en"],
                },
                action_type="data_read",
            )

        # 4. Balance check for types that deduct balance
        available_days = None
        if leave_type.get("deducts_balance") and not is_time_based:
            year = (start_date or today).year
            balances = self._ds.get_leave_balance_detail(ctx.tenant_id, employee_code, year)
            bal = next((b for b in balances if b["leave_type_code"] == leave_type_code), None)
            if bal:
                available_days = bal["balance_days"]
                if available_days < days_requested:
                    return ToolResult(
                        success=True,
                        data={
                            "eligible": False,
                            "reason": f"Insufficient balance. Available: {available_days:.1f} days, requested: {days_requested:.0f} days.",
                            "leave_type_name": leave_type["name_en"],
                            "available_days": available_days,
                        },
                        action_type="data_read",
                    )
            elif leave_type_code == "compensatory":
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": "No compensatory days have been earned yet.",
                        "leave_type_name": leave_type["name_en"],
                        "available_days": 0,
                    },
                    action_type="data_read",
                )

        # 5. Overlap check (date-based types only)
        if start_date and end_date and employee.get("id"):
            overlapping = self._ds.check_leave_overlap(
                ctx.tenant_id, employee["id"], input["start_date"], input["end_date"]
            )
            if overlapping:
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": f"You already have an approved or pending leave request that overlaps with {input['start_date']} – {input['end_date']}.",
                        "leave_type_name": leave_type["name_en"],
                    },
                    action_type="data_read",
                )

        # 6. Service minimum (e.g. marriage/umrah: 1 year, hajj: 5 years)
        service_min = leave_type.get("service_min_days", 0) or 0
        if service_min > 0 and employee.get("start_date"):
            hire_date = _parse_date(employee["start_date"])
            service_days = (today - hire_date).days
            if service_days < service_min:
                eligible_from = hire_date + timedelta(days=service_min)
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": (
                            f"{leave_type['name_en']} requires at least {service_min} days of service "
                            f"({service_min // 365} year{'s' if service_min >= 730 else ''}). "
                            f"You have {service_days} days of service. "
                            f"Eligible from {eligible_from.isoformat()}."
                        ),
                        "leave_type_name": leave_type["name_en"],
                    },
                    action_type="data_read",
                )

        # 7. Career usage cap (e.g. marriage=1, hajj=1, umrah=1, maternity=3, paternity=3)
        max_times = leave_type.get("max_times_in_career")
        if max_times is not None and employee.get("id"):
            used_times = self._ds.count_leave_type_usage(
                ctx.tenant_id, employee["id"], leave_type_code
            )
            if used_times >= max_times:
                times_str = "once" if max_times == 1 else f"{max_times} times"
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": (
                            f"{leave_type['name_en']} can only be taken {times_str} during a career. "
                            f"Records show {used_times} prior request(s) already on file."
                        ),
                        "leave_type_name": leave_type["name_en"],
                    },
                    action_type="data_read",
                )

        # 8. WFH weekly/monthly limits
        if leave_type_code == "wfh" and start_date:
            week_start_date = _week_start(start_date)
            wfh_usage = self._ds.get_wfh_usage(
                ctx.tenant_id, employee["id"],
                week_start_date.isoformat(), start_date.month, start_date.year,
            )
            max_week = policy.get("wfh_max_days_per_week")
            max_month = policy.get("wfh_max_days_per_month")
            if max_week and (wfh_usage["days_this_week"] + days_requested) > max_week:
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": f"WFH weekly limit exceeded. Limit: {max_week} days/week, already used this week: {wfh_usage['days_this_week']:.0f} days.",
                        "leave_type_name": leave_type["name_en"],
                    },
                    action_type="data_read",
                )
            if max_month and (wfh_usage["days_this_month"] + days_requested) > max_month:
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": f"WFH monthly limit exceeded. Limit: {max_month} days/month, already used this month: {wfh_usage['days_this_month']:.0f} days.",
                        "leave_type_name": leave_type["name_en"],
                    },
                    action_type="data_read",
                )

        # 9. Casual consecutive limit (annual leave only)
        # WIN policy: casual leave is limited to max 2 consecutive days per request.
        is_casual = bool(input.get("is_casual", False))
        if leave_type_code == "annual" and is_casual and not is_time_based:
            if days_requested > 2:
                return ToolResult(
                    success=True,
                    data={
                        "eligible": False,
                        "reason": (
                            f"Casual leave is limited to a maximum of 2 consecutive days per request. "
                            f"You requested {int(days_requested)} days. "
                            "For longer periods, submit as regular (non-casual) annual leave."
                        ),
                        "leave_type_name": leave_type["name_en"],
                    },
                    action_type="data_read",
                )

        # 10. Carry-over expiry check (annual leave only)
        # WIN policy: carry-over days are only usable in Q1 (by March 31).
        # If today > carry_over_expiry_date, those days are no longer available.
        # This check is advisory — we recompute available_days here if carry-over has expired.
        advisory_flags: list[str] = []
        if leave_type_code == "annual" and available_days is not None:
            # available_days already computed in check #4 using balance_days which includes carry_over.
            # Re-fetch balance row to check expiry.
            year = (start_date or today).year
            balances = self._ds.get_leave_balance_detail(ctx.tenant_id, employee_code, year)
            bal = next((b for b in balances if b["leave_type_code"] == "annual"), None)
            if bal:
                carry_over = float(bal.get("carry_over_days") or 0)
                # carry_over_expiry_date is not in get_leave_balance_detail; check separately if needed.
                # For now, advisory: if we're past March 31 and carry_over > 0, flag it.
                if carry_over > 0 and today.month > 3:
                    # Treat carry-over as expired — subtract from available_days
                    effective_available = available_days - carry_over
                    advisory_flags.append(
                        f"carry_over_expired:{carry_over:.1f}_days"
                    )
                    if effective_available < days_requested:
                        return ToolResult(
                            success=True,
                            data={
                                "eligible": False,
                                "reason": (
                                    f"Your {carry_over:.1f} carry-over days have expired (carry-over is only valid in Q1, by March 31). "
                                    f"Without carry-over, you have {effective_available:.1f} days available but requested {int(days_requested)} days."
                                ),
                                "leave_type_name": leave_type["name_en"],
                                "available_days": effective_available,
                                "expired_carry_over_days": carry_over,
                            },
                            action_type="data_read",
                        )
                    # Enough balance even without carry-over — update available_days for the return value
                    available_days = effective_available

        # 11. First-year / age-50 allocation advisory (annual leave only)
        # WIN policy: 15 days in hire year; 30 days for age ≥50 or ≥10 years SI.
        # This check surfaces advisory info; it does not block (allocation is set at balance creation).
        if leave_type_code == "annual" and not is_time_based and employee.get("start_date"):
            hire_date = _parse_date(employee["start_date"])
            if hire_date.year == today.year:
                # First hiring year — should have 15 days, not 21
                advisory_flags.append("first_hire_year_allocation")
            elif employee.get("id"):
                years_of_service = (today - hire_date).days // 365
                age = self._ds.get_employee_age(ctx.tenant_id, employee["id"])
                if years_of_service >= 10 or (age is not None and age >= 50):
                    # Enhanced allocation: 30 days (23 regular + 7 casual)
                    advisory_flags.append("enhanced_allocation_30_days")

        # All checks passed
        result_data: dict = {
            "eligible": True,
            "leave_type_name": leave_type["name_en"],
            "is_time_based": is_time_based,
        }
        if is_time_based:
            result_data["duration_hours"] = duration_hours
        else:
            result_data["days_requested"] = days_requested
            result_data["available_days"] = available_days
            if available_days is not None:
                result_data["would_leave_days_remaining"] = available_days - days_requested

        if advisory_flags:
            result_data["advisory_flags"] = advisory_flags
            if "first_hire_year_allocation" in advisory_flags:
                result_data["advisory"] = (
                    "You are in your first year of employment. Per WIN policy, "
                    "your annual leave allocation should be 15 days (not 21). "
                    "If your balance shows 21 days, please contact HR to correct the allocation."
                )
            elif "enhanced_allocation_30_days" in advisory_flags:
                result_data["advisory"] = (
                    "You are entitled to 30 days annual leave (23 regular + 7 casual) "
                    "under WIN policy (age ≥50 or ≥10 years of service). "
                    "If your balance shows less than 30 days, please contact HR to update it."
                )

        if is_casual:
            result_data["is_casual"] = True

        # Warn about medical certificate requirement
        cert_after = policy.get("requires_medical_cert_after_days")
        if cert_after and not is_time_based and days_requested > cert_after:
            result_data["warning"] = f"Sick leave over {cert_after} days requires a medical certificate."

        return ToolResult(
            success=True,
            data=result_data,
            data_fields_accessed=["leave_balance", "leave_policy", "employment_start_date"],
            action_type="data_read",
        )


# ─── Tool 3: submit_leave_request ────────────────────────────────────────────

class SubmitLeaveRequestTool(Tool):
    spec = ToolSpec(
        name="submit_leave_request",
        description=(
            "Submit a leave or out-of-office request. "
            "ALWAYS call check_leave_eligibility first — do not submit if eligible=false. "
            "Manager is looked up automatically from the database — do NOT ask the employee who their manager is. "
            "For Permission type: provide start_datetime and end_datetime (e.g. '2026-07-01T14:00:00') or duration_hours. "
            "For all other types: provide start_date and end_date. "
            "Returns the request ID and confirmation details."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "leave_type_code": {
                    "type": "string",
                    "description": "annual, sick, emergency, permission, business_trip, wfh, outside_duty, compensatory, unpaid",
                },
                "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (not required for permission)."},
                "end_date": {"type": "string", "description": "End date YYYY-MM-DD (not required for permission)."},
                "start_datetime": {"type": "string", "description": "Start datetime ISO 8601 for permission type."},
                "end_datetime": {"type": "string", "description": "End datetime ISO 8601 for permission type."},
                "duration_hours": {"type": "number", "description": "Duration in hours for permission type."},
                "reason": {"type": "string", "description": "Optional reason or note."},
                "attachment_path": {"type": "string", "description": "Optional path to an uploaded file (e.g., medical certificate)."},
                "is_casual": {
                    "type": "boolean",
                    "description": "Annual leave only: true = casual leave (max 2 consecutive days, from casual sub-quota). Omit or false for regular.",
                },
            },
            "required": ["leave_type_code"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = ctx.employee_code
        leave_type_code = input.get("leave_type_code", "").lower()

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error="Your employee record was not found.")

        leave_type = self._ds.get_leave_type_by_code(ctx.tenant_id, leave_type_code)
        if not leave_type:
            return ToolResult(success=False, error=f"Leave type '{leave_type_code}' is not available.")

        policy = self._ds.get_leave_policy(ctx.tenant_id, leave_type["id"]) or {}
        is_time_based = leave_type.get("is_time_based", False)

        # Read per-tenant routing policy (deadline hours, top-of-hierarchy behaviour)
        routing_policy = get_routing_policy(ctx.tenant_id, self._ds)

        # Manager lookup — from DB only, never from user input
        manager = self._ds.get_employee_manager(ctx.tenant_id, employee_code)
        # Any role with no manager goes to the top-of-hierarchy path — never crash, never self-approve
        is_top_of_hierarchy = manager is None

        # Prepare request data
        start_date = input.get("start_date")
        end_date = input.get("end_date")
        start_datetime = input.get("start_datetime")
        end_datetime = input.get("end_datetime")
        duration_hours = input.get("duration_hours")
        days_requested: float | None = None

        if is_time_based:
            if start_datetime and end_datetime:
                try:
                    dt_start = datetime.fromisoformat(start_datetime)
                    dt_end = datetime.fromisoformat(end_datetime)
                    diff_hours = (dt_end - dt_start).total_seconds() / 3600
                    duration_hours = round(diff_hours, 1)
                except ValueError:
                    return ToolResult(success=False, error="Invalid datetime format for permission type. Use ISO 8601 (e.g., 2026-07-01T14:00:00).")
            elif not duration_hours:
                return ToolResult(success=False, error="Permission type requires start_datetime + end_datetime or duration_hours.")
            if not start_datetime and not start_date:
                return ToolResult(success=False, error="Provide start_datetime (or start_date) for the permission request.")
        else:
            if not start_date or not end_date:
                return ToolResult(success=False, error="start_date and end_date are required for this leave type.")
            try:
                sd = _parse_date(start_date)
                ed = _parse_date(end_date)
            except ValueError:
                return ToolResult(success=False, error="Invalid date format. Use YYYY-MM-DD.")
            if ed < sd:
                return ToolResult(success=False, error="end_date must be on or after start_date.")
            days_requested = _calendar_days(sd, ed)

        # Re-run eligibility checks (defense in depth)
        elig_input = {
            "employee_code": employee_code,
            "leave_type_code": leave_type_code,
        }
        if is_time_based:
            elig_input["duration_hours"] = duration_hours
        else:
            elig_input["start_date"] = start_date
            elig_input["end_date"] = end_date
        if input.get("is_casual"):
            elig_input["is_casual"] = True

        elig_result = CheckLeaveEligibilityTool(self._ds).execute(elig_input, ctx)
        if elig_result.success and elig_result.data and not elig_result.data.get("eligible", True):
            return ToolResult(
                success=False,
                error=f"Leave request blocked: {elig_result.data.get('reason', 'Eligibility check failed.')}",
            )

        # Compute idempotency key and correlation token
        workflow_id = str(uuid.uuid4())
        idempotency_key = hashlib.sha256(
            f"{workflow_id}:waiting_manager_approval:1".encode()
        ).hexdigest()
        correlation_token = str(uuid.uuid4())

        # Create leave request
        lr_data = {
            "employee_code": employee_code,
            "leave_type_code": leave_type_code,
            "start_date": start_date,
            "end_date": end_date,
            "days_requested": days_requested,
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
            "duration_hours": duration_hours,
            "reason": input.get("reason"),
            "attachment_path": input.get("attachment_path"),
            "manager_id": manager["id"] if manager else None,
            "is_casual": bool(input.get("is_casual", False)),
        }
        leave_request = self._ds.create_leave_request(ctx.tenant_id, lr_data)

        # Create workflow instance
        wf = self._ds.create_workflow_instance(ctx.tenant_id, {
            "workflow_type": "leave_approval",
            "subject_employee_code": employee_code,
            "triggered_by_user_id": ctx.user_id,
            "leave_request_id": leave_request["id"],
            "current_step": "waiting_manager_approval",
            "status": "waiting_human",
            "state_snapshot": {
                "leave_request_id": leave_request["id"],
                "employee_code": employee_code,
                "leave_type_code": leave_type_code,
                "top_of_hierarchy": is_top_of_hierarchy,
            },
        })

        # Compute deadline using per-tenant policy (default 72 hours)
        deadline = datetime.now(timezone.utc) + timedelta(hours=routing_policy.default_deadline_hours)

        # Build approval URLs
        approve_url = f"{config.API_BASE_URL}/api/leave/resolve/{correlation_token}?decision=approved"
        reject_url = f"{config.API_BASE_URL}/api/leave/resolve/{correlation_token}?decision=rejected"

        # Build email content
        if is_time_based:
            duration_desc = f"{duration_hours} hours"
            dates_desc = f"on {(start_datetime or start_date or 'TBD')[:10]} for {duration_desc}"
        else:
            dates_desc = f"from {start_date} to {end_date} ({days_requested:.0f} days)"

        raw_reason = input.get("reason") or ""
        # Wrap for LLM context (pending_actions.prompt_text, context_snapshot) — prevents injection
        safe_reason_for_context = wrap_untrusted_content("LEAVE_REASON", raw_reason) if raw_reason else "Not provided"
        # Escape for HTML email body — prevents XSS in manager's email client
        safe_reason_for_email = sanitize_for_html_email(raw_reason) if raw_reason else "Not provided"

        prompt_text = (
            f"{employee['full_name']} has requested {leave_type['name_en']} {dates_desc}.\n\n"
            f"Reason: {safe_reason_for_context}\n\n"
            f"Approve: {approve_url}\n"
            f"Reject: {reject_url}\n"
        )

        # Top-of-hierarchy path — flag and log; no pending_action, no email
        if is_top_of_hierarchy:
            self._ds.link_leave_request_to_workflow(
                ctx.tenant_id, leave_request["id"], wf["id"]
            )
            self._ds.update_leave_request_status(
                ctx.tenant_id, leave_request["id"], "pending_top_of_hierarchy", {}
            )
            self._ds.create_workflow_event(
                ctx.tenant_id, wf["id"], "top_of_hierarchy_flagged",
                employee["id"], ctx.user_id,
                {"message": "Leave request flagged for board/delegate review — no manager assigned."},
            )
            return ToolResult(
                success=True,
                data={
                    "request_id": leave_request["id"],
                    "leave_type": leave_type["name_en"],
                    "dates": dates_desc,
                    "days_requested": days_requested,
                    "status": "pending_top_of_hierarchy",
                    "message": (
                        "You are at the top of the reporting hierarchy. "
                        "This request has been flagged and logged for board/delegate review."
                    ),
                },
                data_fields_accessed=["employee_id", "manager_id", "leave_balance"],
                action_type="data_write",
                authz_note="top_of_hierarchy_flagged",
            )

        # Normal approval path — manager is not None below here
        # Pre-generate pending_action UUID so we can embed it in the Message-ID header
        pa_id = str(uuid.uuid4())
        outbound_message_id = f"<{pa_id}@{config.EMAIL_MESSAGE_ID_DOMAIN}>"

        # Create pending action
        self._ds.create_pending_action(ctx.tenant_id, {
            "pa_id": pa_id,
            "outbound_message_id": outbound_message_id,
            "workflow_instance_id": wf["id"],
            "action_type": "email_approval",
            "assigned_to_employee_code": manager["employee_code"],
            "assigned_to_email": manager["email"],
            "correlation_token": correlation_token,
            "context_snapshot": {
                "employee_code": employee_code,
                "employee_name": employee["full_name"],
                "leave_type": leave_type_code,
                "dates": dates_desc,
                "reason": safe_reason_for_context,
            },
            "prompt_text": prompt_text,
            "deadline_at": deadline.isoformat(),
            "idempotency_key": idempotency_key,
        })

        # Link workflow to leave request
        self._ds.link_leave_request_to_workflow(
            ctx.tenant_id, leave_request["id"], wf["id"]
        )
        # Send approval email — HTML body built separately to avoid XSS
        email_subject = f"Leave Approval Required: {employee['full_name']} — {leave_type['name_en']}"
        body_html = (
            f"<p>{employee['full_name']} has requested {leave_type['name_en']} {dates_desc}.</p>"
            f"<p>Reason: {safe_reason_for_email}</p>"
            f"<p><a href='{approve_url}'>Approve</a> | <a href='{reject_url}'>Reject</a></p>"
        )
        email_svc.send_email(
            to_email=manager["email"],
            subject=email_subject,
            body_html=body_html,
            body_plain=prompt_text + f"\n\nReply-Token: {outbound_message_id}",
            message_id=outbound_message_id,
        )

        # Warn about medical certificate if sick leave > threshold
        cert_after = policy.get("requires_medical_cert_after_days")
        cert_warning = ""
        if cert_after and days_requested and days_requested > cert_after:
            cert_warning = f" Note: a medical certificate will be required for sick leave exceeding {cert_after} days."

        submission_message = (
            f"Your {leave_type['name_en']} request has been submitted. "
            f"An approval request has been sent to {manager['full_name']} ({manager['email']}). "
            f"Request ID: {leave_request['id']}.{cert_warning}"
        )

        return ToolResult(
            success=True,
            data={
                "request_id": leave_request["id"],
                "leave_type": leave_type["name_en"],
                "dates": dates_desc,
                "days_requested": days_requested,
                "duration_hours": duration_hours,
                "manager_name": manager["full_name"],
                "manager_email": manager["email"],
                "status": "pending_approval",
                "message": submission_message,
            },
            data_fields_accessed=["employee_id", "manager_id", "leave_balance"],
            action_type="data_write",
        )


# ─── Tool 4: get_leave_requests ──────────────────────────────────────────────

class GetLeaveRequestsTool(Tool):
    spec = ToolSpec(
        name="get_leave_requests",
        description=(
            "Retrieve leave requests. Employee role sees only their own requests. "
            "HR roles can optionally filter by employee_code and/or status."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "Filter by employee (HR only — employees always see their own).",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: pending_approval, manager_approved, manager_rejected, hr_approved, hr_rejected, cancelled, withdrawn, completed.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10, max 50).",
                },
            },
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        limit = min(int(input.get("limit") or 10), 50)
        status = input.get("status")

        if ctx.role == "employee":
            employee_code = ctx.employee_code
        else:
            employee_code = input.get("employee_code")

        decision = can_access(ctx, "read_leave_requests", {"employee_code": employee_code})
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        employee = None
        employee_id = None
        if employee_code:
            employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
            if not employee:
                return ToolResult(success=False, error=f"Employee {employee_code} not found.")
            employee_id = employee["id"]
        elif ctx.role == "employee":
            employee = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
            if not employee:
                return ToolResult(success=False, error="Your employee record was not found.")
            employee_id = employee["id"]
        else:
            # HR with no employee_code filter — use get_leave_requests with no filter
            requests = self._ds.get_leave_requests(ctx.tenant_id, None, status)[:limit]
            return ToolResult(
                success=True,
                data={"requests": requests, "count": len(requests)},
                action_type="data_read",
            )

        requests = self._ds.get_leave_requests_for_employee(
            ctx.tenant_id, employee_id, status=status, limit=limit
        )
        return ToolResult(
            success=True,
            data={
                "employee_name": employee["full_name"] if employee else None,
                "requests": requests,
                "count": len(requests),
            },
            data_fields_accessed=["leave_request_status", "leave_type", "dates"],
            action_type="data_read",
        )


# ─── Tool 5: get_pending_approvals ───────────────────────────────────────────

class GetPendingApprovalsTool(Tool):
    spec = ToolSpec(
        name="get_pending_approvals",
        description=(
            "Show all leave requests waiting for your approval as a manager. "
            "Returns requests assigned to the calling manager that are in pending_approval status."
        ),
        input_schema={"type": "object", "properties": {}},
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        manager_employee = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
        if not manager_employee:
            return ToolResult(success=False, error="Your employee record was not found.")

        pending = self._ds.get_pending_approvals_for_manager(
            ctx.tenant_id, manager_employee["id"]
        )
        return ToolResult(
            success=True,
            data={
                "pending_approvals": pending,
                "count": len(pending),
                "message": (
                    f"You have {len(pending)} pending approval{'s' if len(pending) != 1 else ''}."
                    if pending else "No pending approvals at this time."
                ),
            },
            data_fields_accessed=["leave_request_status", "employee_name", "dates"],
            action_type="data_read",
        )


# ─── Tool 6: approve_leave_request ───────────────────────────────────────────

class ApproveLeaveRequestTool(Tool):
    spec = ToolSpec(
        name="approve_leave_request",
        description=(
            "Approve a leave request as a manager. "
            "Use get_pending_approvals first to get the request_id. "
            "Only the assigned manager can approve a request."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The leave request UUID to approve.",
                },
                "comment": {
                    "type": "string",
                    "description": "Optional comment for the employee.",
                },
                "override_reason": {
                    "type": "string",
                    "description": (
                        "Required only when the constraint engine returns requires_override "
                        "(e.g. department cap or balance exceeded). Provide a business justification "
                        "to proceed. Only hr_manager and admin roles may override."
                    ),
                },
            },
            "required": ["request_id"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        request_id = input.get("request_id", "").strip()
        if not request_id:
            return ToolResult(success=False, error="request_id is required.")

        lr = self._ds.get_leave_request_by_id(ctx.tenant_id, request_id)
        if not lr:
            return ToolResult(success=False, error=f"Leave request {request_id} not found.")

        if lr["status"] != "pending_approval":
            return ToolResult(
                success=False,
                error=f"Request cannot be approved — current status is '{lr['status']}'.",
            )

        mgr_employee = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
        decision = can_access(ctx, "approve_leave", {
            "assigned_manager_db_id": lr.get("manager_db_id"),
            "caller_employee_db_id": mgr_employee["id"] if mgr_employee else None,
        })
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        # Constraint engine: evaluate hard rules, soft thresholds, advisory flags
        constraint = evaluate_constraints(
            ctx, "approve_leave", lr, self._ds,
            override_reason=input.get("override_reason"),
        )
        if constraint.verdict == "blocked":
            return ToolResult(success=False, error=constraint.reason)
        if constraint.verdict == "requires_override":
            return ToolResult(
                success=False,
                error=constraint.reason,
                data={"override_reason_required": True, "flags": constraint.flags},
            )
        # Write constraint event (policy_exception / advisory_shown) before state change
        if constraint.event_type and lr.get("workflow_instance_id"):
            self._ds.create_workflow_event(
                ctx.tenant_id,
                lr["workflow_instance_id"],
                constraint.event_type,
                mgr_employee["id"] if mgr_employee else None,
                ctx.user_id,
                constraint.event_data,
            )

        ok = self._ds.update_leave_request_status(
            ctx.tenant_id,
            request_id,
            "manager_approved",
            {"manager_comment": input.get("comment"), "manager_decision_at": "now"},
        )
        if not ok:
            return ToolResult(success=False, error="Failed to update leave request status.")

        # Commit balance: move days from pending → used (mirrors resolve_pending_action email-link path)
        if lr.get("deducts_balance") and lr.get("days_requested") and lr.get("leave_type_id") and lr.get("employee_id"):
            ref_date = lr.get("start_date") or (
                lr.get("start_datetime", "")[:10] if lr.get("start_datetime") else None
            )
            if ref_date:
                year = int(ref_date[:4])
                self._ds.update_leave_balance(
                    ctx.tenant_id,
                    lr["employee_id"],
                    lr["leave_type_id"],
                    year,
                    delta_pending=-float(lr["days_requested"]),
                    delta_used=+float(lr["days_requested"]),
                )

        # Sync workflow state: close pending_action + workflow_instance + write workflow_event
        self._ds.sync_workflow_decision(
            ctx.tenant_id,
            request_id,
            "approved",
            mgr_employee["id"] if mgr_employee else None,
            ctx.user_id,
            input.get("comment"),
        )

        # Notify employee
        employee = self._ds.get_employee_by_code(ctx.tenant_id, lr["employee_code"])
        if employee and employee.get("email"):
            date_info = (
                f"{lr['start_date']} to {lr['end_date']}"
                if lr.get("start_date") else f"{lr.get('duration_hours')} hours"
            )
            email_svc.send_email(
                to_email=employee["email"],
                subject=f"Leave Request Approved — {lr['leave_type_name']}",
                body_html=f"<p>Your {lr['leave_type_name']} request ({date_info}) has been approved by your manager.</p>",
                body_plain=f"Your {lr['leave_type_name']} request ({date_info}) has been approved by your manager.",
            )

        return ToolResult(
            success=True,
            data={
                "request_id": request_id,
                "new_status": "manager_approved",
                "employee_name": lr.get("employee_name"),
                "leave_type": lr.get("leave_type_name"),
                "message": f"Leave request for {lr.get('employee_name')} has been approved.",
            },
            action_type="data_write",
        )


# ─── Tool 7: reject_leave_request ────────────────────────────────────────────

class RejectLeaveRequestTool(Tool):
    spec = ToolSpec(
        name="reject_leave_request",
        description=(
            "Reject a leave request as a manager. A comment (reason) is required. "
            "Only the assigned manager can reject a request."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The leave request UUID to reject.",
                },
                "comment": {
                    "type": "string",
                    "description": "Reason for rejection (required).",
                },
            },
            "required": ["request_id", "comment"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        request_id = input.get("request_id", "").strip()
        comment = input.get("comment", "").strip()
        if not request_id:
            return ToolResult(success=False, error="request_id is required.")
        if not comment:
            return ToolResult(success=False, error="A reason (comment) is required when rejecting a leave request.")

        lr = self._ds.get_leave_request_by_id(ctx.tenant_id, request_id)
        if not lr:
            return ToolResult(success=False, error=f"Leave request {request_id} not found.")

        if lr["status"] != "pending_approval":
            return ToolResult(
                success=False,
                error=f"Request cannot be rejected — current status is '{lr['status']}'.",
            )

        mgr_employee = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
        decision = can_access(ctx, "reject_leave", {
            "assigned_manager_db_id": lr.get("manager_db_id"),
            "caller_employee_db_id": mgr_employee["id"] if mgr_employee else None,
        })
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        # Constraint engine: hard rules (sick+cert blocks rejection) and advisory flags
        constraint = evaluate_constraints(ctx, "reject_leave", lr, self._ds)
        if constraint.verdict == "blocked":
            return ToolResult(success=False, error=constraint.reason)
        # Write advisory event before state change (advisory verdict does not block)
        advisory_flags: list[str] = []
        if constraint.event_type and lr.get("workflow_instance_id"):
            self._ds.create_workflow_event(
                ctx.tenant_id,
                lr["workflow_instance_id"],
                constraint.event_type,
                mgr_employee["id"] if mgr_employee else None,
                ctx.user_id,
                constraint.event_data,
            )
            advisory_flags = constraint.flags

        ok = self._ds.update_leave_request_status(
            ctx.tenant_id,
            request_id,
            "manager_rejected",
            {
                "manager_comment": comment,
                "rejection_reason": comment,
                "manager_decision_at": "now",
            },
        )
        if not ok:
            return ToolResult(success=False, error="Failed to update leave request status.")

        # Release pending balance
        if lr.get("deducts_balance") and lr.get("days_requested") and lr.get("leave_type_id") and lr.get("employee_id"):
            ref_date = lr.get("start_date") or (
                lr.get("start_datetime", "")[:10] if lr.get("start_datetime") else None
            )
            if ref_date:
                year = int(ref_date[:4])
                self._ds.update_leave_balance(
                    ctx.tenant_id,
                    lr["employee_id"],
                    lr["leave_type_id"],
                    year,
                    delta_pending=-float(lr["days_requested"]),
                )

        # Sync workflow state: close pending_action + workflow_instance + write workflow_event
        self._ds.sync_workflow_decision(
            ctx.tenant_id,
            request_id,
            "rejected",
            mgr_employee["id"] if mgr_employee else None,
            ctx.user_id,
            comment,
        )

        # Notify employee
        employee = self._ds.get_employee_by_code(ctx.tenant_id, lr["employee_code"])
        if employee and employee.get("email"):
            date_info = (
                f"{lr['start_date']} to {lr['end_date']}"
                if lr.get("start_date") else f"{lr.get('duration_hours')} hours"
            )
            safe_comment = sanitize_for_html_email(comment)
            email_svc.send_email(
                to_email=employee["email"],
                subject=f"Leave Request Rejected — {lr['leave_type_name']}",
                body_html=f"<p>Your {lr['leave_type_name']} request ({date_info}) was rejected. Reason: {safe_comment}</p>",
                body_plain=f"Your {lr['leave_type_name']} request ({date_info}) was rejected. Reason: {comment}",
            )

        result_data: dict = {
            "request_id": request_id,
            "new_status": "manager_rejected",
            "employee_name": lr.get("employee_name"),
            "message": f"Leave request for {lr.get('employee_name')} has been rejected. The employee has been notified.",
        }
        if advisory_flags:
            result_data["advisory_flags"] = advisory_flags
        return ToolResult(success=True, data=result_data, action_type="data_write")


# ─── Tool 8: cancel_leave_request ────────────────────────────────────────────

class CancelLeaveRequestTool(Tool):
    spec = ToolSpec(
        name="cancel_leave_request",
        description=(
            "Cancel a leave request. Only possible while the request is still pending_approval (not yet decided by manager). "
            "Employees can only cancel their own requests. HR can cancel any pending request."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The leave request UUID to cancel.",
                },
            },
            "required": ["request_id"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        request_id = input.get("request_id", "").strip()
        if not request_id:
            return ToolResult(success=False, error="request_id is required.")

        lr = self._ds.get_leave_request_by_id(ctx.tenant_id, request_id)
        if not lr:
            return ToolResult(success=False, error=f"Leave request {request_id} not found.")

        decision = can_access(ctx, "cancel_leave", {"request_employee_code": lr.get("employee_code")})
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        if lr["status"] != "pending_approval":
            return ToolResult(
                success=False,
                error=f"Request cannot be cancelled — current status is '{lr['status']}'. Only pending_approval requests can be cancelled.",
            )

        ok = self._ds.update_leave_request_status(
            ctx.tenant_id, request_id, "cancelled", {}
        )
        if not ok:
            return ToolResult(success=False, error="Failed to cancel leave request.")

        # Release pending balance
        if lr.get("deducts_balance") and lr.get("days_requested") and lr.get("leave_type_id") and lr.get("employee_id"):
            ref_date = lr.get("start_date") or (
                lr.get("start_datetime", "")[:10] if lr.get("start_datetime") else None
            )
            if ref_date:
                year = int(ref_date[:4])
                self._ds.update_leave_balance(
                    ctx.tenant_id,
                    lr["employee_id"],
                    lr["leave_type_id"],
                    year,
                    delta_pending=-float(lr["days_requested"]),
                )

        return ToolResult(
            success=True,
            data={
                "request_id": request_id,
                "new_status": "cancelled",
                "message": f"Your {lr.get('leave_type_name', 'leave')} request has been cancelled.",
            },
            action_type="data_write",
        )


# ─── Tool 9: get_leave_waiting_status ────────────────────────────────────────

class GetLeaveWaitingStatusTool(Tool):
    spec = ToolSpec(
        name="get_leave_waiting_status",
        description=(
            "Show requests that are currently waiting for a decision. "
            "For employees: shows their own pending requests and how long they've been waiting. "
            "For managers/HR: shows their approval inbox (same as get_pending_approvals but with timing info)."
        ),
        input_schema={"type": "object", "properties": {}},
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        today = _today()

        if ctx.role == "employee":
            employee = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
            if not employee:
                return ToolResult(success=False, error="Your employee record was not found.")
            requests = self._ds.get_leave_requests_for_employee(
                ctx.tenant_id, employee["id"], status="pending_approval", limit=20
            )
            waiting = []
            for r in requests:
                submitted = r.get("submitted_at", "")
                waiting.append({
                    **r,
                    "waiting_since": submitted,
                })
            return ToolResult(
                success=True,
                data={
                    "waiting_requests": waiting,
                    "count": len(waiting),
                    "message": (
                        f"You have {len(waiting)} request{'s' if len(waiting) != 1 else ''} awaiting approval."
                        if waiting else "You have no pending leave requests."
                    ),
                },
                action_type="data_read",
            )
        else:
            # Manager/HR: show their pending approval queue with timing
            mgr_employee = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
            if not mgr_employee:
                return ToolResult(success=False, error="Your employee record was not found.")
            pending = self._ds.get_pending_approvals_for_manager(ctx.tenant_id, mgr_employee["id"])
            # Also include pending_actions with deadline info
            pa_queue = self._ds.get_pending_approvals(ctx.tenant_id, ctx.employee_code)
            return ToolResult(
                success=True,
                data={
                    "pending_approvals": pending,
                    "approval_queue_with_deadlines": pa_queue,
                    "count": len(pending),
                    "message": (
                        f"You have {len(pending)} request{'s' if len(pending) != 1 else ''} waiting for your decision."
                        if pending else "No requests are waiting for your approval."
                    ),
                },
                action_type="data_read",
            )


# ─── Tool 10: add_compensatory_day ────────────────────────────────────────────

class AddCompensatoryDayTool(Tool):
    spec = ToolSpec(
        name="add_compensatory_day",
        description=(
            "Credit one compensatory off day to an employee's annual leave balance "
            "for working on a public holiday or weekend. "
            "WIN policy HR/BTE 001/7-2025: compensatory days require prior manager approval "
            "before the employee works the holiday/weekend. "
            "HR only — employees cannot self-grant compensatory days."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "Employee code of the employee who worked the holiday.",
                },
                "holiday_date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD) of the public holiday or weekend day worked.",
                },
                "approved_by_manager": {
                    "type": "boolean",
                    "description": "Confirm the direct manager pre-approved this holiday work (required: true).",
                },
            },
            "required": ["employee_code", "holiday_date", "approved_by_manager"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = input.get("employee_code", "").strip()
        holiday_date_str = input.get("holiday_date", "").strip()
        approved_by_manager = input.get("approved_by_manager", False)

        if not employee_code:
            return ToolResult(success=False, error="employee_code is required.")
        if not holiday_date_str:
            return ToolResult(success=False, error="holiday_date is required.")
        if not approved_by_manager:
            return ToolResult(
                success=False,
                error=(
                    "Compensatory days require prior manager approval before the employee works the holiday. "
                    "Please confirm approved_by_manager=true."
                ),
            )

        try:
            holiday_date = _parse_date(holiday_date_str)
        except ValueError:
            return ToolResult(success=False, error="Invalid holiday_date format. Use YYYY-MM-DD.")

        # Validate that the date is actually a weekend or public holiday
        holidays = {date.fromisoformat(d) for d in getattr(config, "EGYPT_PUBLIC_HOLIDAYS_2026", [])}
        weekend = set(getattr(config, "EGYPT_WEEKEND_DAYS", [4, 5]))
        if holiday_date.weekday() not in weekend and holiday_date not in holidays:
            return ToolResult(
                success=False,
                error=(
                    f"{holiday_date_str} is not a public holiday or weekend. "
                    "Compensatory days are only granted for working on official holidays (Fri/Sat) "
                    "or days listed in EGYPT_PUBLIC_HOLIDAYS_2026."
                ),
            )

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error=f"Employee {employee_code} not found.")

        result = self._ds.add_compensatory_day(
            tenant_id=ctx.tenant_id,
            employee_id=employee["id"],
            holiday_date=holiday_date_str,
            approved_by_employee_id=employee["id"],  # self-referential fallback; manager lookup above is for audit
        )
        if not result.get("success"):
            return ToolResult(success=False, error=result.get("error", "Failed to credit compensatory day."))

        return ToolResult(
            success=True,
            data={
                "employee_code": employee_code,
                "employee_name": employee["full_name"],
                "holiday_date": holiday_date_str,
                "new_annual_leave_allocated_days": result["new_allocated_days"],
                "message": (
                    f"1 compensatory day has been credited to {employee['full_name']}'s annual leave balance "
                    f"for working on {holiday_date_str}. "
                    f"New annual leave allocation: {result['new_allocated_days']:.1f} days."
                ),
            },
            data_fields_accessed=["leave_balance", "allocated_days"],
            action_type="data_write",
        )
