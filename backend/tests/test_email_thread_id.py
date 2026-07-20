"""
Tests for services/email_listener.py::_extract_thread_id and
services/email_listener.py::_strip_quoted_content.

Only exercises pure header/text-parsing logic (no DB/IMAP), except
TestQuoteStrippingWiredIntoListener which exercises _process_imap_message
end-to-end with a fake IMAP connection and a mocked DataSource.
"""
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from services.email_listener import _extract_thread_id, _strip_quoted_content


class _FakeMsg(dict):
    """Minimal stand-in for email.message.Message — supports .get(name, default)."""


def test_prefers_references_root_over_in_reply_to():
    msg = _FakeMsg({
        "References": "<root@x> <mid1@x> <mid2@x>",
        "In-Reply-To": "<mid2@x>",
        "Message-ID": "<mid3@x>",
    })
    assert _extract_thread_id(msg) == "root@x"


def test_falls_back_to_in_reply_to_when_no_references():
    msg = _FakeMsg({"In-Reply-To": "<parent@x>", "Message-ID": "<child@x>"})
    assert _extract_thread_id(msg) == "parent@x"


def test_falls_back_to_message_id_for_new_thread():
    msg = _FakeMsg({"Message-ID": "<first@x>"})
    assert _extract_thread_id(msg) == "first@x"


def test_generates_uuid_when_no_headers_present():
    msg = _FakeMsg({})
    thread_id = _extract_thread_id(msg)
    assert thread_id  # non-empty
    assert "@" not in thread_id  # UUID fallback, not a message-id shape


def test_strips_angle_brackets():
    msg = _FakeMsg({"References": "<abc123@mail.example.com>"})
    assert _extract_thread_id(msg) == "abc123@mail.example.com"


class TestThreadIdStabilityAcrossHops:
    """
    Regression coverage for the bug where a mid-conversation leave-type
    change ("actually, sick leave") got lost: our own outgoing References
    header used to be re-derived from whatever the inbound message carried
    (see old services/email.py::_send_via_smtp), truncating to a single ID
    on every hop. After ~2 hops the true thread root dropped out of the
    chain the recipient's client sent back, and _extract_thread_id() minted
    a brand-new, history-less thread mid-conversation.

    The fix (services/email_agent.py::_send_reply) anchors the outgoing
    References header to the stable thread_id on every reply, regardless of
    hop count. This simulates a compliant mail client (References = parent's
    References + parent's Message-ID) to prove thread_id now stays stable
    across arbitrarily many hops.
    """

    def test_thread_id_stays_stable_across_three_hops(self):
        # Turn 1: employee's first email — brand new thread
        msg1 = _FakeMsg({"Message-ID": "<m1@client>"})
        thread_id = _extract_thread_id(msg1)
        assert thread_id == "m1@client"

        # Our reply anchors References to thread_id (the fix) instead of
        # deriving it from msg1's headers.
        reply1_references = f"<{thread_id}>"
        reply1_message_id = "<r1@agent>"

        # Turn 2: employee replies to our reply. A compliant client builds
        # References = parent's References + parent's Message-ID.
        msg2 = _FakeMsg({
            "References": f"{reply1_references} {reply1_message_id}",
            "In-Reply-To": reply1_message_id,
            "Message-ID": "<m2@client>",
        })
        assert _extract_thread_id(msg2) == thread_id

        # Our second reply re-anchors to the SAME thread_id — not
        # accumulated from what we received.
        reply2_references = f"<{thread_id}>"
        reply2_message_id = "<r2@agent>"

        # Turn 3: employee replies again.
        msg3 = _FakeMsg({
            "References": f"{reply2_references} {reply2_message_id}",
            "In-Reply-To": reply2_message_id,
            "Message-ID": "<m3@client>",
        })
        assert _extract_thread_id(msg3) == thread_id

    def test_old_single_entry_references_would_drift_after_two_hops(self):
        """
        Documents the OLD (buggy) behaviour for contrast: if our reply's
        References is derived hop-by-hop from the inbound message (the old
        `in_reply_to`-derived approach) instead of anchored to thread_id,
        the true root drops out by the third message.
        """
        msg1 = _FakeMsg({"Message-ID": "<m1@client>"})
        thread_id = _extract_thread_id(msg1)

        # OLD behaviour: our reply's References = just the id it was
        # replying to (single entry), not the stable thread_id.
        reply1_references = "<m1@client>"
        reply1_message_id = "<r1@agent>"

        msg2 = _FakeMsg({
            "References": f"{reply1_references} {reply1_message_id}",
            "In-Reply-To": reply1_message_id,
            "Message-ID": "<m2@client>",
        })
        assert _extract_thread_id(msg2) == thread_id  # still fine after 1 hop

        # OLD behaviour again: References = just r1's id (single entry) —
        # m1 has already dropped out.
        reply2_references = "<r1@agent>"
        reply2_message_id = "<r2@agent>"

        msg3 = _FakeMsg({
            "References": f"{reply2_references} {reply2_message_id}",
            "In-Reply-To": reply2_message_id,
            "Message-ID": "<m3@client>",
        })
        # The true root has dropped out — thread_id drifts to r1's id
        # instead of staying at m1. This is the bug that got fixed.
        assert _extract_thread_id(msg3) != thread_id
        assert _extract_thread_id(msg3) == "r1@agent"


