from __future__ import annotations

from typing import TYPE_CHECKING

from tools.base import Tool, ToolContext, ToolResult, ToolSpec

if TYPE_CHECKING:
    from data.base import DataSource


class CreateEmployeeRecordTool(Tool):
    """
    HITL-gated write tool. First call (confirmed=False) returns a preview
    for the HR manager to review. Second call (confirmed=True) executes the insert.

    Rule 12: role is ALWAYS hardcoded to 'employee' server-side — never LLM-supplied.
    Rule 15: requires hr_manager or admin — hr_staff cannot create records.
    """

    def __init__(self, data_source: "DataSource") -> None:
        self._ds = data_source

    spec = ToolSpec(
        name="create_employee_record",
        description=(
            "Create a new employee record in the HR system. "
            "Call once without confirmed=true to preview the record. "
            "Call again with confirmed=true to save it. "
            "Required fields: full_name, position, department, employment_type, "
            "start_date (YYYY-MM-DD), email, basic_salary. "
            "Optional: arabic_name, notification_email, housing_allowance, "
            "transport_allowance, manager_code, birth_date (YYYY-MM-DD)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "full_name": {"type": "string", "description": "Employee's full name in English"},
                "arabic_name": {"type": "string", "description": "Employee's full name in Arabic (optional)"},
                "position": {"type": "string", "description": "Job title / position"},
                "department": {"type": "string", "description": "Department name"},
                "employment_type": {
                    "type": "string",
                    "enum": ["Full-Time", "Part-Time", "Contract", "Intern"],
                    "description": "Employment type",
                },
                "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                "email": {"type": "string", "description": "Company email address"},
                "notification_email": {"type": "string", "description": "Personal email for notifications (optional)"},
                "basic_salary": {"type": "number", "description": "Basic monthly salary in EGP"},
                "housing_allowance": {"type": "number", "description": "Monthly housing allowance in EGP (default 0)"},
                "transport_allowance": {"type": "number", "description": "Monthly transport allowance in EGP (default 0)"},
                "manager_code": {"type": "string", "description": "Employee code of the direct manager (optional)"},
                "birth_date": {"type": "string", "description": "Date of birth in YYYY-MM-DD format (optional)"},
                "confirmed": {
                    "type": "boolean",
                    "description": "Set to true to confirm and save the record. Omit or set false to preview first.",
                },
            },
            "required": ["full_name", "position", "department", "employment_type", "start_date", "email", "basic_salary"],
        },
        allowed_roles=["hr_manager", "admin"],
    )

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        full_name = input.get("full_name", "").strip()
        arabic_name = input.get("arabic_name")
        position = input.get("position", "").strip()
        department = input.get("department", "").strip()
        employment_type = input.get("employment_type", "Full-Time")
        start_date = input.get("start_date", "").strip()
        email = input.get("email", "").strip()
        notification_email = input.get("notification_email")
        basic_salary = float(input.get("basic_salary", 0))
        housing_allowance = float(input.get("housing_allowance", 0))
        transport_allowance = float(input.get("transport_allowance", 0))
        manager_code = input.get("manager_code")
        birth_date = input.get("birth_date")
        confirmed = input.get("confirmed", False)

        # Basic validation
        if not full_name:
            return ToolResult(success=False, error="full_name is required.")
        if not email or "@" not in email:
            return ToolResult(success=False, error="A valid email address is required.")
        if basic_salary <= 0:
            return ToolResult(success=False, error="basic_salary must be greater than 0.")
        try:
            year = int(start_date[:4])
            if year < 2000 or year > 2100:
                raise ValueError
        except (ValueError, IndexError):
            return ToolResult(success=False, error="start_date must be in YYYY-MM-DD format.")

        total_salary = basic_salary + housing_allowance + transport_allowance

        # Preview mode — return what WILL be created, ask for confirmation
        if not confirmed:
            preview = {
                "full_name": full_name,
                "arabic_name": arabic_name,
                "position": position,
                "department": department,
                "employment_type": employment_type,
                "start_date": start_date,
                "email": email,
                "notification_email": notification_email,
                "basic_salary_egp": basic_salary,
                "housing_allowance_egp": housing_allowance,
                "transport_allowance_egp": transport_allowance,
                "total_salary_egp": total_salary,
                "manager_code": manager_code,
                "birth_date": birth_date,
                "role": "employee",  # always — never LLM-supplied
                "annual_leave_balance_days": 21,
            }
            return ToolResult(
                success=True,
                data={
                    "status": "pending_confirmation",
                    "message": (
                        "Please review the employee record below and confirm by calling "
                        "this tool again with confirmed=true to save it to the system."
                    ),
                    "preview": preview,
                },
                action_type="preview",
                authz_note="preview_only",
            )

        # Confirmed — execute the write
        try:
            employee = self._ds.create_employee_record(
                tenant_id=ctx.tenant_id,
                full_name=full_name,
                arabic_name=arabic_name,
                position=position,
                department=department,
                employment_type=employment_type,
                start_date=start_date,
                email=email,
                notification_email=notification_email,
                basic_salary=basic_salary,
                housing_allowance=housing_allowance,
                transport_allowance=transport_allowance,
                manager_code=manager_code,
                birth_date=birth_date,
                created_by_user_id=ctx.user_id,
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to create employee record: {exc}")

        return ToolResult(
            success=True,
            data={
                "message": f"Employee record created successfully.",
                "employee": employee,
                "next_step": (
                    f"You can now start onboarding for {full_name} using their "
                    f"employee code {employee['employee_code']}."
                ),
            },
            action_type="create_employee_record",
            authz_note=f"confirmed_by:{ctx.user_id}",
        )
