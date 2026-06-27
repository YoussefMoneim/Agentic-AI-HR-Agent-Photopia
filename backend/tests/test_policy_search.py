"""
Integration tests for SearchPolicyTool and the search_policy DataSource method.

Tests insert and clean up chunks directly via db_conn — no dependency on real
policy files being present or the ingestion script having run.

All pre-filter ACL checks happen in the SQL WHERE clause (allowed_roles && caller_roles),
which means restricted chunks are never returned to lower-privileged callers — they
are filtered by the database, not by Python post-processing.
"""

import uuid

import pytest

from tools.base import ToolContext

TENANT_UUID = None  # resolved in fixture scope


@pytest.fixture(autouse=True)
def clean_test_chunks(db_conn):
    """Remove test chunks before and after each test."""
    marker = "test_policy_search_marker"
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM private_document_chunks WHERE document_id LIKE %s",
            (f"%{marker}%",),
        )
    db_conn.commit()
    yield
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM private_document_chunks WHERE document_id LIKE %s",
            (f"%{marker}%",),
        )
    db_conn.commit()


def _get_tenant_id(db_conn) -> str:
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM tenants WHERE slug = 'fotopia'")
        row = cur.fetchone()
    assert row is not None, "fotopia tenant must exist for policy search tests"
    return str(row[0])


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


def test_search_returns_relevant_chunk(db_conn, registry, tenant_id):
    """Inserting a chunk with known keyword and searching for that keyword returns it."""
    doc_id = "doc_test_policy_search_marker_relevant"
    _insert_chunk(
        db_conn, tenant_id, doc_id,
        "Employees are entitled to 21 annual leave working days per year.",
        ["employee", "hr_staff", "hr_manager", "admin"],
    )

    ctx = _make_ctx(tenant_id, role="hr_manager")
    result = registry.execute("search_policy", {"query": "annual leave days"}, ctx)

    assert result.success is True
    assert len(result.data["results"]) >= 1
    contents = [r["content"] for r in result.data["results"]]
    assert any("annual leave" in c.lower() for c in contents)


def test_employee_cannot_retrieve_enterprise_chunk(db_conn, registry, tenant_id):
    """A chunk restricted to hr_manager/admin is invisible to employee callers."""
    doc_id = "doc_test_policy_search_marker_enterprise"
    unique_token = "TESTMARKERA7F9B"  # unique token not in the real policy corpus
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'restricted', %s, 'policies/enterprise/test.md', now())
            """,
            (tenant_id, doc_id, f"Confidential {unique_token} salary band governance policy.", ["hr_manager", "admin"]),
        )
    db_conn.commit()

    ctx = _make_ctx(tenant_id, role="employee")
    result = registry.execute("search_policy", {"query": unique_token}, ctx)

    assert result.success is True
    assert result.data["results"] == []


def test_hr_manager_can_retrieve_enterprise_chunk(db_conn, registry, tenant_id):
    """The same restricted chunk is visible to hr_manager callers."""
    doc_id = "doc_test_policy_search_marker_enterprise_mgr"
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'restricted', %s, 'policies/enterprise/test.md', now())
            """,
            (tenant_id, doc_id, "Restricted governance framework for agentic systems.", ["hr_manager", "admin"]),
        )
    db_conn.commit()

    ctx = _make_ctx(tenant_id, role="hr_manager")
    result = registry.execute("search_policy", {"query": "governance framework agentic"}, ctx)

    assert result.success is True
    assert len(result.data["results"]) >= 1


def test_search_no_results_returns_empty_list(db_conn, registry, tenant_id):
    """Searching for nonsense text returns success with an empty results list."""
    ctx = _make_ctx(tenant_id, role="hr_manager")
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


def test_classified_at_null_excluded(db_conn, registry, tenant_id):
    """Chunks with classified_at = NULL (quarantine) are never returned by search."""
    doc_id = "doc_test_policy_search_marker_quarantine"
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'public_tenant', %s, 'policies/public/test.md', NULL)
            """,
            (tenant_id, doc_id, "Quarantined chunk about parental entitlements.", ["employee", "hr_staff", "hr_manager", "admin"]),
        )
    db_conn.commit()

    ctx = _make_ctx(tenant_id, role="hr_manager")
    result = registry.execute("search_policy", {"query": "parental entitlements"}, ctx)

    assert result.success is True
    # The quarantined chunk must not appear even though it matches the query
    contents = [r["content"] for r in result.data["results"]]
    assert not any("Quarantined chunk" in c for c in contents)


def test_pre_filter_before_text_search(db_conn, registry, tenant_id):
    """ACL overlap check happens in SQL WHERE — restricted chunk never reaches Python even if text matches."""
    doc_id = "doc_test_policy_search_marker_prefilter"
    keyword = "uniqueprefilterterm9371"
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO private_document_chunks
                (tenant_id, document_id, chunk_index, content,
                 sensitivity, allowed_roles, source_file, classified_at)
            VALUES (%s, %s, 0, %s, 'restricted', %s, 'policies/enterprise/test.md', now())
            """,
            (tenant_id, doc_id, f"Restricted section about {keyword} for managers only.", ["hr_manager", "admin"]),
        )
    db_conn.commit()

    ctx = _make_ctx(tenant_id, role="employee")
    result = registry.execute("search_policy", {"query": keyword}, ctx)

    assert result.success is True
    assert result.data["results"] == []
