"""
agent/onboarding.py — onboarding orchestrator (slot-filling, order-independent).

Deliberately NOT inside agent/orchestrator/ (Youssef's owned directory) and
NOT a wrapper around orchestrator.run()'s LLM tool-use loop — this is a
plain Python step function. The LLM only ever classifies/extracts; Python
alone decides which real tool calls happen (connect_odoo,
ingest_policy_document — both llm_visible=False, see tools/odoo_connect.py,
tools/knowledge_ingest.py). That split is what keeps this safe even though
the flow is now fully order-independent: the LLM can never fabricate a slot
being filled — it can only report what a message said, and only Python-run
tool calls ever actually resolve a slot.

Originally a fixed 5-question script asked in a strict order. Reworked (per
explicit request, after real usage: an HR manager wanted to give everything
in one message, or upload documents before stating the company name, and
got blocked by the old step gate) into a SLOT-FILLING model: the session
tracks which of {company_name, odoo connect/skip, handbook, leave policy}
are already known, and each turn — text OR file upload — is reasoned about
for whatever NEW information it provides, in whatever order it arrives.
What to ask next is always "the first slot still missing", so a plain
"set up your agent" click still gets the same friendly one-question-at-a-
time flow; a rich message or an out-of-order upload just skips ahead.

Security: maybe_handle_turn() is the only text-message entry point, gated to
hr_manager/admin — checked BEFORE any LLM call so other roles never pay for
a classification that could only ever be refused. Every classification
(trigger detection, slot extraction, document-type classification) fails
closed: an LLM/parse failure or ambiguity means "nothing extracted", never a
guessed value or a silently skipped real action. Odoo credentials are never
accepted via chat (see tools/odoo_connect.py).

Document uploads are NOT resolved through chat text at all — see
handle_document_upload(), called by the separate
POST /api/onboarding/{session_id}/upload endpoint. An upload is accepted at
ANY point once onboarding is in progress — not gated to a particular step —
and the LLM classifies the content itself (employee handbook vs. leave
policy vs. neither) to decide which slot it fills.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tools.base import ToolContext

if TYPE_CHECKING:
    from data.base import DataSource
    from llm.base import LLMProvider
    from tools.registry import ToolRegistry

_log = logging.getLogger(__name__)

TRIGGER_PHRASE = "set up your agent"

# Order here is only the DEFAULT question order for a plain "set up your
# agent" click with nothing else given — it is NOT an enforced sequence.
# Any slot can be filled in any order; _missing_slots() just always asks
# about whichever missing slot comes first in this list.
_SLOT_QUESTIONS = {
    "company_name": "What's your company name, and which country/jurisdiction are you based in?",
    "odoo": "Should I connect to Odoo now? Reply 'yes' to connect, or 'skip' to do this later.",
    "handbook": "Please attach your employee handbook using the button below.",
    "leave_policy": "Please attach your leave policy document using the button below.",
}


@dataclass
class OnboardingReply:
    text: str
    awaiting_upload: bool = False


def _missing_slots(answers: dict) -> list[str]:
    missing = []
    if not answers.get("company_name"):
        missing.append("company_name")
    if not answers.get("odoo_resolved"):
        missing.append("odoo")
    if not answers.get("handbook_document_id"):
        missing.append("handbook")
    if not answers.get("leave_policy_document_id"):
        missing.append("leave_policy")
    return missing


def _next_reply(ctx: ToolContext, session_id: str, ds: "DataSource", answers: dict, extra_notes: list[str] | None = None) -> OnboardingReply:
    """Given the current known slots, either declare completion or ask about
    whichever slot is still missing. Shared by the text-turn path and the
    upload path so both end up at the same "what's left" logic."""
    notes = list(extra_notes or [])
    missing = _missing_slots(answers)

    if not missing:
        ds.update_onboarding_session(ctx.tenant_id, session_id, status="completed")
        company_name = answers.get("company_name") or "your company"
        notes.append(
            f"I'm ready! Your agent is now set up with {company_name}'s policies. "
            f"Ask me anything — for example, a real policy question."
        )
        return OnboardingReply(text="\n\n".join(notes))

    notes.append(_SLOT_QUESTIONS[missing[0]])
    return OnboardingReply(text="\n\n".join(notes), awaiting_upload=missing[0] in ("handbook", "leave_policy"))


_TURN_EXTRACTION_PROMPT = """\
You are extracting onboarding information from an HR manager's message about
setting up a new company's HR agent. The manager may give information in
any order, all at once, or split across several messages — extract
whatever THIS message states, regardless of what's already known or what
order things arrive in.

