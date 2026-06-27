"""
Ingestion script: walks backend/policies/, chunks by ## heading boundaries,
and upserts chunks into private_document_chunks for the fotopia tenant.

Run:
    docker exec fotopia-hr-agent-backend-1 python scripts/ingest_policies.py

Idempotent: deletes existing chunks for (tenant_id, source_file) before re-inserting.
Empty files are skipped — placeholders stay silent until real content is added.
"""

import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
    sys.exit(1)

POLICIES_DIR = Path(__file__).parent.parent / "policies"
MAX_CHUNK_CHARS = 3200

ACL_MAP = {
    "public": {
        "sensitivity": "public_tenant",
        "allowed_roles": ["employee", "hr_staff", "hr_manager", "admin"],
    },
    "enterprise": {
        "sensitivity": "restricted",
        "allowed_roles": ["hr_manager", "admin"],
    },
}


def split_into_chunks(text: str) -> list[str]:
    """Split at ## headings; further split oversized sections at blank lines."""
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= MAX_CHUNK_CHARS:
            chunks.append(section)
        else:
            # Split at blank lines, keeping heading with first sub-chunk
            paragraphs = re.split(r"\n{2,}", section)
            current = ""
            for para in paragraphs:
                if current and len(current) + len(para) + 2 > MAX_CHUNK_CHARS:
                    chunks.append(current.strip())
                    current = para
                else:
                    current = (current + "\n\n" + para).strip() if current else para
            if current:
                chunks.append(current.strip())
    return chunks


def ingest():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM tenants WHERE slug = 'fotopia'")
            row = cur.fetchone()
            if row is None:
                print("ERROR: fotopia tenant not found in DB", file=sys.stderr)
                sys.exit(1)
            tenant_id = str(row["id"])

        total_inserted = 0

        for md_file in sorted(POLICIES_DIR.rglob("*.md")):
            content = md_file.read_text(encoding="utf-8").strip()
            if not content:
                print(f"  {md_file.name}: skipped (empty)")
                continue

            parent_dir = md_file.parent.name
            acl = ACL_MAP.get(parent_dir)
            if acl is None:
                print(f"  {md_file.name}: skipped (unknown ACL tier '{parent_dir}')")
                continue

            source_file = str(md_file.relative_to(POLICIES_DIR.parent))
            document_id = md_file.stem
            chunks = split_into_chunks(content)

            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM private_document_chunks WHERE tenant_id = %s AND source_file = %s",
                        (tenant_id, source_file),
                    )
                    for idx, chunk_text in enumerate(chunks):
                        cur.execute(
                            """
                            INSERT INTO private_document_chunks
                                (tenant_id, document_id, chunk_index, content,
                                 sensitivity, allowed_roles, source_file, classified_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                            """,
                            (
                                tenant_id,
                                document_id,
                                idx,
                                chunk_text,
                                acl["sensitivity"],
                                acl["allowed_roles"],
                                source_file,
                            ),
                        )

            print(f"  {md_file.name}: {len(chunks)} chunks inserted (sensitivity={acl['sensitivity']})")
            total_inserted += len(chunks)

        print(f"\nDone. Total chunks inserted: {total_inserted}")
    finally:
        conn.close()


if __name__ == "__main__":
    ingest()
