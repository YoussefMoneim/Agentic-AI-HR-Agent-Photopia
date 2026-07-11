"""
Tests for services/email.py::_send_via_smtp header construction.

Regression coverage for the bug where References was unconditionally
overwritten with in_reply_to (`msg["References"] = in_reply_to`), discarding
any accumulated/anchored chain a caller intended to send. That silently
truncated every outgoing reply's References to a single entry, which after
~2 hops dropped the true thread root and caused services/email_listener.py's
_extract_thread_id() to mint a brand-new, history-less thread mid-conversation
(see tests/test_email_thread_id.py::TestThreadIdStabilityAcrossHops and
tests/test_email_agent.py::test_reply_anchors_references_to_thread_id).
"""
from unittest.mock import MagicMock, patch

from services.email import send_email


def _send_via_mocked_smtp(**send_email_kwargs) -> bytes:
    """Call send_email() with SMTP forced as the active path, and capture
    the raw bytes handed to smtplib's sendmail()."""
    captured = {}

    def fake_sendmail(from_addr, to_addr, raw_bytes):
        captured["raw"] = raw_bytes

    with patch("services.email.config") as cfg:
        cfg.AZURE_COMMUNICATION_CONNECTION_STRING = ""
        cfg.SMTP_HOST = "smtp.example.com"
        cfg.SMTP_PORT = 587
        cfg.SMTP_USERNAME = "user"
        cfg.SMTP_PASSWORD = "pass"
        cfg.SMTP_FROM_ADDRESS = "agent@example.com"
        cfg.SMTP_USE_STARTTLS = True

        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("1.2.3.4", 587))]):
            with patch("smtplib.SMTP") as mock_smtp_cls:
                instance = MagicMock()
                instance.__enter__.return_value = instance
                instance.sendmail.side_effect = fake_sendmail
                mock_smtp_cls.return_value = instance

                send_email(
                    to_email="employee@example.com",
                    subject="Re: Leave request",
                    body_html="<p>hi</p>",
                    body_plain="hi",
                    **send_email_kwargs,
                )

    return captured["raw"]


class TestReferencesHeaderConstruction:

    def test_explicit_references_is_sent_verbatim_not_overwritten_by_in_reply_to(self):
        raw = _send_via_mocked_smtp(
            message_id="<r2@agent>",
            in_reply_to="<m2@client>",
            references="<root@client>",
        )
        assert b"References: <root@client>" in raw
        assert b"In-Reply-To: <m2@client>" in raw

    def test_falls_back_to_in_reply_to_when_references_not_given(self):
        """Backward-compat: callers not tracking a stable thread anchor still
        get a References header (old single-entry behaviour, unchanged)."""
        raw = _send_via_mocked_smtp(
            message_id="<r1@agent>",
            in_reply_to="<m1@client>",
        )
        assert b"References: <m1@client>" in raw
