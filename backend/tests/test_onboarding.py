"""
Tests for agent/onboarding.py — the slot-filling, order-independent
onboarding flow.

Most tests use a mocked DataSource (a stateful in-memory fake, mirroring the
`stored` dict pattern in tests/test_email_agent.py's TestTwoEmailThreadRetainsContext)
and a mocked ToolRegistry. TestOnboardingSessionRLS uses the real DB via the
shared conftest.py fixtures to prove tenant isolation actually holds.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from unittest.mock import MagicMock

from agent import onboarding
from tools.base import ToolContext, ToolResult


def _ctx(role="hr_manager", user_id="test-user"):
    return ToolContext(
        tenant_id="tenant-uuid", user_id=user_id, role=role,
        employee_code="EMP002", display_name="Noura Al Rashidi",
    )


def _llm_returning(payload):
    llm = MagicMock()
    llm.classify.return_value = json.dumps(payload)
    return llm


def _turn_info(is_trigger=False, company_name=None, jurisdiction=None, odoo_decision=None):
    return _llm_returning({
        "is_trigger": is_trigger, "company_name": company_name,
        "jurisdiction": jurisdiction, "odoo_decision": odoo_decision,
    })


def _doc_type(document_type, confidence="high", reason="because"):
    return _llm_returning({"document_type": document_type, "confidence": confidence, "reason": reason})


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


# ── Trigger detection / role gating ──────────────────────────────────────────

class TestTriggerAndRoleGating:

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

    def test_employee_free_text_never_reaches_llm_classifier(self):
        ds = _make_fake_ds()
        llm = MagicMock()
        result = onboarding.maybe_handle_turn(
            "I want to create an agent for Acme and connect it to Odoo",
            _ctx(role="employee"), "sid-1b", ds, MagicMock(), llm,
        )
        assert result is None
        llm.classify.assert_not_called()

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

    def test_natural_language_trigger_recognized_when_llm_provided(self):
        ds = _make_fake_ds()
        llm = _turn_info(is_trigger=True)
        result = onboarding.maybe_handle_turn(
            "I want to create an agent", _ctx(), "sid-nl", ds, MagicMock(), llm,
        )
        assert result is not None
        assert "company name" in result.text.lower()
        ds.create_onboarding_session.assert_called_once()

    def test_natural_language_trigger_ignored_without_llm(self):
        ds = _make_fake_ds()
        result = onboarding.maybe_handle_turn(
            "I want to create an agent for Fotopia and connect it to Odoo",
            _ctx(), "sid-nl2", ds, MagicMock(),
        )
        assert result is None
        ds.create_onboarding_session.assert_not_called()

    def test_ontopic_message_correctly_classified_as_not_a_trigger(self):
        ds = _make_fake_ds()
        llm = _turn_info(is_trigger=False)
        result = onboarding.maybe_handle_turn(
            "Can you help me configure the leave policy for my team?",
            _ctx(), "sid-nl3", ds, MagicMock(), llm,
        )
        assert result is None
        llm.classify.assert_called_once()
        ds.create_onboarding_session.assert_not_called()

    def test_trigger_classification_failure_fails_closed(self):
        ds = _make_fake_ds()
        llm = MagicMock()
        llm.classify.side_effect = RuntimeError("API unavailable")
        result = onboarding.maybe_handle_turn(
            "I want to set up an agent for my company",
            _ctx(), "sid-nl5", ds, MagicMock(), llm,
        )
        assert result is None
        ds.create_onboarding_session.assert_not_called()


# ── Slot-filling, order-independent flow ─────────────────────────────────────

class TestSlotFillingOrderIndependence:

    def test_everything_given_in_one_message_skips_straight_to_documents(self):
        """The exact ask: company + jurisdiction + Odoo intent all in one
        message should resolve both slots immediately (real Odoo call) and
        land on the next actually-missing question."""
        ds = _make_fake_ds()
        llm = _turn_info(is_trigger=True, company_name="Fotopia", jurisdiction="Egypt", odoo_decision="connect")
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=True, data={"employee_count": 32})

        result = onboarding.maybe_handle_turn(
            "I want to create an agent for Fotopia, Egypt, and connect it to Odoo",
            _ctx(), "sid-all", ds, registry, llm,
        )

        registry.execute.assert_called_once_with("connect_odoo", {}, registry.execute.call_args.args[2])
        assert "fotopia" in result.text.lower()
        assert "egypt" in result.text.lower()
        assert "32 employees" in result.text
        assert "handbook" in result.text.lower()
        assert result.awaiting_upload is True

        answers = ds.get_onboarding_session("tenant-uuid", "sid-all")["answers"]
        assert answers["company_name"] == "Fotopia"
        assert answers["jurisdiction"] == "Egypt"
        assert answers["odoo_resolved"] is True
        assert answers["odoo_connected"] is True

    def test_company_only_leaves_odoo_still_pending(self):
        ds = _make_fake_ds()
        llm = _turn_info(is_trigger=True, company_name="Acme Corp")
        registry = MagicMock()

        result = onboarding.maybe_handle_turn(
            "I want to set up an agent for Acme Corp", _ctx(), "sid-co", ds, registry, llm,
        )

        registry.execute.assert_not_called()
        assert "acme corp" in result.text.lower()
        assert "odoo" in result.text.lower()
        assert result.awaiting_upload is False

    def test_odoo_answered_before_company_name_asks_for_company_next(self):
        """Reverse order: the trigger message only addresses Odoo — the next
        question must be whatever's ACTUALLY still missing (company), not a
        rigid insistence on asking company name first no matter what."""
        ds = _make_fake_ds()
        llm = _turn_info(is_trigger=True, odoo_decision="skip")

        result = onboarding.maybe_handle_turn(
            "set up my agent, skip Odoo for now", _ctx(), "sid-rev", ds, MagicMock(), llm,
        )

        assert "company name" in result.text.lower()
        answers = ds.get_onboarding_session("tenant-uuid", "sid-rev")["answers"]
        assert answers["odoo_resolved"] is True
        assert answers["odoo_connected"] is False

    def test_bare_yes_reply_is_correctly_attributed_to_pending_odoo_question(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-bare", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-bare", answers={"company_name": "Fotopia"})
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=True, data={"employee_count": 32})
        llm = _turn_info(odoo_decision="connect")

        result = onboarding.maybe_handle_turn("yes", _ctx(), "sid-bare", ds, registry, llm)

        registry.execute.assert_called_once()
        assert "32 employees" in result.text
        # Context passed to the classifier should mention what's pending
        sent_context = llm.classify.call_args.args[1]
        assert "odoo" in sent_context.lower()

    def test_odoo_not_re_triggered_once_already_resolved(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-noretouch", "test-user")
        ds.update_onboarding_session(
            "tenant-uuid", "sid-noretouch",
            answers={"company_name": "Fotopia", "odoo_resolved": True, "odoo_connected": False},
        )
        registry = MagicMock()
        llm = _turn_info(odoo_decision="connect")  # mentions odoo again, already resolved

        onboarding.maybe_handle_turn("actually connect odoo now", _ctx(), "sid-noretouch", ds, registry, llm)

        registry.execute.assert_not_called()

    def test_odoo_connect_failure_still_resolves_and_moves_on(self):
        ds = _make_fake_ds()
        llm = _turn_info(is_trigger=True, company_name="Fotopia", odoo_decision="connect")
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=False, error="connection refused")

        result = onboarding.maybe_handle_turn(
            "set up an agent for Fotopia and connect to odoo", _ctx(), "sid-fail", ds, registry, llm,
        )

        assert "couldn't connect" in result.text.lower()
        assert "handbook" in result.text.lower()  # still moves on, doesn't get stuck
        answers = ds.get_onboarding_session("tenant-uuid", "sid-fail")["answers"]
        assert answers["odoo_resolved"] is True
        assert answers["odoo_connected"] is False


# ── Document uploads accepted at any point, classified by content ───────────

class TestUploadOrderIndependence:

    def test_upload_handbook_before_company_name_is_accepted(self):
        """The specific pain point reported: uploading a document before the
        company name was given used to be rejected outright."""
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-up1", "test-user")
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=True, data={"document_id": "doc-hb"})
        llm = _doc_type("employee handbook")

        result = onboarding.handle_document_upload(
            "handbook content", "handbook.pdf", _ctx(), "sid-up1", ds, registry, llm,
        )

        registry.execute.assert_called_once_with(
            "ingest_policy_document", {"content": "handbook content", "document_name": "handbook.pdf"},
            registry.execute.call_args.args[2],
        )
        assert "handbook" in result.text.lower()
        assert "company name" in result.text.lower()  # still asks for what's missing
        answers = ds.get_onboarding_session("tenant-uuid", "sid-up1")["answers"]
        assert answers["handbook_document_id"] == "doc-hb"
        assert "company_name" not in answers

    def test_upload_leave_policy_before_handbook_is_accepted(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-up2", "test-user")
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=True, data={"document_id": "doc-lp"})
        llm = _doc_type("leave policy document")

        result = onboarding.handle_document_upload(
            "leave policy content", "leave.pdf", _ctx(), "sid-up2", ds, registry, llm,
        )

        answers = ds.get_onboarding_session("tenant-uuid", "sid-up2")["answers"]
        assert answers["leave_policy_document_id"] == "doc-lp"
        # leave policy is filled but company/odoo/handbook are still missing —
        # company_name is first in priority order, so that's what's asked next.
        assert "company name" in result.text.lower()

    def test_unrecognized_document_is_rejected_with_explanation(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-up3", "test-user")
        registry = MagicMock()
        llm = _doc_type("other", reason="This is a resume, not a policy document.")

        result = onboarding.handle_document_upload(
            "objective: seeking a role in...", "resume.pdf", _ctx(), "sid-up3", ds, registry, llm,
        )

        registry.execute.assert_not_called()
        assert result.awaiting_upload is True
        assert "employee handbook" in result.text.lower()
        assert "leave policy document" in result.text.lower()
        answers = ds.get_onboarding_session("tenant-uuid", "sid-up3")["answers"]
        assert "handbook_document_id" not in answers
        assert "leave_policy_document_id" not in answers

    def test_replacing_an_already_filled_slot_says_updated_not_got(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-up4", "test-user")
        ds.update_onboarding_session("tenant-uuid", "sid-up4", answers={"handbook_document_id": "old-doc"})
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=True, data={"document_id": "new-doc"})
        llm = _doc_type("employee handbook")

        result = onboarding.handle_document_upload(
            "new handbook content", "handbook_v2.pdf", _ctx(), "sid-up4", ds, registry, llm,
        )

        assert "updated your employee handbook" in result.text.lower()
        answers = ds.get_onboarding_session("tenant-uuid", "sid-up4")["answers"]
        assert answers["handbook_document_id"] == "new-doc"

    def test_upload_with_no_session_and_disallowed_role_is_rejected(self):
        ds = _make_fake_ds()
        result = onboarding.handle_document_upload(
            "content", "file.pdf", _ctx(role="employee"), "sid-nonexistent", ds, MagicMock(),
            _doc_type("employee handbook"),
        )
        assert "no document upload is expected" in result.text.lower()
        ds.create_onboarding_session.assert_not_called()

    def test_upload_with_no_session_auto_starts_onboarding(self):
        """The reported bug: attaching a file as the very first action (no
        prior 'set up your agent' message) used to always be rejected,
        regardless of role — attaching a document is just as valid a way to
        start onboarding as typing the trigger phrase."""
        ds = _make_fake_ds()
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=True, data={"document_id": "doc-hb"})

        result = onboarding.handle_document_upload(
            "handbook content", "handbook.pdf", _ctx(), "sid-fresh-upload", ds, registry,
            _doc_type("employee handbook"),
        )

        ds.create_onboarding_session.assert_called_once()
        assert "handbook" in result.text.lower()
        assert "company name" in result.text.lower()  # still asks what's missing
        answers = ds.get_onboarding_session("tenant-uuid", "sid-fresh-upload")["answers"]
        assert answers["handbook_document_id"] == "doc-hb"

    def test_upload_ingestion_failure_reprompts_for_retry(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-up5", "test-user")
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=False, error="No extractable text.")
        llm = _doc_type("employee handbook")

        result = onboarding.handle_document_upload(
            "", "scanned.pdf", _ctx(), "sid-up5", ds, registry, llm,
        )

        assert result.awaiting_upload is True
        assert "couldn't process" in result.text.lower()
        answers = ds.get_onboarding_session("tenant-uuid", "sid-up5")["answers"]
        assert "handbook_document_id" not in answers

    def test_classification_logged_on_match_and_mismatch(self):
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-up6", "test-user")
        registry = MagicMock()
        registry.execute.return_value = ToolResult(success=True, data={"document_id": "doc-1"})

        onboarding.handle_document_upload(
            "handbook content", "handbook.pdf", _ctx(), "sid-up6", ds, registry, _doc_type("employee handbook"),
        )
        assert ds.create_workflow_event.call_count == 1
        call_args = ds.create_workflow_event.call_args.args
        assert call_args[2] == "document_type_classification"
        assert call_args[5]["matched_slot"] == "handbook_document_id"

        onboarding.handle_document_upload(
            "resume content", "resume.pdf", _ctx(), "sid-up6", ds, registry, _doc_type("other"),
        )
        assert ds.create_workflow_event.call_count == 2
        logged = ds.create_workflow_event.call_args.args[5]
        assert logged["matched_slot"] is None


class TestClassifyUploadedDocumentType:

    def test_markdown_fenced_response_is_parsed_correctly(self):
        llm = MagicMock()
        llm.classify.return_value = (
            '```json\n{"document_type": "leave policy document", "confidence": "high", '
            '"reason": "Single-topic content."}\n```'
        )
        verdict = onboarding.classify_uploaded_document_type("some text", llm)
        assert verdict["document_type"] == "leave policy document"
        assert verdict["confidence"] == "high"

    def test_malformed_json_response_fails_closed_to_other(self):
        llm = MagicMock()
        llm.classify.return_value = "not valid json at all"
        verdict = onboarding.classify_uploaded_document_type("some text", llm)
        assert verdict["document_type"] == "other"
        assert verdict["confidence"] == "low"

    def test_llm_exception_fails_closed_to_other(self):
        llm = MagicMock()
        llm.classify.side_effect = RuntimeError("API unavailable")
        verdict = onboarding.classify_uploaded_document_type("some text", llm)
        assert verdict["document_type"] == "other"

    def test_content_excerpt_is_truncated_not_full_document(self):
        llm = _doc_type("employee handbook")
        huge_content = "A" * 5000
        onboarding.classify_uploaded_document_type(huge_content, llm)
        sent_user_text = llm.classify.call_args.args[1]
        assert len(sent_user_text) < 5000


# ── Completion ────────────────────────────────────────────────────────────────

class TestCompletion:

    def test_completes_once_all_four_slots_filled(self):
        ds = _make_fake_ds()
        registry = MagicMock()
        registry.execute.side_effect = lambda name, args, ctx: {
            "connect_odoo": ToolResult(success=True, data={"employee_count": 32}),
            "ingest_policy_document": ToolResult(success=True, data={"document_id": "doc-x"}),
        }[name]

        sid = "sid-complete"
        llm1 = _turn_info(is_trigger=True, company_name="Fotopia", jurisdiction="Egypt", odoo_decision="connect")
        r1 = onboarding.maybe_handle_turn("set up an agent for Fotopia, Egypt, connect odoo", _ctx(), sid, ds, registry, llm1)
        assert r1.awaiting_upload is True

        r2 = onboarding.handle_document_upload(
            "handbook content", "handbook.pdf", _ctx(), sid, ds, registry, _doc_type("employee handbook"),
        )
        assert r2.awaiting_upload is True
        assert "leave policy" in r2.text.lower()
        assert ds.get_onboarding_session("tenant-uuid", sid)["status"] == "in_progress"

        r3 = onboarding.handle_document_upload(
            "leave policy content", "leave.pdf", _ctx(), sid, ds, registry, _doc_type("leave policy document"),
        )
        assert "ready" in r3.text.lower()
        assert "Fotopia" in r3.text
        final = ds.get_onboarding_session("tenant-uuid", sid)
        assert final["status"] == "completed"

    def test_can_complete_by_uploading_documents_before_answering_anything_else(self):
        """The other half of the reported flexibility ask: documents first,
        company/Odoo last."""
        ds = _make_fake_ds()
        ds.create_onboarding_session("tenant-uuid", "sid-docs-first", "test-user")
        registry = MagicMock()
        registry.execute.side_effect = lambda name, args, ctx: {
            "connect_odoo": ToolResult(success=True, data={"employee_count": 5}),
            "ingest_policy_document": ToolResult(success=True, data={"document_id": "doc-x"}),
        }[name]

        onboarding.handle_document_upload(
            "handbook content", "handbook.pdf", _ctx(), "sid-docs-first", ds, registry, _doc_type("employee handbook"),
        )
        onboarding.handle_document_upload(
            "leave content", "leave.pdf", _ctx(), "sid-docs-first", ds, registry, _doc_type("leave policy document"),
        )

        llm = _turn_info(company_name="Acme", jurisdiction="UAE", odoo_decision="connect")
        result = onboarding.maybe_handle_turn(
            "Acme, UAE, connect odoo please", _ctx(), "sid-docs-first", ds, registry, llm,
        )

        assert "ready" in result.text.lower()
        assert ds.get_onboarding_session("tenant-uuid", "sid-docs-first")["status"] == "completed"


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
