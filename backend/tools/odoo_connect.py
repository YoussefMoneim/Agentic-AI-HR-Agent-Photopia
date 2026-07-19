from __future__ import annotations
from connectors.odoo_adapter import test_and_summarize_connection
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


class ConnectOdooTool(Tool):
    """Onboarding step 2 — verify Odoo connectivity.

    Calls the odoo_adapter boundary only, never OdooClient directly, so the
    eventual swap to an MCP-standard connector doesn't require touching this
    tool's contract."""

    spec = ToolSpec(
        name="connect_odoo",
        description=(
            "Test the configured Odoo connection during agent onboarding. "
            "Never accepts credentials as input — Odoo is configured via "
            "environment variables, never via chat."
        ),
        input_schema={"type": "object", "properties": {}},
        allowed_roles=["hr_manager", "admin"],
        llm_visible=False,  # only agent/onboarding.py calls this, via direct execute()
    )

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        result = test_and_summarize_connection()

        if not result["connected"]:
            return ToolResult(
                success=False,
                error=result["error"] or "Could not connect to Odoo.",
            )

        return ToolResult(
            success=True,
            data={"employee_count": result["employee_count"]},
            action_type="data_read",
        )
