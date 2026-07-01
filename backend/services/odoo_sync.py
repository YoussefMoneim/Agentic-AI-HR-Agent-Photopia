"""
Odoo sync service — writes approved leave data to Odoo after our system approves it.
One-way: our system → Odoo. Never reads from Odoo to make decisions.
Fail-safe: if Odoo is unreachable, logs the error but does NOT roll back our approval.
"""
import logging
import xmlrpc.client
from typing import Any

import config

_log = logging.getLogger(__name__)


class OdooClient:
    """Thin wrapper around Odoo XML-RPC API."""

    def __init__(self):
        self._url = config.ODOO_URL
        self._db = config.ODOO_DB
        self._username = config.ODOO_USERNAME
        self._password = config.ODOO_PASSWORD
        self._uid = None

    def _authenticate(self):
        if self._uid:
            return self._uid
        common = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/common")
        uid = common.authenticate(self._db, self._username, self._password, {})
        if not uid:
            raise RuntimeError("Odoo authentication failed — check credentials")
        self._uid = uid
        return uid

    def _models(self):
        return xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/object")

    def search_read(self, model: str, domain: list, fields: list, limit: int = 10) -> list:
        uid = self._authenticate()
        return self._models().execute_kw(
            self._db, uid, self._password,
            model, "search_read",
            [domain],
            {"fields": fields, "limit": limit},
        )

    def create(self, model: str, values: dict) -> int:
        uid = self._authenticate()
        return self._models().execute_kw(
            self._db, uid, self._password,
            model, "create", [values],
        )

    def write(self, model: str, ids: list, values: dict) -> bool:
        uid = self._authenticate()
        return self._models().execute_kw(
            self._db, uid, self._password,
            model, "write", [ids, values],
        )

    def action(self, model: str, ids: list, method: str) -> Any:
        uid = self._authenticate()
        return self._models().execute_kw(
            self._db, uid, self._password,
            model, method, [ids],
        )


def _get_client():
    if not config.ODOO_ENABLED:
        return None
    if not all([config.ODOO_URL, config.ODOO_DB, config.ODOO_USERNAME, config.ODOO_PASSWORD]):
        _log.warning("Odoo sync enabled but credentials incomplete — skipping")
        return None
    return OdooClient()


def find_odoo_employee(client: OdooClient, email: str):
    try:
        results = client.search_read(
            "hr.employee",
            [["work_email", "=", email]],
            ["id", "name"],
            limit=1,
        )
        if results:
            return results[0]["id"]
        _log.warning("Odoo employee not found by email %s", email)
        return None
    except Exception as e:
        _log.error("Error finding Odoo employee: %s", e)
        return None


# Maps our leave type codes to confirmed Odoo leave type names (ilike search).
_CODE_TO_ODOO_NAME = {
    "annual":             "Annual Leave",
    "sick":               "Sick Leave",
    "casual":             "Annual Leave",
    "maternity":          "Maternity",
    "paternity":          "New Baby",
    "hajj":               "Hajj Leave",
    "umrah":              "Umrah Leave",
    "marriage":           "Marriage Leave",
    "funeral_1st_degree": "Funeral",
    "funeral_2nd_degree": "Funeral",
    "educational":        "Educational Leave",
    "military":           "Military Service Leave",
    "military_summon":    "Military Service Leave",
    "compensatory_off":   "Compensatory Off Balance",
    "unpaid":             "Unpaid Leave",
    "wfh":                "Annual Leave",
    "outside_duty":       "Annual Leave",
    "permission":         "Annual Leave",
    "business_trip":      "Annual Leave",
}


def find_odoo_leave_type(client: OdooClient, leave_type_code: str):
    search_name = _CODE_TO_ODOO_NAME.get(leave_type_code, leave_type_code)
    try:
        results = client.search_read(
            "hr.leave.type",
            [["name", "ilike", search_name]],
            ["id", "name"],
            limit=1,
        )
        if results:
            _log.info(
                "Mapped leave type '%s' to Odoo '%s' (id=%d)",
                leave_type_code, results[0]["name"], results[0]["id"],
            )
            return results[0]["id"]
        _log.warning("Odoo leave type not found for code '%s'", leave_type_code)
        return None
    except Exception as e:
        _log.error("Error finding Odoo leave type: %s", e)
        return None


