"""
services/email_listener.py — Inbound email processing for leave approval replies.

Three public entry points:
  parse_decision(body_text)          — pure function; security-critical decision parser
  process_inbound_email(...)         — pure function; called by IMAP loop AND simulate endpoint
  run_email_listener(ds, tenant_id)  — async task loop; started from api/main.py lifespan

Design principles:
  - No new pip dependencies; uses stdlib imaplib, email, re only.
  - All resolution goes through ds.resolve_pending_action() — same path as link-click.
  - Emails are always marked \\Seen after processing — even on parse failure — to prevent
    infinite retry on the same message.
  - Disabled silently when EMAIL_LISTENER_ENABLED=false or credentials missing.
  - Symmetric with link-click path: employee confirmation email sent after resolution.
"""
from __future__ import annotations

import asyncio
import email as _email_stdlib
import email.header
import email.utils
import imaplib
import logging
import re
import uuid
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from data.base import DataSource

_log = logging.getLogger(__name__)

# ── Decision parsing constants ─────────────────────────────────────────────────

_NEGATIONS = frozenset([
    "not", "n't", "never", "don't", "doesn't", "didn't",
    "shouldn't", "won't", "cannot", "can't", "no",
])

_QUOTED_LINE_RE = re.compile(r"^>.*", re.MULTILINE)
_QUOTE_PREAMBLE_RE = re.compile(r"^On .+wrote:.*$", re.MULTILINE | re.DOTALL)
_REPLY_TOKEN_RE = re.compile(r"Reply-Token:\s*(<[^>]+>)", re.IGNORECASE)

# Outlook's default reply/forward quote block: a long underscore separator,
# or the "From:/Sent:/To:/Subject:" header block it inserts above the quoted
# message. Neither is caught by _QUOTE_PREAMBLE_RE (Gmail/Apple-Mail style
# "On ... wrote:" only).
_OUTLOOK_QUOTE_RE = re.compile(
    r"^_{5,}\s*$|^From:.*\r?\nSent:.*\r?\nTo:.*\r?\nSubject:.*$",
    re.MULTILINE,
)
# Belt-and-suspenders: this exact phrase only ever appears inside our own
# branded reply template (_send_reply in services/email_agent.py). If a mail
# client renders the quoted HTML reply as plain text and echoes it back
# (seen from Outlook), this phrase marks where OUR text starts — anything
# from here on is quoted, never new content from the sender.
_OWN_REPLY_SIGNATURE_RE = re.compile(r"Fotopia HR System", re.IGNORECASE)


# ── Private helpers ───────────────────────────────────────────────────────────

def _has_negation_before(text: str, match_start: int) -> bool:
    """Return True if a negation word appears within 60 chars before match_start."""
    window = text[max(0, match_start - 60):match_start]
    tokens = re.findall(r"\b\w+(?:'\w+)?\b", window)
    return bool(frozenset(tokens) & _NEGATIONS)


def _strip_quoted_content(body_text: str) -> str:
    """Remove quoted prior-message content, leaving only the sender's new text.

    Must run before body text reaches any content-sensitive parsing (decision
    parsing, intent classification, regex date/leave-type extraction) —
    otherwise a mail client that echoes the previous message back (Outlook's
    "From:/Sent:/To:/Subject:" block, Gmail/Apple-Mail's "On ... wrote:", or
    plain ">"-quoting) can leak OUR OWN previous reply — including its
    placeholder example text like "Start date (e.g. 2026-07-21)" — back in as
    if the sender had typed it. That previously caused the email leave-request
    flow to silently submit using the example dates instead of asking again.
    """
    text = _QUOTED_LINE_RE.sub("", body_text)
    text = _QUOTE_PREAMBLE_RE.sub("", text)
    for pattern in (_OUTLOOK_QUOTE_RE, _OWN_REPLY_SIGNATURE_RE):
        m = pattern.search(text)
        if m:
            text = text[:m.start()]
    return text.strip()


# ── Public interface ──────────────────────────────────────────────────────────

