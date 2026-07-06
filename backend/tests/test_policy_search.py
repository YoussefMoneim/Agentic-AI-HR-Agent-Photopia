"""
Integration tests for SearchPolicyTool and the search_policy DataSource method.

Tests insert and clean up chunks directly via policy_db_conn — no dependency on
real policy files being present or the ingestion script having run.

These tests run against their own throwaway tenant (policy_tenant_id), not the
shared fotopia tenant_id fixture. The fotopia tenant now has real Voyage
embeddings (backend/scripts/ingest_policies.py has been run against it), which
would make PgvectorKnowledgeBase.search() take the live vector-search branch
for every query — real, rate-limited Voyage API calls on every test run.
Since this tenant never gets embeddings, search() always takes the
deterministic full-text fallback path these tests are designed to exercise.

All pre-filter ACL checks happen in the SQL WHERE clause (allowed_roles && caller_roles),
which means restricted chunks are never returned to lower-privileged callers — they
are filtered by the database, not by Python post-processing.
"""

import uuid

import psycopg2
import pytest

from tools.base import ToolContext


@pytest.fixture(scope="module")
def policy_tenant_id(database_url):
    """Throwaway tenant, isolated from the real fotopia tenant's embeddings."""
    conn = psycopg2.connect(database_url)
    slug = f"test-policy-search-{uuid.uuid4().hex[:12]}"
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (name, slug) VALUES (%s, %s) RETURNING id",
                ("Test Policy Search Tenant", slug),
            )
            tid = str(cur.fetchone()[0])
    try:
        yield tid
    finally:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM private_document_chunks WHERE tenant_id = %s", (tid,))
                cur.execute("DELETE FROM tenants WHERE id = %s", (tid,))
        conn.close()


@pytest.fixture
def policy_db_conn(database_url, policy_tenant_id):
    """Raw psycopg2 connection scoped to the isolated policy-search tenant."""
    conn = psycopg2.connect(database_url)
    with conn.cursor() as cur:
        cur.execute("SET app.current_tenant_id = %s", (policy_tenant_id,))
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_test_chunks(policy_db_conn):
    """Remove test chunks before and after each test."""
    marker = "test_policy_search_marker"
    with policy_db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM private_document_chunks WHERE document_id LIKE %s",
            (f"%{marker}%",),
        )
    policy_db_conn.commit()
    yield
    with policy_db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM private_document_chunks WHERE document_id LIKE %s",
            (f"%{marker}%",),
        )
    policy_db_conn.commit()


def _insert_chunk(db_conn, tenant_id, document_id, content, allowed_roles, classified_at="now()"):
    """Helper: insert a single test chunk and commit."""
    classified_expr = "now()" if classified_at == "now()" else "NULL"
    with db_conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s,
                    'public_tenant', %s, 'policies/test.md', {classified_expr})
            """,
            (tenant_id, document_id, content, allowed_roles),
        )
    db_conn.commit()


def _make_ctx(tenant_id, role="hr_manager") -> ToolContext:
    return ToolContext(
        tenant_id=tenant_id,
        user_id="test-user",
        role=role,
        employee_code="EMP001",
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_search_returns_relevant_chunk(policy_db_conn, registry, policy_tenant_id):
    """Inserting a chunk with known keyword and searching for that keyword returns it."""
    doc_id = "doc_test_policy_search_marker_relevant"
    _insert_chunk(
        policy_db_conn, policy_tenant_id, doc_id,
        "Employees are entitled to 21 annual leave working days per year.",
        ["employee", "hr_staff", "hr_manager", "admin"],
    )

    ctx = _make_ctx(policy_tenant_id, role="hr_manager")
    result = registry.execute("search_policy", {"query": "annual leave days"}, ctx)

    assert result.success is True
    assert len(result.data["results"]) >= 1
    contents = [r["content"] for r in result.data["results"]]
    assert any("annual leave" in c.lower() for c in contents)


def test_employee_cannot_retrieve_enterprise_chunk(policy_db_conn, registry, policy_tenant_id):
    """A chunk restricted to hr_manager/admin is invisible to employee callers."""
    doc_id = "doc_test_policy_search_marker_enterprise"
    unique_token = "TESTMARKERA7F9B"  # unique token not in the real policy corpus
    with policy_db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'restricted', %s, 'policies/enterprise/test.md', now())
            """,
            (policy_tenant_id, doc_id, f"Confidential {unique_token} salary band governance policy.", ["hr_manager", "admin"]),
        )
    policy_db_conn.commit()

    ctx = _make_ctx(policy_tenant_id, role="employee")
    result = registry.execute("search_policy", {"query": unique_token}, ctx)

    assert result.success is True
    assert result.data["results"] == []


