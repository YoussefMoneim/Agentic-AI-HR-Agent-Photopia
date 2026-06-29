"""
Deterministic constraint engine for leave request approval/rejection.

Evaluates three rule classes before any state change is committed:
  Hard rules   — BLOCK the action; no override possible.
  Soft rules   — WARN and require an override_reason from a permitted role.
  Advisory flags — Inform but do not block; action proceeds, flag is logged.

The LLM receives the ConstraintDecision as a tool response and uses it to
explain the situation to the user. The decision is never delegated to the LLM.

evaluate_constraints() is the single entry point; call it BEFORE
update_leave_request_status() in ApproveLeaveRequestTool / RejectLeaveRequestTool.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from data.base import DataSource
    from tools.base import ToolContext


def count_working_days(start_date: date, end_date: date) -> int:
    """
    Count working days between start and end date inclusive.
    Working days: Monday through Friday (weekday() 0-4).
    Saturday (5) and Sunday (6) are excluded.
    Future: extend to check public_holidays table.
    """
    if start_date > end_date:
        return 0
    count = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Monday=0, Friday=4
            count += 1
        current += timedelta(days=1)
    return count


def get_first_working_day(start_date: date) -> date:
    """Return start_date if it's a working day, else the next working day."""
    while start_date.weekday() >= 5:
        start_date += timedelta(days=1)
    return start_date


@dataclass
class ConstraintDecision:
    verdict: Literal["allowed", "blocked", "requires_override", "advisory"]
    reason: str
    flags: list[str] = field(default_factory=list)
    override_reason_required: bool = False
    # When not None, a workflow_events row is written before the state change
    event_type: str | None = None
    event_data: dict = field(default_factory=dict)


_ALLOWED = ConstraintDecision(verdict="allowed", reason="")

_DEFAULT_THRESHOLDS: dict = {
    "max_concurrent_leave_pct": 0.25,
    "allow_balance_override_roles": ["hr_manager", "admin"],
}


def _thresholds(settings: dict) -> dict:
    cfg = settings.get("constraints", {})
    return {
        "max_concurrent_leave_pct": float(
            cfg.get("max_concurrent_leave_pct", 0.25)
        ),
        "allow_balance_override_roles": list(
            cfg.get("allow_balance_override_roles", ["hr_manager", "admin"])
        ),
    }