def parse_decision(body_text: str) -> str | None:
    """Extract approve/reject decision from email body text.

    Returns 'approved', 'rejected', or None (ambiguous/unrecognised).
    Security-critical: designed to fail CLOSED (return None) on any ambiguity.
    Strips quoted reply content before parsing — operates on new content only.
    """
    text = _strip_quoted_content(body_text).lower()

    approved_match = re.search(r"\bapproved\b", text)
    rejected_match = re.search(r"\brejected\b", text)

    # Both present — ambiguous
    if approved_match and rejected_match:
        _log.debug("parse_decision: both keywords found — ambiguous")
        return None

    # Neither present
    if not approved_match and not rejected_match:
        _log.debug("parse_decision: no decision keyword found")
        return None

    # One keyword found — apply negation guard
    if approved_match:
        if _has_negation_before(text, approved_match.start()):
            _log.debug("parse_decision: 'approved' negated — ambiguous")
            return None
        return "approved"

    # rejected_match only
    if _has_negation_before(text, rejected_match.start()):
        _log.debug("parse_decision: 'rejected' negated — ambiguous")
        return None
    return "rejected"


def process_inbound_email(
    ds: "DataSource",
    tenant_id: str,
    from_email: str,
    in_reply_to: str | None,
    body_text: str,
) -> dict:
    """Process one inbound email reply.

    Callable by both the IMAP polling loop and the simulate-inbound endpoint.

    Lookup order:
      1. in_reply_to → pending_actions.outbound_message_id (primary)
      2. Reply-Token: <uuid@domain> in body_text (fallback)

    Returns dict with keys:
      resolved (bool), decision (str|None), error (str|None),
      pending_action_id (str|None), already_resolved (bool)
    """
    _log.info(
        "process_inbound_email: from=%s in_reply_to=%s",
        from_email, in_reply_to,
    )

    # ── Step 1: Locate the pending_action ────────────────────────────────────
    pa = None

    if in_reply_to:
        pa = ds.get_pending_action_by_outbound_message_id(tenant_id, in_reply_to)
        if pa:
            _log.debug("Matched pending_action %s via In-Reply-To", pa["id"])

    if pa is None:
        token_match = _REPLY_TOKEN_RE.search(body_text)
        if token_match:
            token_value = token_match.group(1)
            pa = ds.get_pending_action_by_outbound_message_id(tenant_id, token_value)
            if pa:
                _log.debug("Matched pending_action %s via Reply-Token in body", pa["id"])

    if pa is None:
        _log.warning(
            "process_inbound_email: no matching pending_action — from=%s in_reply_to=%s",
            from_email, in_reply_to,
        )
        return {
            "resolved": False,
            "decision": None,
            "error": "no_matching_pending_action",
            "pending_action_id": None,
            "already_resolved": False,
        }

    # ── Step 2: Idempotency check ─────────────────────────────────────────────
    if pa["status"] != "pending":
        _log.info(
            "process_inbound_email: pending_action %s already resolved (%s)",
            pa["id"], pa["status"],
        )
        return {
            "resolved": True,
            "decision": pa["status"],
            "error": None,
            "pending_action_id": pa["id"],
            "already_resolved": True,
        }

    # ── Step 3: Sender verification ───────────────────────────────────────────
    if from_email.strip().lower() != pa["assigned_to_email"].strip().lower():
        _log.warning(
            "process_inbound_email: sender %s does not match assigned_to_email %s "
            "for pending_action %s",
            from_email, pa["assigned_to_email"], pa["id"],
        )
        return {
            "resolved": False,
            "decision": None,
            "error": "sender_not_authorised",
            "pending_action_id": pa["id"],
            "already_resolved": False,
        }

    # ── Step 4: Parse decision ────────────────────────────────────────────────
    decision = parse_decision(body_text)
    if decision is None:
        _log.warning(
            "process_inbound_email: ambiguous decision from %s for pending_action %s — "
            "body snippet: %r",
            from_email, pa["id"], body_text[:200],
        )
        return {
            "resolved": False,
            "decision": None,
            "error": "ambiguous_decision",
            "pending_action_id": pa["id"],
            "already_resolved": False,
        }

    # ── Step 5: Resolve ───────────────────────────────────────────────────────
    result = ds.resolve_pending_action(
        tenant_id=tenant_id,
        correlation_token=pa["correlation_token"],
        decision=decision,
        resolved_by_code=None,
        note=f"Resolved via email reply from {from_email} (decision: {decision})",
    )

    if not result.get("success"):
        _log.error(
            "process_inbound_email: resolve_pending_action failed for %s: %s",
            pa["id"], result.get("error"),
        )
        return {
            "resolved": False,
            "decision": decision,
            "error": result.get("error", "resolve_failed"),
            "pending_action_id": pa["id"],
            "already_resolved": False,
        }

    # ── Step 6: Employee confirmation email ───────────────────────────────────
    # Symmetric with the link-click path in api/main.py — employee must be notified
    # regardless of which resolution path was used. Shared branded template with
    # the chat-tool and email-link paths (tools.leave.send_leave_decision_email).
    try:
        leave_request_id = result.get("leave_request_id")
        if leave_request_id:
            from tools.leave import send_leave_decision_email
            send_leave_decision_email(ds, tenant_id, leave_request_id, decision)
    except Exception:
        _log.exception(
            "process_inbound_email: failed to send employee confirmation for %s", pa["id"]
        )

    # ── Step 7: Write email_reply_resolved workflow event ─────────────────────
    try:
        ds.create_workflow_event(
            tenant_id=tenant_id,
            workflow_instance_id=pa["workflow_instance_id"],
            event_type="email_reply_resolved",
            actor_employee_id=pa.get("assigned_to_employee_id"),
            actor_user_id=None,
            data={
                "decision": decision,
                "from_email": from_email,
                "in_reply_to": in_reply_to,
                "pending_action_id": pa["id"],
            },
        )
    except Exception:
        _log.exception(
            "process_inbound_email: failed to write email_reply_resolved event for %s",
            pa["id"],
        )

    _log.info(
        "process_inbound_email: resolved pending_action %s → %s", pa["id"], decision
    )
    return {
        "resolved": True,
        "decision": decision,
        "error": None,
        "pending_action_id": pa["id"],
        "already_resolved": False,
    }


