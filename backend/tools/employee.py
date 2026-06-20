from datetime import date

from data.base import DataSource
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


class SearchEmployeesTool(Tool):
    spec = ToolSpec(
        name="search_employees",
        description=(
            "Search for employees by name. Returns a list of matching employees with their "
            "employee_code, name, position, and department. Use this first to find an employee "
            "before requesting their full data or generating documents."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Full or partial name of the employee to search for.",
                }
            },
            "required": ["name"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        name = input.get("name", "").strip()
        if not name:
            return ToolResult(success=False, error="name is required")

        matches = self._ds.find_employees_by_name(ctx.tenant_id, name)
        if not matches:
            return ToolResult(success=True, data={"employees": [], "message": f"No employees found matching '{name}'"}, action_type="data_read")

        return ToolResult(success=True, data={"employees": matches, "count": len(matches)}, action_type="data_read")


class ListEmployeesTool(Tool):
    spec = ToolSpec(
        name="list_employees",
        description=(
            "List employees, optionally filtered by department. "
            "Returns employee_code, name, position, department, employment type, email, and manager for each. "
            "Use when the user asks to see all employees or everyone in a specific department "
            "(e.g. 'list all employees', 'show me the R&D team'). "
            "Omit department to list everyone. Do not pass department='all' or similar — just omit it. "
            "Does not include salary fields; use get_employee_data for full financial details."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": (
                        "Name of the department to filter by, e.g. 'R&D', 'HR', 'Finance'. "
                        "Case-insensitive. Omit entirely to list all employees."
                    ),
                }
            },
            "required": [],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        department = (input.get("department") or "").strip() or None

        rows = self._ds.list_employees(ctx.tenant_id, department)

        truncated = len(rows) > 200
        employees = rows[:200]

        if not employees:
            msg = (
                f"No employees found in the '{department}' department."
                if department
                else "No employees found."
            )
            return ToolResult(success=True, data={"employees": [], "count": 0, "message": msg}, action_type="data_read")

        return ToolResult(
            success=True,
            data={
                "employees": employees,
                "count": len(employees),
                "truncated": truncated,
            },
            action_type="data_read",
        )


class GetEmployeeDataTool(Tool):
    spec = ToolSpec(
        name="get_employee_data",
        description=(
            "Retrieve full details for a single employee by their employee_code. "
            "Includes salary, department, start date, and contact info. "
            "HR roles may access any employee. Employees may only access their own record."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The unique employee code (e.g. EMP001) obtained from search_employees.",
                }
            },
            "required": ["employee_code"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin", "employee"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        # Row-level security: HR sees any record, employees only see their own
        if ctx.role == "employee" and code != ctx.employee_code:
            return ToolResult(success=False, error="Access denied: you may only view your own record")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, code)
        if employee is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        return ToolResult(success=True, data={"employee": employee}, action_type="data_read")


