"""
test_email_correlation.py — Integration tests for the Step 8 email reply flow.

Tests the full inbound-email resolution path:
  - pending_action has outbound_message_id set after a leave submit
  - resolution via In-Reply-To header (primary path)
  - employee confirmation email sent after reply-path resolution
  - resolution via Reply-Token in body (fallback path)
  - wrong sender is rejected
  - parse_decision() logic (unit tests, no DB)
  - simulate-inbound HTTP endpoint

All DB tests use the shared conftest fixtures (real PostgreSQL, cleaned per test).
"""
import unittest.mock
from datetime import date, timedelta

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _submit_leave(registry, tenant_id, days=3):
    """Submit a leave request for EMP001 (annual) using the ToolRegistry."""
    from tools.base import ToolContext
    ctx = ToolContext(
        tenant_id=tenant_id,
        user_id="test-emp001",
        role="employee",
        employee_code="EMP001",
        display_name="Saif Ahmed Hassan",
    )
    start = (date.today() + timedelta(days=60)).isoformat()
    end = (date.today() + timedelta(days=60 + days - 1)).isoformat()
    result = registry.execute(
        "submit_leave_request",
        {
            "leave_type_code": "annual",
            "start_date": start,
            "end_date": end,
            "reason": "Email correlation test",
        },
        ctx,
    )
    assert result.success, f"submit_leave_request failed: {result.error}"
    return result.data


# ─────────────────────────────────────────────────────────────────────────────
# 1. outbound_message_id is populated after submit
# ─────────────────────────────────────────────────────────────────────────────