# ── IMAP polling internals ────────────────────────────────────────────────────

def _extract_body(msg) -> str:
    """Extract plain text body from an email.message.Message object."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            return ""


def _extract_thread_id(msg) -> str:
    """
    Extract a stable thread identifier from email headers.
    Prefers References (the full thread chain — first ID is the root),
    falls back to In-Reply-To (immediate parent), then this message's own
    Message-ID (new thread), then a random UUID if none of those exist.
    """
    references = msg.get("References", "").strip()
    if references:
        first_ref = references.split()[0].strip()
        if first_ref:
            return first_ref.strip("<>")

    in_reply_to = msg.get("In-Reply-To", "").strip()
    if in_reply_to:
        return in_reply_to.strip("<>")

    message_id = msg.get("Message-ID", "").strip()
    return message_id.strip("<>") if message_id else str(uuid.uuid4())


def _decode_header_value(raw: str | None) -> str:
    """Decode RFC 2047 encoded email header values."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for part_bytes, charset in parts:
        if isinstance(part_bytes, bytes):
            decoded.append(part_bytes.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part_bytes)
    return "".join(decoded)


def _process_imap_message(
    imap: imaplib.IMAP4_SSL,
    msg_id: bytes,
    ds: "DataSource",
    tenant_id: str,
) -> None:
    """Fetch one IMAP message, call process_inbound_email, then mark Seen."""
    status, data = imap.fetch(msg_id, "(RFC822)")
    if status != "OK" or not data or not data[0]:
        _log.warning("IMAP fetch failed for message %s: status=%s", msg_id, status)
        imap.store(msg_id, "+FLAGS", "\\Seen")
        return

    raw = data[0][1]
    msg = _email_stdlib.message_from_bytes(raw)

    from_raw = _decode_header_value(msg.get("From", ""))
    _, from_addr = email.utils.parseaddr(from_raw)
    from_email = from_addr.strip().lower()

    # Self-email guard: never process emails sent by our own SMTP address.
    # In demo mode the system sends to itself; without this guard the listener
    # would process every outbound approval notification as if it were a reply.
    own_address = config.SMTP_FROM_ADDRESS.strip().lower()
    if own_address and from_email == own_address:
        _log.debug(
            "IMAP: skipping self-sent message %s (from=%s matches SMTP_FROM_ADDRESS)",
            msg_id, from_email,
        )
        imap.store(msg_id, "+FLAGS", "\\Seen")
        return

    in_reply_to = msg.get("In-Reply-To", "").strip() or None
    message_id = msg.get("Message-ID", "").strip() or None
    thread_id = _extract_thread_id(msg)
    body_text = _extract_body(msg)

    _log.debug(
        "IMAP: processing message %s from=%s in_reply_to=%s body_len=%d",
        msg_id, from_email, in_reply_to, len(body_text),
    )

    resolution = process_inbound_email(
        ds=ds,
        tenant_id=tenant_id,
        from_email=from_email,
        in_reply_to=in_reply_to,
        body_text=body_text,
    )

    if not resolution.get("resolved"):
        from services.email_agent import process_employee_email  # noqa: PLC0415
        msg_headers = {k.lower(): v for k, v in msg.items()}
        process_employee_email(
            ds=ds,
            tenant_id=tenant_id,
            from_email=from_email,
            body_text=_strip_quoted_content(body_text),
            in_reply_to_message_id=in_reply_to,
            our_message_id=message_id,
            msg_headers=msg_headers,
            thread_id=thread_id,
        )

    # Always mark Seen — even on parse failure — to prevent infinite retry
    imap.store(msg_id, "+FLAGS", "\\Seen")
    _log.debug("IMAP: marked message %s as Seen", msg_id)


