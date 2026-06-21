import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone

import config
from data.base import DataSource
from services import email as email_svc
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


def _today() -> date:
    return date.today()


def _parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def _calendar_days(start: date, end: date) -> float:
    return float((end - start).days + 1)


def _months_employed(start_date: date, reference_date: date) -> int:
    return (reference_date.year - start_date.year) * 12 + (reference_date.month - start_date.month)


def _week_start(d: date) -> date:
    """Return the Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


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
        if ctx.role == "employee" and employee_code != ctx.employee_code:
            return ToolResult(success=False, error="You can only check your own leave balance.")

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
            },
            "required": ["leave_type_code"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = input.get("employee_code") or ctx.employee_code
        if ctx.role == "employee" and employee_code != ctx.employee_code:
            return ToolResult(success=False, error="You can only check your own eligibility.")

        leave_type_code = input.get("leave_type_code", "").lower()

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error=f"Employee {employee_code} not found.")

        leave_type = self._ds.get_leave_type_by_code(ctx.tenant_id, leave_type_code)
        if not leave_type:
            return ToolResult(
                success=False,
                error=f"Leave type '{leave_type_code}' is not available. Valid types: annual, sick, emergency, permission, business_trip, wfh, outside_duty, compensatory, unpaid.",
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

        # 2. Min notice days
        min_notice = policy.get("min_notice_days", 0) or 0
        if min_notice > 0 and start_date:
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

        # 6. WFH weekly/monthly limits
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

        # Manager lookup — from DB only, never from user input
        manager = self._ds.get_employee_manager(ctx.tenant_id, employee_code)
        if not manager:
            return ToolResult(
                success=False,
                error="No manager is assigned to your employee record. Please contact HR to update your profile before submitting leave requests.",
            )

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
            "manager_id": manager["id"],
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
            },
        })

        # Compute deadline (72 hours from now)
        deadline = datetime.now(timezone.utc) + timedelta(hours=72)

        # Build approval URLs
        approve_url = f"{config.API_BASE_URL}/api/leave/resolve/{correlation_token}?decision=approved"
        reject_url = f"{config.API_BASE_URL}/api/leave/resolve/{correlation_token}?decision=rejected"

        # Build email content
        if is_time_based:
            duration_desc = f"{duration_hours} hours"
            dates_desc = f"on {(start_datetime or start_date or 'TBD')[:10]} for {duration_desc}"
        else:
            dates_desc = f"from {start_date} to {end_date} ({days_requested:.0f} days)"

        prompt_text = (
            f"{employee['full_name']} has requested {leave_type['name_en']} {dates_desc}.\n\n"
            f"Reason: {input.get('reason') or 'Not provided'}\n\n"
            f"Approve: {approve_url}\n"
            f"Reject: {reject_url}\n"
        )

        # Create pending action
        self._ds.create_pending_action(ctx.tenant_id, {
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
            },
            "prompt_text": prompt_text,
            "deadline_at": deadline.isoformat(),
            "idempotency_key": idempotency_key,
        })

        # Link workflow to leave request
        self._ds.link_leave_request_to_workflow(
            ctx.tenant_id, leave_request["id"], wf["id"]
        )

        # Send approval email to manager
        email_svc.send_email(
            to_email=manager["email"],
            subject=f"Leave Approval Required: {employee['full_name']} — {leave_type['name_en']}",
            body_html=(
                f"<p>{prompt_text.replace(chr(10), '<br>')}</p>"
            ),
            body_plain=prompt_text,
        )

        # Warn about medical certificate if sick leave > threshold
        cert_after = policy.get("requires_medical_cert_after_days")
        cert_warning = ""
        if cert_after and days_requested and days_requested > cert_after:
            cert_warning = f" Note: a medical certificate will be required for sick leave exceeding {cert_after} days."

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
                "message": (
                    f"Your {leave_type['name_en']} request has been submitted. "
                    f"An approval request has been sent to {manager['full_name']} ({manager['email']}). "
                    f"Request ID: {leave_request['id']}.{cert_warning}"
                ),
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

        # Verify this manager is the assigned approver
        mgr_employee = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
        if mgr_employee and lr.get("manager_db_id") and lr["manager_db_id"] != mgr_employee["id"]:
            return ToolResult(
                success=False,
                error="You are not the assigned approver for this request.",
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
        if mgr_employee and lr.get("manager_db_id") and lr["manager_db_id"] != mgr_employee["id"]:
            return ToolResult(
                success=False,
                error="You are not the assigned approver for this request.",
            )

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

        # Notify employee
        employee = self._ds.get_employee_by_code(ctx.tenant_id, lr["employee_code"])
        if employee and employee.get("email"):
            date_info = (
                f"{lr['start_date']} to {lr['end_date']}"
                if lr.get("start_date") else f"{lr.get('duration_hours')} hours"
            )
            email_svc.send_email(
                to_email=employee["email"],
                subject=f"Leave Request Rejected — {lr['leave_type_name']}",
                body_html=f"<p>Your {lr['leave_type_name']} request ({date_info}) was rejected. Reason: {comment}</p>",
                body_plain=f"Your {lr['leave_type_name']} request ({date_info}) was rejected. Reason: {comment}",
            )

        return ToolResult(
            success=True,
            data={
                "request_id": request_id,
                "new_status": "manager_rejected",
                "employee_name": lr.get("employee_name"),
                "message": f"Leave request for {lr.get('employee_name')} has been rejected. The employee has been notified.",
            },
            action_type="data_write",
        )


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

        # Row-level check: employee can only cancel own requests
        if ctx.role == "employee" and lr.get("employee_code") != ctx.employee_code:
            return ToolResult(success=False, error="You can only cancel your own leave requests.")

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
