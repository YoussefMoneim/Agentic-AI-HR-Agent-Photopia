"""
Ingestion script: walks backend/policies/, chunks documents,
generates Voyage AI embeddings, and stores in private_document_chunks.

Run:
    docker exec fotopia-hr-agent-backend-1 python scripts/ingest_policies.py

Idempotent: deletes existing chunks for (tenant_id, document_id) before re-inserting.
Empty files are skipped.
Requires VOYAGE_API_KEY in environment.
"""

import os
import sys
from pathlib import Path

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

# Add app root to path so knowledge/ imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from knowledge.factory import get_knowledge_base

POLICIES_DIR = Path(__file__).parent.parent / "policies"

ACL_MAP = {
    "public": {
        "access_level": "all",
        "document_type": "policy",
    },
    "enterprise": {
        "access_level": "hr_manager",
        "document_type": "policy",
    },
}


def get_fotopia_tenant_id() -> str:
    conn = psycopg2.connect(DATABASE_URL)
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


def main():
    if not config.VOYAGE_API_KEY or "your_voyage" in config.VOYAGE_API_KEY:
        print("ERROR: VOYAGE_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    tenant_id = get_fotopia_tenant_id()
    kb = get_knowledge_base()
    print(f"Ingesting policies for tenant: {tenant_id}\n")

    total_chunks = 0
    total_files = 0

    for md_file in sorted(POLICIES_DIR.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8").strip()
        if not content:
            print(f"  {md_file.name}: skipped (empty)")
            continue

        parent_dir = md_file.parent.name
        acl = ACL_MAP.get(parent_dir)
        if acl is None:
            print(f"  {md_file.name}: skipped (unknown dir '{parent_dir}')")
            continue

        # Use stem as document_id for consistency with existing convention
        document_name = md_file.stem
        source_url = str(md_file.relative_to(POLICIES_DIR.parent))

        print(f"  {md_file.name} ({len(content)} chars)...")

        result = kb.ingest(
            content=content,
            document_name=document_name,
            document_type=acl["document_type"],
            tenant_id=tenant_id,
            access_level=acl["access_level"],
            ingested_by="system:ingest_policies",
            metadata={"source_path": str(md_file)},
            source_url=source_url,
        )

        if result.success:
            print(
                f"  ✓ {result.document_name}: "
                f"{result.chunks_created} chunks"
                + (f", {result.chunks_replaced} replaced" if result.chunks_replaced else "")
            )
            total_chunks += result.chunks_created
            total_files += 1
        else:
            print(f"  ✗ FAILED: {result.error}")

    print(f"\nDone: {total_files} files, {total_chunks} total chunks")
    print("\nNext: run validation")
    print(
        "  docker exec fotopia-hr-agent-backend-1 "
        "python /app/scripts/test_knowledge_base.py"
    )


if __name__ == "__main__":
    main()
