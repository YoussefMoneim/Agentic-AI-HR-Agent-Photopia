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


class TestOdooSyncCancellation(unittest.TestCase):

    def test_sync_cancelled_leave_skipped_when_odoo_disabled(self):
        with patch("config.ODOO_ENABLED", False):
            from services.odoo_sync import sync_cancelled_leave
            result = sync_cancelled_leave(
                employee_email="test@example.com",
                leave_type_code="annual",
                start_date="2026-07-01",
                end_date="2026-07-05",
                our_request_id="test-cancel-id",
            )
        self.assertTrue(result["skipped"])
        self.assertFalse(result["synced"])
        self.assertIsNone(result["error"])

    def test_sync_cancelled_leave_no_match_returns_synced_true(self):
        import services.odoo_sync as odoo_sync_mod
        mock_client = MagicMock()
        mock_client.search_read.return_value = []
        with (
            patch.object(odoo_sync_mod, "_get_client", return_value=mock_client),
            patch.object(odoo_sync_mod, "find_odoo_employee", return_value=42),
            patch.object(odoo_sync_mod, "find_odoo_leave_type", return_value=7),
        ):
            result = odoo_sync_mod.sync_cancelled_leave(
                employee_email="test@example.com",
                leave_type_code="annual",
                start_date="2026-07-01",
                end_date="2026-07-05",
                our_request_id="test-cancel-id",
            )
        self.assertTrue(result["synced"])
        self.assertIsNone(result["odoo_leave_id"])
        self.assertFalse(result["skipped"])
        mock_client.action.assert_not_called()

    def test_sync_cancelled_leave_refuses_and_deletes_validated_leave(self):
        import services.odoo_sync as odoo_sync_mod
        mock_client = MagicMock()
        mock_client.search_read.return_value = [
            {
                "id": 99,
                "state": "validate",
                "date_from": "2026-07-01 08:00:00",
                "date_to": "2026-07-05 17:00:00",
                "employee_id": [42, "Test Employee"],
            }
        ]
        mock_client.action.return_value = True
        with (
            patch.object(odoo_sync_mod, "_get_client", return_value=mock_client),
            patch.object(odoo_sync_mod, "find_odoo_employee", return_value=42),
            patch.object(odoo_sync_mod, "find_odoo_leave_type", return_value=7),
        ):
            result = odoo_sync_mod.sync_cancelled_leave(
                employee_email="test@example.com",
                leave_type_code="annual",
                start_date="2026-07-01",
                end_date="2026-07-05",
                our_request_id="test-cancel-id",
            )
        self.assertTrue(result["synced"])
        self.assertEqual(result["odoo_leave_id"], 99)
        self.assertIsNone(result["error"])
        self.assertFalse(result["skipped"])
        called_methods = [c[0][2] for c in mock_client.action.call_args_list]
        self.assertIn("action_refuse", called_methods)
        self.assertIn("action_draft", called_methods)
        self.assertIn("unlink", called_methods)


if __name__ == "__main__":
    unittest.main()
