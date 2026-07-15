"""
connectors/odoo_adapter.py — Week-1 onboarding boundary for Odoo connectivity.

Wraps the existing services/odoo_sync.py::OdooClient (XML-RPC) behind a
single narrow function so tools never depend on the underlying transport.
When the planned MCP-standard connector (connectors/odoo_mcp.py, using the
community ivnvxd/mcp-server-odoo server) lands, only this file's internals
change — callers (tools/odoo_connect.py) keep the same contract.

Fail-safe by design, matching services/odoo_sync.py's own convention:
config.ODOO_ENABLED defaults false, and no credentials are configured in
this environment — this function reports that clearly rather than
attempting a doomed connection.
"""
import logging

import config

_log = logging.getLogger(__name__)


def test_and_summarize_connection() -> dict:
    """Attempt to connect to Odoo and summarize what was found.

    Returns: {"connected": bool, "employee_count": int | None, "error": str | None}
    Never raises — all failure modes are caught and reported in the result.
    """
    if not config.ODOO_ENABLED:
        return {
            "connected": False,
            "employee_count": None,
            "error": "Odoo is not enabled in this environment (ODOO_ENABLED is not set).",
        }

    try:
        from services.odoo_sync import OdooClient
        client = OdooClient()
        employees = client.search_read("hr.employee", [], ["id"], limit=1000)
        return {
            "connected": True,
            "employee_count": len(employees),
            "error": None,
        }
    except Exception as e:
        _log.warning("odoo_adapter: connection test failed: %s", e)
        return {
            "connected": False,
            "employee_count": None,
            "error": str(e),
        }
