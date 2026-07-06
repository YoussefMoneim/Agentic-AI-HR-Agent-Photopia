"""
Validate knowledge base retrieval quality after seeding.
Tests English and Arabic queries against WIN Holding policy content.

Usage:
    docker exec fotopia-hr-agent-backend-1 python /app/scripts/test_knowledge_base.py
"""
import sys
sys.path.insert(0, '/app')

import config
import psycopg2
from knowledge.factory import get_knowledge_base


def get_fotopia_tenant_id() -> str:
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE slug = 'fotopia'")
            row = cur.fetchone()
            return str(row[0]) if row else None
    finally:
        conn.close()


def main():
    kb = get_knowledge_base()
    tenant_id = get_fotopia_tenant_id()
    if not tenant_id:
        print("ERROR: fotopia tenant not found")
        sys.exit(1)

    # Verify rows exist
    conn = psycopg2.connect(config.DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COUNT(embedding) FROM private_document_chunks "
            "WHERE tenant_id = %s", (tenant_id,)
        )
        total, with_embeddings = cur.fetchone()
    conn.close()

    print(f"Chunks in DB: {total} total, {with_embeddings} with embeddings")
    if total == 0:
        print("ERROR: no chunks found — run ingest_policies.py first")
        sys.exit(1)

    test_cases = [
        # (query, keyword_expected_in_result, role, description)
        ("What is the notice period for annual leave?",
         "notice",     "employee",   "EN: annual leave notice period"),
        ("How many sick leave days per year?",
         "sick",       "employee",   "EN: sick leave entitlement"),
        ("Requirements for Hajj leave eligibility",
         "hajj",       "employee",   "EN: Hajj leave requirements"),
        ("Medical certificate requirement sick leave",
         "certif",     "employee",   "EN: sick leave certificate"),
        ("كم عدد أيام الإجازة السنوية؟",
         "annual",     "employee",   "AR: annual leave days"),
        ("ما هي شروط إجازة الحج؟",
         "hajj",       "employee",   "AR: Hajj leave conditions"),
        ("Employee handbook onboarding",
         "employee",   "employee",   "EN: handbook content"),
    ]

    print(f"\nRunning {len(test_cases)} retrieval tests\n" + "="*60)
    passed = failed = 0

    for query, keyword, role, desc in test_cases:
        chunks = kb.search(
            query=query,
            tenant_id=tenant_id,
            user_role=role,
            top_k=2,
        )
        if not chunks:
            print(f"✗ {desc}")
            print(f"  NO RESULTS for: {query}")
            failed += 1
            continue

        top = chunks[0]
        found = keyword.lower() in top.chunk_text.lower()
        status = "✓" if found else "⚠"
        if found:
            passed += 1
        else:
            failed += 1

        print(f"{status} {desc}")
        print(f"  Score: {top.similarity_score:.3f} | Doc: {top.document_name}")
        print(f"  Preview: {top.chunk_text[:120].strip()}...")

    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("\n✓ Vector knowledge base is working correctly")
        print("  The HR agent will now answer policy questions from documents.")
    elif failed <= 2:
        print("\n⚠ Mostly working — review failed queries above")
    else:
        print("\n✗ Poor results — check seeding and chunking")


if __name__ == "__main__":
    main()