Respond ONLY with valid JSON, no markdown fences, no text outside the JSON object:
{
    "is_trigger": true or false,
    "company_name": "extracted company name" or null,
    "jurisdiction": "extracted country/region" or null,
    "odoo_decision": "connect" or "skip" or null
}

Rules:
- is_trigger: true only if the message expresses genuine intent to START
  setting up/configuring a new company's HR agent right now — as opposed to
  a general question, a how-does-this-work question, or an unrelated
  message. If in doubt, false (fail closed) — normal chat is the safe
  default; starting a stateful onboarding flow by mistake is not.
- company_name / jurisdiction: extract ONLY if explicitly stated in this
  message. Never guess or infer from context — null if not mentioned.
- odoo_decision: "connect" if the message asks to connect/use Odoo now, or is
  a clear affirmative reply ("yes", "sure", "go ahead") to a PENDING
  question about connecting to Odoo (see context below). "skip" if it says
  to skip/defer Odoo, or is a clear negative/deferral reply to that same
  pending question. null if Odoo isn't addressed in this message at all.
- Use the context below only to correctly interpret short replies like
  "yes" or "skip" — never to invent a value the message doesn't actually
  state.

Examples:
- "I want to create an agent for Fotopia, Egypt, and connect it to Odoo" ->
  {"is_trigger": true, "company_name": "Fotopia", "jurisdiction": "Egypt", "odoo_decision": "connect"}
- "Set up your agent" ->
  {"is_trigger": true, "company_name": null, "jurisdiction": null, "odoo_decision": null}
- "yes" (context: most recently asked about Odoo) ->
  {"is_trigger": false, "company_name": null, "jurisdiction": null, "odoo_decision": "connect"}
- "How would I integrate this with Odoo?" ->
  {"is_trigger": false, "company_name": null, "jurisdiction": null, "odoo_decision": null}
