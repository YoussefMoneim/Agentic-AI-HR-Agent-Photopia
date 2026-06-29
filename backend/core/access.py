from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.base import ToolContext

# Salary and national_id fields that require field-level access control.
# national_id is future-proofed here — the column does not yet exist in the schema.
SALARY_FIELDS: frozenset[str] = frozenset({
    "basic_salary", "housing_allowance", "transport_allowance", "total_salary",
})
NATIONAL_ID_FIELDS: frozenset[str] = frozenset({"national_id"})
SENSITIVE_FIELDS: frozenset[str] = SALARY_FIELDS | NATIONAL_ID_FIELDS

_APPROVE_REJECT_ROLES: frozenset[str] = frozenset({"hr_staff", "hr_manager", "admin"})


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str = ""
    masked_fields: frozenset[str] = field(default_factory=frozenset)


def can_access(caller: "ToolContext", action: str, target: dict) -> AccessDecision:
    """
    Single entry point for all three access-control gates.

    Gate 1 — RBAC: caller.role must be permitted for this action.
    Gate 2 — Row/Resource ACL: caller must own or have explicit rights to the target row.
    Gate 3 — Field masking: returns masked_fields; callers null those keys before the
              result dict reaches the LLM context.

    Signature is OPA-compatible (Phase 5 swap):
        caller  → input.caller
        action  → input.action
        target  → input.resource

    Fail-closed: unknown action strings return AccessDecision(allowed=False).
    """
    role = caller.role

    # ── read_employee_row ──────────────────────────────────────────────────────
    # Gate 2: employees may only read their own row.
    # Gate 3: hr_staff see the row but salary fields are masked to null.
    if action == "read_employee_row":
        target_code = target.get("employee_code", "")
        if role == "employee" and target_code != caller.employee_code:
            return AccessDecision(
                allowed=False,
                reason="Access denied: you may only view your own record.",
            )
        mask = SALARY_FIELDS if role == "hr_staff" else frozenset()
        return AccessDecision(allowed=True, masked_fields=mask)

    # ── read_leave_balance ─────────────────────────────────────────────────────
    if action == "read_leave_balance":
        target_code = target.get("employee_code", "")
        if role == "employee" and target_code != caller.employee_code:
            return AccessDecision(
                allowed=False,
                reason="You can only check your own leave balance.",
            )
        return AccessDecision(allowed=True)

    # ── read_leave_eligibility ─────────────────────────────────────────────────
    if action == "read_leave_eligibility":
        target_code = target.get("employee_code", "")
        if role == "employee" and target_code != caller.employee_code:
            return AccessDecision(
                allowed=False,
                reason="You can only check your own eligibility.",
            )
        return AccessDecision(allowed=True)

    # ── read_leave_requests ────────────────────────────────────────────────────
    # None employee_code = HR requesting "all requests" — allowed for HR, blocked for employees.
    if action == "read_leave_requests":
        target_code = target.get("employee_code")
        if role == "employee" and target_code and target_code != caller.employee_code:
            return AccessDecision(
                allowed=False,
                reason="You can only view your own leave requests.",
            )
        return AccessDecision(allowed=True)

    # ── approve_leave / reject_leave ───────────────────────────────────────────
    if action in ("approve_leave", "reject_leave"):
        # Gate 1: employee role may never approve or reject
        if role not in _APPROVE_REJECT_ROLES:
            return AccessDecision(
                allowed=False,
                reason=f"Role '{role}' is not permitted to {action.replace('_', ' ')}.",
            )
        # Gate 2: caller must be the assigned manager for this specific request
        assigned_id = target.get("assigned_manager_db_id")
        caller_id = target.get("caller_employee_db_id")
        if assigned_id and caller_id and assigned_id != caller_id:
            return AccessDecision(
                allowed=False,
                reason="You are not the assigned approver for this request.",
            )
        return AccessDecision(allowed=True)

    # ── cancel_leave ───────────────────────────────────────────────────────────
    if action == "cancel_leave":
        request_owner = target.get("request_employee_code", "")
        if role == "employee" and request_owner != caller.employee_code:
            return AccessDecision(
                allowed=False,
                reason="You can only cancel your own leave requests.",
            )
        return AccessDecision(allowed=True)

    # ── request_leave_cancellation ─────────────────────────────────────────────
    # Any role may request cancellation; employees only for their own leave.
    if action == "request_leave_cancellation":
        request_owner = target.get("request_employee_code", "")
        if role == "employee" and request_owner != caller.employee_code:
            return AccessDecision(
                allowed=False,
                reason="You can only request cancellation of your own leave.",
            )
        return AccessDecision(allowed=True)

    # ── approve_leave_cancellation ─────────────────────────────────────────────
    # HR roles only — employees cannot approve cancellations (even of their own).
    if action == "approve_leave_cancellation":
        if role not in _APPROVE_REJECT_ROLES:
            return AccessDecision(
                allowed=False,
                reason=f"Role '{role}' is not permitted to approve leave cancellations.",
            )
        return AccessDecision(allowed=True)

    # ── view_pending_cancellations ─────────────────────────────────────────────
    if action == "view_pending_cancellations":
        if role not in _APPROVE_REJECT_ROLES:
            return AccessDecision(
                allowed=False,
                reason=f"Role '{role}' is not permitted to view pending cancellations.",
            )
        return AccessDecision(allowed=True)

    # Fail-closed: unknown action
    return AccessDecision(
        allowed=False,
        reason=f"Unknown action '{action}'. Access denied.",
    )
