"""
agent/onboarding.py — Week-1 onboarding orchestrator (5-question MVP).

Deliberately NOT inside agent/orchestrator/ (Youssef's owned directory) and
NOT a wrapper around orchestrator.run()'s LLM tool-use loop — this is a
plain Python step function. The demo needs exactly 5 fixed questions in a
fixed order every time; a flexible LLM-driven loop is the wrong reliability
profile for a rehearsed, repeatable demo.

Security: maybe_handle_turn() is the only text-message entry point. The
trigger phrase is gated to hr_manager/admin — same explicit-deny pattern as
ToolRegistry.execute(), never a silent fallthrough. Odoo credentials are
never accepted via chat (see tools/odoo_connect.py).

Questions 4 and 5 (document uploads) are NOT resolved through chat text at
all — see handle_document_upload(), called by the separate
POST /api/onboarding/{session_id}/upload endpoint.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import config
from llm.claude import ClaudeProvider
from tools.base import ToolContext

if TYPE_CHECKING:
    from data.base import DataSource
    from tools.registry import ToolRegistry

_log = logging.getLogger(__name__)

TRIGGER_PHRASE = "set up your agent"

_QUESTIONS = {
    1: "Let's get your agent set up! First — what's your company name, and which country/jurisdiction are you based in?",
    2: (
        "Thanks! Next: I'll connect to Odoo using the credentials already "
        "configured for this environment. Reply 'yes' to connect, or 'skip' "
        "to do this later."
    ),
    3: "Got it. Where should I pull your policy documents from — SharePoint, or would you like to upload files directly?",
    4: "Great — let's start with your employee handbook. Attach the file using the button below.",
    5: "Handbook received! Now, please attach your leave policy document.",
}


@dataclass
class OnboardingReply:
    text: str
    awaiting_upload: bool = False


def _extract_company_info(text: str) -> tuple[str, str | None]:
    """Returns (company_name, jurisdiction). Fails open — a parse failure
    never blocks progression, it just stores the raw text."""
    try:
        provider = ClaudeProvider(api_key=config.ANTHROPIC_API_KEY, model="claude-haiku-4-5-20251001")
        prompt = (
            "Extract the company name and jurisdiction (country/region) from this "
            "text. Respond with ONLY valid JSON, no markdown, no explanation:\n"
            '{"company_name": "...", "jurisdiction": "... or null"}\n\n'
            f"Text: {text[:300]}"
        )
        response = provider.classify(
            system_prompt="Extract structured data. Respond only with valid JSON.",
            user_text=prompt,
        )
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
        name = (data.get("company_name") or "").strip() or text[:200]
        return name, data.get("jurisdiction")
    except Exception as e:
        _log.warning("onboarding: company-info extraction failed, using raw text: %s", e)
        parts = [p.strip() for p in text.split(",", 1)]
        name = parts[0] or text[:200]
        jurisdiction = parts[1] if len(parts) > 1 else None
        return name, jurisdiction


def _handle_step_1(text: str, ctx: ToolContext, session_id: str, ds: "DataSource", registry: "ToolRegistry") -> OnboardingReply:
    company_name, jurisdiction = _extract_company_info(text)
    ds.update_onboarding_session(
        ctx.tenant_id, session_id, current_step=2,
        answers={"company_name": company_name, "jurisdiction": jurisdiction},
    )
    return OnboardingReply(text=_QUESTIONS[2])


def _handle_step_2(text: str, ctx: ToolContext, session_id: str, ds: "DataSource", registry: "ToolRegistry") -> OnboardingReply:
    lowered = text.lower()
    if "skip" in lowered or "no" in lowered:
        ds.update_onboarding_session(
            ctx.tenant_id, session_id, current_step=3,
            answers={"odoo_connected": False},
        )
        return OnboardingReply(text=_QUESTIONS[3])

    result = registry.execute("connect_odoo", {}, ctx)
    if result.success:
        note = f"Connected — found {result.data['employee_count']} employees in Odoo."
        ds.update_onboarding_session(
            ctx.tenant_id, session_id, current_step=3,
            answers={"odoo_connected": True},
        )
    else:
        note = f"I couldn't connect to Odoo ({result.error}) — continuing without it for now."
        ds.update_onboarding_session(
            ctx.tenant_id, session_id, current_step=3,
            answers={"odoo_connected": False},
        )
    return OnboardingReply(text=f"{note}\n\n{_QUESTIONS[3]}")


def _handle_step_3(text: str, ctx: ToolContext, session_id: str, ds: "DataSource", registry: "ToolRegistry") -> OnboardingReply:
    lowered = text.lower()
    doc_source = "sharepoint" if "sharepoint" in lowered else "upload"
    note = ""
    if doc_source == "sharepoint":
        note = "SharePoint sync isn't wired into onboarding yet this week — let's upload directly for now.\n\n"
    ds.update_onboarding_session(
        ctx.tenant_id, session_id, current_step=4,
        answers={"document_source": doc_source},
    )
    return OnboardingReply(text=f"{note}{_QUESTIONS[4]}", awaiting_upload=True)


def _handle_awaiting_upload(text: str, ctx: ToolContext, session_id: str, ds: "DataSource", registry: "ToolRegistry") -> OnboardingReply:
    """Steps 4 and 5 only advance via handle_document_upload(). A text reply
    while we're waiting for a file just re-prompts."""
    return OnboardingReply(
        text="Please attach a file using the button below to continue.",
        awaiting_upload=True,
    )