class TestOutboundMessageIdPopulated:
    def test_pending_action_has_outbound_message_id_after_submit(
        self, ds, registry, tenant_id, db_conn
    ):
        _submit_leave(registry, tenant_id)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT outbound_message_id FROM pending_actions WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()

        assert row is not None, "No pending_action found after submit"
        msg_id = row[0]
        assert msg_id is not None, "outbound_message_id is NULL"
        assert msg_id.startswith("<"), "outbound_message_id must start with <"
        assert msg_id.endswith(">"), "outbound_message_id must end with >"
        assert "@" in msg_id, "outbound_message_id must contain @"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Primary path: resolve via In-Reply-To
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessInboundEmailPrimaryPath:
    def _get_pa(self, db_conn, tenant_id):
        with db_conn.cursor() as cur:
            cur.execute(
                """SELECT pa.outbound_message_id, pa.assigned_to_email
                   FROM pending_actions pa
                   WHERE pa.tenant_id = %s""",
                (tenant_id,),
            )
            return cur.fetchone()

    def test_resolves_via_in_reply_to(self, ds, registry, tenant_id, db_conn):
        _submit_leave(registry, tenant_id)
        row = self._get_pa(db_conn, tenant_id)
        assert row, "No pending_action found"
        outbound_msg_id, assigned_email = row

        from services.email_listener import process_inbound_email
        result = process_inbound_email(
            ds=ds,
            tenant_id=tenant_id,
            from_email=assigned_email,
            in_reply_to=outbound_msg_id,
            body_text="Approved.",
        )

        assert result["resolved"] is True, f"Expected resolved=True, got: {result}"
        assert result["decision"] == "approved"
        assert result["error"] is None

        # DB state should reflect approval
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM leave_requests WHERE tenant_id = %s ORDER BY updated_at DESC LIMIT 1",
                (tenant_id,),
            )
            leave_row = cur.fetchone()
        assert leave_row and leave_row[0] in ("approved", "manager_approved")

    def test_employee_receives_confirmation_after_reply_approval(
        self, ds, registry, tenant_id, db_conn
    ):
        _submit_leave(registry, tenant_id)
        row = self._get_pa(db_conn, tenant_id)
        assert row
        outbound_msg_id, assigned_email = row

        with unittest.mock.patch(
            "services.email.send_email"
        ) as mock_send:
            mock_send.return_value = True
            from services.email_listener import process_inbound_email
            result = process_inbound_email(
                ds=ds,
                tenant_id=tenant_id,
                from_email=assigned_email,
                in_reply_to=outbound_msg_id,
                body_text="Approved.",
            )

        assert result["resolved"] is True

        # At least one call must be to the employee's email
        called_recipients = [call.kwargs.get("to_email") or call.args[0]
                             for call in mock_send.call_args_list]
        emp = ds.get_employee_by_code(tenant_id, "EMP001")
        assert emp["email"] in called_recipients, (
            f"Employee confirmation email not sent. Got recipients: {called_recipients}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fallback path: resolve via Reply-Token in body
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessInboundEmailFallbackPath:
    def test_resolves_via_reply_token_in_body(self, ds, registry, tenant_id, db_conn):
        _submit_leave(registry, tenant_id)

        with db_conn.cursor() as cur:
            cur.execute(
                """SELECT pa.outbound_message_id, pa.assigned_to_email
                   FROM pending_actions pa WHERE pa.tenant_id = %s""",
                (tenant_id,),
            )
            row = cur.fetchone()
        assert row
        outbound_msg_id, assigned_email = row

        # in_reply_to is None — listener falls back to Reply-Token in body
        body_with_token = f"Rejected, too short notice.\n\nReply-Token: {outbound_msg_id}"

        from services.email_listener import process_inbound_email
        result = process_inbound_email(
            ds=ds,
            tenant_id=tenant_id,
            from_email=assigned_email,
            in_reply_to=None,
            body_text=body_with_token,
        )

        assert result["resolved"] is True, f"Expected resolved=True, got: {result}"
        assert result["decision"] == "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Sender verification
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessInboundEmailSenderVerification:
    def test_wrong_sender_rejected(self, ds, registry, tenant_id, db_conn):
        _submit_leave(registry, tenant_id)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT outbound_message_id FROM pending_actions WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
        assert row
        outbound_msg_id = row[0]

        from services.email_listener import process_inbound_email
        result = process_inbound_email(
            ds=ds,
            tenant_id=tenant_id,
            from_email="attacker@evil.com",
            in_reply_to=outbound_msg_id,
            body_text="Approved.",
        )

        assert result["resolved"] is False
        assert result["error"] == "sender_not_authorised"

        # Leave request must still be pending
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM leave_requests WHERE tenant_id = %s ORDER BY updated_at DESC LIMIT 1",
                (tenant_id,),
            )
            lr = cur.fetchone()
        assert lr and lr[0] == "pending_approval"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Decision parsing (unit tests, no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisionParsing:
    @pytest.mark.parametrize("body,expected", [
        # Clear approvals
        ("Approved.", "approved"),
        ("I hereby approved this request.", "approved"),
        ("APPROVED", "approved"),
        # Clear rejections
        ("Rejected.", "rejected"),
        ("I rejected this.", "rejected"),
        # Negated approvals → None
        ("I don't think this should be approved.", None),
        ("Not approved.", None),
        # Negated rejections → None
        ("Should not be rejected.", None),
        ("never rejected this before, approved", None),  # both keywords → ambiguous
        # Ambiguous (both)
        ("approved but then rejected", None),
        # Quoted content should be stripped
        ("> I think it should be approved\nRejected.", "rejected"),
        # Empty / no keyword
        ("Thanks for the email.", None),
    ])
    def test_parse_decision(self, body, expected):
        from services.email_listener import parse_decision
        assert parse_decision(body) == expected


# ─────────────────────────────────────────────────────────────────────────────
# 6. simulate-inbound HTTP endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestSimulateInboundEndpoint:
    def test_simulate_inbound_endpoint_approves(
        self, client, make_jwt, ds, registry, tenant_id, db_conn
    ):
        _submit_leave(registry, tenant_id)

        with db_conn.cursor() as cur:
            cur.execute(
                """SELECT pa.outbound_message_id, pa.assigned_to_email
                   FROM pending_actions pa WHERE pa.tenant_id = %s""",
                (tenant_id,),
            )
            row = cur.fetchone()
        assert row
        outbound_msg_id, assigned_email = row

        token = make_jwt(employee_code="EMP002", role="hr_manager")
        resp = client.post(
            "/api/email/simulate-inbound",
            json={
                "from_email": assigned_email,
                "in_reply_to": outbound_msg_id,
                "body_text": "Approved. All good.",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["resolved"] is True
        assert data["decision"] == "approved"
        assert data["error"] is None