class GetLeaveBalanceTool(Tool):
    spec = ToolSpec(
        name="get_leave_balance",
        description=(
            "Get the current annual leave balance (remaining days) for an employee. "
            "HR roles may check any employee. Employees may only check their own balance."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The unique employee code (e.g. EMP001).",
                }
            },
            "required": ["employee_code"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin", "employee"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        # Row-level security: HR sees any record, employees only see their own
        if ctx.role == "employee" and code != ctx.employee_code:
            return ToolResult(success=False, error="Access denied: you may only check your own leave balance")

        balance = self._ds.get_leave_balance(ctx.tenant_id, code)
        if balance is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        return ToolResult(success=True, data={"employee_code": code, "annual_leave_balance": balance}, action_type="data_read")


class GetEmployeeSummaryTool(Tool):
    spec = ToolSpec(
        name="get_employee_summary",
        description=(
            "Get a rich summary of an employee in one call: full record, leave balance, "
            "and calculated years of service. Use when the user asks for a full profile or "
            "'everything about' an employee. HR roles may access any employee; "
            "employees may only access their own record."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The unique employee code (e.g. EMP001).",
                }
            },
            "required": ["employee_code"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        # Row-level security: HR sees any record, employees only see their own
        if ctx.role == "employee" and code != ctx.employee_code:
            return ToolResult(success=False, error="Access denied: you may only view your own record")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, code)
        if employee is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        balance = self._ds.get_leave_balance(ctx.tenant_id, code)

        years_of_service = 0.0
        start_raw = employee.get("start_date", "")
        if start_raw:
            try:
                start = date.fromisoformat(start_raw)
                years_of_service = round((date.today() - start).days / 365.25, 2)  # 365.25 accounts for leap years
            except ValueError:
                pass

        summary = {
            **employee,
            "annual_leave_balance": balance,
            "years_of_service": years_of_service,
        }
        return ToolResult(success=True, data={"employee": summary}, action_type="data_read")


class GetEmployeeDocumentsTool(Tool):
    spec = ToolSpec(
        name="get_employee_documents",
        description=(
            "List all documents previously generated for an employee: salary certificates, "
            "employment letters, and experience certificates. Returns document type, issue date, "
            "document_id, and outcome for each entry. "
            "HR roles may see documents for any employee; employees may only see their own."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The unique employee code (e.g. EMP001).",
                }
            },
            "required": ["employee_code"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        # Row-level security: HR sees any record, employees only see their own
        if ctx.role == "employee" and code != ctx.employee_code:
            return ToolResult(success=False, error="Access denied: you may only view your own documents")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, code)
        if employee is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        rows = self._ds.get_employee_document_history(ctx.tenant_id, code)

        _type_labels = {
            "generate_salary_certificate": "Salary Certificate",
            "generate_twimc_letter": "Employment Letter (TWIMC)",
            "generate_experience_certificate": "Experience Certificate",
        }

        documents = []
        for row in rows:
            # audit_log stores result_summary as "document_id=<uuid>" for doc tools
            doc_id = None
            summary = row.get("result_summary", "") or ""
            if summary.startswith("document_id="):
                doc_id = summary.split("=", 1)[1]
            documents.append({
                "document_type": _type_labels.get(row["tool_name"], row["tool_name"]),
                "issue_date": row.get("created_at", ""),
                "document_id": doc_id,
                "outcome": row.get("outcome", ""),
            })

        return ToolResult(
            success=True,
            data={
                "employee_code": code,
                "employee_name": employee["full_name"],
                "documents": documents,
                "count": len(documents),
            },
            action_type="data_read",
        )


class CalculateEndOfServiceTool(Tool):
    spec = ToolSpec(
        name="calculate_end_of_service",
        description=(
            "Calculate the end-of-service gratuity an employee is entitled to under Egyptian Labor Law. "
            "The calculation is deterministic — it is never delegated to the LLM. "
            "Returns years of service, gratuity amount, and a step-by-step breakdown for HR verification. "
            "This tool does NOT generate a document and does NOT write anything."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The unique employee code (e.g. EMP001).",
                },
                "last_working_day": {
                    "type": "string",
                    "description": "The employee's last working day as ISO date (YYYY-MM-DD). Required.",
                },
                "resignation_type": {
                    "type": "string",
                    "enum": ["voluntary", "termination"],
                    "description": "Whether the employee resigned voluntarily or was terminated. Defaults to 'voluntary'.",
                },
            },
            "required": ["employee_code", "last_working_day"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        lwd_raw = input.get("last_working_day", "").strip()
        if not lwd_raw:
            return ToolResult(success=False, error="last_working_day is required")
        try:
            last_working_day = date.fromisoformat(lwd_raw)
        except ValueError:
            return ToolResult(success=False, error=f"Invalid last_working_day '{lwd_raw}'. Use YYYY-MM-DD format.")

        resignation_type = input.get("resignation_type", "voluntary").strip().lower()
        if resignation_type not in ("voluntary", "termination"):
            return ToolResult(success=False, error="resignation_type must be 'voluntary' or 'termination'")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, code)
        if employee is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        start_raw = employee.get("start_date", "")
        if not start_raw:
            return ToolResult(success=False, error=f"Employee '{code}' has no start_date on record")
        try:
            start_date = date.fromisoformat(start_raw)
        except ValueError:
            return ToolResult(success=False, error=f"Employee '{code}' has an invalid start_date '{start_raw}'")

        if last_working_day < start_date:
            return ToolResult(success=False, error="last_working_day cannot be before start_date")

        basic_salary = float(employee.get("basic_salary") or 0)
        currency = employee.get("currency", "EGP")
        years = (last_working_day - start_date).days / 365.25  # 365.25 for leap year accuracy
        years_rounded = round(years, 4)

        breakdown_lines = [
            f"Start date:        {start_date.isoformat()}",
            f"Last working day:  {last_working_day.isoformat()}",
            f"Years of service:  {years_rounded:.4f} years",
            f"Basic salary:      {basic_salary:,.2f} {currency}",
        ]

        # Egyptian Labor Law: < 1yr = nothing, 1-5yrs = 0.5 months/yr, > 5yrs = 1 month/yr
        if years < 1:
            gross_gratuity = 0.0
            breakdown_lines.append("Bracket: < 1 year → no gratuity entitlement")
        elif years <= 5:
            gross_gratuity = basic_salary * 0.5 * years
            breakdown_lines.append(
                f"Bracket: 1–5 years → ½ month per year: "
                f"0.5 × {basic_salary:,.2f} × {years_rounded:.4f} = {gross_gratuity:,.2f} {currency}"
            )
        else:
            gross_gratuity = basic_salary * 1.0 * years
            breakdown_lines.append(
                f"Bracket: > 5 years → 1 month per year: "
                f"1.0 × {basic_salary:,.2f} × {years_rounded:.4f} = {gross_gratuity:,.2f} {currency}"
            )

        # Voluntary resignation < 10 years gets 50% reduction; termination always full
        if resignation_type == "voluntary" and years < 1:
            final_gratuity = 0.0
            breakdown_lines.append("Resignation type: voluntary, < 1 year → no gratuity")
        elif resignation_type == "voluntary" and years < 10:
            final_gratuity = gross_gratuity * 0.5
            breakdown_lines.append(
                f"Resignation type: voluntary, years < 10 → 50% reduction: "
                f"{gross_gratuity:,.2f} × 0.5 = {final_gratuity:,.2f} {currency}"
            )
        else:
            final_gratuity = gross_gratuity
            if resignation_type == "voluntary":
                breakdown_lines.append("Resignation type: voluntary, years ≥ 10 → full gratuity (no reduction)")
            else:
                breakdown_lines.append("Resignation type: termination → full gratuity (no reduction)")

        breakdown_lines.append(f"FINAL GRATUITY: {final_gratuity:,.2f} {currency}")

        return ToolResult(
            success=True,
            data={
                "employee_code": code,
                "employee_name": employee["full_name"],
                "start_date": start_raw,
                "last_working_day": lwd_raw,
                "years_of_service": round(years, 2),
                "basic_salary": basic_salary,
                "currency": currency,
                "resignation_type": resignation_type,
                "gratuity_amount": round(final_gratuity, 2),
                "calculation_breakdown": "\n".join(breakdown_lines),
            },
            action_type="data_read",
        )