_STEP_HANDLERS = {
    1: _handle_step_1,
    2: _handle_step_2,
    3: _handle_step_3,
    4: _handle_awaiting_upload,
    5: _handle_awaiting_upload,
}


def maybe_handle_turn(
    message: str,
    ctx: ToolContext,
    session_id: str,
    data_source: "DataSource",
    registry: "ToolRegistry",
) -> OnboardingReply | None:
    """Return a reply if this chat turn is part of an onboarding interview,
    or None if the caller should fall through to normal chat instead."""
    trimmed = (message or "").strip()
    existing = data_source.get_onboarding_session(ctx.tenant_id, session_id)

    if existing is None:
        if trimmed.lower() != TRIGGER_PHRASE:
            return None
        if ctx.role not in ("hr_manager", "admin"):
            return OnboardingReply(
                text="Setting up an agent requires an HR manager or admin role."
            )
        data_source.create_onboarding_session(ctx.tenant_id, session_id, ctx.user_id)
        return OnboardingReply(text=_QUESTIONS[1])

    if existing["status"] != "in_progress":
        return None  # completed/abandoned — treat as normal chat from here on

    handler = _STEP_HANDLERS[existing["current_step"]]
    return handler(trimmed, ctx, session_id, data_source, registry)


def handle_document_upload(
    content: str,
    document_name: str,
    ctx: ToolContext,
    session_id: str,
    data_source: "DataSource",
    registry: "ToolRegistry",
) -> OnboardingReply:
    """Called by POST /api/onboarding/{session_id}/upload — never routed
    through maybe_handle_turn(), since an upload never arrives as a /chat
    text message."""
    existing = data_source.get_onboarding_session(ctx.tenant_id, session_id)
    if (
        existing is None
        or existing["status"] != "in_progress"
        or existing["current_step"] not in (4, 5)
    ):
        return OnboardingReply(text="No document upload is expected right now.")

    result = registry.execute(
        "ingest_policy_document",
        {"content": content, "document_name": document_name},
        ctx,
    )
    if not result.success:
        return OnboardingReply(
            text=f"I couldn't process that document: {result.error}. Please try again.",
            awaiting_upload=True,
        )

    step = existing["current_step"]
    if step == 4:
        data_source.update_onboarding_session(
            ctx.tenant_id, session_id, current_step=5,
            answers={"handbook_document_id": result.data["document_id"]},
        )
        return OnboardingReply(text=_QUESTIONS[5], awaiting_upload=True)

    # step == 5 — final document, onboarding complete
    company_name = (existing["answers"] or {}).get("company_name", "your company")
    data_source.update_onboarding_session(
        ctx.tenant_id, session_id, status="completed",
        answers={"leave_policy_document_id": result.data["document_id"]},
    )
    return OnboardingReply(
        text=(
            f"I'm ready! Your agent is now set up with {company_name}'s policies. "
            f"Ask me anything — for example, a real policy question."
        ),
    )
