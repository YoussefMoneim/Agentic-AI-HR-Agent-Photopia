# This is the only file that imports the anthropic SDK.
import anthropic

from llm.base import LLMProvider, LLMResponse, ToolCall


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        system: str,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools  # Anthropic errors if you pass an empty list, so only include when non-empty

        message = self._client.messages.create(**kwargs)

        text = ""
        tool_calls: list[ToolCall] = []

        for block in message.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=message.stop_reason,
            raw_blocks=message.content,
        )

    def classify(self, system_prompt: str, user_text: str) -> str:
        """Single-turn classification using claude-haiku-4-5 (cheapest tier)."""
        message = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=system_prompt,
            messages=[{"role": "user", "content": user_text}],
        )
        return message.content[0].text.strip() if message.content else ""
