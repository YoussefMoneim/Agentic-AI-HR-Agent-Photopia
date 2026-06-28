"""
Appropriateness Layer — Permission ≠ Appropriateness

SCENARIOS COVERED BY THIS MODULE:
  A. New document upload — scan before ingestion (check_share_mismatch)
  B. Existing document explicit share — scan before sharing (check_share_mismatch)
  C. Silent folder access audit — periodic review (SensitivityAuditTool)
  E. Agent-generated document — scan before delivery (existing check_appropriateness)
  J. External recipient — always flag sensitive content (recipient_role=None)

SCENARIOS HANDLED ELSEWHERE (do not duplicate):
  D. Search returns unexpected content — handled by RAG ACL pre-filter in search_policy SQL
  G. Role change after access — handled by RLS checking current role on every query
  I. Cross-tenant access — handled by RLS tenant_isolation policy on all tables

SCENARIOS DEFERRED TO PHASE 3:
  F. Content changes after classification — requires document versioning system
  H. Bulk share aggregation — requires group membership analysis at share time
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from data.base import DataSource
    from llm.base import LLMProvider
    from tools.base import ToolContext

# Sensitivity classification for the three document types that exist today.
# Extend this dict as new document types are added — never remove existing keys.
DOCUMENT_SENSITIVITY: dict[str, str] = {
    "salary_certificate": "restricted",       # contains salary + bank routing data
    "twimc_letter": "internal",
    "experience_certificate": "internal",
}

# Which roles may access / receive documents at each sensitivity level.
SENSITIVITY_PERMITTED_ROLES: dict[str, frozenset[str]] = {
    "restricted": frozenset({"hr_manager", "admin"}),
    "internal":   frozenset({"hr_staff", "hr_manager", "admin"}),
}

# Salary-related field names used in Check 2 (overshare_risk).
SALARY_FIELDS: frozenset[str] = frozenset({
    "basic_salary", "housing_allowance", "transport_allowance",
    "total_salary", "salary", "compensation",
})


@dataclass
class AppropriatenessDecision:
    flagged: bool
    reason: str
    flag_code: str | None        # "sensitivity_mismatch" | "overshare_risk"
    severity: Literal["info", "warning"]
    event_type: str = field(default="appropriateness_flag")


_NOT_FLAGGED = AppropriatenessDecision(
    flagged=False, reason="", flag_code=None, severity="info"
)


def check_appropriateness(
    ctx: "ToolContext",
    action: str,
    resource_metadata: dict,
    ds: "DataSource",
) -> AppropriatenessDecision:
    """
    Evaluate whether an action is appropriate given sensitivity classification.

    action values:
      "access_document"  — caller is reading a document or its history
      "generate_document"| "send_document" | "notify" — outbound actions

    resource_metadata keys (all optional):
      document_type: str           — e.g. "salary_certificate"
      document_types: list[str]    — list of types (for access_document with history)
      payload_fields: list[str]    — field names in the payload (for notify)
      recipient_role: str | None   — recipient's role (None = external/unknown)
    """
    if action == "access_document":
        return _check_sensitivity_mismatch(ctx, resource_metadata)

    if action in ("generate_document", "send_document", "notify"):
        return _check_overshare_risk(ctx, action, resource_metadata)

    return _NOT_FLAGGED


def _check_sensitivity_mismatch(
    ctx: "ToolContext",
    resource_metadata: dict,
) -> AppropriatenessDecision:
    """Check 1: caller's role is not permitted for the most sensitive doc in the set."""
    doc_types: list[str] = resource_metadata.get("document_types") or (
        [resource_metadata["document_type"]]
        if resource_metadata.get("document_type")
        else []
    )
    if not doc_types:
        return _NOT_FLAGGED

    max_sensitivity = "internal"
    for dt in doc_types:
        if DOCUMENT_SENSITIVITY.get(dt) == "restricted":
            max_sensitivity = "restricted"
            break

    permitted = SENSITIVITY_PERMITTED_ROLES.get(max_sensitivity, frozenset())
    if ctx.role in permitted:
        return _NOT_FLAGGED

    return AppropriatenessDecision(
        flagged=True,
        reason=(
            f"This employee's document history includes {max_sensitivity} documents "
            f"(e.g. salary certificates). Your role ({ctx.role!r}) is not normally "
            "associated with salary data access. Proceed only if this is intentional "
            "and you have a valid business reason."
        ),
        flag_code="sensitivity_mismatch",
        severity="warning",
    )


