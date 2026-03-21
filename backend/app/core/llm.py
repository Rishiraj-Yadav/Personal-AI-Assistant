"""
LLM adapter with provider selection.

Primary reasoning/parsing model: Gemini 2.5 Pro
Fallback and tool-calling model: Groq
"""
import asyncio
import base64
from typing import Any, Dict, List, Optional

from groq import AsyncGroq
from loguru import logger

from app.config import settings
from app.models import Message, MessageRole


class LLMAdapter:
    """LLM adapter with Gemini-first routing and Groq fallback."""

    def __init__(self):
        """Initialize Gemini as primary and Groq as fallback/tool provider."""
        self.groq_model = settings.GROQ_MODEL
        self.groq_max_tokens = settings.GROQ_MAX_TOKENS
        self.groq_temperature = settings.GROQ_TEMPERATURE
        self.groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None
        self._groq_available = self.groq_client is not None

        self.gemini_model_name = settings.GEMINI_MODEL
        self.gemini_max_tokens = settings.GEMINI_MAX_TOKENS
        self.gemini_temperature = settings.GEMINI_TEMPERATURE
        self._gemini_model = None
        self._gemini_available = False

        try:
            import google.generativeai as genai

            if settings.GOOGLE_API_KEY:
                genai.configure(api_key=settings.GOOGLE_API_KEY)
                self._gemini_model = genai.GenerativeModel(self.gemini_model_name)
                self._gemini_available = True
                logger.info(f"Gemini primary model configured: {self.gemini_model_name}")
        except Exception as exc:
            logger.warning(f"Gemini provider unavailable: {exc}")

        if self._gemini_available:
            primary = self.gemini_model_name
            fallback = self.groq_model if self._groq_available else "none"
        else:
            primary = self.groq_model if self._groq_available else "none"
            fallback = "none"

        if not self._gemini_available and not self._groq_available:
            logger.error("No LLM provider configured. Set GOOGLE_API_KEY or GROQ_API_KEY.")

        logger.info(
            "Initialized LLM adapter with primary={} and fallback/tool-calling={}".format(
                primary,
                fallback,
            )
        )

    @property
    def model(self) -> str:
        """Expose the primary model name for backward compatibility."""
        if self._gemini_available:
            return self.gemini_model_name
        if self._groq_available:
            return self.groq_model
        return "unconfigured"

    def _format_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        formatted = []
        for msg in messages:
            formatted.append(
                {
                    "role": msg.role.value,
                    "content": msg.content,
                }
            )
        return formatted

    def _build_gemini_inline_image_part(self, image_base64: str, mime_type: str = "image/png") -> Optional[Any]:
        if not image_base64:
            return None
        try:
            raw = base64.b64decode(image_base64)
        except Exception:
            return None

        try:
            import google.generativeai as genai

            return genai.protos.Part(
                inline_data=genai.protos.Blob(
                    mime_type=mime_type or "image/png",
                    data=raw,
                )
            )
        except Exception:
            return None

    def _message_to_gemini_content(self, msg: Message) -> Optional[Any]:
        try:
            import google.generativeai as genai
        except Exception:
            return None

        role_map = {
            MessageRole.USER.value: "user",
            MessageRole.ASSISTANT.value: "model",
        }
        role = role_map.get(msg.role.value)
        if role is None:
            return None

        parts = [genai.protos.Part(text=msg.content)]
        metadata = msg.metadata or {}
        for image in metadata.get("images") or []:
            if not isinstance(image, dict):
                continue
            image_part = self._build_gemini_inline_image_part(
                str(image.get("image_base64", "")),
                str(image.get("mime_type", "image/png") or "image/png"),
            )
            if image_part is not None:
                parts.append(image_part)

        return genai.protos.Content(role=role, parts=parts)

    def _build_gemini_contents(self, messages: List[Message]) -> List[Any]:
        import google.generativeai as genai

        contents: List[Any] = []
        system_messages = [msg.content for msg in messages if msg.role == MessageRole.SYSTEM and msg.content]
        if system_messages:
            system_text = "\n\n".join(system_messages)
        else:
            system_text = settings.SYSTEM_PROMPT

        contents.append(
            genai.protos.Content(
                role="user",
                parts=[genai.protos.Part(text=f"System instructions:\n{system_text}")],
            )
        )

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            content = self._message_to_gemini_content(msg)
            if content is not None:
                contents.append(content)

        return contents

    async def generate_response(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate a response with provider-aware fallback behavior."""
        if tools:
            if self._groq_available:
                try:
                    return await self._call_groq(messages, tools, temperature, max_tokens)
                except Exception as groq_err:
                    logger.warning(f"Groq tool-calling failed, falling back to Gemini text response: {groq_err}")
                    if self._gemini_available:
                        return await self._call_gemini(messages, max_tokens=max_tokens, temperature=temperature)
                    raise
            if self._gemini_available:
                logger.warning("Tools requested without Groq configured. Falling back to Gemini text-only mode.")
                return await self._call_gemini(messages, max_tokens=max_tokens, temperature=temperature)
            raise RuntimeError("No LLM provider available for tool-enabled request.")

        if self._gemini_available:
            try:
                return await self._call_gemini(messages, max_tokens=max_tokens, temperature=temperature)
            except Exception as gemini_err:
                logger.warning(f"Gemini failed, falling back to Groq: {gemini_err}")
                if self._groq_available:
                    return await self._call_groq(messages, tools=None, temperature=temperature, max_tokens=max_tokens)
                raise

        if self._groq_available:
            return await self._call_groq(messages, tools=None, temperature=temperature, max_tokens=max_tokens)

        raise RuntimeError("No LLM provider configured. Set GOOGLE_API_KEY or GROQ_API_KEY.")

    async def _call_groq(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Call the Groq chat completions API."""
        if not self.groq_client:
            raise RuntimeError("Groq is not configured.")

        formatted_messages = self._format_messages(messages)
        if not any(msg["role"] == "system" for msg in formatted_messages):
            formatted_messages.insert(
                0,
                {
                    "role": "system",
                    "content": settings.SYSTEM_PROMPT,
                },
            )

        api_params: Dict[str, Any] = {
            "model": self.groq_model,
            "messages": formatted_messages,
            "temperature": temperature if temperature is not None else self.groq_temperature,
            "max_tokens": max_tokens or self.groq_max_tokens,
            "top_p": 1,
            "stream": False,
        }

        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = "auto"

        response = await self.groq_client.chat.completions.create(**api_params)
        choice = response.choices[0]
        tokens_used = response.usage.total_tokens if response.usage else None

        result: Dict[str, Any] = {
            "model": self.groq_model,
            "provider": "groq",
            "tokens_used": tokens_used,
            "finish_reason": choice.finish_reason,
        }

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            result["tool_calls"] = []
            for tool_call in choice.message.tool_calls:
                result["tool_calls"].append(
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )
            result["response"] = choice.message.content or ""
            logger.info(f"Groq requested {len(result['tool_calls'])} tool calls")
        else:
            result["response"] = choice.message.content or ""
            logger.info(f"Groq response generated: {tokens_used} tokens used")

        return result

    async def _call_gemini(
        self,
        messages: List[Message],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Call Gemini using the synchronous SDK through a worker thread."""
        if not self._gemini_available or not self._gemini_model:
            raise RuntimeError("Gemini is not configured.")

        generation_config = {
            "temperature": temperature if temperature is not None else self.gemini_temperature,
            "max_output_tokens": max_tokens or self.gemini_max_tokens,
        }
        contents = self._build_gemini_contents(messages)

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._gemini_model.generate_content(
                contents,
                generation_config=generation_config,
            ),
        )

        text = getattr(response, "text", "") or ""
        logger.info(f"Gemini response generated ({len(text)} chars)")

        return {
            "model": self.gemini_model_name,
            "provider": "gemini",
            "tokens_used": None,
            "finish_reason": "stop",
            "response": text,
        }

    async def check_health(self) -> Dict[str, bool]:
        """Check provider availability with lightweight test calls."""
        health = {
            "gemini": False,
            "groq": False,
        }

        if self._gemini_available:
            try:
                await self._call_gemini([Message(role=MessageRole.USER, content="Hello")])
                health["gemini"] = True
            except Exception as exc:
                logger.error(f"Gemini health check failed: {exc}")

        if self._groq_available:
            try:
                await self.groq_client.chat.completions.create(
                    model=self.groq_model,
                    messages=[{"role": "user", "content": "Hello"}],
                    max_tokens=5,
                )
                health["groq"] = True
            except Exception as exc:
                logger.error(f"Groq health check failed: {exc}")

        return health


llm_adapter = LLMAdapter()
