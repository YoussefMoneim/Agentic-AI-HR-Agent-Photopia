from data.base import DataSource
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


class GetTeamCalendarTool(Tool):
    """Retrieve team leave calendar for a given month, scoped by caller role."""

    spec = ToolSpec(
        name="get_team_calendar",
        description=(
            "Get team leave calendar showing who is on leave and team availability for a month. "
            "Employee role: own leave events + anonymous team counts (no colleague names). "
            "Manager role: direct reports' leave events with names and leave types. "
            "HR role: all employees, optionally filterable by department. "
            "Use when asked 'who is off next week', 'is it a good time to take leave', "
            "or before approving a leave request to surface availability context."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "Year (e.g. 2026). Defaults to current year if omitted.",
                },
                "month": {
                    "type": "integer",
                    "description": "Month number 1–12. Defaults to current month if omitted.",
                },
                "department": {
                    "type": "string",
                    "description": "Filter by department name. HR/admin only — silently ignored for other roles.",
                },
            },
            "required": [],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        from datetime import date
        today = date.today()
        year  = int(input.get("year")  or today.year)
        month = int(input.get("month") or today.month)
        department = input.get("department")

        if not (1 <= month <= 12):
            return ToolResult(success=False, error="month must be between 1 and 12.")
        if not (2020 <= year <= 2030):
            return ToolResult(success=False, error="year must be between 2020 and 2030.")

        # Department filter is HR/admin only — silently drop for other roles
        if ctx.role not in ("hr_staff", "hr_manager", "admin"):
            department = None

        emp = self._ds.get_employee_by_code(ctx.tenant_id, ctx.employee_code)
        caller_employee_id = str(emp["id"]) if emp else None

        result = self._ds.get_team_calendar(
            tenant_id=ctx.tenant_id,
            caller_role=ctx.role,
            caller_employee_id=caller_employee_id,
            year=year,
            month=month,
            department=department,
        )

        days_over = [d for d, s in result["daily_summary"].items() if s["over_threshold"]]
        result["agent_summary"] = (
            f"Calendar for {year}-{month:02d}: "
            f"{result['total_employees_in_scope']} employees in scope. "
            + (
                f"{len(days_over)} day(s) exceed the 25% concurrent absence threshold."
                if days_over
                else "No days exceed the 25% threshold."
            )
        )

        return ToolResult(success=True, data=result, action_type="data_read")
