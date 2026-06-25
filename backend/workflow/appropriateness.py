"""
Appropriateness layer — permission ≠ appropriateness.

Steps 0–5 enforce *can* (access gates) and *should* (constraint engine).
This module adds a third check: *is this appropriate* even when technically
permitted and within policy. Detection is deterministic — sensitivity
classification + role rules, never LLM judgment.

The agent NEVER blocks on appropriateness grounds. check_appropriateness()
returns a flag; the caller surfaces it alongside the normal result. Both the
flag and the human's decision ("proceeded" / "cancelled") are recorded in
workflow_events for the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from data.base import DataSource
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
