"""
Tests for agent/onboarding.py — the Week-1 5-question onboarding state machine.

Most tests use a mocked DataSource (a stateful in-memory fake, mirroring the
`stored` dict pattern in tests/test_email_agent.py's TestTwoEmailThreadRetainsContext)
and a mocked ToolRegistry. TestOnboardingSessionRLS uses the real DB via the
shared conftest.py fixtures to prove tenant isolation actually holds.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest

from agent import onboarding
from tools.base import ToolContext, ToolResult


def _ctx(role="hr_manager", user_id="test-user"):
    return ToolContext(
        tenant_id="tenant-uuid", user_id=user_id, role=role,
        employee_code="EMP002", display_name="Noura Al Rashidi",
    )


def _make_fake_ds():
    """A stateful fake DataSource backing onboarding_sessions in a plain dict,
    keyed by (tenant_id, session_id) — enough to drive the real state machine
    logic without a live DB."""
    store: dict[tuple[str, str], dict] = {}
    ds = MagicMock()

    def get(tenant_id, session_id):
        row = store.get((tenant_id, session_id))
        return dict(row) if row else None

    def create(tenant_id, session_id, started_by_user_id):
        row = {
            "status": "in_progress", "current_step": 1, "answers": {},
            "started_by_user_id": started_by_user_id,
        }
        store[(tenant_id, session_id)] = row
        return dict(row)

    def update(tenant_id, session_id, current_step=None, status=None, answers=None):
        row = store[(tenant_id, session_id)]
        if current_step is not None:
            row["current_step"] = current_step
        if status is not None:
            row["status"] = status
        if answers is not None:
            row["answers"] = {**row["answers"], **answers}

    ds.get_onboarding_session.side_effect = get
    ds.create_onboarding_session.side_effect = create
    ds.update_onboarding_session.side_effect = update
    return ds


# ── Trigger / role gating ───────────────────────────────────────────────────

class TestTrigger:

    def test_non_trigger_message_with_no_session_returns_none(self):
        ds = _make_fake_ds()
        result = onboarding.maybe_handle_turn("hello", _ctx(), "sid-1", ds, MagicMock())
        assert result is None
        ds.create_onboarding_session.assert_not_called()

    def test_employee_role_denied_no_session_created(self):
        ds = _make_fake_ds()
        result = onboarding.maybe_handle_turn(
            "Set up your agent", _ctx(role="employee"), "sid-1", ds, MagicMock(),
        )
        assert "hr manager or admin" in result.text.lower()
        ds.create_onboarding_session.assert_not_called()

    def test_trigger_case_insensitive_and_whitespace_tolerant(self):
        ds = _make_fake_ds()
        result = onboarding.maybe_handle_turn(
            "  SET UP your Agent  ", _ctx(), "sid-1", ds, MagicMock(),
        )
        assert result is not None
        assert "company name" in result.text.lower()

    def test_admin_role_allowed(self):
        ds = _make_fake_ds()
        result = onboarding.maybe_handle_turn(
            "Set up your agent", _ctx(role="admin"), "sid-1", ds, MagicMock(),
        )
        assert "company name" in result.text.lower()

    def test_completed_session_falls_through_to_none(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-1", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-1", status="completed")
        result = onboarding.maybe_handle_turn(
            "what's my leave balance?", _ctx(), "sid-1", ds, MagicMock(),
        )
        assert result is None


# ── Full 5-step happy path ──────────────────────────────────────────────────

class TestFullFlow:

    @patch("agent.onboarding.ClaudeProvider")
    def test_all_five_steps_end_to_end(self, mock_cls):
        import json
        mock_cls.return_value.classify.return_value = json.dumps(
            {"company_name": "Fotopia Technologies", "jurisdiction": "Egypt"}
        )

        ds = _make_fake_ds()
        registry = MagicMock()
        registry.execute.side_effect = lambda name, args, ctx: {
            "connect_odoo": ToolResult(success=True, data={"employee_count": 32}),
            "ingest_policy_document": ToolResult(
                success=True, data={"document_id": "doc-1", "chunks_created": 3},
            ),
        }[name]

        sid = "sid-full"
        r1 = onboarding.maybe_handle_turn("Set up your agent", _ctx(), sid, ds, registry)
        assert "company name" in r1.text.lower()

        r2 = onboarding.maybe_handle_turn("Fotopia Technologies, Egypt", _ctx(), sid, ds, registry)
        assert "odoo" in r2.text.lower()

        r3 = onboarding.maybe_handle_turn("yes", _ctx(), sid, ds, registry)
        assert "32 employees" in r3.text
        assert "document" in r3.text.lower()

        r4 = onboarding.maybe_handle_turn("upload", _ctx(), sid, ds, registry)
        assert r4.awaiting_upload is True
        assert "handbook" in r4.text.lower()

        r5 = onboarding.handle_document_upload(
            "handbook content", "handbook.pdf", _ctx(), sid, ds, registry,
        )
        assert r5.awaiting_upload is True
        assert "leave policy" in r5.text.lower()

        r6 = onboarding.handle_document_upload(
            "leave policy content", "leave_policy.pdf", _ctx(), sid, ds, registry,
        )
        assert r6.awaiting_upload is False
        assert "ready" in r6.text.lower()
        assert "Fotopia Technologies" in r6.text

        final = ds.get_onboarding_session("tenant-uuid", sid)
        assert final["status"] == "completed"
        assert final["answers"]["odoo_connected"] is True
        assert final["answers"]["document_source"] == "upload"


# ── Individual step fallback paths ──────────────────────────────────────────

class TestStepFallbacks:

    def test_step1_extraction_failure_falls_back_to_comma_split(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-2", "test-user")
        with patch("agent.onboarding.ClaudeProvider", side_effect=Exception("LLM down")):
            result = onboarding.maybe_handle_turn(
                "Acme Corp, United Arab Emirates", _ctx(), "sid-2", ds, MagicMock(),
            )
        assert "odoo" in result.text.lower()  # progressed to Q2 despite LLM failure
        answers = ds.get_onboarding_session("tenant-uuid", "sid-2")["answers"]
        assert answers["company_name"] == "Acme Corp"
        assert answers["jurisdiction"] == "United Arab Emirates"

    def test_step2_skip_keyword_does_not_call_odoo_tool(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-3", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-3", current_step=2)
        registry = MagicMock()
        result = onboarding.maybe_handle_turn("skip for now", _ctx(), "sid-3", ds, registry)
        registry.execute.assert_not_called()
        assert "document" in result.text.lower()
        assert ds.get_onboarding_session("tenant-uuid", "sid-3")["answers"]["odoo_connected"] is False

    def test_step2_odoo_failure_still_progresses(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-4", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-4", current_step=2)
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=False, error="connection refused")
        result = onboarding.maybe_handle_turn("yes please", _ctx(), "sid-4", ds, registry)
        assert "couldn't connect" in result.text.lower()
        assert "document" in result.text.lower()  # still asks Q3, doesn't get stuck
        assert ds.get_onboarding_session("tenant-uuid", "sid-4")["answers"]["odoo_connected"] is False

    def test_step3_sharepoint_answer_falls_back_to_upload_for_week1(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-5", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-5", current_step=3)
        result = onboarding.maybe_handle_turn("we use SharePoint", _ctx(), "sid-5", ds, MagicMock())
        assert result.awaiting_upload is True
        assert "sharepoint" in result.text.lower()
        assert ds.get_onboarding_session("tenant-uuid", "sid-5")["answers"]["document_source"] == "sharepoint"

    def test_text_reply_while_awaiting_upload_reprompts_without_advancing(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-6", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-6", current_step=4)
        result = onboarding.maybe_handle_turn("here's the file", _ctx(), "sid-6", ds, MagicMock())
        assert result.awaiting_upload is True
        assert ds.get_onboarding_session("tenant-uuid", "sid-6")["current_step"] == 4  # unchanged

    def test_upload_with_no_active_session_is_rejected(self):
        ds = _make_fake_ds()
        result = onboarding.handle_document_upload(
            "content", "file.pdf", _ctx(), "sid-nonexistent", ds, MagicMock(),
        )
        assert "no document upload is expected" in result.text.lower()

    def test_upload_ingestion_failure_reprompts_for_retry(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-7", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-7", current_step=4)
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=False, error="No extractable text.")
        result = onboarding.handle_document_upload(
            "", "scanned.pdf", _ctx(), "sid-7", ds, registry,
        )
        assert result.awaiting_upload is True
        assert "couldn't process" in result.text.lower()
        assert ds.get_onboarding_session("tenant-uuid", "sid-7")["current_step"] == 4  # unchanged


# ── Real DB / RLS ────────────────────────────────────────────────────────────

class TestOnboardingSessionRLS:

    def test_create_get_update_round_trip(self, ds, tenant_id, database_url):
        session_id = "rls-test-session"
        try:
            created = ds.create_onboarding_session(tenant_id, session_id, "test-user")
            assert created["status"] == "in_progress"
            assert created["current_step"] == 1

            ds.update_onboarding_session(tenant_id, session_id, current_step=2, answers={"a": 1})
            row = ds.get_onboarding_session(tenant_id, session_id)
            assert row["current_step"] == 2
            assert row["answers"] == {"a": 1}

            ds.update_onboarding_session(tenant_id, session_id, answers={"b": 2})
            row = ds.get_onboarding_session(tenant_id, session_id)
            assert row["answers"] == {"a": 1, "b": 2}  # shallow-merged, not replaced
        finally:
            import psycopg2
            conn = psycopg2.connect(database_url)
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                    cur.execute(
                        "DELETE FROM onboarding_sessions WHERE tenant_id = %s AND session_id = %s",
                        (tenant_id, session_id),
                    )
            conn.close()

    def test_rls_blocks_cross_tenant_read_without_app_level_filter(self, ds, tenant_id, database_url):
        """
        Real RLS proof (matching tests/test_security.py::TestRowLevelSecurity's
        pattern) — not just this file's own WHERE tenant_id=... clause, which
        would return 0 rows for a wrong tenant_id regardless of whether RLS is
        enabled at all. This test creates a row under the REAL tenant, then
        issues a raw query with the session's tenant context set to a
        different (fake) tenant and NO tenant_id filter in the WHERE clause —
        RLS itself must still hide the row.
        """
        import psycopg2

        session_id = "rls-cross-tenant-test"
        ds.create_onboarding_session(tenant_id, session_id, "test-user")
        try:
            conn = psycopg2.connect(database_url)
            try:
                with conn.cursor() as cur:
                    cur.execute("SET ROLE fotopia_app")  # non-superuser; subject to RLS
                    cur.execute(
                        "SET app.current_tenant_id = %s",
                        ("00000000-0000-0000-0000-000000000000",),
                    )
                    cur.execute(
                        "SELECT COUNT(*) FROM onboarding_sessions WHERE session_id = %s",
                        (session_id,),
                    )
                    assert cur.fetchone()[0] == 0, "Cross-tenant isolation not enforced"
            finally:
                conn.close()
        finally:
            conn = psycopg2.connect(database_url)
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                    cur.execute(
                        "DELETE FROM onboarding_sessions WHERE tenant_id = %s AND session_id = %s",
                        (tenant_id, session_id),
                    )
            conn.close()