def test_hr_manager_can_retrieve_enterprise_chunk(policy_db_conn, registry, policy_tenant_id):
    """The same restricted chunk is visible to hr_manager callers."""
    doc_id = "doc_test_policy_search_marker_enterprise_mgr"
    with policy_db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'restricted', %s, 'policies/enterprise/test.md', now())
            """,
            (policy_tenant_id, doc_id, "Restricted governance framework for agentic systems.", ["hr_manager", "admin"]),
        )
    policy_db_conn.commit()

    ctx = _make_ctx(policy_tenant_id, role="hr_manager")
    result = registry.execute("search_policy", {"query": "governance framework agentic"}, ctx)

    assert result.success is True
    assert len(result.data["results"]) >= 1


def test_search_no_results_returns_empty_list(policy_db_conn, registry, policy_tenant_id):
    """Searching for nonsense text returns success with an empty results list."""
    ctx = _make_ctx(policy_tenant_id, role="hr_manager")
    # Use truly invented tokens with no real English stems so tsvector produces
    # no lexemes → or_query IS NULL → WHERE clause fails → 0 rows (not falling
    # through to "policy"/"section" which are real words in the corpus).
    result = registry.execute(
        "search_policy",
        {"query": "xzzqwvvv zzzyxwvu qpqpqpq"},
        ctx,
    )

    assert result.success is True
    assert result.data["results"] == []
    assert "message" in result.data


def test_classified_at_null_excluded(policy_db_conn, registry, policy_tenant_id):
    """Chunks with classified_at = NULL (quarantine) are never returned by search."""
    doc_id = "doc_test_policy_search_marker_quarantine"
    with policy_db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'public_tenant', %s, 'policies/public/test.md', NULL)
            """,
            (policy_tenant_id, doc_id, "Quarantined chunk about parental entitlements.", ["employee", "hr_staff", "hr_manager", "admin"]),
        )
    policy_db_conn.commit()

    ctx = _make_ctx(policy_tenant_id, role="hr_manager")
    result = registry.execute("search_policy", {"query": "parental entitlements"}, ctx)

    assert result.success is True
    # The quarantined chunk must not appear even though it matches the query
    contents = [r["content"] for r in result.data["results"]]
    assert not any("Quarantined chunk" in c for c in contents)


def test_pre_filter_before_text_search(policy_db_conn, registry, policy_tenant_id):
    """ACL overlap check happens in SQL WHERE — restricted chunk never reaches Python even if text matches."""
    doc_id = "doc_test_policy_search_marker_prefilter"
    keyword = "uniqueprefilterterm9371"
    with policy_db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'restricted', %s, 'policies/enterprise/test.md', now())
            """,
            (policy_tenant_id, doc_id, f"Restricted section about {keyword} for managers only.", ["hr_manager", "admin"]),
        )
    policy_db_conn.commit()

    ctx = _make_ctx(policy_tenant_id, role="employee")
    result = registry.execute("search_policy", {"query": keyword}, ctx)

    assert result.success is True
    assert result.data["results"] == []