def evaluate_constraints(
    ctx: "ToolContext",
    action: Literal["approve_leave", "reject_leave"],
    leave_request: dict,
    ds: "DataSource",
    override_reason: str | None = None,
) -> ConstraintDecision:
    """
    Evaluate all constraints for the given action against the leave_request dict
    (as returned by get_leave_request_by_id, which now includes
    has_medical_certificate and employee_department).

    Returns a ConstraintDecision. Callers must:
      - Return an error if verdict == "blocked" or "requires_override"
      - Write the workflow_event before the state change if event_type is set
      - Surface flags to the LLM if verdict == "advisory"
    """
    settings = ds.get_tenant_settings(ctx.tenant_id)
    t = _thresholds(settings)
    leave_type_code = leave_request.get("leave_type_code", "")

    # ──────────────────────────────────────────────────────────────────────────
    # REJECT path
    # ──────────────────────────────────────────────────────────────────────────
    if action == "reject_leave":
        # Hard rule: sick leave + certificate on file → BLOCK
        if leave_type_code == "sick" and leave_request.get("has_medical_certificate"):
            return ConstraintDecision(
                verdict="blocked",
                reason=(
                    "Sick leave with a valid medical certificate cannot be rejected "
                    "under Egyptian Labour Law (Art. 68). "
                    "To proceed, approve this request or escalate to HR."
                ),
                event_type="hard_rule_blocked",
                event_data={
                    "rule": "sick_leave_with_cert",
                    "leave_type": leave_type_code,
                    "request_id": leave_request.get("id"),
                },
            )

        # Advisory: long sick leave without certificate
        if leave_type_code == "sick" and not leave_request.get("has_medical_certificate"):
            policy = ds.get_leave_policy(ctx.tenant_id, leave_request["leave_type_id"])
            cert_threshold = (policy or {}).get("requires_medical_cert_after_days") or 0
            days = leave_request.get("days_requested") or 0
            if cert_threshold and days > cert_threshold:
                return ConstraintDecision(
                    verdict="advisory",
                    reason=(
                        f"This sick leave ({days} days) exceeds the {cert_threshold}-day "
                        "medical certificate threshold, but no certificate is on file. "
                        "Rejection is permitted but may conflict with employee protections."
                    ),
                    flags=["no_medical_certificate"],
                    event_type="advisory_shown",
                    event_data={
                        "flag": "no_medical_certificate",
                        "days_requested": days,
                        "cert_threshold": cert_threshold,
                        "request_id": leave_request.get("id"),
                    },
                )

        return _ALLOWED

    # ──────────────────────────────────────────────────────────────────────────
    # APPROVE path
    # ──────────────────────────────────────────────────────────────────────────
    if action == "approve_leave":
        allow_roles = t["allow_balance_override_roles"]
        cap_pct = t["max_concurrent_leave_pct"]

        # Soft rule 1: 25% concurrent department cap
        department = leave_request.get("employee_department")
        start_date = leave_request.get("start_date")
        end_date = leave_request.get("end_date")

        if department and start_date and end_date:
            counts = ds.count_active_leaves_in_department(
                ctx.tenant_id, department, start_date, end_date,
                exclude_request_id=leave_request.get("id"),
            )
            total = counts.get("total_employees", 0)
            active = counts.get("active_count", 0)

            # Only apply cap when someone is already on leave — prevents false triggers
            # on small teams where the first approval would always exceed the threshold.
            if total > 0 and active >= 1 and (active + 1) / total > cap_pct:
                pct_str = f"{(active + 1) / total * 100:.0f}%"
                threshold_str = f"{cap_pct * 100:.0f}%"
                if not override_reason:
                    return ConstraintDecision(
                        verdict="requires_override",
                        reason=(
                            f"Approving this request would put {active + 1}/{total} employees "
                            f"({pct_str}) in '{department}' on leave simultaneously, "
                            f"exceeding the {threshold_str} concurrent threshold. "
                            "Supply an override_reason to proceed."
                        ),
                        flags=["dept_cap_exceeded"],
                        override_reason_required=True,
                    )
                if ctx.role not in allow_roles:
                    return ConstraintDecision(
                        verdict="blocked",
                        reason=(
                            f"Overriding the concurrent leave cap requires the "
                            f"hr_manager or admin role. "
                            f"Your role ({ctx.role!r}) is not permitted to override this policy."
                        ),
                    )
                # Override accepted by permitted role — log as policy_exception
                return ConstraintDecision(
                    verdict="allowed",
                    reason="",
                    event_type="policy_exception",
                    event_data={
                        "rule": "dept_cap_exceeded",
                        "department": department,
                        "active_count": active + 1,
                        "total_employees": total,
                        "cap_pct": cap_pct,
                        "override_reason": override_reason,
                        "overriding_role": ctx.role,
                    },
                )

        # Soft rule 2: balance exceeded
        days = leave_request.get("days_requested")
        employee_code = leave_request.get("employee_code")
        if days and employee_code:
            year = int(start_date[:4]) if start_date else datetime.date.today().year
            balances = ds.get_leave_balance_detail(ctx.tenant_id, employee_code, year)
            balance_row = next(
                (b for b in balances if b["leave_type_code"] == leave_type_code), None
            )
            if balance_row is not None:
                # balance_days = allocated - used - pending + carry_over
                # This already accounts for the pending reservation made at submission.
                # A negative value means the request exceeds entitlement.
                balance_days = balance_row.get("balance_days") or 0.0
                if balance_days < 0:
                    if not override_reason:
                        return ConstraintDecision(
                            verdict="requires_override",
                            reason=(
                                f"This {leave_type_code} request ({days} days) exceeds the "
                                f"employee's entitlement by {abs(balance_days):.1f} days. "
                                "Supply an override_reason to approve beyond entitlement."
                            ),
                            flags=["balance_exceeded"],
                            override_reason_required=True,
                        )
                    if ctx.role not in allow_roles:
                        return ConstraintDecision(
                            verdict="blocked",
                            reason=(
                                f"Overriding the leave balance limit requires the "
                                f"hr_manager or admin role. "
                                f"Your role ({ctx.role!r}) is not permitted to override this policy."
                            ),
                        )
                    return ConstraintDecision(
                        verdict="allowed",
                        reason="",
                        event_type="policy_exception",
                        event_data={
                            "rule": "balance_exceeded",
                            "leave_type": leave_type_code,
                            "days_requested": days,
                            "balance_days": balance_days,
                            "override_reason": override_reason,
                            "overriding_role": ctx.role,
                        },
                    )

        return _ALLOWED

    return _ALLOWED
