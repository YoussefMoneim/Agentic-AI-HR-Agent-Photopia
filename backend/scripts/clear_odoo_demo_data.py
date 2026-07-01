"""
clear_odoo_demo_data.py — Delete all Odoo hr.leave and hr.leave.allocation
records for the 25 demo employees, then re-create the initial allocations.

Run from inside the backend container:
  python /app/scripts/clear_odoo_demo_data.py

Or from the repo root with proper environment variables:
  python backend/scripts/clear_odoo_demo_data.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import xmlrpc.client

import config

# Work emails from seed.sql (used to look up employees in Odoo by work_email).
# FT-2022-010 may appear under either email depending on whether the demo
# customization (saif.ahmed) was applied before or after the last Odoo sync.
DEMO_EMAILS = [
    "mohammed.nuaimi@fotopiatech.com",
    "khalid.hashmi@fotopiatech.com",
    "noura.rashidi@fotopiatech.com",
    "ahmed.mansouri@fotopiatech.com",
    "sara.zaabi@fotopiatech.com",
    "reem.ketbi@fotopiatech.com",
    "saeed.marri@fotopiatech.com",
    "tariq.ameri@fotopiatech.com",
    "jaber.kindi@fotopiatech.com",
    "hessa.mazrouei@fotopiatech.com",
    "omar.shehhi@fotopiatech.com",
    "maryam.falasi@fotopiatech.com",
    "rashed.blooshi@fotopiatech.com",
    "fatima.suwaidi@fotopiatech.com",
    "i-youssef.abdelmoneim@fotopiatech.com",  # FT-2022-010 seed.sql default
    "saif.ahmed@fotopiatech.com",              # FT-2022-010 demo customization
    "i-saif.ahmed@fotopiatech.com",            # FT-2022-011 Saif Ahmed
    "layla.qassimi@fotopiatech.com",
    "hamdan.nuaimi@fotopiatech.com",
    "shaikha.ketbi@fotopiatech.com",
    "amna.muhairi@fotopiatech.com",
    "mansoor.dhaheri@fotopiatech.com",
    "wadima.hosani@fotopiatech.com",
    "maitha.romaithi@fotopiatech.com",
    "zayed.kaabi@fotopiatech.com",
    "nadia.shamsi@fotopiatech.com",
    "lina.rashidi@fotopiatech.com",
]

# Odoo allocation overrides — all others get DEFAULT_DAYS.
ANNUAL_ALLOCATIONS = {
    "mohammed.nuaimi@fotopiatech.com": 30,  # age ≥50 enhanced entitlement
    "lina.rashidi@fotopiatech.com":    15,  # first calendar year (hired 2026-03)
}
DEFAULT_DAYS = 21
ANNUAL_LEAVE_TYPE_ID = 22  # hr.holiday.status id for Annual Leave in Odoo staging


def _connect():
    common = xmlrpc.client.ServerProxy(f"{config.ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(config.ODOO_DB, config.ODOO_USERNAME, config.ODOO_PASSWORD, {})
    if not uid:
        raise RuntimeError("Odoo authentication failed — check ODOO_* env vars")
    models = xmlrpc.client.ServerProxy(f"{config.ODOO_URL}/xmlrpc/2/object")
    return uid, models


def _get_employees(uid, models):
    """Return (employees_list, emp_ids) found in Odoo by work_email."""
    results = models.execute_kw(
        config.ODOO_DB, uid, config.ODOO_PASSWORD,
        "hr.employee", "search_read",
        [[["work_email", "in", DEMO_EMAILS]]],
        {"fields": ["id", "name", "work_email"], "limit": len(DEMO_EMAILS) + 5},
    )
    emp_ids = [e["id"] for e in results]
    return results, emp_ids


def _clear_model(uid, models, model_name, emp_ids):
    """Refuse → draft → delete all records for emp_ids in model_name."""
    record_ids = models.execute_kw(
        config.ODOO_DB, uid, config.ODOO_PASSWORD,
        model_name, "search",
        [[["employee_id", "in", emp_ids]]],
    )
    if not record_ids:
        print(f"  {model_name}: no records found — skipping")
        return

    print(f"  {model_name}: found {len(record_ids)} record(s) — clearing...")

    for method in ("action_refuse", "action_draft"):
        try:
            models.execute_kw(
                config.ODOO_DB, uid, config.ODOO_PASSWORD,
                model_name, method, [record_ids],
            )
        except Exception as e:
            print(f"    {method}: {e} (continuing)")

    try:
        models.execute_kw(
            config.ODOO_DB, uid, config.ODOO_PASSWORD,
            model_name, "unlink", [record_ids],
        )
        print(f"    ✓ Deleted {len(record_ids)} {model_name} record(s)")
    except Exception as e:
        print(f"    ✗ Delete failed: {e}")
        print("      You may need to refuse and delete these manually in the Odoo UI.")


def _create_allocations(uid, models, employees):
    """Re-create initial annual leave allocations for all demo employees."""
    print(f"  Creating annual leave allocations for {len(employees)} employee(s)...")
    created = 0
    for emp in employees:
        email = emp.get("work_email", "")
        days = ANNUAL_ALLOCATIONS.get(email, DEFAULT_DAYS)
        try:
            models.execute_kw(
                config.ODOO_DB, uid, config.ODOO_PASSWORD,
                "hr.leave.allocation", "create",
                [{
                    "employee_id": emp["id"],
                    "holiday_status_id": ANNUAL_LEAVE_TYPE_ID,
                    "number_of_days": days,
                    "name": "Annual Leave 2026",
                    "state": "validate",
                }],
            )
            created += 1
        except Exception as e:
            print(f"    ✗ Allocation failed for {emp.get('name')} ({email}): {e}")
    print(f"  ✓ Created {created} allocation(s)")


def main():
    print("\n── Odoo demo data reset ─────────────────────────────")

    if not config.ODOO_ENABLED:
        print("  ODOO_ENABLED=false — skipping")
        return

    if not all([config.ODOO_URL, config.ODOO_DB, config.ODOO_USERNAME, config.ODOO_PASSWORD]):
        print("  Odoo credentials incomplete — skipping")
        return

    try:
        uid, models = _connect()
        print(f"  Connected to Odoo at {config.ODOO_URL}")
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return

    employees, emp_ids = _get_employees(uid, models)
    print(f"  Found {len(employees)} demo employee(s) in Odoo")

    if not emp_ids:
        print("  No employees found — run sync_employees_to_odoo.py first")
        return

    _clear_model(uid, models, "hr.leave", emp_ids)
    _clear_model(uid, models, "hr.leave.allocation", emp_ids)
    _create_allocations(uid, models, employees)

    print("  ✓ Odoo demo data reset complete\n")


if __name__ == "__main__":
    main()
