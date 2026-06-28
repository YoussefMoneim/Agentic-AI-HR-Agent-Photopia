import json
import httpx
from openai import OpenAI
from llm.base import LLMProvider, LLMResponse, ToolCall


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            http_client=httpx.Client(),
        )
        self._model = model

    def _to_openai_messages(self, messages: list[dict], system: str) -> list[dict]:
        """Convert Anthropic-format message history to OpenAI format.

        The orchestrator stores history in Anthropic format (tool_result user messages,
        assistant content as a list of typed blocks). Gemini's OpenAI-compatible API
        needs role=tool messages and assistant messages with a tool_calls array.
        """
        openai_messages: list[dict] = [{"role": "system", "content": system}]

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            # Anthropic tool results: {"role": "user", "content": [{"type": "tool_result", ...}]}
            if (
                role == "user"
                and isinstance(content, list)
                and content
                and isinstance(content[0], dict)
                and content[0].get("type") == "tool_result"
            ):
                for tr in content:
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": tr["content"],
                    })
                continue

            # Anthropic assistant turn with typed blocks (our raw_blocks dict format)
            if role == "assistant" and isinstance(content, list):
                text_parts: list[str] = []
                oai_tool_calls: list[dict] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        oai_tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": " ".join(text_parts) or None,
                }
                if oai_tool_calls:
                    assistant_msg["tool_calls"] = oai_tool_calls
                openai_messages.append(assistant_msg)
                continue

            # Plain text user/assistant messages
            openai_messages.append({"role": role, "content": content})

        return openai_messages

    def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        system: str,
    ) -> LLMResponse:
        openai_messages = self._to_openai_messages(messages, system)

        openai_tools = None
        if tools:
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        response = self._client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            **({"tools": openai_tools} if openai_tools else {}),
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

        # Store raw_blocks as Anthropic-compatible dicts so the orchestrator's history
        # can be converted back by _to_openai_messages() on the next turn.
        raw_blocks: list[dict] = []
        if text:
            raw_blocks.append({"type": "text", "text": text})
        for tc in tool_calls:
            raw_blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})

        stop_reason = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw_blocks=raw_blocks,
        )
