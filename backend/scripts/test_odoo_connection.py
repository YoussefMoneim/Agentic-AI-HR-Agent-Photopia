#!/usr/bin/env python3
"""
Test Odoo connectivity. Run before configuring the connector.
Usage: docker exec fotopia-hr-agent-backend-1 python /app/scripts/test_odoo_connection.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from services.odoo_sync import OdooClient, find_odoo_employee, find_odoo_leave_type


def test_connection():
    if not config.ODOO_ENABLED:
        print("ODOO_ENABLED=false in .env — set to true to test")
        return

    print(f"Testing connection to: {config.ODOO_URL}")
    print(f"Database: {config.ODOO_DB}")
    print(f"Username: {config.ODOO_USERNAME}")
    print()

    client = OdooClient()

    try:
        uid = client._authenticate()
        print(f"Authentication successful — user ID: {uid}")
    except Exception as e:
        print(f"Authentication failed: {e}")
        return

    print("\nTesting employee lookup...")
    emp = find_odoo_employee(client, config.ODOO_USERNAME)
    if emp:
        print(f"Found current user as employee — ID: {emp}")
    else:
        print("Current user not found as hr.employee (may be an admin-only account)")

    print("\nTesting leave type lookup...")
    for code in ["annual", "sick"]:
        lt = find_odoo_leave_type(client, code)
        if lt:
            print(f"Leave type '{code}' -> Odoo ID: {lt}")
        else:
            print(f"Leave type '{code}' not mapped — check _CODE_TO_ODOO_NAME in odoo_sync.py")

    print("\nRecord counts:")
    models = client._models()
    uid = client._uid
    for model in ["hr.employee", "hr.leave", "hr.leave.allocation", "hr.leave.type"]:
        try:
            count = models.execute_kw(
                config.ODOO_DB, uid, config.ODOO_PASSWORD,
                model, "search_count", [[]]
            )
            print(f"  {model}: {count} records")
        except Exception as e:
            print(f"  {model}: ERROR — {e}")

    print("\nConnection test complete")


if __name__ == "__main__":
    test_connection()
