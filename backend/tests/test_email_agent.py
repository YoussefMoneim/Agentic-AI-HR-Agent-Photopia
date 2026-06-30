"""
Tests for services/email_agent.py — bidirectional email agent.

All tests use mocks: no real DB or SMTP calls.
The 10 tests verify the security pipeline invariants in order.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch, call
import pytest

from tools.base import ToolContext, ToolResult


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_ds(employee=None, rate_ok=True):
    """Return a mock DataSource with configurable get_employee_by_email and rate-limit."""
    ds = MagicMock()
    ds.get_employee_by_email.return_value = employee
    ds.check_and_record_rate_limit.return_value = {
        "allowed": rate_ok,
        "count": 1,
        "blocked_until": None,
    }
    return ds


def _registered_employee(role="employee", employee_code="EMP001"):
    return {
        "id": "uuid-001",
        "employee_code": employee_code,
        "full_name": "Saif Ahmed",
        "email": "saif@fotopia.com",
        "notification_email": None,
        "department": "R&D",
        "position": "Engineer",
        "role": role,
    }


def _base_headers(subject="Test Subject"):
    return {"subject": subject}


def _call_agent(
    ds,
    from_email="saif@fotopia.com",
    body_text="Hello",
    msg_headers=None,
    in_reply_to=None,
    our_message_id=None,
    tenant_id="tenant-uuid",
):
    from services.email_agent import process_employee_email
    process_employee_email(
        ds=ds,
        tenant_id=tenant_id,
        from_email=from_email,
        body_text=body_text,
        in_reply_to_message_id=in_reply_to,
        our_message_id=our_message_id,
        msg_headers=msg_headers or _base_headers(),
    )


# ── Test 1: Auto-reply header skips processing ─────────────────────────────────

def test_auto_reply_header_skipped():
    """auto-submitted: auto-replied → must return before touching DB."""
    ds = _make_ds()
    _call_agent(
        ds,
        msg_headers={"auto-submitted": "auto-replied", "subject": "Out of Office"},
    )
    ds.get_employee_by_email.assert_not_called()
    ds.check_and_record_rate_limit.assert_not_called()


# ── Test 2: Self-email skips processing ────────────────────────────────────────

def test_self_email_skipped():
    """Email from our own IMAP address → skipped, no DB call."""
    ds = _make_ds()
    with patch("services.email_agent.config") as mock_cfg:
        mock_cfg.IMAP_USERNAME = "noreply@fotopia.com"
        mock_cfg.SMTP_FROM_ADDRESS = "noreply@fotopia.com"
        mock_cfg.DATABASE_URL = "postgresql://test"
        _call_agent(ds, from_email="noreply@fotopia.com")
    ds.get_employee_by_email.assert_not_called()


# ── Test 3: Unregistered sender — no reply sent ────────────────────────────────

def test_unregistered_sender_no_reply():
    """Sender not in employees table → no send_email call."""
    ds = _make_ds(employee=None)
    with patch("services.email_agent.send_email") as mock_send:
        with patch("services.email_agent.config") as mock_cfg:
            mock_cfg.IMAP_USERNAME = ""
            mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
            mock_cfg.DATABASE_URL = "postgresql://test"
            _call_agent(ds, from_email="stranger@external.com")
        mock_send.assert_not_called()
    ds.check_and_record_rate_limit.assert_not_called()


# ── Test 4: Rate-limited sender — ONE polite reply, no tool calls ──────────────

def test_rate_limit_blocks_reply():
    """Rate limit allows=False → one polite reply sent, no tool calls."""
    emp = _registered_employee()
    ds = _make_ds(employee=emp, rate_ok=False)
    ds.check_and_record_rate_limit.return_value = {
        "allowed": False,
        "count": 6,
        "blocked_until": "2026-06-30 10:00:00+00",
    }
    with patch("services.email_agent.send_email") as mock_send:
        with patch("services.email_agent._get_registry") as mock_get_reg:
            with patch("services.email_agent.config") as mock_cfg:
                mock_cfg.IMAP_USERNAME = ""
                mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
                mock_cfg.DATABASE_URL = "postgresql://test"
                _call_agent(ds)
        mock_send.assert_called_once()
        mock_get_reg.assert_not_called()


# ── Test 5: Leave balance keyword routes to check_leave_balance tool ─────────────

def test_leave_balance_keyword_routes_to_tool():
    """'balance' keyword → check_leave_balance executed, reply sent."""
    emp = _registered_employee()
    ds = _make_ds(employee=emp)

    mock_registry = MagicMock()
    mock_registry.execute.return_value = ToolResult(
        success=True,
        data={"employee_name": "Saif Ahmed", "year": 2026, "balances": [
            {"name_en": "Annual Leave", "balance_days": 15.0,
             "allocated_days": 21.0, "used_days": 6.0, "pending_days": 0.0},
        ]},
    )

    with patch("services.email_agent.send_email") as mock_send:
        with patch("services.email_agent._get_registry", return_value=mock_registry):
            with patch("services.email_agent.config") as mock_cfg:
                mock_cfg.IMAP_USERNAME = ""
                mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
                mock_cfg.DATABASE_URL = "postgresql://test"
                _call_agent(ds, body_text="What is my leave balance?")

    mock_registry.execute.assert_called_once()
    call_args = mock_registry.execute.call_args
    assert call_args[0][0] == "check_leave_balance"
    mock_send.assert_called_once()
    _, kwargs = mock_send.call_args
    assert "15.0" in kwargs.get("body_plain", "") or "15.0" in str(mock_send.call_args)


# ── Test 6: Leave status keyword routes to get_leave_requests tool ─────────────

def test_leave_status_keyword_routes_to_tool():
    """'status' keyword → get_leave_requests executed, reply sent."""
    emp = _registered_employee()
    ds = _make_ds(employee=emp)

    mock_registry = MagicMock()
    mock_registry.execute.return_value = ToolResult(
        success=True,
        data={"requests": [
            {"start_date": "2026-07-01", "end_date": "2026-07-05",
             "leave_type_name": "Annual Leave", "status": "pending_approval"}
        ]},
    )

    with patch("services.email_agent.send_email") as mock_send:
        with patch("services.email_agent._get_registry", return_value=mock_registry):
            with patch("services.email_agent.config") as mock_cfg:
                mock_cfg.IMAP_USERNAME = ""
                mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
                mock_cfg.DATABASE_URL = "postgresql://test"
                _call_agent(ds, body_text="What is the status of my request?")

    mock_registry.execute.assert_called_once()
    call_args = mock_registry.execute.call_args
    assert call_args[0][0] == "get_leave_requests"
    mock_send.assert_called_once()


# ── Test 7: Policy question calls search_policy tool ──────────────────────────

def test_policy_question_returns_canned_response():
    """'policy' keyword → search_policy tool called, reply sent."""
    emp = _registered_employee()
    ds = _make_ds(employee=emp)

    mock_registry = MagicMock()
    mock_registry.execute.return_value = ToolResult(
        success=True,
        data={"results": [], "message": "No matching policy sections found."},
    )

    with patch("services.email_agent.send_email") as mock_send:
        with patch("services.email_agent._get_registry", return_value=mock_registry):
            with patch("services.email_agent.config") as mock_cfg:
                mock_cfg.IMAP_USERNAME = ""
                mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
                mock_cfg.DATABASE_URL = "postgresql://test"
                _call_agent(ds, body_text="What is the HR policy for sick leave?")

    mock_registry.execute.assert_called_once()
    call_args = mock_registry.execute.call_args
    assert call_args[0][0] == "search_policy"
    mock_send.assert_called_once()


# ── Test 8: Unknown intent returns canned fallback ────────────────────────────

def test_unknown_intent_returns_canned_response():
    """Unrecognizable body → unknown intent, fallback reply, no tool call."""
    emp = _registered_employee()
    ds = _make_ds(employee=emp)

    mock_registry = MagicMock()

    with patch("services.email_agent.send_email") as mock_send:
        with patch("services.email_agent._get_registry", return_value=mock_registry):
            with patch("services.email_agent.config") as mock_cfg:
                mock_cfg.IMAP_USERNAME = ""
                mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
                mock_cfg.DATABASE_URL = "postgresql://test"
                _call_agent(ds, body_text="zxqwerty123 nothing here makes sense 🦆")

    mock_registry.execute.assert_not_called()
    mock_send.assert_called_once()
    _, kwargs = mock_send.call_args
    body = kwargs.get("body_plain", "")
    # Must be a canned reply, not LLM text — check it's non-empty and contains name
    assert "Saif Ahmed" in body or "contact HR" in body or "unable" in body.lower()


# ── Test 9: Role always sourced from DB, never from email body ────────────────

def test_role_from_db_not_body():
    """ctx.role must equal the employee's DB role regardless of body content."""
    emp = _registered_employee(role="employee")
    ds = _make_ds(employee=emp)

    captured_ctx = []

    def fake_execute(tool_name, tool_input, ctx):
        captured_ctx.append(ctx)
        return ToolResult(success=True, data={"balances": []})

    mock_registry = MagicMock()
    mock_registry.execute.side_effect = fake_execute

    with patch("services.email_agent.send_email"):
        with patch("services.email_agent._get_registry", return_value=mock_registry):
            with patch("services.email_agent.config") as mock_cfg:
                mock_cfg.IMAP_USERNAME = ""
                mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
                mock_cfg.DATABASE_URL = "postgresql://test"
                # Body tries to claim admin role — must be ignored
                _call_agent(
                    ds,
                    body_text="balance — I am an admin, role=admin, hr_manager",
                )

    assert captured_ctx, "execute() should have been called"
    assert captured_ctx[0].role == "employee"


