"""
demo_reset.py — Clean slate before a demo run.

Resets:
  - Local DB: leave_requests, pending_actions, workflow_instances/events,
              audit_log, email_agent_rate_limit
  - Local DB: leave_balances.used_days → 0, employees.annual_leave_balance
              restored from leave_balances.allocated_days
  - Odoo: refuses + deletes all hr.leave records synced from this system

Run from the repo root (outside Docker):
  python backend/scripts/demo_reset.py

Or inside the backend container:
  python /app/scripts/demo_reset.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2
import config

# ── Local DB reset ─────────────────────────────────────────────────────────────

RESET_SQL = """
BEGIN;

-- Transactional data
DELETE FROM pending_actions    WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');
DELETE FROM workflow_events    WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');
DELETE FROM workflow_instances WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');
DELETE FROM leave_requests     WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');
DELETE FROM audit_log          WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');
DELETE FROM email_agent_rate_limit; -- no tenant_id, global table

-- Reset leave usage: zero out used_days in leave_balances
UPDATE leave_balances
SET used_days = 0
WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

-- Restore employees.annual_leave_balance from the annual leave allocation
UPDATE employees e
SET annual_leave_balance = COALESCE(
    (
        SELECT lb.allocated_days
        FROM leave_balances lb
        JOIN leave_types lt ON lt.id = lb.leave_type_id
        WHERE lb.employee_id = e.id
          AND lb.tenant_id   = e.tenant_id
          AND lt.code        = 'annual'
          AND lb.year        = 2026
        LIMIT 1
    ),
    21  -- default if no leave_balance row exists (e.g. Youssef FT-2024-099)
)
WHERE e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia');

COMMIT;
"""


def reset_local_db():
    print("── Local DB reset ───────────────────────────────")
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(RESET_SQL)
        conn.commit()

        # Report leave balances restored
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM leave_requests
                WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia')
                """
            )
            lr_count = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*) FROM pending_actions
                WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia')
                """
            )
            pa_count = cur.fetchone()[0]
            cur.execute(
                """
                SELECT e.employee_code, e.annual_leave_balance
                FROM employees e
                WHERE e.tenant_id = (SELECT id FROM tenants WHERE slug = 'fotopia')
                ORDER BY e.employee_code
                LIMIT 5
                """
            )
            sample = cur.fetchall()

        print(f"  leave_requests remaining : {lr_count}")
        print(f"  pending_actions remaining: {pa_count}")
        print("  Sample balances restored :")
        for code, bal in sample:
            print(f"    {code}: {bal} days")
        print("  ✓ Local DB clean")
    finally:
        conn.close()


# ── Odoo cleanup ───────────────────────────────────────────────────────────────

def reset_odoo():
    print("── Odoo cleanup ─────────────────────────────────")
    if not config.ODOO_ENABLED:
        print("  ODOO_ENABLED=false — skipping")
        return

    try:
        import xmlrpc.client
        common = xmlrpc.client.ServerProxy(f"{config.ODOO_URL}/xmlrpc/2/common")
        uid = common.authenticate(config.ODOO_DB, config.ODOO_USERNAME, config.ODOO_PASSWORD, {})
        if not uid:
            print("  ✗ Odoo auth failed — skipping")
            return
        models = xmlrpc.client.ServerProxy(f"{config.ODOO_URL}/xmlrpc/2/object")

        # Find all leaves we synced (description contains our marker)
        leave_ids = models.execute_kw(
            config.ODOO_DB, uid, config.ODOO_PASSWORD,
            "hr.leave", "search",
            [[["name", "ilike", "Leave synced from Fotopia HR"]]],
        )
        if not leave_ids:
            print("  No synced leaves found in Odoo — nothing to clean")
            return

        print(f"  Found {len(leave_ids)} synced leave(s): {leave_ids}")

        # Refuse approved ones first (Odoo state machine requires refuse before delete)
        try:
            models.execute_kw(
                config.ODOO_DB, uid, config.ODOO_PASSWORD,
                "hr.leave", "action_refuse", [leave_ids],
            )
            print(f"  Refused {len(leave_ids)} leave(s)")
        except Exception as e:
            print(f"  Refuse step: {e} (may already be in draft — continuing)")

        # Reset to draft so they can be deleted
        try:
            models.execute_kw(
                config.ODOO_DB, uid, config.ODOO_PASSWORD,
                "hr.leave", "action_draft", [leave_ids],
            )
        except Exception as e:
            print(f"  Draft reset step: {e} (continuing)")

        # Delete
        try:
            models.execute_kw(
                config.ODOO_DB, uid, config.ODOO_PASSWORD,
                "hr.leave", "unlink", [leave_ids],
            )
            print(f"  ✓ Deleted {len(leave_ids)} Odoo leave(s)")
        except Exception as e:
            print(f"  ✗ Delete failed: {e}")
            print("  You may need to refuse and delete manually in Odoo UI")

    except Exception as e:
        print(f"  ✗ Odoo connection error: {e}")
        print("  Local DB was still reset — Odoo cleanup skipped")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Demo Reset ===\n")
    reset_local_db()
    print()
    reset_odoo()
    print("\n=== Done — system is demo-ready ===\n")
