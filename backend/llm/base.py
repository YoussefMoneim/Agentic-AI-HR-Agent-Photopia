from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str    # must be echoed back in tool_result so the LLM matches request to response
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" = done, "tool_use" = wants to call a tool
    raw_blocks: Any = None         # provider's native content object; passed back as-is for the next message


class LLMProvider(ABC):

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        system: str,
    ) -> LLMResponse: ...

    def classify(self, system_prompt: str, user_text: str) -> str:
        """
        Single-turn classification call.
        Returns raw response text (expected to be JSON).
        Default: fail-closed fallback for providers that don't override this.
        """
        return '{"is_sensitive": true, "confidence": "low", "reason": "Classification not available for this provider", "false_positive_type": null}'