def _check_overshare_risk(
    ctx: "ToolContext",
    action: str,
    resource_metadata: dict,
) -> AppropriatenessDecision:
    """Check 2: salary-classified content going to a recipient without salary visibility.

    generate_document with no recipient_role is not flagged — the document is
    just written to a file; no one has received it yet. Overshare risk only
    materialises when actively sending/sharing to a specific party.
    """
    doc_type = resource_metadata.get("document_type", "")
    payload_fields: set[str] = set(resource_metadata.get("payload_fields") or [])
    recipient_role: str | None = resource_metadata.get("recipient_role")

    has_salary_content = (
        DOCUMENT_SENSITIVITY.get(doc_type) == "restricted"
        or bool(payload_fields & SALARY_FIELDS)
    )
    if not has_salary_content:
        return _NOT_FLAGGED

    permitted_for_restricted = SENSITIVITY_PERMITTED_ROLES.get("restricted", frozenset())

    if recipient_role is not None:
        # Explicit recipient — flag only if they lack salary access
        if recipient_role in permitted_for_restricted:
            return _NOT_FLAGGED
        return AppropriatenessDecision(
            flagged=True,
            reason=(
                f"This document contains salary-classified data. "
                f"The intended recipient role ({recipient_role!r}) does not have "
                "confirmed salary visibility. Confirm the recipient is authorised "
                "before proceeding."
            ),
            flag_code="overshare_risk",
            severity="warning",
        )

    # recipient_role is None — distinguish generation from active sharing
    if action == "generate_document":
        # Writing to a file only; no recipient has received it yet → not an overshare
        return _NOT_FLAGGED

    # send_document / notify with no identified recipient → unknown external → flag
    return AppropriatenessDecision(
        flagged=True,
        reason=(
            "This document contains salary-classified data and is being sent to an "
            "unidentified external recipient. Confirm the recipient is authorised "
            "to receive salary information before proceeding."
        ),
        flag_code="overshare_risk",
        severity="warning",
    )


def record_appropriateness_decision(
    tenant_id: str,
    workflow_event_id: str,
    decision: str,
    ds: "DataSource",
) -> None:
    """
    Record the human's response to an appropriateness flag.
    decision: "proceeded" | "cancelled"
    Updates workflow_events.data.human_decision for the audit trail.
    """
    ds.record_appropriateness_decision(tenant_id, workflow_event_id, decision)


# ── Content scanner and share mismatch detector (Component 1) ─────────────────

# Sensitive content patterns — deterministic regex, not LLM
SENSITIVITY_PATTERNS: dict[str, list[str]] = {
    "salary": [
        r"\bbasic[\s_-]?salary\b",
        r"\bEGP\s*[\d,]+\b",
        r"\bmonthly[\s_-]?salary\b",
        r"\bhousing[\s_-]?allowance\b",
        r"\btransport[\s_-]?allowance\b",
        r"\btotal[\s_-]?salary\b",
        r"\bcompensation[\s_-]?package\b",
        r"\bpayslip\b",
        r"\bpayroll\b",
        r"\bnet[\s_-]?pay\b",
    ],
    "national_id": [
        r"\b\d{14}\b",
        r"\bnational[\s_-]?id\b",
        r"\bnational[\s_-]?number\b",
        r"\bid[\s_-]?number\b",
    ],
    "medical": [
        r"\bdiagnosis\b",
        r"\bmedical[\s_-]?report\b",
        r"\bprescription\b",
        r"\bdisease\b",
        r"\btreatment\b",
        r"\bhospital\b",
        r"\bsick[\s_-]?certificate\b",
    ],
    "performance": [
        r"\bperformance[\s_-]?review\b",
        r"\bdisciplinary\b",
        r"\bwarning[\s_-]?letter\b",
        r"\btermination\b",
        r"\bpip\b",
    ],
    "financial": [
        r"\bbank[\s_-]?account\b",
        r"\biban\b",
        r"\bswift[\s_-]?code\b",
        r"\bbudget\b",
        r"\bfinancial[\s_-]?forecast\b",
        r"\brevenue\b",
        r"\bprofit[\s_-]?loss\b",
    ],
}

# Which roles may see each sensitivity type
SENSITIVITY_ROLE_REQUIREMENTS: dict[str, frozenset[str]] = {
    "salary":      frozenset({"hr_manager", "admin", "finance"}),
    "national_id": frozenset({"hr_manager", "admin"}),
    "medical":     frozenset({"hr_manager", "admin"}),
    "performance": frozenset({"hr_manager", "admin"}),
    "financial":   frozenset({"finance", "admin", "executive"}),
}


_SENSITIVITY_CLASSIFIER_PROMPT = """\
You are a document sensitivity classifier. You receive a short text excerpt that
matched a sensitivity pattern and must decide if it is genuinely sensitive.

Respond ONLY with valid JSON — no text outside the JSON object:
{
    "is_sensitive": true or false,
    "confidence": "high" or "medium" or "low",
    "reason": "one sentence",
    "false_positive_type": "expense" or "price_list" or "technical" or "general_text" or null
}

Rules:
- If in doubt respond with is_sensitive: true (fail closed)
- "EGP 850 team lunch" → false positive (expense), is_sensitive: false
- "Basic salary EGP 25,000 per month" → is_sensitive: true
- "diagnosis confirmed by physician" → is_sensitive: true
- "the diagnosis of the problem was fixed" → is_sensitive: false (technical context)
"""


