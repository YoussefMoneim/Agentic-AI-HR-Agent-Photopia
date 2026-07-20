"""
Tests for connectors/odoo_adapter.py and tools/odoo_connect.py.

All tests use mocks — no real Odoo connection required, matching the style
of tests/test_odoo_sync.py.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

from tools.base import ToolContext


def _ctx(role="hr_manager"):
    return ToolContext(
        tenant_id="tenant-uuid", user_id="test-user", role=role,
        employee_code="EMP002", display_name="Noura Al Rashidi",
    )


class TestOdooAdapter:

    def test_reports_not_connected_when_odoo_disabled(self):
        with patch("config.ODOO_ENABLED", False):
            from connectors.odoo_adapter import test_and_summarize_connection
            result = test_and_summarize_connection()
        assert result["connected"] is False
        assert result["employee_count"] is None
        assert "not enabled" in result["error"].lower()

    def test_reports_connected_with_employee_count_on_success(self):
        mock_client = MagicMock()
        mock_client.search_read.return_value = [{"id": i} for i in range(5)]
        with patch("config.ODOO_ENABLED", True):
            with patch("services.odoo_sync.OdooClient", return_value=mock_client):
                from connectors.odoo_adapter import test_and_summarize_connection
                result = test_and_summarize_connection()
        assert result["connected"] is True
        assert result["employee_count"] == 5
        assert result["error"] is None

    def test_reports_error_without_raising_on_failure(self):
        mock_client = MagicMock()
        mock_client.search_read.side_effect = RuntimeError("Odoo authentication failed")
        with patch("config.ODOO_ENABLED", True):
            with patch("services.odoo_sync.OdooClient", return_value=mock_client):
                from connectors.odoo_adapter import test_and_summarize_connection
                result = test_and_summarize_connection()
        assert result["connected"] is False
        assert "authentication failed" in result["error"].lower()


class TestConnectOdooTool:

    def test_success_returns_employee_count(self):
        from tools.odoo_connect import ConnectOdooTool
        with patch(
            "tools.odoo_connect.test_and_summarize_connection",
            return_value={"connected": True, "employee_count": 32, "error": None},
        ):
            result = ConnectOdooTool().execute({}, _ctx())
        assert result.success is True
        assert result.data["employee_count"] == 32

    def test_failure_surfaces_error(self):
        from tools.odoo_connect import ConnectOdooTool
        with patch(
            "tools.odoo_connect.test_and_summarize_connection",
            return_value={"connected": False, "employee_count": None, "error": "boom"},
        ):
            result = ConnectOdooTool().execute({}, _ctx())
        assert result.success is False
        assert result.error == "boom"

    def test_allowed_roles_exclude_employee(self):
        from tools.odoo_connect import ConnectOdooTool
        assert "employee" not in ConnectOdooTool.spec.allowed_roles
        assert "hr_manager" in ConnectOdooTool.spec.allowed_roles
        assert "admin" in ConnectOdooTool.spec.allowed_roles

    def test_registry_denies_employee_role(self):
        from tools.registry import ToolRegistry
        from tools.odoo_connect import ConnectOdooTool
        from audit.logger import AuditLogger

        registry = ToolRegistry([ConnectOdooTool()], MagicMock(spec=AuditLogger))
        result = registry.execute("connect_odoo", {}, _ctx(role="employee"))
        assert result.success is False
        assert "not permitted" in result.error.lower()

    def test_not_offered_to_llm_tool_use_loop(self):
        """
        Regression test for a real bug: the general chat agent picked
        connect_odoo as an available tool from casual phrasing like "connect
        it to Odoo" — completely bypassing agent/onboarding.py's state
        machine — then fabricated an "onboarding complete" claim on top.
        connect_odoo must never appear in get_specs_for_role()'s output,
        even for a role that's otherwise allowed to call it directly.
        """
        from tools.registry import ToolRegistry
        from tools.odoo_connect import ConnectOdooTool
        from audit.logger import AuditLogger

        assert ConnectOdooTool.spec.llm_visible is False

        registry = ToolRegistry([ConnectOdooTool()], MagicMock(spec=AuditLogger))
        specs = registry.get_specs_for_role("hr_manager")
        assert all(s["name"] != "connect_odoo" for s in specs)

        # Still directly executable by name — onboarding.py's own calls must
        # keep working; only LLM auto-discovery is blocked.
        with patch(
            "tools.odoo_connect.test_and_summarize_connection",
            return_value={"connected": True, "employee_count": 5, "error": None},
        ):
            result = registry.execute("connect_odoo", {}, _ctx())
        assert result.success is True