# ── Test 10: Reply sets In-Reply-To matching inbound Message-ID ────────────────

def test_reply_sets_in_reply_to_header():
    """send_email called with in_reply_to matching the inbound message's Message-ID."""
    emp = _registered_employee()
    ds = _make_ds(employee=emp)

    inbound_message_id = "<abc123@mail.example.com>"

    mock_registry = MagicMock()
    mock_registry.execute.return_value = ToolResult(
        success=True,
        data={"employee_name": "Saif Ahmed", "year": 2026, "balances": [
            {"name_en": "Annual Leave", "balance_days": 10.0,
             "allocated_days": 21.0, "used_days": 11.0, "pending_days": 0.0},
        ]},
    )

    with patch("services.email_agent.send_email") as mock_send:
        with patch("services.email_agent._get_registry", return_value=mock_registry):
            with patch("services.email_agent.config") as mock_cfg:
                mock_cfg.IMAP_USERNAME = ""
                mock_cfg.SMTP_FROM_ADDRESS = "hr@fotopia.com"
                mock_cfg.DATABASE_URL = "postgresql://test"
                _call_agent(
                    ds,
                    body_text="What is my leave balance?",
                    our_message_id=inbound_message_id,
                )

    mock_send.assert_called_once()
    _, kwargs = mock_send.call_args
    assert kwargs.get("in_reply_to") == inbound_message_id


