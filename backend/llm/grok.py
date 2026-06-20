import json

import openai

from llm.base import LLMProvider, LLMResponse, ToolCall


class GrokProvider(LLMProvider):
    """xAI Grok via the OpenAI-compatible API. Used for cost testing."""

    def __init__(self, api_key: str, model: str = "grok-beta") -> None:
        self._client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        self._model = model

    def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        system: str,
    ) -> LLMResponse:
        # OpenAI expects system prompt as first message, not a separate parameter
        openai_messages = [{"role": "system", "content": system}] + messages

        # Convert Anthropic-style tool specs to OpenAI format
        openai_tools = None
        if tools:
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),  # Anthropic calls it input_schema, OpenAI calls it parameters
                    },
                }
                for t in tools
            ]

        response = self._client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            tools=openai_tools or openai.NOT_GIVEN,  # NOT_GIVEN omits the key entirely; None would cause an API error
        )

        choice = response.choices[0]
        msg = choice.message
        text = msg.content or ""
        tool_calls: list[ToolCall] = []

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))

        stop_reason = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            # Store in Anthropic-compatible shape so orchestrator can pass it back
            raw_blocks=msg,
        )
