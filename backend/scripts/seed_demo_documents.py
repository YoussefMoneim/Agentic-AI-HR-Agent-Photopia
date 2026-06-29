#!/usr/bin/env python3
"""Seed two demo documents into demo_documents. Safe to run multiple times (ON CONFLICT DO NOTHING)."""
import json
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

DOC_1_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
DOC_1_FILENAME = "salary_certificate_ahmed_hassan.pdf"
DOC_1_CONTENT = """\
SALARY CERTIFICATE

Date: 15 March 2025
Reference: SC-2025-0847

TO WHOM IT MAY CONCERN

This is to certify that Mr. Ahmed Hassan (National ID: 29901011234567) is a full-time
employee of Fotopia Technologies, holding the position of Senior Software Engineer in
the Research & Development department.

Employment Details:
- Employee Code: EMP001
- Date of Joining: 12 January 2021
- Employment Type: Full-time, Permanent

Compensation Details (Monthly):
- Basic Salary: EGP 45,000
- Housing Allowance: EGP 8,000
- Transportation Allowance: EGP 2,500
- Total Monthly Compensation: EGP 55,500

This certificate is issued upon the employee's request for the purpose of bank account
opening and financial verification.

Authorized Signatory:
Nourhan Hosny
HR Manager, Fotopia Technologies
"""
DOC_1_SCAN = {
    "salary": {
        "examples": ["basic salary", "EGP 45,000", "housing allowance"],
        "llm_verdict": {
            "is_sensitive": True,
            "confidence": "high",
            "reason": "Document contains personal compensation data including salary figures and allowances for a named individual.",
        },
    },
    "national_id": {
        "examples": ["29901011234567"],
        "llm_verdict": {
            "is_sensitive": True,
            "confidence": "high",
            "reason": "Document contains a 14-digit Egyptian national ID number.",
        },
    },
}
DOC_1_IS_SENSITIVE = True

DOC_2_ID = "b2c3d4e5-f6a7-8901-bcde-fa2345678901"
DOC_2_FILENAME = "q3_planning_meeting_agenda.txt"
DOC_2_CONTENT = """\
Q3 2025 PLANNING MEETING — AGENDA

Date: Monday, 7 July 2025
Time: 10:00 AM – 12:00 PM (Cairo time)
Location: Conference Room B / Google Meet (link TBD)
Facilitator: Raef Eid

ATTENDEES
- Raef Eid (Founder)
- Dr. Ahmed El-Yazbi (R&D AI Director)
- Youssef Abdelmoneim (AI/ML)
- Nourhan Hosny (HR)
- Finance representative (TBC)

AGENDA ITEMS

1. Q2 Retrospective (20 min)
   - Delivery milestones hit / missed
   - Budget vs actual spend
   - Team feedback summary

2. Q3 OKRs and Priorities (30 min)
   - HR Agent: Phase 2 scope and go-live targets
   - DigitizeMe integration milestone
   - Hiring plan: 2 backend engineers, 1 UX designer

3. Risk Review (15 min)
   - PDPL cross-border transfer status
   - ZDR agreement timeline with Anthropic
   - Pilot client readiness (Nourhan to update)

4. Resource Allocation (20 min)
   - Sprint assignments for July–September
   - Tooling budget requests

5. AOB / Open Floor (15 min)

ACTION ITEMS FROM LAST MEETING
- [Youssef] Complete leave workflow engine — DONE
- [Nourhan] Confirm pilot user list — IN PROGRESS
- [Dr. Ahmed] PDPL legal review — PENDING

Next meeting: Monday, 11 August 2025
"""
DOC_2_SCAN: dict = {}
DOC_2_IS_SENSITIVE = False

INSERT_SQL = """
    INSERT INTO demo_documents
        (id, tenant_id, uploaded_by, filename, content_text,
         file_size_bytes, sensitivity_scan, is_sensitive, is_demo)
    VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s, TRUE)
    ON CONFLICT (id) DO NOTHING
"""


def seed() -> None:
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM tenants WHERE slug = 'fotopia'")
            row = cur.fetchone()
            if not row:
                raise RuntimeError("fotopia tenant not found — run docker compose up first")
            tenant_id = str(row["id"])

            cur.execute(
                "SELECT u.id FROM users u "
                "JOIN employees e ON e.id = u.employee_id "
                "WHERE e.employee_code = 'FT-2021-003' AND u.tenant_id = %s",
                (tenant_id,),
            )
            nourhan = cur.fetchone()
            uploaded_by = str(nourhan["id"]) if nourhan else tenant_id

            cur.execute("SET ROLE fotopia_app")
            cur.execute("SET app.current_tenant_id = %s", (tenant_id,))

            for doc_id, filename, content, scan, sensitive in [
                (DOC_1_ID, DOC_1_FILENAME, DOC_1_CONTENT, DOC_1_SCAN, DOC_1_IS_SENSITIVE),
                (DOC_2_ID, DOC_2_FILENAME, DOC_2_CONTENT, DOC_2_SCAN, DOC_2_IS_SENSITIVE),
            ]:
                cur.execute(
                    INSERT_SQL,
                    (
                        doc_id,
                        tenant_id,
                        uploaded_by,
                        filename,
                        content,
                        len(content.encode()),
                        json.dumps(scan),
                        sensitive,
                    ),
                )
                status = "inserted" if cur.rowcount else "already exists"
                print(f"  {filename}: {status}")

        conn.commit()
        print("\nSeed complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
