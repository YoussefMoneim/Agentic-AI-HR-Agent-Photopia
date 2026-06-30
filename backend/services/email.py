"""
services/email.py — Email send with priority: ACS → SMTP → mock.

ACS is used when AZURE_COMMUNICATION_CONNECTION_STRING is set.
SMTP (smtplib, stdlib only) is used when SMTP_HOST + SMTP_USERNAME + SMTP_PASSWORD are set.
Mock (log-only) is the final fallback — safe for local dev and testing.

All three paths accept an optional message_id parameter (RFC 2822 Message-ID header,
angle-bracket-wrapped, e.g. "<uuid@hr.fotopia.com>"). The SMTP path sets it on the
outgoing message so the manager's email client threads replies with In-Reply-To.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

_log = logging.getLogger(__name__)


def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    body_plain: str,
    message_id: str | None = None,
    in_reply_to: str | None = None,
) -> bool:
    """Send an email. Returns True on success, False on send failure."""

    # ── Path 1: Azure Communication Services ─────────────────────────────────
    if config.AZURE_COMMUNICATION_CONNECTION_STRING:
        return _send_via_acs(to_email, subject, body_html, body_plain)

    # ── Path 2: SMTP (smtplib, stdlib) ───────────────────────────────────────
    if config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD:
        return _send_via_smtp(to_email, subject, body_html, body_plain, message_id, in_reply_to)

    # ── Path 3: Mock (log only) ───────────────────────────────────────────────
    _log.info(
        "EMAIL [mock] TO=%s | SUBJECT=%s | MESSAGE-ID=%s | IN-REPLY-TO=%s\n%s",
        to_email, subject, message_id or "(none)", in_reply_to or "(none)", body_plain,
    )
    return True


def _send_via_acs(
    to_email: str, subject: str, body_html: str, body_plain: str
) -> bool:
    try:
        from azure.communication.email import EmailClient
        client = EmailClient.from_connection_string(
            config.AZURE_COMMUNICATION_CONNECTION_STRING
        )
        message = {
            "content": {
                "subject": subject,
                "plainText": body_plain,
                "html": body_html,
            },
            "recipients": {"to": [{"address": to_email}]},
            "senderAddress": config.AZURE_COMMUNICATION_SENDER_EMAIL,
        }
        poller = client.begin_send(message)
        result = poller.result()
        succeeded = result.get("status") == "Succeeded"
        if not succeeded:
            _log.warning("ACS send returned non-success status: %s", result)
        return succeeded

    except ImportError:
        _log.warning(
            "azure-communication-email not installed; re-entering SMTP/mock path"
        )
        if config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD:
            return _send_via_smtp(to_email, subject, body_html, body_plain, None)
        _log.info("EMAIL [mock] TO=%s | SUBJECT=%s\n%s", to_email, subject, body_plain)
        return True

    except Exception:
        _log.exception("ACS send failed for %s; not retrying", to_email)
        return False


def _send_via_smtp(
    to_email: str,
    subject: str,
    body_html: str,
    body_plain: str,
    message_id: str | None,
    in_reply_to: str | None = None,
) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.SMTP_FROM_ADDRESS or config.SMTP_USERNAME
        msg["To"] = to_email
        if message_id:
            msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        # Plain first, HTML last — RFC 2046 preference order (most capable client uses last)
        msg.attach(MIMEText(body_plain, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
            smtp.ehlo()
            if config.SMTP_USE_STARTTLS:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            smtp.sendmail(
                config.SMTP_FROM_ADDRESS or config.SMTP_USERNAME,
                to_email,
                msg.as_bytes(),
            )

        _log.info(
            "EMAIL [smtp] TO=%s | SUBJECT=%s | MESSAGE-ID=%s",
            to_email, subject, message_id or "(none)",
        )
        return True

    except Exception:
        _log.exception("SMTP send failed for %s", to_email)
        return False
