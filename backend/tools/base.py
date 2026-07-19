from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolContext:
    tenant_id: str      # all DB queries must filter on this — never let one company see another's data
    user_id: str        # stored in audit_log so every action is traceable to a person
    role: str           # "employee" | "hr_staff" | "hr_manager" | "admin" — drives what tools are visible
    employee_code: str  # the caller's own code if they're an employee; tools use this for row-level access checks
    display_name: str = ""  # human-readable name injected into the system prompt ("Nourhan Hosny")


@dataclass
class ToolResult:
    success: bool
    data: dict | None = None
    error: str | None = None
    document_id: str | None = None    # set when a PDF was generated; orchestrator collects these for the API response
    document_type: str | None = None  # e.g. "salary_certificate", "twimc_letter", "experience_certificate"
    data_fields_accessed: list[str] | None = None  # sensitive field names read; written to audit_log
    action_type: str = "tool_executed"  # tool_executed | data_read | data_write | decision_denied
    authz_note: str | None = None     # tool-signalled authz decision override written to audit_log.authz_decision


@dataclass
class ToolSpec:
    name: str
    description: str        # shown to the LLM so it knows when to call this tool
    input_schema: dict      # JSON Schema for the tool's parameters; the LLM uses this to form its call
    allowed_roles: list[str] = field(default_factory=list)
    llm_visible: bool = True
    # False = never offered to the LLM tool-use loop (orchestrator.run()) as
    # something it can autonomously decide to call — only reachable via a
    # direct ToolRegistry.execute(name, ...) from deterministic code (e.g.
    # agent/onboarding.py). Still fully executable either way; this only
    # controls what get_specs_for_role() hands to the model. Exists because
    # connect_odoo/ingest_policy_document were being picked by the general
    # chat agent on its own initiative from casual phrasing like "connect it
    # to Odoo" — bypassing the onboarding state machine's gating entirely
    # and then the model fabricating an "onboarding complete" claim on top.

    def to_claude_format(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class Tool(ABC):
    spec: ToolSpec

    @abstractmethod
    def execute(self, input: dict, ctx: ToolContext) -> ToolResult: ...
