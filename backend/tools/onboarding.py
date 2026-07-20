from core.access import can_access
from data.base import DataSource
from tools.base import Tool, ToolContext, ToolResult, ToolSpec

_VALID_STEP_STATUSES = {"pending", "in_progress", "completed", "skipped", "blocked"}
_VALID_CATEGORIES = {"documentation", "it_access", "policies", "training", "team_intro", "compliance"}
_VALID_OWNERS = {"hr", "it", "manager", "employee"}
_HR_ROLES = {"hr_staff", "hr_manager", "admin"}


# ─── Tool 1: create_onboarding ────────────────────────────────────────────────

class CreateOnboardingTool(Tool):
    spec = ToolSpec(
        name="create_onboarding",
        description=(
            "Start an onboarding checklist for a newly hired employee. "
            "Instantiates the tenant's default onboarding template (or a specific one if "
            "template_id is supplied) and creates a step-by-step checklist for the employee. "
            "Use this when a new hire joins and needs their onboarding tracked. "
            "Only HR and admin roles can create onboarding cases."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "Employee code of the new hire (e.g. FT-2026-001).",
                },
                "template_id": {
                    "type": "string",
                    "description": (
                        "Optional UUID of a specific onboarding template to use. "
                        "If omitted, the tenant's default template is used."
                    ),
                },
            },
            "required": ["employee_code"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = (input.get("employee_code") or "").strip().upper()
        template_id = (input.get("template_id") or "").strip() or None
        if not employee_code:
            return ToolResult(success=False, error="employee_code is required.")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error=f"Employee {employee_code} not found.")

        try:
            result = self._ds.create_onboarding_case(
                tenant_id=ctx.tenant_id,
                employee_id=employee["id"],
                template_id=template_id,
                created_by_user_id=ctx.user_id,
                employee_start_date=employee.get("start_date"),
            )
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            data={
                "message": (
                    f"Onboarding started for {employee['full_name']} ({employee_code}) "
                    f"using template '{result['template_name']}'. "
                    f"{result['steps_created']} steps created."
                ),
                "case_id": result["case_id"],
                "employee_code": employee_code,
                "employee_name": employee["full_name"],
                "template_name": result["template_name"],
                "steps_created": result["steps_created"],
            },
            data_fields_accessed=["employee_id", "start_date"],
            action_type="data_write",
        )


# ─── Tool 2: get_onboarding_status ───────────────────────────────────────────

class GetOnboardingStatusTool(Tool):
    spec = ToolSpec(
        name="get_onboarding_status",
        description=(
            "Retrieve the onboarding checklist and completion status for an employee. "
            "Returns all steps, their current status, due dates, and an overall progress percentage. "
            "Employees can only view their own onboarding; HR and managers can view any employee's. "
            "Omit employee_code to view your own (employees only)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": (
                        "Employee code to check. HR/managers can supply any code. "
                        "Employees must omit this (or supply their own code)."
                    ),
                },
            },
            "required": [],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = (input.get("employee_code") or "").strip().upper() or ctx.employee_code

        # Row-level access: employees may only view their own case
        decision = can_access(ctx, "read_onboarding", {"employee_code": employee_code})
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error=f"Employee {employee_code} not found.")

        case = self._ds.get_onboarding_case(ctx.tenant_id, employee["id"])
        if case is None:
            return ToolResult(
                success=True,
                data={
                    "employee_code": employee_code,
                    "employee_name": employee["full_name"],
                    "onboarding_started": False,
                    "message": (
                        f"No onboarding case found for {employee['full_name']}. "
                        "Use create_onboarding to start one."
                    ),
                },
                action_type="data_read",
            )

        progress = case["progress"]
        return ToolResult(
            success=True,
            data={
                "employee_code": employee_code,
                "employee_name": employee["full_name"],
                "onboarding_started": True,
                "case_id": case["id"],
                "status": case["status"],
                "template_name": case.get("template_name"),
                "started_at": case["started_at"],
                "completed_at": case.get("completed_at"),
                "progress": progress,
                "steps": case["steps"],
            },
            action_type="data_read",
        )


# ─── Tool 3: update_onboarding_step ──────────────────────────────────────────

