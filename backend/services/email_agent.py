"""
services/email_agent.py — Handles employee emails that are not workflow replies.

Security pipeline (must never be reordered):
  1. Loop detection  — header check only, zero DB access
  2. Identity check  — ds.get_employee_by_email()
  3. Rate limit      — ds.check_and_record_rate_limit()
  4. Intent classify — LLM (Haiku) classification, keyword fallback on error
  5. Tool dispatch   — employee's real DB role via ToolRegistry.execute()
  6. Branded HTML reply — send_email(), never LLM-generated body text

Invariants:
  - send_email() is NEVER called for auto-reply, self-email, or unregistered senders
  - Rate-limited senders receive exactly ONE polite reply, then return
  - ctx.role always sourced from employees+users DB join, never from email content
  - anthropic SDK imported lazily inside _classify_intent() only (via llm/claude.py)
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import config
from llm.claude import ClaudeProvider
from services.email import send_email
from tools.base import ToolContext

if TYPE_CHECKING:
    from data.base import DataSource
    from tools.registry import ToolRegistry


@dataclass
class EmailIntent:
    intent: str
    confidence: str = "low"
    extracted_params: dict = field(default_factory=dict)
    reason: str = ""

_log = logging.getLogger(__name__)

_MAX_BODY_CHARS = 500

# Auto-reply headers — checked BEFORE any DB access.
_AUTO_REPLY_HEADERS = frozenset([
    "auto-submitted",
    "x-autoreply",
    "x-auto-reply",
    "x-autoresponder",
    "x-autorespond",
])
_AUTO_REPLY_VALUES = frozenset(["auto-replied", "auto-generated", "bulk", "list", "junk"])

# Intent keyword sets — cancellation checked before request (more specific).
_LEAVE_CANCELLATION_KEYWORDS = frozenset([
    "cancel", "cancellation", "withdraw", "cancel my leave",
    "cancel leave", "don't need", "no longer need",
    "إلغاء", "الغاء",
])
_LEAVE_REQUEST_KEYWORDS = frozenset([
    "request leave", "take leave", "apply for leave", "time off",
    "day off", "days off", "vacation", "annual leave request",
    "sick leave", "submit leave", "need leave", "want leave", "want to take",
    "طلب إجازة", "إجازة",
])
_BALANCE_KEYWORDS = frozenset([
    "balance", "remaining", "how many days", "days left", "entitlement",
    "leave balance", "رصيد", "أيام متبقية",
])
_STATUS_KEYWORDS = frozenset([
    "status", "request", "pending", "approved", "rejected", "application",
    "طلب", "حالة",
])
_POLICY_KEYWORDS = frozenset([
    "policy", "policy question", "rules", "allowed", "eligible", "eligibility",
    "سياسة", "قواعد",
])

# Any recognizable date reference — digits, weekday/month names, or common
# relative-time phrases. Used to gate whether the LLM is even ALLOWED to
# return start_date/end_date (see _has_any_date_signal below).
_DATE_SIGNAL_RE = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}"                       # 2026-07-20
    r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"      # 20/07, 07-20-2026
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|january|february|march|april|may|june|july|august|september"
    r"|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
    r"|today|tomorrow|tonight"
    r"|next week|this week|next month|this month|next weekend|this weekend"
    r"|coming week|coming days|few days|couple of days"
    r")\b",
    re.IGNORECASE,
)


# ── Module-level lazy registry singleton ──────────────────────────────────────

_registry: "ToolRegistry | None" = None


def _get_registry(ds: "DataSource") -> "ToolRegistry":
    """Build (once) and return a ToolRegistry for email-agent tool calls."""
    global _registry
    if _registry is None:
        from audit.logger import AuditLogger
        from tools.registry import build_registry
        audit_logger = AuditLogger(config.DATABASE_URL)
        _registry = build_registry(ds, audit_logger)
    return _registry


# ── Loop detection ────────────────────────────────────────────────────────────

def _is_auto_reply(msg_headers: dict) -> bool:
    """Return True if any header signals a machine-generated message."""
    for raw_header, value in msg_headers.items():
        h = raw_header.lower()
        v = (value or "").strip().lower()
        if h == "auto-submitted" and v not in ("", "no"):
            return True
        if h in _AUTO_REPLY_HEADERS and any(kw in v for kw in _AUTO_REPLY_VALUES):
            return True
        if h == "precedence" and v in ("bulk", "list", "junk"):
            return True
    return False


# ── Intent classification ─────────────────────────────────────────────────────

def _format_thread_context(history: list[dict] | None) -> str:
    """
    Render prior turns as short lines for the classifier prompt, so a
    follow-up like "can I take 5 days of that?" resolves against what was
    already discussed (e.g. the leave_type from a prior balance_check).

    History is structured turn data (role/content/intent/extracted_params),
    never raw LLM chat — this only informs classification, it never becomes
    reply content (see module docstring invariant #6).
    """
    if not history:
        return ""
    lines = []
    for turn in history[-6:]:
        if turn.get("role") == "user":
            suffix = f" (classified as {turn['intent']})" if turn.get("intent") else ""
            lines.append(f"Employee previously said: {turn.get('content', '')}{suffix}")
        else:
            lines.append(f"Agent previously replied: {turn.get('content', '')}")
    return "\n".join(lines)


def _has_any_date_signal(body_text: str, history: list[dict] | None) -> bool:
    """
    True if the CURRENT message or any earlier USER turn (never our own
    assistant replies — those contain our own placeholder example dates,
    e.g. "e.g. 2026-07-21", which must never count as the employee having
    named a date) mentions anything date-shaped.

    Guards against the LLM inventing plausible-looking calendar dates for a
    leave request when nothing in the conversation ever specified one —
    e.g. "I want a holiday" -> "annual leave" -> "sick leave", with no date
    mentioned anywhere, must never silently submit using made-up dates.
    """
    combined = body_text or ""
    for turn in (history or []):
        if turn.get("role") == "user":
            combined += " " + (turn.get("content") or "")
    return bool(_DATE_SIGNAL_RE.search(combined))


def _classify_intent(
    body_text: str, subject: str = "", history: list[dict] | None = None
) -> EmailIntent:
    """
    Classify email intent using Claude Haiku LLM.

    SECURITY: Only passes subject + first 500 chars of body to LLM.
    FAIL CLOSED: Any error returns intent='unknown' via keyword fallback — never crashes.
    LLM extracts dates and leave type — no regex needed in handlers when successful.

    history (optional): prior turns in this email thread, used only to help
    resolve references ("that", "it", an earlier-mentioned leave type) —
    never used to generate reply content directly.
    """
    import json

    safe_subject = (subject or "")[:200]
    safe_body = (body_text or "")[:500]
    thread_context = _format_thread_context(history)
    context_block = (
        f"\nPrevious messages in this email thread (for resolving references only):\n"
        f"{thread_context}\n"
        if thread_context else ""
    )

    prompt = f"""You are an HR email classifier. Classify this email and extract key information.
{context_block}
Subject: {safe_subject}
Body: {safe_body}

Respond with ONLY valid JSON, no markdown, no explanation:
{{
  "intent": "leave_request" | "leave_cancellation" | "balance_check" | "leave_status" | "policy_question" | "unknown",
  "confidence": "high" | "medium" | "low",
  "extracted_params": {{
    "leave_type": "annual" | "sick" | "casual" | "maternity" | "paternity" | "hajj" | "umrah" | "marriage" | "funeral_1st_degree" | "funeral_2nd_degree" | "educational" | "military" | "compensatory_off" | "unpaid" | null,
    "start_date": "YYYY-MM-DD or null",
    "end_date": "YYYY-MM-DD or null",
    "reason": "reason text or null"
  }},
  "reason": "one sentence explaining this classification"
}}

Rules:
- "I want a holiday / leave / time off / vacation / break" → leave_request
- "first two weeks of August" → start_date: current year August 1, end_date: August 14 (the phrase itself fully specifies the range — safe to resolve)
- A vague relative period ("next week", "sometime next month", "in a few days") used ALONE, with no day-count that could conflict with it, may be resolved to its natural bounded range approximated from today's date (today is {__import__('datetime').date.today()})
- If the employee gives a specific NUMBER OF DAYS (e.g. "2 days", "3 days") together with a vague relative period like "next week" WITHOUT naming which exact days within that period, do NOT guess which days — set start_date and end_date to null so the employee is asked for exact dates. Example: "2 days sick leave next week" → leave_type: "sick", start_date: null, end_date: null (which 2 of the ~5-7 days in "next week" is not stated — never invent that choice)
- "cancel my leave / withdraw / don't need leave anymore" → leave_cancellation
- "what is my balance / how many days do I have" → balance_check
- "status of my request / is my leave approved" → leave_status
- "what is the policy / how many days do I get" → policy_question
- Greetings, unrelated, unclear with low confidence → unknown
- If the employee says "holiday" or "vacation" or "leave" or "time off" WITHOUT naming a specific type (annual, sick, casual, etc.), set leave_type to null — do NOT guess or assume annual. The employee must be asked to specify which type they mean.
- If dates are mentioned in any natural language form, convert to YYYY-MM-DD format
- If this email references something from the previous messages above (e.g. "that", "it", "the same leave type"), use those previous messages to fill in extracted_params — do not leave a field null if the thread context already answers it"""

    try:
        provider = ClaudeProvider(
            api_key=config.ANTHROPIC_API_KEY,
            model="claude-haiku-4-5-20251001",
        )
        response = provider.classify(
            system_prompt="You are an HR email classifier. Respond only with valid JSON.",
            user_text=prompt,
        )
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
        extracted_params = data.get("extracted_params") or {}
        if not _has_any_date_signal(body_text, history):
            # No date was ever actually mentioned by the employee, in this
            # message or any earlier turn — discard any date the LLM
            # invented anyway rather than trusting it into a real
            # submission. See _has_any_date_signal docstring.
            extracted_params["start_date"] = None
            extracted_params["end_date"] = None
        return EmailIntent(
            intent=data.get("intent", "unknown"),
            confidence=data.get("confidence", "low"),
            extracted_params=extracted_params,
            reason=data.get("reason", ""),
        )
    except Exception as e:
        _log.warning("LLM intent classification failed (falling back to keywords): %s", e)
        snippet = (body_text or "")[:_MAX_BODY_CHARS].lower()
        if any(kw in snippet for kw in _LEAVE_CANCELLATION_KEYWORDS):
            kw_intent = "leave_cancellation"
        elif any(kw in snippet for kw in _POLICY_KEYWORDS):
            kw_intent = "policy_question"
        elif any(kw in snippet for kw in _LEAVE_REQUEST_KEYWORDS):
            kw_intent = "leave_request"
        elif any(kw in snippet for kw in _BALANCE_KEYWORDS):
            kw_intent = "balance_check"
        elif any(kw in snippet for kw in _STATUS_KEYWORDS):
            kw_intent = "leave_status"
        else:
            kw_intent = "unknown"
        return EmailIntent(
            intent=kw_intent,
            confidence="low",
            extracted_params={},
            reason="Keyword fallback (LLM unavailable)",
        )


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(employee: dict, tenant_id: str) -> ToolContext:
    """Role always sourced from the DB join — never from email content."""
    return ToolContext(
        tenant_id=tenant_id,
        user_id=employee["employee_code"],
        role=employee.get("role", "employee"),
        employee_code=employee["employee_code"],
        display_name=employee.get("full_name", ""),
    )


# ── Branded HTML reply sender ─────────────────────────────────────────────────

def _send_reply(
    to_email: str,
    subject: str,
    title: str,
    icon: str,
    color: str,
    html_content: str,
    plain_content: str,
    in_reply_to: str | None,
    our_message_id: str | None,
    thread_id: str | None = None,
) -> None:
    """Send a branded HTML reply. Never called for skipped/unregistered senders.

    thread_id (optional): the stable thread identifier computed by
    services/email_listener.py::_extract_thread_id. Used to anchor the
    outgoing References header — see module docstring on why this must
    stay stable rather than being derived hop-by-hop from whatever the
    inbound message happened to carry.
    """
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    domain = (
        config.SMTP_FROM_ADDRESS.split("@")[-1]
        if "@" in config.SMTP_FROM_ADDRESS else "fotopiatech.com"
    )
    new_message_id = f"<fotopia-hr-agent-{uuid.uuid4()}@{domain}>"

    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:30px 15px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
  <tr>
    <td style="background:#0a0c1a;padding:24px 30px;text-align:center;border-radius:8px 8px 0 0">
      <div style="color:#fff;font-size:20px;font-weight:bold;letter-spacing:1px">Fotopia HR System</div>
      <div style="color:#c9a84c;font-size:12px;margin-top:5px">WIN Holding Group &mdash; HR Portal</div>
    </td>
  </tr>
  <tr>
    <td style="background:#fff;padding:32px 36px;border-radius:0 0 8px 8px">
      <div style="font-size:38px;text-align:center;margin-bottom:14px">{icon}</div>
      <h2 style="margin:0 0 20px 0;color:{color};font-size:20px;text-align:center">{title}</h2>
      {html_content}
      <hr style="border:none;border-top:1px solid #e0e0e0;margin:24px 0">
      <p style="margin:0;font-size:11px;color:#aaa;text-align:center">
        Fotopia HR System &mdash; Automated reply. For assistance contact
        <a href="mailto:hr.agent.fotopia@gmail.com" style="color:#c9a84c">hr.agent.fotopia@gmail.com</a>
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    send_email(
        to_email=to_email,
        subject=reply_subject,
        body_html=body_html,
        body_plain=plain_content,
        message_id=new_message_id,
        # Prefer the direct parent (this inbound message's own Message-ID)
        # over in_reply_to (that message's OWN In-Reply-To, i.e. one hop
        # further back) — the direct parent is always correct when present.
        in_reply_to=our_message_id or in_reply_to,
        # Anchor References to the stable thread_id rather than chaining
        # from whatever the inbound message carried. A single-entry
        # References header (the old behaviour) gets silently truncated on
        # every hop — after two hops the true thread root drops out of the
        # chain the recipient's client sends back, _extract_thread_id()
        # then mints a brand-new (history-less) thread mid-conversation,
        # and multi-turn slot-filling silently loses everything said so
        # far. Re-asserting thread_id here is self-healing regardless of
        # how the recipient's client built its own References.
        references=f"<{thread_id}>" if thread_id else None,
        # Hitting "Reply" must route back to the inbox the IMAP listener
        # actually polls (IMAP_USERNAME), not the SMTP send-from address —
        # otherwise every follow-up email lands in a mailbox nobody reads.
        reply_to=config.IMAP_USERNAME or None,
    )


# ── Tool handlers — each returns (title, icon, color, html_content, plain_content) ──

def _handle_leave_balance(
    ctx: ToolContext, registry: "ToolRegistry", name: str
) -> tuple[str, str, str, str, str]:
    """Calls check_leave_balance. Fields: name_en, balance_days, allocated_days, used_days."""
    result = registry.execute("check_leave_balance", {}, ctx)

    if result.success and result.data:
        balances = result.data.get("balances") or []
        balances = [b for b in balances if float(b.get("allocated_days") or 0) > 0]

        if balances:
            rows = ""
            plain_lines = []
            for i, b in enumerate(balances):
                lt_name = b.get("name_en") or b.get("leave_type_code", "")
                remaining = float(b.get("balance_days") or 0)
                allocated = float(b.get("allocated_days") or 0)
                used = float(b.get("used_days") or 0)
                bg = "#f8f8fb" if i % 2 == 0 else "#ffffff"
                rows += (
                    f"<tr style='background:{bg}'>"
                    f"<td style='padding:10px 16px;color:#666;font-size:14px;"
                    f"border-bottom:1px solid #e0e0e0'>{lt_name}</td>"
                    f"<td style='padding:10px 16px;color:#1a1a2e;font-weight:600;"
                    f"font-size:14px;border-bottom:1px solid #e0e0e0'>{remaining:.1f} days</td>"
                    f"<td style='padding:10px 16px;color:#888;font-size:13px;"
                    f"border-bottom:1px solid #e0e0e0'>of {allocated:.0f} allocated "
                    f"({used:.1f} used)</td></tr>"
                )
                plain_lines.append(
                    f"  {lt_name}: {remaining:.1f} days remaining "
                    f"(of {allocated:.0f} allocated)"
                )

            html = (
                f"<p style='color:#444;font-size:14px;margin:0 0 16px 0'>Dear {name},<br><br>"
                f"Here is your current leave balance:</p>"
                f"<table width='100%' cellpadding='0' cellspacing='0' "
                f"style='border:1px solid #e0e0e0;border-radius:6px;overflow:hidden'>"
                f"<tr style='background:#f0f4f8'>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>"
                f"Leave Type</td>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>"
                f"Remaining</td>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>"
                f"Details</td></tr>{rows}</table>"
                f"<p style='color:#888;font-size:12px;margin-top:16px'>"
                f"To submit a leave request, reply with your leave type and dates, "
                f"or visit the HR portal.</p>"
            )
            plain = (
                f"Dear {name},\n\nYour current leave balance:\n"
                + "\n".join(plain_lines)
            )
            return "Your Leave Balance", "📊", "#2563eb", html, plain

    html = (
        f"<p style='color:#444;font-size:14px'>Dear {name},</p>"
        f"<p style='color:#444;font-size:14px'>We were unable to retrieve your leave balance "
        f"at this time. Please contact HR at "
        f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>hr.agent.fotopia@gmail.com</a>.</p>"
    )
    plain = f"Dear {name},\n\nUnable to retrieve your leave balance. Please contact HR directly."
    return "Leave Balance", "📊", "#2563eb", html, plain


def _handle_leave_status(
    ctx: ToolContext, registry: "ToolRegistry", name: str
) -> tuple[str, str, str, str, str]:
    """Returns last 5 leave requests as a colour-coded HTML table."""
    result = registry.execute("get_leave_requests", {"limit": 5}, ctx)

    _STATUS_COLORS = {
        "pending_approval": "#d97706",
        "manager_approved": "#2563eb",
        "hr_approved": "#2563eb",
        "approved": "#16a34a",
        "completed": "#16a34a",
        "manager_rejected": "#dc2626",
        "hr_rejected": "#dc2626",
        "rejected": "#dc2626",
        "cancelled": "#6b7280",
        "withdrawn": "#6b7280",
        "cancellation_pending": "#d97706",
    }

    if result.success and result.data:
        requests = result.data.get("requests") or []
        if requests:
            rows = ""
            plain_lines = []
            for i, req in enumerate(requests):
                start = req.get("start_date", "")
                end = req.get("end_date", "")
                lt = req.get("leave_type_name") or req.get("leave_type_code", "")
                status = req.get("status", "unknown")
                status_label = status.replace("_", " ").title()
                status_color = _STATUS_COLORS.get(status, "#6b7280")
                days = req.get("days_requested")
                bg = "#f8f8fb" if i % 2 == 0 else "#ffffff"
                date_str = f"{start} &rarr; {end}"
                if days:
                    date_str += f" &nbsp;({days} days)"
                rows += (
                    f"<tr style='background:{bg}'>"
                    f"<td style='padding:10px 16px;color:#444;font-size:13px;"
                    f"border-bottom:1px solid #e0e0e0'>{lt}</td>"
                    f"<td style='padding:10px 16px;color:#444;font-size:13px;"
                    f"border-bottom:1px solid #e0e0e0'>{date_str}</td>"
                    f"<td style='padding:10px 16px;border-bottom:1px solid #e0e0e0'>"
                    f"<span style='background:{status_color};color:#fff;padding:3px 8px;"
                    f"border-radius:4px;font-size:12px;font-weight:bold'>"
                    f"{status_label}</span></td></tr>"
                )
                plain_lines.append(f"  {lt} | {start} to {end} | {status_label}")

            html = (
                f"<p style='color:#444;font-size:14px;margin:0 0 16px 0'>Dear {name},<br><br>"
                f"Here are your recent leave requests:</p>"
                f"<table width='100%' cellpadding='0' cellspacing='0' "
                f"style='border:1px solid #e0e0e0;border-radius:6px;overflow:hidden'>"
                f"<tr style='background:#f0f4f8'>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>"
                f"Type</td>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>"
                f"Dates</td>"
                f"<td style='padding:10px 16px;font-weight:bold;color:#1a1a2e;font-size:13px'>"
                f"Status</td></tr>{rows}</table>"
                f"<p style='color:#888;font-size:12px;margin-top:16px'>"
                f"For details or to cancel a request, log into the HR portal.</p>"
            )
            plain = (
                f"Dear {name},\n\nYour recent leave requests:\n"
                + "\n".join(plain_lines)
            )
            return "Your Leave Requests", "📋", "#2563eb", html, plain

    html = (
        f"<p style='color:#444;font-size:14px'>Dear {name},</p>"
        f"<p style='color:#444;font-size:14px'>No leave requests found on your record.</p>"
    )
    plain = f"Dear {name},\n\nNo leave requests found on your record."
    return "Leave Request Status", "📋", "#2563eb", html, plain


def _handle_policy_question(
    ctx: ToolContext, registry: "ToolRegistry", name: str, body_text: str
) -> tuple[str, str, str, str, str]:
    """Calls search_policy with the email body as query. Shows top result."""
    query = body_text[:200].strip()
    result = registry.execute("search_policy", {"query": query}, ctx)

    if result.success and result.data:
        chunks = result.data.get("results") or []
        if chunks:
            top = chunks[0]
            content_text = (top.get("content") or "")[:600]
            source = top.get("source_file", "WIN Holding HR Policy")
            escaped = content_text.replace("\n", "<br>")

            html = (
                f"<p style='color:#444;font-size:14px;margin:0 0 16px 0'>Dear {name},<br><br>"
                f"Here is the relevant policy information for your question:</p>"
                f"<div style='background:#f8f8fb;border-left:4px solid #c9a84c;"
                f"padding:16px;border-radius:0 6px 6px 0;font-size:14px;"
                f"color:#333;line-height:1.7'>{escaped}</div>"
                f"<p style='color:#888;font-size:12px;margin-top:12px'>"
                f"Source: {source}</p>"
                f"<p style='color:#888;font-size:12px;margin-top:8px'>"
                f"For further clarification, contact HR at "
                f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>hr.agent.fotopia@gmail.com</a></p>"
            )
            plain = (
                f"Dear {name},\n\nPolicy information:\n\n{content_text}\n\n"
                f"Source: {source}\n\nFor further help contact hr.agent.fotopia@gmail.com"
            )
            return "Policy Information", "📖", "#2563eb", html, plain

    html = (
        f"<p style='color:#444;font-size:14px'>Dear {name},</p>"
        f"<p style='color:#444;font-size:14px'>"
        f"We couldn't find a specific policy section matching your question. "
        f"Please contact your HR Business Partner at "
        f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>hr.agent.fotopia@gmail.com</a> "
        f"for clarification.</p>"
        f"<p style='color:#444;font-size:14px'>"
        f"Our system can answer questions about annual, sick, maternity/paternity, "
        f"hajj, and other WIN Holding leave policies.</p>"
    )
    plain = (
        f"Dear {name},\n\nWe couldn't find a specific answer to your policy question. "
        f"Please contact hr.agent.fotopia@gmail.com for clarification."
    )
    return "Policy Information", "📖", "#2563eb", html, plain


_LEAVE_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sick": ("sick", "medical", "ill", "doctor"),
    "casual": ("casual",),
    "maternity": ("maternity",),
    "hajj": ("hajj",),
    "umrah": ("umrah",),
    "annual": ("annual",),
}
# Deliberately NOT mapped to a type: "holiday", "vacation", "leave", "time off",
# "day off" — these are vague and must trigger an explicit question, never a
# silent guess (an employee saying "holiday" doesn't mean "annual" specifically).


def _merge_leave_draft(history: list[dict] | None, current_params: dict) -> dict:
    """
    Merge leave-request fields already given earlier in this email thread
    with the current message's fields, so a multi-email back-and-forth
    (mirroring the chat UI's slot-filling) only asks for what's still
    missing instead of repeating the whole checklist every reply.

    Walks backward through history; stops at the first turn that wasn't
    itself a leave_request (a topic change resets the draft — e.g. if the
    employee asked a balance question in between).
    """
    merged = {
        "leave_type": current_params.get("leave_type"),
        "start_date": current_params.get("start_date"),
        "end_date": current_params.get("end_date"),
        "reason": current_params.get("reason"),
    }
    for turn in reversed(history or []):
        if turn.get("role") != "user":
            continue
        if turn.get("intent") != "leave_request":
            break
        prior = turn.get("extracted_params") or {}
        for field in merged:
            if merged[field] is None and prior.get(field) is not None:
                merged[field] = prior[field]
    return merged


def _handle_leave_request(
    ctx: ToolContext, registry: "ToolRegistry", name: str, body_text: str,
    extracted_params: dict | None = None,
    history: list[dict] | None = None,
) -> tuple[str, str, str, str, str]:
    """Attempt to submit a leave request from email content.

    Merges this message's extracted fields with anything already given
    earlier in the same thread (_merge_leave_draft) — a genuine multi-turn
    conversation across emails, e.g. "I want a holiday" -> asks for type +
    dates -> "annual" -> only asks for dates now, not the whole list again.
    Never bypasses the constraint engine.
    """
    draft = _merge_leave_draft(history, extracted_params or {})
    leave_type_code = draft.get("leave_type")
    start_date = draft.get("start_date")
    end_date = draft.get("end_date")
    reason = draft.get("reason") or "Submitted via email"

    if not start_date or not end_date or not leave_type_code:
        import re
        snippet = body_text[:_MAX_BODY_CHARS].lower()

        date_patterns = [
            r'\b(\d{4}-\d{2}-\d{2})\b',
            r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
            r'\b(\d{1,2}/\d{1,2})\b',
        ]
        found_dates = [d for p in date_patterns for d in re.findall(p, snippet)]

        if not leave_type_code:
            for code, keywords in _LEAVE_TYPE_KEYWORDS.items():
                if any(kw in snippet for kw in keywords):
                    leave_type_code = code
                    break

        # Fill whichever date slot(s) are still missing from THIS message's
        # own text — history already contributed via the merge above.
        for slot in ("start_date", "end_date"):
            if not draft.get(slot) and found_dates:
                draft[slot] = found_dates.pop(0)
        start_date = draft.get("start_date")
        end_date = draft.get("end_date")

    missing = []
    if not leave_type_code:
        missing.append(("Leave type", "Annual, Sick, Casual, Hajj, etc."))
    if not start_date:
        missing.append(("Start date", "e.g. 2026-07-21"))
    if not end_date:
        missing.append(("End date", "e.g. 2026-07-23"))

    if missing:
        known_bits = []
        if leave_type_code:
            known_bits.append(f"{leave_type_code.replace('_', ' ').title()} leave")
        if start_date:
            known_bits.append(f"starting {start_date}")
        if end_date:
            known_bits.append(f"ending {end_date}")
        acknowledgement = f"Got it — {', '.join(known_bits)} noted. " if known_bits else ""

        missing_html = "".join(
            f"<li><strong>{label}</strong> &mdash; {hint}</li>" for label, hint in missing
        )
        missing_plain = "".join(f"- {label} ({hint})\n" for label, hint in missing)

        html = (
            f"<p style='color:#444;font-size:14px'>Dear {name},<br><br>"
            f"{acknowledgement}I just need a bit more to submit this for you:</p>"
            f"<div style='background:#f8f8fb;border-radius:6px;padding:16px;font-size:14px'>"
            f"<p style='margin:0 0 8px 0;font-weight:bold;color:#1a1a2e'>Please reply with:</p>"
            f"<ul style='margin:0;padding-left:20px;color:#444;line-height:2.2'>{missing_html}</ul>"
            f"</div>"
            f"<p style='color:#888;font-size:12px;margin-top:16px'>"
            f"Or log into the HR portal to submit directly.</p>"
        )
        plain = (
            f"Dear {name},\n\n{acknowledgement}To submit your leave request, please provide:\n"
            f"{missing_plain}\n"
            f"Or log into the HR portal."
        )
        return "Leave Request — Details Needed", "📅", "#c9a84c", html, plain

    tool_result = registry.execute("submit_leave_request", {
        "leave_type_code": leave_type_code,
        "start_date": start_date,
        "end_date": end_date,
        "reason": reason,
    }, ctx)

    if tool_result.success:
        data = tool_result.data or {}
        req_id = str(data.get("request_id", ""))[:8]
        manager = data.get("manager_name", "your manager")
        lt_label = leave_type_code.replace("_", " ").title()

        req_id_row = (
            f"<tr style='background:#f8f8fb'>"
            f"<td style='padding:10px 16px;color:#666'>Reference</td>"
            f"<td style='padding:10px 16px;color:#888;font-size:12px'>{req_id}...</td></tr>"
            if req_id else ""
        )
        html = (
            f"<p style='color:#444;font-size:14px'>Dear {name},<br><br>"
            f"Your leave request has been submitted successfully.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' "
            f"style='border:1px solid #e0e0e0;border-radius:6px;font-size:14px'>"
            f"<tr style='background:#f8f8fb'>"
            f"<td style='padding:10px 16px;color:#666'>Leave Type</td>"
            f"<td style='padding:10px 16px;font-weight:600;color:#1a1a2e'>{lt_label} Leave</td></tr>"
            f"<tr><td style='padding:10px 16px;color:#666'>Dates</td>"
            f"<td style='padding:10px 16px;font-weight:600;color:#1a1a2e'>"
            f"{start_date} &rarr; {end_date}</td></tr>"
            f"<tr style='background:#f8f8fb'>"
            f"<td style='padding:10px 16px;color:#666'>Status</td>"
            f"<td style='padding:10px 16px;font-weight:600;color:#d97706'>Pending Approval</td></tr>"
            f"<tr><td style='padding:10px 16px;color:#666'>Sent to</td>"
            f"<td style='padding:10px 16px;color:#444'>{manager}</td></tr>"
            f"{req_id_row}"
            f"</table>"
            f"<p style='color:#888;font-size:12px;margin-top:16px'>"
            f"You will receive an email when your manager makes a decision.</p>"
        )
        plain = (
            f"Dear {name},\n\nYour leave request has been submitted.\n"
            f"Type: {lt_label} Leave\n"
            f"Dates: {start_date} to {end_date}\n"
            f"Status: Pending approval from {manager}\n\n"
            f"You will be notified when a decision is made."
        )
        return "Leave Request Submitted", "✅", "#16a34a", html, plain

    error_msg = tool_result.error or "Unknown error"
    if any(w in error_msg.lower() for w in ("advance notice", "notice period")):
        # The constraint engine's own message is already specific and actionable
        # (e.g. "requires 7 working days advance notice. Earliest allowed start: ...")
        # — surface it directly instead of overwriting it with a generic reason.
        explanation = error_msg
    elif any(w in error_msg.lower() for w in ("weekend", "saturday", "sunday", "public holiday")):
        explanation = (
            "The dates you requested fall entirely on a weekend or public holiday. "
            "Please select working days."
        )
    elif any(w in error_msg.lower() for w in ("balance", "insufficient", "remaining")):
        explanation = f"You do not have sufficient leave balance for this request. {error_msg}"
    elif any(w in error_msg.lower() for w in ("threshold", "cap", "override", "policy")):
        explanation = (
            "This request could not be submitted due to a policy constraint. "
            "Please log into the HR portal where your manager can review and approve."
        )
    else:
        explanation = f"Your request could not be submitted: {error_msg}"

    html = (
        f"<p style='color:#444;font-size:14px'>Dear {name},<br><br>"
        f"We were unable to submit your leave request.</p>"
        f"<div style='background:#fef2f2;border-left:4px solid #dc2626;"
        f"padding:16px;border-radius:0 6px 6px 0;font-size:14px;color:#dc2626'>"
        f"{explanation}</div>"
        f"<p style='color:#888;font-size:12px;margin-top:16px'>"
        f"Please log into the HR portal or contact HR at "
        f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>hr.agent.fotopia@gmail.com</a></p>"
    )
    plain = (
        f"Dear {name},\n\nUnable to submit your leave request: {explanation}\n\n"
        f"Please contact hr.agent.fotopia@gmail.com"
    )
    return "Leave Request — Issue", "⚠️", "#dc2626", html, plain


def _handle_leave_cancellation(name: str) -> tuple[str, str, str, str, str]:
    """Pure template — always redirects to HR portal. No tool calls."""
    html = (
        f"<p style='color:#444;font-size:14px'>Dear {name},<br><br>"
        f"To cancel an approved leave request, please log into the HR portal "
        f"where you can select the specific request to cancel.</p>"
        f"<p style='color:#444;font-size:14px'>"
        f"Cancellations are processed through the portal to ensure:</p>"
        f"<ul style='color:#444;font-size:14px;padding-left:20px;line-height:2'>"
        f"<li>The correct request is cancelled</li>"
        f"<li>Your leave balance is accurately restored</li>"
        f"<li>Your manager is notified of the cancellation</li>"
        f"</ul>"
        f"<p style='color:#888;font-size:12px;margin-top:16px'>"
        f"Questions? Contact HR at "
        f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>hr.agent.fotopia@gmail.com</a></p>"
    )
    plain = (
        f"Dear {name},\n\nTo cancel a leave request, please log into the HR portal. "
        f"This ensures the correct request is cancelled and your balance is accurately restored.\n\n"
        f"Contact hr.agent.fotopia@gmail.com for assistance."
    )
    return "Leave Cancellation", "📋", "#c9a84c", html, plain


def _handle_unknown(name: str) -> tuple[str, str, str, str, str]:
    """Capabilities list reply."""
    html = (
        f"<p style='color:#444;font-size:14px'>Dear {name},<br><br>"
        f"Thank you for reaching out. I can help you with the following:</p>"
        f"<div style='background:#f8f8fb;border-radius:6px;padding:16px;font-size:14px'>"
        f"<ul style='margin:0;padding-left:20px;color:#444;line-height:2.4'>"
        f"<li><strong>Leave balance</strong> &mdash; "
        f"<em>&ldquo;What is my annual leave balance?&rdquo;</em></li>"
        f"<li><strong>Submit leave</strong> &mdash; "
        f"<em>&ldquo;I want 3 days annual leave from 2026-07-21 to 2026-07-23&rdquo;</em></li>"
        f"<li><strong>Leave status</strong> &mdash; "
        f"<em>&ldquo;What is the status of my leave request?&rdquo;</em></li>"
        f"<li><strong>Policy questions</strong> &mdash; "
        f"<em>&ldquo;How many days of sick leave do I get?&rdquo;</em></li>"
        f"</ul></div>"
        f"<p style='color:#888;font-size:12px;margin-top:16px'>"
        f"For other requests, contact HR at "
        f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>hr.agent.fotopia@gmail.com</a></p>"
    )
    plain = (
        f"Dear {name},\n\nI can help with:\n"
        f"- Leave balance: 'What is my leave balance?'\n"
        f"- Submit leave: 'I want 3 days annual leave from 2026-07-21'\n"
        f"- Leave status: 'What is the status of my request?'\n"
        f"- Policy questions: 'How many sick days do I get?'\n\n"
        f"For other requests contact hr.agent.fotopia@gmail.com"
    )
    return "How Can I Help?", "💬", "#2563eb", html, plain


# ── Main entry point ──────────────────────────────────────────────────────────

def process_employee_email(
    ds: "DataSource",
    tenant_id: str,
    from_email: str,
    body_text: str,
    in_reply_to_message_id: str | None,
    our_message_id: str | None,
    msg_headers: dict,
    thread_id: str | None = None,
) -> None:
    """Process an inbound email that is not a workflow approval reply.

    Security pipeline (order is invariant):
      1. Loop detection  — header check, no DB access
      2. Identity check  — DB lookup by sender email
      3. Rate limit      — DB upsert/check; rate-limited senders get one reply
      4. Intent classify — keyword match on first 500 chars, informed by prior
                            thread turns (if thread_id given) for reference
                            resolution only — never used as reply content
      5. Tool dispatch   — uses employee's real DB role
      6. Branded HTML reply — no LLM-generated content in body
      7. Save thread turn — structured (intent/extracted_params/summary) only

    thread_id (optional): stable identifier for this email thread (see
    services/email_listener.py::_extract_thread_id). When given, turn
    history is loaded before classification and saved after the reply is
    built, so a follow-up email in the same thread has context.
    """

    # 1. Loop detection — MUST be first, no DB access whatsoever
    if _is_auto_reply(msg_headers):
        _log.info("email_agent: skipping auto-reply from %s", from_email)
        return

    own_address = config.IMAP_USERNAME.strip().lower()
    if own_address and from_email.strip().lower() == own_address:
        _log.info("email_agent: skipping self-email from %s", from_email)
        return

    # 2. Identity check
    employee = ds.get_employee_by_email(tenant_id, from_email)
    if not employee:
        _log.info("email_agent: unregistered sender %s — no reply sent", from_email)
        return  # send_email() MUST NOT be called for unregistered senders

    display_name = employee.get("full_name", from_email)
    subject = msg_headers.get("subject", "") or "HR Enquiry"

    # 3. Rate limit — fires before any tool calls or LLM
    rl = ds.check_and_record_rate_limit(tenant_id, from_email)
    if not rl["allowed"]:
        _log.warning(
            "email_agent: rate limit exceeded for %s (count=%d, blocked_until=%s)",
            from_email, rl["count"], rl.get("blocked_until"),
        )
        # Read the actual enforced limit from the result rather than hardcoding a
        # number here — the two used to drift (message said 5, enforcement was 10).
        limit = rl.get("max_per_hour", 10)
        html = (
            f"<p style='color:#444;font-size:14px'>Dear {display_name},<br><br>"
            f"You have sent too many requests in the last hour (maximum {limit} per hour). "
            f"Please try again later.</p>"
            f"<p style='color:#888;font-size:12px'>"
            f"For urgent requests, contact HR directly at "
            f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>hr.agent.fotopia@gmail.com</a></p>"
        )
        plain = (
            f"Dear {display_name},\n\nToo many requests in the last hour (max {limit}). "
            f"Please try again later or contact hr.agent.fotopia@gmail.com"
        )
        _send_reply(
            to_email=from_email,
            subject=subject,
            title="Too Many Requests",
            icon="⏱️",
            color="#d97706",
            html_content=html,
            plain_content=plain,
            in_reply_to=in_reply_to_message_id,
            our_message_id=our_message_id,
            thread_id=thread_id,
        )
        return

    # 4. Classify intent — load prior thread turns first, if any, so the
    # classifier can resolve references to earlier messages in this thread.
    history = ds.get_email_session(tenant_id, thread_id) if thread_id else []

    try:
        intent_result = _classify_intent(
            body_text, subject=msg_headers.get("subject", ""), history=history
        )
        intent = intent_result.intent
        _log.info(
            "email_agent: from=%s intent=%s confidence=%s",
            from_email, intent, intent_result.confidence,
        )

        # 5. Dispatch to tool using employee's real DB role
        ctx = _build_context(employee, tenant_id)
        registry = _get_registry(ds)

        if intent == "balance_check":
            title, icon, color, html, plain = _handle_leave_balance(ctx, registry, display_name)
        elif intent == "leave_status":
            title, icon, color, html, plain = _handle_leave_status(ctx, registry, display_name)
        elif intent == "policy_question":
            title, icon, color, html, plain = _handle_policy_question(
                ctx, registry, display_name, body_text
            )
        elif intent == "leave_request":
            title, icon, color, html, plain = _handle_leave_request(
                ctx, registry, display_name, body_text,
                extracted_params=intent_result.extracted_params,
                history=history,
            )
        elif intent == "leave_cancellation":
            title, icon, color, html, plain = _handle_leave_cancellation(display_name)
        else:
            title, icon, color, html, plain = _handle_unknown(display_name)

        # 6. Send branded HTML reply
        _send_reply(
            to_email=from_email,
            subject=subject,
            title=title,
            icon=icon,
            color=color,
            html_content=html,
            plain_content=plain,
            in_reply_to=in_reply_to_message_id,
            our_message_id=our_message_id,
            thread_id=thread_id,
        )
        _log.info("email_agent: reply sent to %s (intent=%s)", from_email, intent)

        # 7. Save thread turn — structured summary only, never the HTML/LLM body
        if thread_id:
            updated_history = history + [
                {
                    "role": "user",
                    "content": body_text[:300],
                    "intent": intent,
                    "extracted_params": intent_result.extracted_params,
                },
                {"role": "assistant", "content": plain[:300]},
            ]
            ds.upsert_email_session(tenant_id, thread_id, from_email, updated_history)

    except Exception:
        # Guarantee the employee is never left without ANY response — a
        # classification, tool, or DB error partway through must still
        # produce a reply, not silence. This is the one place in the
        # pipeline allowed to send a generic message, precisely because
        # everything more specific above it has already failed.
        _log.exception(
            "email_agent: unhandled error processing email from %s — sending fallback reply",
            from_email,
        )
        try:
            _send_reply(
                to_email=from_email,
                subject=subject,
                title="We Hit a Snag",
                icon="⚠️",
                color="#dc2626",
                html_content=(
                    f"<p style='color:#444;font-size:14px'>Dear {display_name},<br><br>"
                    f"We ran into an unexpected issue processing your email. "
                    f"Please try again, or contact HR directly at "
                    f"<a href='mailto:hr.agent.fotopia@gmail.com' style='color:#c9a84c'>"
                    f"hr.agent.fotopia@gmail.com</a>.</p>"
                ),
                plain_content=(
                    f"Dear {display_name},\n\nWe ran into an unexpected issue processing "
                    f"your email. Please try again, or contact hr.agent.fotopia@gmail.com."
                ),
                in_reply_to=in_reply_to_message_id,
                our_message_id=our_message_id,
                thread_id=thread_id,
            )
        except Exception:
            _log.exception(
                "email_agent: fallback reply ALSO failed for %s — giving up, no reply sent",
                from_email,
            )