# ── Quote stripping — regression for the Outlook placeholder-date bug ────────

# Shaped after a real Outlook reply that triggered the bug in production:
# replying "Annual leave" to the agent's own "Details Needed" email quoted
# that reply back verbatim — including its placeholder example dates.
_OUTLOOK_QUOTED_REPLY = (
    "Annual leave\r\n"
    "________________________________\r\n"
    "From: Fotoagent <fotoagent@fotopiatech.com>\r\n"
    "Sent: 10 July 2026 10:48\r\n"
    "To: Saif Ahmed <i-saif.ahmed@fotopiatech.com>\r\n"
    "Subject: Re: Holiday request\r\n"
    "\r\n"
    "Fotopia HR System\r\n"
    "WIN Holding Group — HR Portal\r\n"
    "Leave Request — Details Needed\r\n"
    "\r\n"
    "Dear Saif Ahmed,\n\n"
    "Got it — Annual leave noted. To submit your leave request, please provide:\n"
    "- Start date (e.g. 2026-07-21)\n"
    "- End date (e.g. 2026-07-23)\n\n"
    "Or log into the HR portal."
)


class TestStripQuotedContent:

    def test_strips_outlook_header_block(self):
        """
        Regression test: "Annual leave" + Outlook's quoted reply (containing
        OUR OWN placeholder dates "e.g. 2026-07-21" / "e.g. 2026-07-23") must
        not leak those dates through — they previously got submitted as if
        the employee had typed them. Stripping must cut everything from the
        underscore separator onward.
        """
        result = _strip_quoted_content(_OUTLOOK_QUOTED_REPLY)
        assert result == "Annual leave"
        assert "2026-07-21" not in result
        assert "2026-07-23" not in result

    def test_strips_gmail_style_wrote_preamble(self):
        body = (
            "Sounds good.\n"
            "On Fri, Jul 10, 2026 at 10:00 AM Fotoagent <x@y.com> wrote:\n"
            "> old content"
        )
        assert _strip_quoted_content(body) == "Sounds good."

    def test_strips_angle_bracket_quoted_lines(self):
        body = "> old quoted line\nNew reply text"
        assert _strip_quoted_content(body) == "New reply text"

    def test_cuts_at_own_reply_signature_even_without_header_block(self):
        """
        Some clients render the quoted HTML reply without a From:/Sent:
        header block at all — the branded signature phrase alone must still
        be enough to cut the tail.
        """
        body = "annual leave\n\nFotopia HR System\nWIN Holding Group — HR Portal\nDetails Needed..."
        assert _strip_quoted_content(body) == "annual leave"

    def test_no_quoted_content_passes_through_unchanged(self):
        body = "I want annual leave from 2026-07-27 to 2026-07-29"
        assert _strip_quoted_content(body) == body


class TestQuoteStrippingWiredIntoListener:

    def test_process_imap_message_strips_quotes_before_email_agent(self):
        """
        Full-pipeline regression: build a real RFC822 message shaped like the
        Outlook reply that triggered the bug, run it through
        _process_imap_message, and assert the email agent receives only
        "Annual leave" — not the quoted placeholder dates.
        """
        from services.email_listener import _process_imap_message

        msg = EmailMessage()
        msg["From"] = "Saif Ahmed <employee@example.com>"
        msg["To"] = "hr.agent.fotopia@gmail.com"
        msg["Subject"] = "Re: Holiday request"
        msg["Message-ID"] = "<new@example.com>"
        msg["In-Reply-To"] = "<prev@example.com>"
        msg["References"] = "<root@example.com> <prev@example.com>"
        msg.set_content(_OUTLOOK_QUOTED_REPLY)
        raw = bytes(msg)

        imap = MagicMock()
        imap.fetch.return_value = ("OK", [(b"1", raw)])

        ds = MagicMock()
        ds.get_pending_action_by_outbound_message_id.return_value = None

        with patch("services.email_agent.process_employee_email") as mock_agent:
            with patch("services.email_listener.config") as mock_cfg:
                mock_cfg.SMTP_FROM_ADDRESS = "hr.agent.fotopia@gmail.com"
                _process_imap_message(imap, b"1", ds, "tenant-1")

        mock_agent.assert_called_once()
        kwargs = mock_agent.call_args.kwargs
        assert kwargs["body_text"] == "Annual leave"