class UpdateOnboardingStepTool(Tool):
    spec = ToolSpec(
        name="update_onboarding_step",
        description=(
            "Mark an onboarding step as pending, in_progress, completed, skipped, or blocked. "
            "Employees can only update steps where the owner is 'employee'. "
            "HR, managers, and admins can update any step. "
            "When all required steps are completed or skipped, the case is auto-marked as completed. "
            "Use get_onboarding_status first to get the step IDs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "Employee code whose onboarding step is being updated.",
                },
                "step_id": {
                    "type": "string",
                    "description": "UUID of the onboarding_case_step to update.",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "skipped", "blocked"],
                    "description": "New status for the step.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes or comments about this step (e.g. reason for skip).",
                },
            },
            "required": ["employee_code", "step_id", "status"],
        },
        allowed_roles=["employee", "hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        employee_code = (input.get("employee_code") or "").strip().upper()
        step_id = (input.get("step_id") or "").strip()
        new_status = (input.get("status") or "").strip()
        notes = (input.get("notes") or "").strip() or None

        if not employee_code:
            return ToolResult(success=False, error="employee_code is required.")
        if not step_id:
            return ToolResult(success=False, error="step_id is required.")
        if new_status not in _VALID_STEP_STATUSES:
            return ToolResult(success=False, error=f"status must be one of: {', '.join(sorted(_VALID_STEP_STATUSES))}")

        # Row-level access: employees can only update their own steps
        decision = can_access(ctx, "update_onboarding_step", {"employee_code": employee_code})
        if not decision.allowed:
            return ToolResult(success=False, error=decision.reason)

        employee = self._ds.get_employee_by_code(ctx.tenant_id, employee_code)
        if not employee:
            return ToolResult(success=False, error=f"Employee {employee_code} not found.")

        # For employees, verify the step's owner field allows self-service
        if ctx.role == "employee":
            case = self._ds.get_onboarding_case(ctx.tenant_id, employee["id"])
            if case is None:
                return ToolResult(success=False, error="No onboarding case found for this employee.")
            target_step = next((s for s in case["steps"] if s["id"] == step_id), None)
            if target_step is None:
                return ToolResult(success=False, error=f"Step {step_id} not found in your onboarding case.")
            if target_step["owner"] != "employee":
                return ToolResult(
                    success=False,
                    error=(
                        f"You are not permitted to update step '{target_step['title']}' "
                        f"(owner: {target_step['owner']}). Only HR, IT, or your manager can update it."
                    ),
                )

        try:
            result = self._ds.update_onboarding_step(
                tenant_id=ctx.tenant_id,
                step_id=step_id,
                new_status=new_status,
                completed_by_user_id=ctx.user_id,
                notes=notes,
            )
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        msg = f"Step updated to '{new_status}'."
        if result["case_auto_completed"]:
            msg += f" All required steps complete — onboarding for {employee['full_name']} is now marked as completed."

        return ToolResult(
            success=True,
            data={
                "message": msg,
                "step_id": result["step_id"],
                "new_status": result["new_status"],
                "case_id": result["case_id"],
                "case_auto_completed": result["case_auto_completed"],
                "employee_code": employee_code,
                "employee_name": employee["full_name"],
            },
            action_type="data_write",
        )


# ─── Tool 4: customize_onboarding_template ───────────────────────────────────

class CustomizeOnboardingTemplateTool(Tool):
    spec = ToolSpec(
        name="customize_onboarding_template",
        description=(
            "Create a new onboarding template or replace the steps of an existing one. "
            "Supply template_id to edit an existing template's steps. "
            "Omit template_id to create a brand-new template. "
            "Set set_as_default=true to make this the template used when no template_id "
            "is specified in create_onboarding. "
            "Only HR managers and admins can customise templates."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the template (e.g. 'Engineering Onboarding Q3 2026').",
                },
                "description": {
                    "type": "string",
                    "description": "Optional description of what this template covers.",
                },
                "template_id": {
                    "type": "string",
                    "description": "UUID of an existing template to update. Omit to create a new one.",
                },
                "set_as_default": {
                    "type": "boolean",
                    "description": "If true, this template becomes the default for new onboardings.",
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered list of onboarding steps for the template.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Short title for the step."},
                            "description": {"type": "string", "description": "Detailed explanation of what needs to be done."},
                            "category": {
                                "type": "string",
                                "enum": ["documentation", "it_access", "policies", "training", "team_intro", "compliance"],
                                "description": "Category of the step.",
                            },
                            "owner": {
                                "type": "string",
                                "enum": ["hr", "it", "manager", "employee"],
                                "description": "Who is responsible for completing this step.",
                            },
                            "due_offset_days": {
                                "type": "integer",
                                "description": "Days from the employee's start date by which this step should be done.",
                            },
                            "is_required": {
                                "type": "boolean",
                                "description": "Whether this step must be completed/skipped before the case closes.",
                            },
                        },
                        "required": ["title", "category", "owner"],
                    },
                },
            },
            "required": ["name", "steps"],
        },
        allowed_roles=["hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        name = (input.get("name") or "").strip()
        description = (input.get("description") or "").strip() or None
        template_id = (input.get("template_id") or "").strip() or None
        set_as_default = bool(input.get("set_as_default", False))
        steps = input.get("steps") or []

        if not name:
            return ToolResult(success=False, error="name is required.")
        if not steps:
            return ToolResult(success=False, error="At least one step is required.")

        # Validate each step
        for i, step in enumerate(steps):
            if not step.get("title"):
                return ToolResult(success=False, error=f"Step {i + 1} is missing a title.")
            if step.get("category") and step["category"] not in _VALID_CATEGORIES:
                return ToolResult(success=False, error=f"Step {i + 1} has invalid category '{step['category']}'.")
            if step.get("owner") and step["owner"] not in _VALID_OWNERS:
                return ToolResult(success=False, error=f"Step {i + 1} has invalid owner '{step['owner']}'.")

        try:
            result = self._ds.upsert_onboarding_template(
                tenant_id=ctx.tenant_id,
                name=name,
                description=description,
                steps=steps,
                set_as_default=set_as_default,
                created_by_user_id=ctx.user_id,
                template_id=template_id,
            )
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        action = "updated" if template_id else "created"
        return ToolResult(
            success=True,
            data={
                "message": (
                    f"Onboarding template '{result['name']}' {action} successfully "
                    f"with {result['steps_count']} steps."
                    + (" This is now the default template." if result["is_default"] else "")
                ),
                "template_id": result["template_id"],
                "name": result["name"],
                "steps_count": result["steps_count"],
                "is_default": result["is_default"],
            },
            action_type="data_write",
        )
