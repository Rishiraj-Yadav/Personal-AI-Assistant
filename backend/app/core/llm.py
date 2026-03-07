"""
LLM Adapter with Model Failover
Primary: Groq (fast) → Fallback: Gemini (reliable)
Inspired by OpenClaw's model failover architecture.
"""
import os
from groq import AsyncGroq
from typing import List, Dict, Optional
from app.config import settings
from app.models import Message, MessageRole
from loguru import logger


class LLMAdapter:
    """LLM adapter with automatic failover: Groq → Gemini"""

    def __init__(self):
        """Initialize primary (Groq) and fallback (Gemini) clients"""
        # Primary: Groq
        self.groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.groq_model = settings.GROQ_MODEL
        self.max_tokens = settings.GROQ_MAX_TOKENS
        self.temperature = settings.GROQ_TEMPERATURE

        # Fallback: Gemini (via google-generativeai)
        self._gemini_model = None
        self._gemini_available = False
        try:
            import google.generativeai as genai
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if api_key:
                genai.configure(api_key=api_key)
                self._gemini_model = genai.GenerativeModel("gemini-2.5-flash")
                self._gemini_available = True
                logger.info("✅ Gemini fallback model configured")
        except Exception as e:
            logger.warning(f"⚠️ Gemini fallback not available: {e}")

        # Track consecutive failures for health monitoring
        self._groq_failures = 0
        self._max_failures_before_fallback = 2

        logger.info(f"Initialized LLM with model: {self.groq_model} (failover: {'Gemini' if self._gemini_available else 'none'})")

    # Keep backward compat property
    @property
    def model(self):
        return self.groq_model

    def _format_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        formatted = []
        for msg in messages:
            formatted.append({
                "role": msg.role.value,
                "content": msg.content
            })
        return formatted

    async def generate_response(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, any]:
        """Generate response with automatic failover"""
        # Try primary (Groq) first
        try:
            result = await self._call_groq(messages, tools, temperature, max_tokens)
            self._groq_failures = 0  # Reset on success
            return result
        except Exception as groq_err:
            self._groq_failures += 1
            logger.warning(f"⚠️ Groq failed ({self._groq_failures}x): {groq_err}")

            # Try Gemini fallback
            if self._gemini_available:
                try:
                    logger.info("🔄 Failing over to Gemini...")
                    result = await self._call_gemini(messages, max_tokens)
                    return result
                except Exception as gemini_err:
                    logger.error(f"❌ Gemini fallback also failed: {gemini_err}")
                    raise groq_err  # Raise the original error
            else:
                raise

    async def _call_groq(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, any]:
        """Call Groq API"""
        formatted_messages = self._format_messages(messages)

        if not any(msg["role"] == "system" for msg in formatted_messages):
            formatted_messages.insert(0, {
                "role": "system",
                "content": settings.SYSTEM_PROMPT
            })

        api_params = {
            "model": self.groq_model,
            "messages": formatted_messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "top_p": 1,
            "stream": False
        }

        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = "auto"

        response = await self.groq_client.chat.completions.create(**api_params)
        choice = response.choices[0]
        tokens_used = response.usage.total_tokens if response.usage else None

        result = {
            "model": self.groq_model,
            "provider": "groq",
            "tokens_used": tokens_used,
            "finish_reason": choice.finish_reason
        }

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            result["tool_calls"] = []
            for tool_call in choice.message.tool_calls:
                result["tool_calls"].append({
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })
            result["response"] = choice.message.content or ""
            logger.info(f"LLM requested {len(result['tool_calls'])} tool calls")
        else:
            result["response"] = choice.message.content
            logger.info(f"Groq response generated: {tokens_used} tokens used")

        return result

    async def _call_gemini(
        self,
        messages: List[Message],
        max_tokens: Optional[int] = None
    ) -> Dict[str, any]:
        """Call Gemini as fallback (sync wrapper)"""
        import asyncio

        # Build a single prompt from messages
        parts = []
        for msg in messages:
            prefix = {"system": "System", "user": "User", "assistant": "Assistant"}.get(msg.role.value, "User")
            parts.append(f"{prefix}: {msg.content}")
        prompt = "\n\n".join(parts)

        # Gemini SDK is synchronous, run in thread
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._gemini_model.generate_content(prompt)
        )

        text = response.text if response.text else ""
        logger.info(f"Gemini fallback response generated ({len(text)} chars)")

        return {
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "tokens_used": None,
            "finish_reason": "stop",
            "response": text
        }

    async def check_health(self) -> Dict[str, bool]:
        """Check health of all LLM providers"""
        health = {"groq": False, "gemini": self._gemini_available}

        try:
            test_messages = [{"role": "user", "content": "Hello"}]
            await self.groq_client.chat.completions.create(
                model=self.groq_model, messages=test_messages, max_tokens=5
            )
            health["groq"] = True
        except Exception as e:
            logger.error(f"Groq health check failed: {e}")

        return health


# Global LLM adapter instance (backward compatible name)
llm_adapter = LLMAdapter()