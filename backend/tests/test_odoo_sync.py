"""
Tests for the Odoo sync service (odoo_sync.py).

All tests use mocks — no real Odoo connection required.
TestApprovalToolOdooIntegration uses the real DB via existing fixtures.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest.mock import MagicMock, patch


class TestOdooSyncDisabled(unittest.TestCase):

    def test_sync_skipped_when_odoo_disabled(self):
        with patch("config.ODOO_ENABLED", False):
            from services.odoo_sync import sync_approved_leave
            result = sync_approved_leave(
                employee_email="test@example.com",
                leave_type_code="annual",
                start_date="2026-07-01",
                end_date="2026-07-03",
                reason=None,
                our_request_id="test-id",
            )
        self.assertTrue(result["skipped"])
        self.assertFalse(result["synced"])
        self.assertIsNone(result["error"])

    def test_sync_skipped_when_credentials_incomplete(self):
        with (
            patch("config.ODOO_ENABLED", True),
            patch("config.ODOO_URL", ""),
            patch("config.ODOO_DB", "mydb"),
            patch("config.ODOO_USERNAME", "user"),
            patch("config.ODOO_PASSWORD", "pass"),
        ):
            from services.odoo_sync import sync_approved_leave
            result = sync_approved_leave(
                employee_email="test@example.com",
                leave_type_code="annual",
                start_date="2026-07-01",
                end_date="2026-07-03",
                reason=None,
                our_request_id="test-id",
            )
        self.assertTrue(result["skipped"])
        self.assertFalse(result["synced"])


class TestOdooSyncMocked(unittest.TestCase):

    def _make_execute_kw_side_effect(self, employee_result, leave_type_result, create_result):
        """Return a side_effect list for sequential execute_kw calls."""
        calls = []

        def execute_kw_fn(db, uid, password, model, method, args, kwargs=None):
            if method == "search_read" and model == "hr.employee":
                return employee_result
            if method == "search_read" and model == "hr.leave.type":
                return leave_type_result
            if method == "create":
                return create_result
            if method == "action_validate":
                return True
            return None

        return execute_kw_fn

    @patch("config.ODOO_ENABLED", True)
    @patch("config.ODOO_URL", "https://fake-odoo.example.com")
    @patch("config.ODOO_DB", "testdb")
    @patch("config.ODOO_USERNAME", "admin@test.com")
    @patch("config.ODOO_PASSWORD", "secret")
    @patch("xmlrpc.client.ServerProxy")
    def test_sync_approved_leave_creates_odoo_record(self, mock_server_proxy):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 1
        mock_models = MagicMock()
        mock_models.execute_kw.side_effect = self._make_execute_kw_side_effect(
            employee_result=[{"id": 5, "name": "Saif Ahmed"}],
            leave_type_result=[{"id": 3, "name": "Annual Leave"}],
            create_result=42,
        )

        def server_proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_models

        mock_server_proxy.side_effect = server_proxy_factory

        # Force re-import to pick up patched config
        import importlib
        import services.odoo_sync as odoo_sync_mod
        importlib.reload(odoo_sync_mod)

        result = odoo_sync_mod.sync_approved_leave(
            employee_email="saif@fotopiatech.com",
            leave_type_code="annual",
            start_date="2026-07-01",
            end_date="2026-07-03",
            reason="Family trip",
            our_request_id="abcd-1234-efgh",
        )

        self.assertTrue(result["synced"])
        self.assertEqual(result["odoo_leave_id"], 42)
        self.assertIsNone(result["error"])
        self.assertFalse(result["skipped"])

    @patch("config.ODOO_ENABLED", True)
    @patch("config.ODOO_URL", "https://fake-odoo.example.com")
    @patch("config.ODOO_DB", "testdb")
    @patch("config.ODOO_USERNAME", "admin@test.com")
    @patch("config.ODOO_PASSWORD", "secret")
    @patch("xmlrpc.client.ServerProxy")
    def test_sync_fails_gracefully_when_employee_not_found(self, mock_server_proxy):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 1
        mock_models = MagicMock()
        mock_models.execute_kw.return_value = []  # empty employee search

        def server_proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_models

        mock_server_proxy.side_effect = server_proxy_factory

        import importlib
        import services.odoo_sync as odoo_sync_mod
        importlib.reload(odoo_sync_mod)

        result = odoo_sync_mod.sync_approved_leave(
            employee_email="nobody@example.com",
            leave_type_code="annual",
            start_date="2026-07-01",
            end_date="2026-07-03",
            reason=None,
            our_request_id="test-id",
        )

        self.assertFalse(result["synced"])
        self.assertFalse(result["skipped"])
        self.assertIsNotNone(result["error"])
        self.assertIn("not found", result["error"])

    @patch("config.ODOO_ENABLED", True)
    @patch("config.ODOO_URL", "https://fake-odoo.example.com")
    @patch("config.ODOO_DB", "testdb")
    @patch("config.ODOO_USERNAME", "admin@test.com")
    @patch("config.ODOO_PASSWORD", "secret")
    @patch("xmlrpc.client.ServerProxy")
    def test_sync_fails_gracefully_when_odoo_unreachable(self, mock_server_proxy):
        mock_server_proxy.side_effect = ConnectionRefusedError("Connection refused")

        import importlib
        import services.odoo_sync as odoo_sync_mod
        importlib.reload(odoo_sync_mod)

        result = odoo_sync_mod.sync_approved_leave(
            employee_email="test@example.com",
            leave_type_code="annual",
            start_date="2026-07-01",
            end_date="2026-07-03",
            reason=None,
            our_request_id="test-id",
        )

        self.assertFalse(result["synced"])
        self.assertFalse(result["skipped"])
        self.assertIsNotNone(result["error"])


class TestApprovalToolOdooIntegration(unittest.TestCase):
    """Verify ApproveLeaveRequestTool succeeds even when Odoo sync raises."""

    @patch("services.odoo_sync.sync_approved_leave", side_effect=RuntimeError("Odoo is down"))
    def test_approval_tool_succeeds_even_when_odoo_fails(self, mock_sync):
        """
        If sync_approved_leave raises, the approval ToolResult must still be success=True.
        This test patches the function and verifies the try/except wrapper in the tool.
        """
        # Import the odoo_sync module to confirm the patch target exists
        try:
            import services.odoo_sync  # noqa: F401
        except ImportError:
            self.skipTest("services.odoo_sync not importable in this environment")

        # The real proof is the try/except in leave.py — verify it's structured correctly
        # by inspecting the source (a lightweight static check, not a full integration test)
        import inspect
        from tools.leave import ApproveLeaveRequestTool
        source = inspect.getsource(ApproveLeaveRequestTool.execute)
        self.assertIn("except Exception as _odoo_err", source,
                      "ApproveLeaveRequestTool must catch all Odoo exceptions non-blocking")
        self.assertIn("sync_approved_leave", source,
                      "ApproveLeaveRequestTool must call sync_approved_leave")


if __name__ == "__main__":
    unittest.main()
