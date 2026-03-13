import os
from google.genai import types
from typing import List, Dict, Any, Optional, Callable, Awaitable
from providers.base import LLMProvider
import google.genai as genai

DISCORD_MESSAGE_LIMIT = 2000
MAX_TOOL_ITERATIONS = 10


class GeminiProvider(LLMProvider):
    def __init__(self, base_url: str = None, api_key: str = None, **kwargs):

        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        self.client = genai.Client(api_key=self.api_key)
        self.async_client = genai.Client(api_key=self.api_key).aio
        self.extra_kwargs = kwargs

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        images: Optional[List[str]] = None,
        tools: Optional[List[Dict]] = None,
        tool_executor: Optional[Callable[[str, Dict], Awaitable[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Sends a chat request using Google's Gemini API.
        Handles tool calls in an agentic loop.
        """

        gemini_messages = self._build_messages(messages, images)

        gemini_tools = None
        if tools:
            gemini_tools = []
            for tool in tools:
                if tool.get("type") == "function" and "function" in tool:
                    func = tool["function"]
                    gemini_tools.append(
                        types.Tool(
                            function_declarations=[
                                types.FunctionDeclaration(
                                    name=func.get("name"),
                                    description=func.get("description"),
                                    parameters_json_schema=func.get("parameters"),
                                )
                            ]
                        )
                    )

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                generate_content_config = types.GenerateContentConfig(
                    tools=gemini_tools,
                )
                response = await self.async_client.models.generate_content(
                    model=model,
                    contents=gemini_messages,
                    config=generate_content_config,
                )
            except Exception as e:
                return {"error": {"message": f"Gemini API error: {str(e)}"}}

            fc_parts = []
            if hasattr(response, "function_calls") and response.function_calls:
                fc_parts = response.function_calls
            elif response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc_parts.append(part.function_call)

            if fc_parts:
                for fc in fc_parts:
                    func_name = fc.name
                    arguments = dict(fc.args) if hasattr(fc, "args") else {}

                    if tool_executor:
                        result = await tool_executor(func_name, arguments)
                    else:
                        result = f"(tool '{func_name}' has no executor)"

                    gemini_messages.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "function_response": {
                                        "name": func_name,
                                        "response": {"result": str(result)},
                                    }
                                }
                            ],
                        }
                    )
            else:
                content = ""
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, "text") and part.text:
                            content += part.text

                return self._build_response(content.strip())

        return {
            "error": {"message": "Max tool iterations reached without a final answer."}
        }

    def _build_messages(
        self,
        messages: List[Dict],
        images: Optional[List[bytes]] = None,
    ) -> List:
        result = []
        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                result.append(f"SYSTEM: {content}")
            elif role == "user" and images and i == len(messages) - 1:
                parts = [content] if content else []
                for img_bytes in images:
                    from PIL import Image
                    import io

                    img = Image.open(io.BytesIO(img_bytes))
                    parts.append(img)
                result.extend(parts)
            elif role == "assistant":
                result.append(content)
            else:
                result.append(content)
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