"""

_DEFAULT_TURN_INFO = {
    "is_trigger": False, "company_name": None, "jurisdiction": None, "odoo_decision": None,
}


def _extract_turn_info(message: str, context_note: str, llm: "LLMProvider | None") -> dict:
    """Reasons about a single chat turn — trigger detection AND slot
    extraction in one call, since either can appear in the same message
    (e.g. the very first message already stating the company name). Exact
    button-click phrase always triggers with zero LLM dependency. Any other
    phrasing is genuinely reasoned about when an LLMProvider is supplied —
    no keyword pre-filter, no substring matching. Fails closed: any
    classification failure or ambiguity means nothing extracted, never a
    guessed value or an accidental trigger."""
    if message.strip().lower() == TRIGGER_PHRASE:
        return {**_DEFAULT_TURN_INFO, "is_trigger": True}
    if llm is None:
        return dict(_DEFAULT_TURN_INFO)
    try:
        user_text = f"Context: {context_note}\nMessage: {message[:400]}"
        raw = llm.classify(_TURN_EXTRACTION_PROMPT, user_text)
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
        odoo_decision = data.get("odoo_decision")
        return {
            "is_trigger": bool(data.get("is_trigger", False)),
            "company_name": data.get("company_name") or None,
            "jurisdiction": data.get("jurisdiction") or None,
            "odoo_decision": odoo_decision if odoo_decision in ("connect", "skip") else None,
        }
    except Exception as e:
        _log.warning("onboarding: turn extraction unavailable, defaulting to no-op: %s", e)
        return dict(_DEFAULT_TURN_INFO)


def _connect_odoo_and_record(ctx: ToolContext, registry: "ToolRegistry", updates: dict) -> str:
    """The one and only place connect_odoo is actually called — a real,
    audited registry.execute() call, never something the LLM decides to do
    itself (connect_odoo is llm_visible=False)."""
    result = registry.execute("connect_odoo", {}, ctx)
    updates["odoo_resolved"] = True
    if result.success:
        updates["odoo_connected"] = True
        return f"Connected — found {result.data['employee_count']} employees in Odoo."
    updates["odoo_connected"] = False
    return f"I couldn't connect to Odoo ({result.error}) — continuing without it for now."


def _apply_extracted_info(
    info: dict, ctx: ToolContext, session_id: str, ds: "DataSource", registry: "ToolRegistry", answers: dict,
) -> OnboardingReply:
    notes = []
    updates = {}

    if info.get("company_name"):
        updates["company_name"] = info["company_name"]
        updates["jurisdiction"] = info.get("jurisdiction")
        label = f"{info['company_name']}, {info['jurisdiction']}" if info.get("jurisdiction") else info["company_name"]
        notes.append(f"Got it — {label}.")

    if info.get("odoo_decision") and not answers.get("odoo_resolved"):
        if info["odoo_decision"] == "connect":
            notes.append(_connect_odoo_and_record(ctx, registry, updates))
        else:
            updates["odoo_resolved"] = True
            updates["odoo_connected"] = False

    if updates:
        ds.update_onboarding_session(ctx.tenant_id, session_id, answers=updates)
        answers = {**answers, **updates}

    return _next_reply(ctx, session_id, ds, answers, extra_notes=notes)


def maybe_handle_turn(
    message: str,
    ctx: ToolContext,
    session_id: str,
    data_source: "DataSource",
    registry: "ToolRegistry",
    llm: "LLMProvider | None" = None,
) -> OnboardingReply | None:
    """Return a reply if this chat turn is part of an onboarding interview,
    or None if the caller should fall through to normal chat instead.

    llm is used only to classify intent and extract whatever a message
    states — it never decides what happens next. Python alone decides
    which slots get updated and which real tool calls (connect_odoo) run.
    """
    trimmed = (message or "").strip()
    existing = data_source.get_onboarding_session(ctx.tenant_id, session_id)

    if existing is None:
        if ctx.role not in ("hr_manager", "admin"):
            # A real access-control boundary, not a content guess — these
            # roles can never onboard regardless of what the message says,
            # so there's nothing to reason about. Only the exact button
            # phrase gets an explicit denial; free text just falls through
            # to normal chat rather than spending a classification call on a
            # request that could only ever be refused.
            if trimmed.lower() == TRIGGER_PHRASE:
                return OnboardingReply(
                    text="Setting up an agent requires an HR manager or admin role."
                )
            return None
        answers = {}
    else:
        if existing["status"] != "in_progress":
            return None  # completed/abandoned — treat as normal chat from here on
        answers = existing["answers"] or {}

    missing = _missing_slots(answers)
    context_note = (
        f"Missing so far: {', '.join(missing) if missing else 'nothing'}. "
        f"Most recently asked about: {missing[0] if missing else 'nothing — onboarding should be complete'}."
    )
    info = _extract_turn_info(trimmed, context_note, llm)

    if existing is None:
        if not info["is_trigger"]:
            return None
        data_source.create_onboarding_session(ctx.tenant_id, session_id, ctx.user_id)

    return _apply_extracted_info(info, ctx, session_id, data_source, registry, answers)


_DOCUMENT_TYPE_CLASSIFIER_PROMPT = """\
You are a document-type classifier for HR agent onboarding. You receive an
excerpt of an uploaded file's content. Decide which of these it is:

- "employee handbook": a broad, multi-topic company reference (working
  hours, code of conduct, benefits, leave, etc. — several distinct
  sections).
- "leave policy document": content specifically and narrowly about leave/
  vacation entitlements, accrual, and notice periods — NOT a broad handbook,
  even if a real handbook would also mention this topic briefly. Judge the
  SCOPE of the content, not just topic overlap.
- "other": neither of the above (e.g. a resume, an unrelated document).

Respond ONLY with valid JSON, no markdown fences, no text outside the JSON object:
{
    "document_type": "employee handbook" or "leave policy document" or "other",
    "confidence": "high" or "medium" or "low",
    "reason": "one sentence"
}

Rules:
- Judge by the CONTENT's actual subject matter, never by filename or labels
  (you are not given the filename).
