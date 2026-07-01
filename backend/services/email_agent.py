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

def _classify_intent(body_text: str, subject: str = "") -> EmailIntent:
    """
    Classify email intent using Claude Haiku LLM.

    SECURITY: Only passes subject + first 500 chars of body to LLM.
    FAIL CLOSED: Any error returns intent='unknown' via keyword fallback — never crashes.
    LLM extracts dates and leave type — no regex needed in handlers when successful.
    """
    import json

    safe_subject = (subject or "")[:200]
    safe_body = (body_text or "")[:500]

    prompt = f"""You are an HR email classifier. Classify this email and extract key information.

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
- "first two weeks of August" → start_date: current year August 1, end_date: August 14
- "next week" → approximate from today's date (today is {__import__('datetime').date.today()})
- "cancel my leave / withdraw / don't need leave anymore" → leave_cancellation
- "what is my balance / how many days do I have" → balance_check
- "status of my request / is my leave approved" → leave_status
- "what is the policy / how many days do I get" → policy_question
- Greetings, unrelated, unclear with low confidence → unknown
- Default leave_type to "annual" if employee says "holiday" or "vacation" or "leave" without specifying type
- If dates are mentioned in any natural language form, convert to YYYY-MM-DD format"""

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
        return EmailIntent(
            intent=data.get("intent", "unknown"),
            confidence=data.get("confidence", "low"),
            extracted_params=data.get("extracted_params") or {},
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
) -> None:
    """Send a branded HTML reply. Never called for skipped/unregistered senders."""
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
        <a href="mailto:hr@fotopia.com" style="color:#c9a84c">hr@fotopia.com</a>
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
        in_reply_to=in_reply_to or our_message_id,
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
        f"<a href='mailto:hr@fotopia.com' style='color:#c9a84c'>hr@fotopia.com</a>.</p>"
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
                f"<a href='mailto:hr@fotopia.com' style='color:#c9a84c'>hr@fotopia.com</a></p>"
            )
            plain = (
                f"Dear {name},\n\nPolicy information:\n\n{content_text}\n\n"
                f"Source: {source}\n\nFor further help contact hr@fotopia.com"
            )
            return "Policy Information", "📖", "#2563eb", html, plain

    html = (
        f"<p style='color:#444;font-size:14px'>Dear {name},</p>"
        f"<p style='color:#444;font-size:14px'>"
        f"We couldn't find a specific policy section matching your question. "
        f"Please contact your HR Business Partner at "
        f"<a href='mailto:hr@fotopia.com' style='color:#c9a84c'>hr@fotopia.com</a> "
        f"for clarification.</p>"
        f"<p style='color:#444;font-size:14px'>"
        f"Our system can answer questions about annual, sick, maternity/paternity, "
        f"hajj, and other WIN Holding leave policies.</p>"
    )
    plain = (
        f"Dear {name},\n\nWe couldn't find a specific answer to your policy question. "
        f"Please contact hr@fotopia.com for clarification."
    )
    return "Policy Information", "📖", "#2563eb", html, plain


