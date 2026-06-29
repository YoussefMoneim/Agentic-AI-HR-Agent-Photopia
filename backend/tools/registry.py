import time
from typing import TYPE_CHECKING

from audit.logger import AuditLogger
from tools.base import Tool, ToolContext, ToolResult

if TYPE_CHECKING:
    from data.base import DataSource


class ToolRegistry:
    def __init__(self, tools: list[Tool], audit_logger: AuditLogger) -> None:
        self._tools: dict[str, Tool] = {t.spec.name: t for t in tools}
        self._audit = audit_logger

    def get_specs_for_role(self, role: str) -> list[dict]:
        # Policy before prompt: filter BEFORE sending to the LLM so it never
        # even knows about tools it can't call — can't be tricked into requesting them.
        return [
            t.spec.to_claude_format()
            for t in self._tools.values()
            if role in t.spec.allowed_roles
        ]

    def execute(self, tool_name: str, tool_input: dict, ctx: ToolContext) -> ToolResult:
        """Single audited execution path. Every tool call passes through here."""
        start = time.monotonic()
        authz_decision = "allowed"

        # Security layer 1: does the tool exist?
        tool = self._tools.get(tool_name)
        if tool is None:
            result = ToolResult(success=False, error=f"Unknown tool: {tool_name}")
            authz_decision = "unknown_tool"
            self._audit.log(ctx, tool_name, tool_input, result, authz_decision, 0)
            return result

        # Security layer 2: is this role allowed to call it?
        # Second check after get_specs_for_role — defence in depth.
        if ctx.role not in tool.spec.allowed_roles:
            result = ToolResult(success=False, error=f"Role '{ctx.role}' is not permitted to call '{tool_name}'")
            authz_decision = "denied"
            latency_ms = int((time.monotonic() - start) * 1000)
            self._audit.log(ctx, tool_name, tool_input, result, authz_decision, latency_ms)
            return result

        # Security layer 3: tool executes; may do its own row-level checks inside
        try:
            result = tool.execute(tool_input, ctx)
        except Exception as exc:
            result = ToolResult(success=False, error=f"Tool raised an exception: {exc}")

        # Security layer 4: every execution is logged regardless of outcome
        latency_ms = int((time.monotonic() - start) * 1000)
        final_authz = result.authz_note or authz_decision
        self._audit.log(ctx, tool_name, tool_input, result, final_authz, latency_ms)
        return result


def build_registry(data_source: "DataSource", audit_logger: AuditLogger) -> "ToolRegistry":
    # Imports deferred to avoid circular imports at module load time
    from tools.calendar import GetTeamCalendarTool
    from tools.documents import (
        CheckDocumentSensitivityTool,
        GenerateExperienceCertificateTool,
        GenerateSalaryCertificateTool,
        GenerateTwimcLetterTool,
        SensitivityAuditTool,
    )
    from tools.employee import (
        CalculateEndOfServiceTool,
        GetEmployeeDataTool,
        GetEmployeeDocumentsTool,
        GetEmployeeSummaryTool,
        GetLeaveBalanceTool,
        ListEmployeesTool,
        SearchEmployeesTool,
    )
    from tools.leave import (
        AddCompensatoryDayTool,
        ApproveLeaveCancellationTool,
        ApproveLeaveRequestTool,
        CancelLeaveRequestTool,
        CheckLeaveBalanceTool,
        CheckLeaveEligibilityTool,
        CheckRequestCompletenessTool,
        GetLeaveRequestsTool,
        GetLeaveWaitingStatusTool,
        GetPendingApprovalsTool,
        GetPendingCancellationsTool,
        RejectLeaveRequestTool,
        RequestLeaveCancellationTool,
        SubmitLeaveRequestTool,
    )
    from tools.policy import SearchPolicyTool

    tools: list[Tool] = [
        # Employee read tools (7)
        SearchEmployeesTool(data_source),
        ListEmployeesTool(data_source),
        GetEmployeeDataTool(data_source),
        GetLeaveBalanceTool(data_source),
        GetEmployeeSummaryTool(data_source),
        GetEmployeeDocumentsTool(data_source),
        CalculateEndOfServiceTool(data_source),
        # Document generation tools (3)
        GenerateSalaryCertificateTool(data_source),
        GenerateTwimcLetterTool(data_source),
        GenerateExperienceCertificateTool(data_source),
        # Leave / OOO tools (11)
        CheckRequestCompletenessTool(data_source),
        CheckLeaveBalanceTool(data_source),
        CheckLeaveEligibilityTool(data_source),
        SubmitLeaveRequestTool(data_source),
        GetLeaveRequestsTool(data_source),
        GetPendingApprovalsTool(data_source),
        ApproveLeaveRequestTool(data_source),
        RejectLeaveRequestTool(data_source),
        CancelLeaveRequestTool(data_source),
        GetLeaveWaitingStatusTool(data_source),
        AddCompensatoryDayTool(data_source),
        RequestLeaveCancellationTool(data_source),
        ApproveLeaveCancellationTool(data_source),
        GetPendingCancellationsTool(data_source),
        # Policy search / RAG (1)
        SearchPolicyTool(data_source),
        # Document sensitivity tools (2)
        CheckDocumentSensitivityTool(data_source),
        SensitivityAuditTool(data_source),
        # Calendar (1)
        GetTeamCalendarTool(data_source),
    ]
    return ToolRegistry(tools, audit_logger)
