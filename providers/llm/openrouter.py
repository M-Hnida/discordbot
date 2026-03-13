import os
import json
from typing import List, Dict, Any, Optional, Callable, Awaitable
from providers.base import LLMProvider

DISCORD_MESSAGE_LIMIT = 2000
MAX_TOOL_ITERATIONS = 10


class OpenRouterProvider(LLMProvider):
    def __init__(self, base_url: str = None, api_key: str = None, **kwargs):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("openai is not installed. Run: pip install openai")

        # OpenRouter's OpenAI-compatible endpoint
        self.base_url = base_url or "https://openrouter.ai/api/v1"
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.extra_kwargs = kwargs

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        images: Optional[List[str]] = None,
        tools: Optional[List[Dict]] = None,
        tool_executor: Optional[Callable[[str, Dict], Awaitable[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Sends a chat request using the OpenAI SDK (targeting OpenRouter).
        Handles tool calls natively in an agentic loop.
        """
        openai_messages = self._build_messages(messages, images)
        current_model = model or "google/gemini-2.5-flash-free"

        for _ in range(MAX_TOOL_ITERATIONS):
            kwargs = {
                "model": current_model,
                "messages": openai_messages,
                **self.extra_kwargs,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            try:
                response = await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                return {"error": {"message": f"OpenRouter API error: {str(e)}"}}

            message = response.choices[0].message

            # No tool calls — we have a final answer
            if not message.tool_calls:
                content = (message.content or "").strip()
                return self._build_response(content)

            # Reconstruct the assistant message for history tracking
            # The OpenAI SDK returns an object, but we need dictionaries for history
            assistant_msg = {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
            openai_messages.append(assistant_msg)

            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}

                if tool_executor:
                    result = await tool_executor(func_name, arguments)
                else:
                    result = f"(tool '{func_name}' has no executor)"

                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": str(result),
                    }
                )

        return {
            "error": {"message": "Max tool iterations reached without a final answer."}
        }

    def _build_messages(
        self,
        messages: List[Dict],
        images: Optional[List[str]],
    ) -> List[Dict]:
        result = []
        for msg in messages:
            content = msg.get("content", "")
            if msg.get("role") == "user" and images:
                image_parts = [
                    {"type": "image_url", "image_url": {"url": url}} for url in images
                ]
                parts = (
                    [{"type": "text", "text": content}] if content else []
                ) + image_parts
                result.append({"role": msg["role"], "content": parts})
            else:
                result.append(msg)
        return result

    def _build_response(self, content: str) -> Dict[str, Any]:
        if not content:
            content = "No response content received."

        if len(content) <= DISCORD_MESSAGE_LIMIT:
            return {
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "additional_chunks": [],
            }

        chunks = [
            content[i : i + DISCORD_MESSAGE_LIMIT]
            for i in range(0, len(content), DISCORD_MESSAGE_LIMIT)
        ]
        return {
            "choices": [{"message": {"role": "assistant", "content": chunks[0]}}],
            "additional_chunks": chunks[1:],
        }