def _poll_once(ds: "DataSource", tenant_id: str) -> None:
    """One IMAP polling pass: connect, search UNSEEN, process each, disconnect."""
    _log.debug("IMAP poll starting")
    try:
        with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT) as imap:
            imap.login(config.IMAP_USERNAME, config.IMAP_PASSWORD)
            imap.select("INBOX")

            status, data = imap.search(None, "UNSEEN")
            if status != "OK":
                _log.warning("IMAP SEARCH returned status=%s", status)
                return

            message_ids = data[0].split()
            if not message_ids:
                _log.debug("IMAP poll: no unseen messages")
                return

            _log.info("IMAP poll: %d unseen message(s)", len(message_ids))

            for msg_id in message_ids:
                try:
                    _process_imap_message(imap, msg_id, ds, tenant_id)
                except Exception:
                    _log.exception(
                        "IMAP: unhandled error on message %s; marking Seen", msg_id
                    )
                    try:
                        imap.store(msg_id, "+FLAGS", "\\Seen")
                    except Exception:
                        _log.exception("IMAP: failed to mark %s as Seen after error", msg_id)

    except imaplib.IMAP4.error:
        _log.exception("IMAP connection/auth error — will retry next poll")
    except Exception:
        _log.exception("Unexpected error in IMAP poll — will retry next poll")


async def run_email_listener(ds: "DataSource", tenant_id: str) -> None:
    """Async background task: poll IMAP on a fixed interval.

    Exits silently if not enabled or credentials are missing.
    Uses run_in_executor to avoid blocking the event loop during IMAP I/O.
    """
    if not config.EMAIL_LISTENER_ENABLED:
        _log.info("Email listener disabled (EMAIL_LISTENER_ENABLED=false)")
        return
    if not (config.IMAP_HOST and config.IMAP_USERNAME and config.IMAP_PASSWORD):
        _log.info(
            "Email listener: IMAP credentials not configured — listener not started"
        )
        return

    _log.info(
        "Email listener started: host=%s port=%d interval=%ds",
        config.IMAP_HOST, config.IMAP_PORT, config.EMAIL_LISTENER_POLL_INTERVAL_SECONDS,
    )

    while True:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _poll_once, ds, tenant_id)
        except Exception:
            _log.exception("Unexpected error in email listener task — continuing")

        await asyncio.sleep(config.EMAIL_LISTENER_POLL_INTERVAL_SECONDS)