def sync_approved_leave(
    employee_email: str,
    leave_type_code: str,
    start_date: str,
    end_date: str,
    reason: str | None,
    our_request_id: str,
) -> dict:
    """
    Create and validate an hr.leave record in Odoo for an approved leave.

    Called AFTER our system has already approved the leave.
    If Odoo sync fails: logs the error, returns failure dict.
    The failure NEVER rolls back our approval — our system is the source of truth.

    Returns: {synced, odoo_leave_id, error, skipped}
    """
    client = _get_client()
    if client is None:
        return {"synced": False, "odoo_leave_id": None, "error": None, "skipped": True}

    try:
        odoo_employee_id = find_odoo_employee(client, employee_email)
        if not odoo_employee_id:
            return {
                "synced": False,
                "odoo_leave_id": None,
                "error": f"Employee with email {employee_email} not found in Odoo",
                "skipped": False,
            }

        odoo_leave_type_id = find_odoo_leave_type(client, leave_type_code)
        if not odoo_leave_type_id:
            return {
                "synced": False,
                "odoo_leave_id": None,
                "error": f"Leave type '{leave_type_code}' not found in Odoo",
                "skipped": False,
            }

        leave_values = {
            "employee_id": odoo_employee_id,
            "holiday_status_id": odoo_leave_type_id,
            "date_from": f"{start_date} 08:00:00",
            "date_to": f"{end_date} 17:00:00",
            "name": f"{leave_type_code.replace('_', ' ').title()} — Approved via Fotopia HR System",
            "state": "draft",
        }
        odoo_leave_id = client.create("hr.leave", leave_values)
        _log.info("Created Odoo hr.leave id=%d for our request %s", odoo_leave_id, our_request_id)

        try:
            client.action("hr.leave", [odoo_leave_id], "action_confirm")
            _log.info("Confirmed Odoo leave id=%d", odoo_leave_id)
        except Exception as confirm_err:
            _log.warning("Could not confirm Odoo leave %d: %s", odoo_leave_id, confirm_err)

        try:
            client.action("hr.leave", [odoo_leave_id], "action_validate")
            _log.info("Validated Odoo leave id=%d", odoo_leave_id)
        except Exception as validate_err:
            _log.warning(
                "Could not validate Odoo leave %d: %s — left as confirmed",
                odoo_leave_id, validate_err,
            )

        return {"synced": True, "odoo_leave_id": odoo_leave_id, "error": None, "skipped": False}

    except Exception as e:
        _log.error("Odoo sync failed for request %s: %s", our_request_id, e)
        return {"synced": False, "odoo_leave_id": None, "error": str(e), "skipped": False}


