#!/usr/bin/env python3
"""
Sync our 25 demo employees from PostgreSQL into Odoo staging.
Safe to run multiple times — checks for existing records by work_email before creating.

Usage:
    docker exec fotopia-hr-agent-backend-1 python /app/scripts/sync_employees_to_odoo.py
"""
import os, sys, xmlrpc.client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config, psycopg2
from psycopg2.extras import RealDictCursor

DEPT_MAP = {
    'Engineering':      918,
    'Human Resources':  900,
    'Finance':          880,
    'Sales':            898,
    'Marketing':        913,
    'Product':          912,
    'IT':               891,
    'Executive':        853,
}

def get_our_employees():
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get tenant ID first, then set it as a string (no subquery in SET)
            cur.execute("SELECT id FROM tenants WHERE slug = 'fotopia'")
            tenant_id = str(cur.fetchone()['id'])
            cur.execute('SET ROLE fotopia_app')
            cur.execute(f"SET app.current_tenant_id = '{tenant_id}'")
            cur.execute("""
                SELECT e.employee_code, e.full_name, e.email, e.position,
                       e.department, e.start_date,
                       COALESCE(u.role, 'employee') AS role
                FROM employees e
                LEFT JOIN users u ON u.employee_id = e.id AND u.tenant_id = e.tenant_id
                WHERE e.tenant_id = %s
                ORDER BY e.start_date, e.employee_code
            """, (tenant_id,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_or_create_odoo_employee(models, db, uid, password, employee):
    email = employee.get('email', '')
    if not email or '@' not in email:
        return None, False
    existing = models.execute_kw(db, uid, password,
        'hr.employee', 'search_read',
        [[['work_email', '=', email]]],
        {'fields': ['id', 'name'], 'limit': 1})
    if existing:
        return existing[0]['id'], False
    dept_id = DEPT_MAP.get(employee.get('department', ''))
    values = {'name': employee['full_name'], 'work_email': email}
    if dept_id:
        values['department_id'] = dept_id

    odoo_id = models.execute_kw(db, uid, password, 'hr.employee', 'create', [values])
    return odoo_id, True

def main():
    if not config.ODOO_ENABLED:
        print("ODOO_ENABLED=false — set to true in .env first")
        return
    print(f"Connecting to Odoo: {config.ODOO_URL}")
    common = xmlrpc.client.ServerProxy(f"{config.ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(config.ODOO_DB, config.ODOO_USERNAME, config.ODOO_PASSWORD, {})
    if not uid:
        print("Authentication failed")
        return
    print(f"Authenticated — user ID: {uid}\n")
    models = xmlrpc.client.ServerProxy(f"{config.ODOO_URL}/xmlrpc/2/object")
    print("Reading employees from PostgreSQL...")
    employees = get_our_employees()
    print(f"Found {len(employees)} employees\n")
    created = skipped = failed = 0
    for emp in employees:
        try:
            odoo_id, was_created = get_or_create_odoo_employee(
                models, config.ODOO_DB, uid, config.ODOO_PASSWORD, emp)
            if odoo_id and was_created:
                print(f"  Created: {emp['full_name']} ({emp['email']}) -> Odoo ID {odoo_id}")
                created += 1
            elif odoo_id:
                print(f"  Exists:  {emp['full_name']} ({emp['email']}) -> Odoo ID {odoo_id}")
                skipped += 1
            else:
                print(f"  Skipped: {emp['full_name']} (no email)")
                failed += 1
        except Exception as e:
            print(f"  Failed:  {emp['full_name']} -- {e}")
            failed += 1
    print(f"\nDone: {created} created, {skipped} existed, {failed} failed")

if __name__ == "__main__":
    main()
