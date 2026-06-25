"""
scripts/seed_users.py — Create demo login accounts.

Applies the password_hash column migration and inserts demo users.
Safe to re-run (uses ON CONFLICT DO NOTHING).

Demo credentials:
  saif.hassan@fotopia.ai    / demo123  (employee)
  nourhan.hosny@fotopia.ai  / demo123  (hr_manager)
  omar.alsayed@fotopia.ai   / demo123  (employee)
"""

import os
import sys

import bcrypt
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
    sys.exit(1)

DEMO_PASSWORD = "demo123"

DEMO_USERS = [
    {"email": "saif.hassan@fotopia.ai",   "full_name": "Saif Ahmed Hassan", "role": "employee"},
    {"email": "nourhan.hosny@fotopia.ai",  "full_name": "Nourhan Hosny",     "role": "hr_manager"},
    {"email": "omar.alsayed@fotopia.ai",   "full_name": "Omar Alsayed",      "role": "employee"},
]

password_hash = bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode()

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False
try:
    with conn.cursor() as cur:
        # Apply migration: add password_hash column if it doesn't exist yet
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS password_hash TEXT
        """)

        # Get tenant ID
        cur.execute("SELECT id FROM tenants WHERE slug = 'fotopia'")
        row = cur.fetchone()
        if not row:
            print("ERROR: tenant 'fotopia' not found. Did you run seed.sql first?", file=sys.stderr)
            sys.exit(1)
        tenant_id = str(row[0])
        cur.execute("SET app.current_tenant_id = %s", (tenant_id,))

        inserted = 0
        for u in DEMO_USERS:
            # Look up the employee record to get employee_id and employee_code
            cur.execute(
                "SELECT id, employee_code FROM employees WHERE tenant_id = %s AND email = %s",
                (tenant_id, u["email"]),
            )
            emp = cur.fetchone()
            employee_id = str(emp[0]) if emp else None

            cur.execute(
                """
                INSERT INTO users (tenant_id, email, full_name, role, employee_id, password_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, email) DO UPDATE
                  SET password_hash = EXCLUDED.password_hash,
                      role = EXCLUDED.role,
                      employee_id = EXCLUDED.employee_id
                """,
                (tenant_id, u["email"], u["full_name"], u["role"], employee_id, password_hash),
            )
            inserted += 1
            print(f"  ✓ {u['email']} ({u['role']})")

    conn.commit()
    print(f"\nDone. {inserted} users seeded with password '{DEMO_PASSWORD}'.")
except Exception as exc:
    conn.rollback()
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