- Example: content covering ONLY annual/sick leave rules and notice periods,
  nothing else → "leave policy document".
- Example: content covering working hours, code of conduct, benefits, AND a
  leave section → "employee handbook".
- If in doubt, respond "other" (fail closed) — asking the user to confirm is
  cheap; silently misfiling a document is not.
"""


def classify_uploaded_document_type(content_text: str, llm: "LLMProvider") -> dict:
    """Ask the LLM which of the two expected onboarding documents (if
    either) the uploaded content actually is. Only an excerpt is sent, never
    the full document. Fails closed — an LLM or parse failure is treated as
    "other" (unrecognized), never silently accepted into either slot."""
    try:
        user_text = f"Content excerpt: {content_text[:1500]}"
        raw = llm.classify(_DOCUMENT_TYPE_CLASSIFIER_PROMPT, user_text)
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        return json.loads(clean.strip())
    except Exception as e:
        _log.warning("onboarding: document-type classification unavailable, failing closed: %s", e)
        return {
            "document_type": "other",
            "confidence": "low",
            "reason": "Document-type classification unavailable — treating as unrecognized by default",
        }


_SLOT_FOR_DOCUMENT_TYPE = {
    "employee handbook": "handbook_document_id",
    "leave policy document": "leave_policy_document_id",
}


def handle_document_upload(
    content: str,
    document_name: str,
    ctx: ToolContext,
    session_id: str,
    data_source: "DataSource",
    registry: "ToolRegistry",
    llm: "LLMProvider",
) -> OnboardingReply:
    """Called by POST /api/onboarding/{session_id}/upload — never routed
    through maybe_handle_turn(), since an upload never arrives as a /chat
    text message.

    Accepted at ANY point once onboarding is in progress — not gated to a
    particular slot being reached first. If NO session exists yet at all
    (the reported case: attaching a file as the very first action, before
    ever sending a trigger message), a new one is started here too — same
    role gate as the text trigger (hr_manager/admin), since attaching a
    document is just as valid a way to start onboarding as typing "set up
    your agent". The LLM classifies which document this actually is
    (handbook / leave policy / neither); Python then either stores it in the
    matching slot (via the same audited ingest_policy_document tool call
    regardless of order) or rejects it with an explanation, never guessing.
    """
    existing = data_source.get_onboarding_session(ctx.tenant_id, session_id)

    if existing is None:
        if ctx.role not in ("hr_manager", "admin"):
            return OnboardingReply(text="No document upload is expected right now.")
        data_source.create_onboarding_session(ctx.tenant_id, session_id, ctx.user_id)
        answers = {}
    else:
        if existing["status"] != "in_progress":
            return OnboardingReply(text="No document upload is expected right now.")
        answers = existing["answers"] or {}

    verdict = classify_uploaded_document_type(content, llm)
    doc_type = verdict.get("document_type")
    slot = _SLOT_FOR_DOCUMENT_TYPE.get(doc_type)

    # Always logged — matched or not — same "log every outcome, not just
    # flags" convention as the sensitivity scanner (tools/documents.py).
    data_source.create_workflow_event(
        ctx.tenant_id, None, "document_type_classification", None, ctx.user_id,
        {
            "detected_type": doc_type,
            "confidence": verdict.get("confidence"),
            "reason": verdict.get("reason"),
            "matched_slot": slot,
        },
    )

    if slot is None:
        detected = doc_type if doc_type and doc_type != "other" else "something else"
        return OnboardingReply(
            text=(
                f"That doesn't look like an employee handbook or a leave policy document — "
                f"it looks more like {detected}. {verdict.get('reason', '')} "
                f"Please attach one of those two documents."
            ).strip(),
            awaiting_upload=True,
        )

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

    already_had = answers.get(slot) is not None
    data_source.update_onboarding_session(ctx.tenant_id, session_id, answers={slot: result.data["document_id"]})
    answers = {**answers, slot: result.data["document_id"]}

    label = "employee handbook" if slot == "handbook_document_id" else "leave policy document"
    note = f"{'Updated' if already_had else 'Got'} your {label}."
    return _next_reply(ctx, session_id, data_source, answers, extra_notes=[note])
