import datetime
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from llm.base import LLMProvider
from tools.base import ToolContext
from tools.registry import ToolRegistry

_log = logging.getLogger(__name__)
_SYSTEM_PROMPT_BASE = (Path(__file__).parent / "system_prompt.txt").read_text()
MAX_ITERATIONS = 10  # cap to avoid infinite loops if the LLM keeps calling tools without finishing


def _build_system_prompt(ctx: ToolContext) -> str:
    today = datetime.date.today().strftime("%A, %B %d, %Y")
    identity = (
        f"Logged-in user: {ctx.display_name} "
        f"(employee_code={ctx.employee_code!r}, role={ctx.role}). "
        "When the user refers to themselves — 'my salary', 'my leave', 'my profile', "
        f"'generate for me' — use employee_code {ctx.employee_code!r} directly "
        "without asking who they are."
    )
    return identity + "\n\n" + _SYSTEM_PROMPT_BASE.format(today=today)


@dataclass
class AgentResponse:
    text: str
    documents: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)  # full raw conversation for session storage


def run(
    user_message: str,
    ctx: ToolContext,
    llm: LLMProvider,
    registry: ToolRegistry,
    prior_messages: list[dict] | None = None,
) -> AgentResponse:
    tools = registry.get_specs_for_role(ctx.role)  # only send the LLM tools this role can actually call
    messages: list[dict] = list(prior_messages or []) + [{"role": "user", "content": user_message}]
    documents: list[dict] = []
    system_prompt = _build_system_prompt(ctx)

    for iteration in range(MAX_ITERATIONS):
        response = llm.generate(messages, tools or None, system_prompt)
        _log.debug("LLM iteration %d stop_reason=%s", iteration, response.stop_reason)

        if response.stop_reason == "end_turn":
            return AgentResponse(text=response.text, documents=documents, messages=messages)

        if response.stop_reason != "tool_use":
            return AgentResponse(text=response.text or "Done.", documents=documents, messages=messages)

        # Store raw provider blocks, not our parsed version — the API needs its own format back
        messages.append({"role": "assistant", "content": response.raw_blocks})

        tool_results = []
        for tc in response.tool_calls:
            result = registry.execute(tc.name, tc.input, ctx)
            if result.document_id:
                documents.append({
                    "id": result.document_id,
                    "type": result.document_type or "",
                    "employee_name": (result.data or {}).get("employee_name", ""),
                })

            content = json.dumps(result.data) if result.success and result.data else json.dumps({"error": result.error})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,  # must match the LLM's tool_use block id so it links request to result
                "content": content,
            })

        messages.append({"role": "user", "content": tool_results})

    return AgentResponse(
        text="I was unable to complete your request within the allowed number of steps. Please try again.",
        documents=documents,
        messages=messages,
    )