def extract_surrounding_context(content: str, match_text: str, window: int = 100) -> str:
    """Return up to `window` chars on each side of the first occurrence of match_text."""
    idx = content.lower().find(match_text.lower())
    if idx == -1:
        return match_text[:200]
    start = max(0, idx - window)
    end = min(len(content), idx + len(match_text) + window)
    return content[start:end]


def verify_sensitivity_with_llm(
    pattern_type: str,
    surrounding_context: str,
    llm_provider: "LLMProvider",
    document_hint: str = "unknown",
) -> dict:
    """
    Stage 2: LLM verifies whether a regex match is genuinely sensitive.
    Only the surrounding context (max 200 chars) is sent — never the full document.
    Returns a structured verdict. Fails closed on any exception.
    """
    try:
        user_text = (
            f"Pattern type: {pattern_type}\n"
            f"Context excerpt: {surrounding_context[:200]}\n"
            f"Document hint: {document_hint}"
        )
        raw = llm_provider.classify(_SENSITIVITY_CLASSIFIER_PROMPT, user_text)
        return json.loads(raw)
    except Exception:
        return {
            "is_sensitive": True,
            "confidence": "low",
            "reason": "Context verification unavailable — treating as sensitive by default",
            "false_positive_type": None,
        }


def scan_content_for_sensitivity(content: str) -> dict[str, list[str]]:
    """
    Deterministic regex scan — never uses LLM.
    Returns {sensitivity_type: [matched_examples]} for each type detected.
    Empty dict means no sensitive content found.
    """
    detected: dict[str, list[str]] = {}
    for sensitivity_type, patterns in SENSITIVITY_PATTERNS.items():
        matches: list[str] = []
        for pattern in patterns:
            found = re.findall(pattern, content, re.IGNORECASE)
            matches.extend(found[:2])
        if matches:
            detected[sensitivity_type] = list(dict.fromkeys(matches))[:3]
    return detected


def check_share_mismatch(
    content: str,
    recipient_role: str | None,
    sharer_role: str,
    document_title: str = "",
    llm_provider: "LLMProvider | None" = None,
) -> AppropriatenessDecision:
    """
    Checks whether document content is appropriate to share with recipient_role.

    Covers these scenarios:
    - Scenario A: new document about to be uploaded
    - Scenario B: existing document being explicitly shared
    - Scenario E: agent-generated document before delivery
    - Scenario J: external recipient (recipient_role=None) — always flag sensitive content

    Does NOT block. Returns a flag the human must acknowledge.
    The human decision must be logged by the caller.
    """
    detected = scan_content_for_sensitivity(content)
    if not detected:
        return AppropriatenessDecision(
            flagged=False, reason="", flag_code=None, severity="info"
        )

    mismatches: list[dict] = []
    for sensitivity_type, examples in detected.items():
        required_roles = SENSITIVITY_ROLE_REQUIREMENTS.get(
            sensitivity_type, frozenset()
        )
        # External recipient (None) never has salary/medical/national_id access
        if recipient_role is None or recipient_role not in required_roles:
            mismatches.append({
                "type": sensitivity_type,
                "required_roles": sorted(required_roles),
                "recipient_role": recipient_role or "external",
                "examples": examples,
            })

    if not mismatches:
        return AppropriatenessDecision(
            flagged=False, reason="", flag_code=None, severity="info"
        )

    # Optional LLM stage: verify each match in context to reduce false positives.
    # If llm_provider is None, skip and trust the regex result.
    llm_verdicts: dict[str, dict] = {}
    if llm_provider is not None:
        for m in mismatches:
            examples = m.get("examples", [])
            if examples:
                context = extract_surrounding_context(content, examples[0])
                verdict = verify_sensitivity_with_llm(
                    pattern_type=m["type"],
                    surrounding_context=context,
                    llm_provider=llm_provider,
                    document_hint=document_title or "unknown",
                )
                llm_verdicts[m["type"]] = verdict
                m["llm_verdict"] = verdict

    types_list = ", ".join(m["type"] for m in mismatches)
    recipient_desc = (
        f"role '{recipient_role}'"
        if recipient_role
        else "an external recipient (outside the company)"
    )

    # Build reason — include LLM explanation only when it's a real verdict (not the fallback)
    llm_reasons = [
        v.get("reason", "")
        for v in llm_verdicts.values()
        if v.get("reason")
        and v.get("is_sensitive", True)
        and v.get("confidence", "low") != "low"  # skip low-confidence fallbacks
    ]
    llm_detail = f" {llm_reasons[0]}." if llm_reasons else ""

    reason = (
        f"This document contains {types_list} data.{llm_detail} "
        f"The intended recipient ({recipient_desc}) does not normally "
        f"have access to this type of information. "
        f"This is a flag, not a block — you have the final decision. "
        f"Your choice will be logged with your name and timestamp."
    )

    return AppropriatenessDecision(
        flagged=True,
        reason=reason,
        flag_code="share_mismatch",
        severity="warning",
    )