def sync_cancelled_leave(
    employee_email: str,
    leave_type_code: str,
    start_date: str,
    end_date: str,
    our_request_id: str,
) -> dict:
    """
    Find and refuse/delete the corresponding Odoo hr.leave record when a leave
    is cancelled in our system.

    Lookup: employee + leave type + overlapping dates + non-refused states.
    No match → log and return synced=True (record may have been manually deleted
    in Odoo, or sync originally failed — both are acceptable outcomes).

    NEVER blocks or rolls back our cancellation.
    Returns same shape as sync_approved_leave(): {synced, odoo_leave_id, error, skipped}
    """
    client = _get_client()
    if client is None:
        return {"synced": False, "odoo_leave_id": None, "error": None, "skipped": True}

    try:
        odoo_employee_id = find_odoo_employee(client, employee_email)
        if not odoo_employee_id:
            _log.warning(
                "Odoo cancel sync: employee not found for %s (request %s)",
                employee_email, our_request_id,
            )
            return {
                "synced": False,
                "odoo_leave_id": None,
                "error": f"Employee {employee_email} not found in Odoo",
                "skipped": False,
            }

        odoo_leave_type_id = find_odoo_leave_type(client, leave_type_code)
        if not odoo_leave_type_id:
            _log.warning(
                "Odoo cancel sync: leave type not found for code %s", leave_type_code
            )
            return {
                "synced": False,
                "odoo_leave_id": None,
                "error": f"Leave type {leave_type_code} not found in Odoo",
                "skipped": False,
            }

        domain = [
            ["employee_id", "=", odoo_employee_id],
            ["holiday_status_id", "=", odoo_leave_type_id],
            ["date_from", "<=", f"{end_date} 23:59:59"],
            ["date_to", ">=", f"{start_date} 00:00:00"],
            ["state", "in", ["validate", "validate1", "confirm", "draft"]],
        ]
        matches = client.search_read(
            "hr.leave", domain,
            ["id", "state", "date_from", "date_to", "employee_id"],
            limit=5,
        )

        if not matches:
            _log.info(
                "Odoo cancel sync: no matching leave found for employee %s "
                "dates %s to %s — skipping (may have been manually deleted)",
                employee_email, start_date, end_date,
            )
            return {"synced": True, "odoo_leave_id": None, "error": None, "skipped": False}

        odoo_leave = matches[0]
        odoo_leave_id = odoo_leave["id"]
        odoo_state = odoo_leave["state"]
        _log.info(
            "Odoo cancel sync: found leave id=%d state=%s for request %s",
            odoo_leave_id, odoo_state, our_request_id,
        )

        if odoo_state in ("validate", "validate1", "confirm"):
            try:
                client.action("hr.leave", [odoo_leave_id], "action_refuse")
                _log.info("Odoo cancel sync: refused leave id=%d", odoo_leave_id)
            except Exception as refuse_err:
                _log.warning(
                    "Odoo cancel sync: could not refuse leave %d: %s — "
                    "attempting deletion anyway",
                    odoo_leave_id, refuse_err,
                )

        try:
            client.action("hr.leave", [odoo_leave_id], "action_draft")
            _log.info("Odoo cancel sync: reset to draft leave id=%d", odoo_leave_id)
        except Exception as draft_err:
            _log.debug(
                "Odoo cancel sync: action_draft failed for %d: %s "
                "(may already be in draft/refused state — continuing)",
                odoo_leave_id, draft_err,
            )

        try:
            client.action("hr.leave", [odoo_leave_id], "unlink")
            _log.info(
                "Odoo cancel sync: deleted leave id=%d for request %s",
                odoo_leave_id, our_request_id,
            )
        except Exception as unlink_err:
            _log.warning(
                "Odoo cancel sync: could not delete leave %d: %s — "
                "left in refused state (balance restored; HR can clean up manually)",
                odoo_leave_id, unlink_err,
            )
            return {
                "synced": True,
                "odoo_leave_id": odoo_leave_id,
                "error": str(unlink_err),
                "skipped": False,
            }

        return {"synced": True, "odoo_leave_id": odoo_leave_id, "error": None, "skipped": False}

    except Exception as e:
        _log.error(
            "Odoo cancel sync failed for request %s: %s", our_request_id, e
        )
        return {"synced": False, "odoo_leave_id": None, "error": str(e), "skipped": False}


def sync_leave_allocation(
    employee_email: str,
    leave_type_code: str,
    number_of_days: float,
    year: int,
    our_employee_code: str,
) -> dict:
    """
    Create an hr.leave.allocation in Odoo for year-start balance allocation.
    Ready for future use by AllocateYearStartLeaveTool.

    Returns: {synced, odoo_leave_id, error, skipped}
    """
    client = _get_client()
    if client is None:
        return {"synced": False, "odoo_leave_id": None, "error": None, "skipped": True}

    try:
        odoo_employee_id = find_odoo_employee(client, employee_email)
        if not odoo_employee_id:
            return {
                "synced": False, "odoo_leave_id": None,
                "error": f"Employee {employee_email} not found in Odoo", "skipped": False,
            }

        odoo_leave_type_id = find_odoo_leave_type(client, leave_type_code)
        if not odoo_leave_type_id:
            return {
                "synced": False, "odoo_leave_id": None,
                "error": f"Leave type {leave_type_code} not found in Odoo", "skipped": False,
            }

        alloc_values = {
            "employee_id": odoo_employee_id,
            "holiday_status_id": odoo_leave_type_id,
            "number_of_days": number_of_days,
            "name": f"{year} Annual Leave Allocation — Fotopia HR",
            "state": "draft",
        }
        alloc_id = client.create("hr.leave.allocation", alloc_values)

        try:
            client.action("hr.leave.allocation", [alloc_id], "action_validate1")
        except Exception:
            pass  # Created as draft — HR can validate in Odoo

        return {"synced": True, "odoo_leave_id": alloc_id, "error": None, "skipped": False}

    except Exception as e:
        _log.error("Odoo allocation sync failed for %s: %s", our_employee_code, e)
        return {"synced": False, "odoo_leave_id": None, "error": str(e), "skipped": False}
