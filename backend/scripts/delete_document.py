"""
delete_document.py — Remove a document and all its chunks from the knowledge base.

Usage (from repo root, outside Docker):
  python backend/scripts/delete_document.py <document_id>

Or inside the backend container:
  python /app/scripts/delete_document.py <document_id>

Example:
  python backend/scripts/delete_document.py leaves_policy_egypt_v2
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2
import config
from knowledge.factory import get_knowledge_base

def get_fotopia_tenant_id() -> str:
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE slug = 'fotopia'")
            row = cur.fetchone()
            if row is None:
                print("ERROR: fotopia tenant not found", file=sys.stderr)
                sys.exit(1)
            return str(row[0])
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python delete_document.py <document_id>")
        sys.exit(1)

    document_id = sys.argv[1]
    tenant_id = get_fotopia_tenant_id()

    kb = get_knowledge_base()
    count = kb.delete_document(document_id, tenant_id)

    if count == 0:
        print(f"No chunks found for document_id='{document_id}' — nothing deleted.")
    else:
        print(f"Deleted {count} chunks for document_id='{document_id}'.")
