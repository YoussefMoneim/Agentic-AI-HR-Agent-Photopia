import json
import logging
from typing import TYPE_CHECKING

import psycopg2

if TYPE_CHECKING:
    from tools.base import ToolContext, ToolResult

_log = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def log(
        self,
        ctx: "ToolContext",
        tool_name: str,
        tool_input: dict,
        result: "ToolResult",
        authz_decision: str,
        latency_ms: int,
    ) -> None:
        outcome = "success" if result.success else "error"
        # Format: "document_id=<uuid>" for doc tools so get_employee_documents can parse it later
        result_summary = result.error or (
            f"document_id={result.document_id}" if result.document_id else str(result.data)[:200] if result.data else ""
        )
        data_fields_json = (
            json.dumps(result.data_fields_accessed)
            if result.data_fields_accessed
            else None
        )
        action = (
            "decision_denied" if authz_decision in ("denied", "unknown_tool")
            else getattr(result, "action_type", "tool_executed")
        )
        try:
            conn = psycopg2.connect(self._database_url)
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SET ROLE fotopia_app")
                    cur.execute("SET app.current_tenant_id = %s", (ctx.tenant_id,))
                    cur.execute(
                        """
                        INSERT INTO audit_log
                            (tenant_id, actor_user_id, actor_role, tool_name, tool_input,
                             outcome, authz_decision, result_summary, latency_ms,
                             data_fields_accessed, action)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            ctx.tenant_id,
                            ctx.user_id,
                            ctx.role,
                            tool_name,
                            json.dumps(tool_input),
                            outcome,
                            authz_decision,
                            result_summary,
                            latency_ms,
                            data_fields_json,
                            action,
                        ),
                    )
            conn.close()
        except Exception:
            # Never re-raise — audit failure must never break the user's request
            _log.exception("Failed to write audit log for tool=%s", tool_name)
