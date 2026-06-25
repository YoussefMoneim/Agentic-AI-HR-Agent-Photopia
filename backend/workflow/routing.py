from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from data.base import DataSource


@dataclass(frozen=True)
class ApprovalRoutingPolicy:
    top_of_hierarchy_action: Literal["self_approve_flagged", "delegate_to_hr"] = "self_approve_flagged"
    default_deadline_hours: int = 72


_DEFAULT_POLICY = ApprovalRoutingPolicy()


def get_routing_policy(tenant_id: str, ds: "DataSource") -> ApprovalRoutingPolicy:
    """Read the approval routing policy for this tenant from DB settings.
    Falls back to the default policy if no settings are found."""
    try:
        settings = ds.get_tenant_settings(tenant_id)
    except Exception:
        return _DEFAULT_POLICY

    cfg = settings.get("approval_routing", {})
    if not cfg:
        return _DEFAULT_POLICY

    action = cfg.get("top_of_hierarchy_action", "self_approve_flagged")
    if action not in ("self_approve_flagged", "delegate_to_hr"):
        action = "self_approve_flagged"

    return ApprovalRoutingPolicy(
        top_of_hierarchy_action=action,
        default_deadline_hours=int(cfg.get("default_deadline_hours", 72)),
    )