def _handle_leave_request(
    ctx: ToolContext, registry: "ToolRegistry", name: str, body_text: str,
    extracted_params: dict | None = None,
) -> tuple[str, str, str, str, str]:
    """Attempt to submit a leave request from email content.
    If dates can't be parsed, returns a clarification template.
    Never bypasses the constraint engine.
    """
    params = extracted_params or {}
    llm_leave_type = params.get("leave_type")
    leave_type_code = llm_leave_type or "annual"
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    reason = params.get("reason") or "Submitted via email"

    if not start_date or not end_date:
        import re
        snippet = body_text[:_MAX_BODY_CHARS].lower()

        date_patterns = [
            r'\b(\d{4}-\d{2}-\d{2})\b',
            r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
            r'\b(\d{1,2}/\d{1,2})\b',
        ]
        found_dates = []
        for pattern in date_patterns:
            found_dates.extend(re.findall(pattern, snippet))

        if not llm_leave_type:
            if any(kw in snippet for kw in ("sick", "medical", "ill", "doctor")):
                leave_type_code = "sick"
            elif "casual" in snippet:
                leave_type_code = "casual"
            elif "maternity" in snippet:
                leave_type_code = "maternity"
            elif "hajj" in snippet:
                leave_type_code = "hajj"
            elif "umrah" in snippet:
                leave_type_code = "umrah"

        if len(found_dates) < 2:
            html = (
                f"<p style='color:#444;font-size:14px'>Dear {name},<br><br>"
                f"Thank you for your leave request. To submit it on your behalf, "
                f"I need a few more details:</p>"
                f"<div style='background:#f8f8fb;border-radius:6px;padding:16px;font-size:14px'>"
                f"<p style='margin:0 0 8px 0;font-weight:bold;color:#1a1a2e'>Please reply with:</p>"
                f"<ul style='margin:0;padding-left:20px;color:#444;line-height:2.2'>"
                f"<li><strong>Leave type</strong> &mdash; Annual, Sick, Casual, Hajj, etc.</li>"
                f"<li><strong>Start date</strong> &mdash; e.g. 2026-07-21</li>"
                f"<li><strong>End date</strong> &mdash; e.g. 2026-07-23</li>"
                f"<li><strong>Reason</strong> &mdash; optional</li>"
                f"</ul></div>"
                f"<p style='color:#888;font-size:12px;margin-top:16px'>"
                f"Or log into the HR portal to submit directly.</p>"
            )
            plain = (
                f"Dear {name},\n\nTo submit your leave request, please provide:\n"
                f"- Leave type (Annual, Sick, etc.)\n"
                f"- Start date (e.g. 2026-07-21)\n"
                f"- End date\n"
                f"- Reason (optional)\n\n"
                f"Or log into the HR portal."
            )
            return "Leave Request — Details Needed", "📅", "#c9a84c", html, plain

        start_date = found_dates[0]
        end_date = found_dates[1]

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
    if any(w in error_msg.lower() for w in ("weekend", "working day", "saturday", "sunday")):
        explanation = (
            "The dates you requested fall on a weekend. "
            "Please select working days (Monday through Friday)."
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
        f"<a href='mailto:hr@fotopia.com' style='color:#c9a84c'>hr@fotopia.com</a></p>"
    )
    plain = (
        f"Dear {name},\n\nUnable to submit your leave request: {explanation}\n\n"
        f"Please contact hr@fotopia.com"
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
        f"<a href='mailto:hr@fotopia.com' style='color:#c9a84c'>hr@fotopia.com</a></p>"
    )
    plain = (
        f"Dear {name},\n\nTo cancel a leave request, please log into the HR portal. "
        f"This ensures the correct request is cancelled and your balance is accurately restored.\n\n"
        f"Contact hr@fotopia.com for assistance."
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
        f"<a href='mailto:hr@fotopia.com' style='color:#c9a84c'>hr@fotopia.com</a></p>"
    )
    plain = (
        f"Dear {name},\n\nI can help with:\n"
        f"- Leave balance: 'What is my leave balance?'\n"
        f"- Submit leave: 'I want 3 days annual leave from 2026-07-21'\n"
        f"- Leave status: 'What is the status of my request?'\n"
        f"- Policy questions: 'How many sick days do I get?'\n\n"
        f"For other requests contact hr@fotopia.com"
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
) -> None:
    """Process an inbound email that is not a workflow approval reply.

    Security pipeline (order is invariant):
      1. Loop detection  — header check, no DB access
      2. Identity check  — DB lookup by sender email
      3. Rate limit      — DB upsert/check; rate-limited senders get one reply
      4. Intent classify — keyword match on first 500 chars
      5. Tool dispatch   — uses employee's real DB role
      6. Branded HTML reply — no LLM-generated content in body
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
        html = (
            f"<p style='color:#444;font-size:14px'>Dear {display_name},<br><br>"
            f"You have sent too many requests in the last hour (maximum 5 per hour). "
            f"Please try again later.</p>"
            f"<p style='color:#888;font-size:12px'>"
            f"For urgent requests, contact HR directly at "
            f"<a href='mailto:hr@fotopia.com' style='color:#c9a84c'>hr@fotopia.com</a></p>"
        )
        plain = (
            f"Dear {display_name},\n\nToo many requests in the last hour (max 5). "
            f"Please try again later or contact hr@fotopia.com"
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
        )
        return

    # 4. Classify intent
    intent_result = _classify_intent(body_text, subject=msg_headers.get("subject", ""))
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
    )
    _log.info("email_agent: reply sent to %s (intent=%s)", from_email, intent)