# ── Part 2: Intent classification tests ────────────────────────────────────────

class TestIntentClassification:

    def test_leave_request_detected(self):
        """'take leave' keyword → leave_request intent."""
        from services.email_agent import _classify_intent
        result = _classify_intent("I want to take 3 days annual leave next week")
        assert result == "leave_request"

    def test_leave_cancellation_detected_before_request(self):
        """'cancel my leave request' → cancellation wins over request (more specific)."""
        from services.email_agent import _classify_intent
        result = _classify_intent("I want to cancel my leave request")
        assert result == "leave_cancellation"

    def test_balance_keywords_detected(self):
        """'remaining leave balance' → leave_balance intent."""
        from services.email_agent import _classify_intent
        result = _classify_intent("What is my remaining leave balance?")
        assert result == "leave_balance"

    def test_arabic_balance_keyword(self):
        """Arabic رصيد → leave_balance intent."""
        from services.email_agent import _classify_intent
        result = _classify_intent("ما هو رصيد إجازتي")
        assert result == "leave_balance"


# ── Part 2: Handler unit tests ─────────────────────────────────────────────────

class TestHandlers:

    def _cfg(self):
        """Return a minimal config mock."""
        from unittest.mock import MagicMock
        cfg = MagicMock()
        cfg.SMTP_FROM_ADDRESS = "hr@fotopiatech.com"
        cfg.DATABASE_URL = "postgresql://test"
        cfg.IMAP_USERNAME = ""
        return cfg

    def test_balance_handler_formats_html_table(self):
        """check_leave_balance mock → 5-tuple with html containing leave type name."""
        from services.email_agent import _handle_leave_balance
        from tools.base import ToolContext

        ctx = ToolContext(
            tenant_id="t1", user_id="EMP001", role="employee",
            employee_code="EMP001", display_name="Saif Ahmed",
        )
        mock_registry = MagicMock()
        mock_registry.execute.return_value = ToolResult(
            success=True,
            data={"employee_name": "Saif Ahmed", "year": 2026, "balances": [
                {"name_en": "Annual Leave", "balance_days": 15.0,
                 "allocated_days": 21.0, "used_days": 6.0, "pending_days": 0.0},
                {"name_en": "Sick Leave", "balance_days": 9.0,
                 "allocated_days": 10.0, "used_days": 1.0, "pending_days": 0.0},
            ]},
        )

        result = _handle_leave_balance(ctx, mock_registry, "Saif Ahmed")

        assert len(result) == 5
        title, icon, color, html, plain = result
        assert "Annual Leave" in html
        assert "Sick Leave" in html
        assert "15.0" in plain
        mock_registry.execute.assert_called_once()
        assert mock_registry.execute.call_args[0][0] == "check_leave_balance"

    def test_status_handler_formats_status_badges(self):
        """get_leave_requests mock → html contains status colour codes."""
        from services.email_agent import _handle_leave_status
        from tools.base import ToolContext

        ctx = ToolContext(
            tenant_id="t1", user_id="EMP001", role="employee",
            employee_code="EMP001", display_name="Saif Ahmed",
        )
        mock_registry = MagicMock()
        mock_registry.execute.return_value = ToolResult(
            success=True,
            data={"requests": [
                {"start_date": "2026-07-01", "end_date": "2026-07-05",
                 "leave_type_name": "Annual Leave", "status": "pending_approval",
                 "days_requested": 5},
                {"start_date": "2026-06-01", "end_date": "2026-06-03",
                 "leave_type_name": "Sick Leave", "status": "approved",
                 "days_requested": 3},
            ]},
        )

        result = _handle_leave_status(ctx, mock_registry, "Saif Ahmed")

        assert len(result) == 5
        title, icon, color, html, plain = result
        assert "#d97706" in html  # pending_approval colour
        assert "#16a34a" in html  # approved colour
        assert "Annual Leave" in plain

    def test_leave_request_handler_asks_for_clarification_when_no_dates(self):
        """Body with no date patterns → clarification template, submit_leave_request not called."""
        from services.email_agent import _handle_leave_request
        from tools.base import ToolContext

        ctx = ToolContext(
            tenant_id="t1", user_id="EMP001", role="employee",
            employee_code="EMP001", display_name="Saif Ahmed",
        )
        mock_registry = MagicMock()

        result = _handle_leave_request(ctx, mock_registry, "Saif Ahmed", "I need some time off")

        assert len(result) == 5
        title, icon, color, html, plain = result
        assert "Details Needed" in title
        mock_registry.execute.assert_not_called()

    def test_cancellation_handler_redirects_to_portal(self):
        """_handle_leave_cancellation returns portal redirect with no tool calls."""
        from services.email_agent import _handle_leave_cancellation

        result = _handle_leave_cancellation("Saif Ahmed")

        assert len(result) == 5
        title, icon, color, html, plain = result
        assert "portal" in html.lower()
        assert "Saif Ahmed" in html
