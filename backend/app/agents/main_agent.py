"""
Main Agent — Top-level orchestration layer.

Responsibilities:
  1. Pre-processing  — enrich user message with context (time, history).
  2. Delegation      — call the AssistantAgent to classify and execute.
  3. Validation      — review raw specialist output using Gemini Flash
                       and produce a polished, user-friendly response.
  4. Structured logs — emit {agent, success, latency_ms, task_type} on every request.
"""

import os
import time
import asyncio
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timezone
from loguru import logger
import google.generativeai as genai

from app.agents.multi_agent_orchestrator import orchestrator as assistant_agent


class MainAgent:
    """
    The Main Agent sits above the Assistant (orchestrator).
    It receives user input, delegates to the Assistant, validates
    the specialist output, and returns a clean response.
    """

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if api_key:
            genai.configure(api_key=api_key)
            self.validator_model = genai.GenerativeModel("gemini-2.0-flash")
            self._validator_available = True
            logger.info("✅ Main Agent initialized with Gemini Flash validator")
        else:
            self._validator_available = False
            logger.warning("⚠️ Main Agent: No GOOGLE_API_KEY — validation disabled")

    # ─── PUBLIC API ───────────────────────────────────────────────

    async def process(
        self,
        user_message: str,
        conversation_id: Optional[str] = None,
        max_iterations: int = 5,
        message_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Full Main Agent pipeline:
        1. Pre-process (add context)
        2. Delegate to Assistant
        3. Validate output
        4. Emit structured log
        """
        start_time = time.time()

        # ── 1. PRE-PROCESSING ────────────────────────────────────
        context = self._build_context(user_message)

        if message_callback:
            await message_callback({
                "type": "status",
                "message": "🧠 Main Agent received your request..."
            })

        # ── 2. DELEGATE TO ASSISTANT ─────────────────────────────
        try:
            raw_result = await assistant_agent.process(
                user_message=user_message,
                conversation_id=conversation_id,
                max_iterations=max_iterations,
                message_callback=message_callback,
            )
        except asyncio.TimeoutError:
            raw_result = self._timeout_fallback(user_message, context)
        except Exception as e:
            logger.error(f"❌ Assistant error: {e}")
            raw_result = self._error_fallback(user_message, str(e))

        # ── 3. VALIDATE OUTPUT ───────────────────────────────────
        validated_output = await self._validate(
            user_message=user_message,
            raw_result=raw_result,
            context=context,
            message_callback=message_callback,
        )

        # Merge validated output back in
        raw_result["output"] = validated_output
        raw_result["validated"] = True

        # ── 4. STRUCTURED LOG ────────────────────────────────────
        latency_ms = round((time.time() - start_time) * 1000)
        self._emit_structured_log(raw_result, latency_ms)

        return raw_result

    # ─── PRE-PROCESSING ──────────────────────────────────────────

    def _build_context(self, user_message: str) -> Dict[str, Any]:
        """Enrich request with system context."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message_length": len(user_message),
        }

    # ─── VALIDATION ──────────────────────────────────────────────

    async def _validate(
        self,
        user_message: str,
        raw_result: Dict[str, Any],
        context: Dict[str, Any],
        message_callback: Optional[Callable] = None,
    ) -> str:
        """
        Use Gemini Flash to review the specialist output and
        produce a polished, concise, user-friendly summary.
        Falls back to raw output if validator is unavailable.
        """
        raw_output = raw_result.get("output", "")
        success = raw_result.get("success", False)
        task_type = raw_result.get("task_type", "unknown")
        agent_path = raw_result.get("agent_path", [])
        error = raw_result.get("error")

        # Skip validation if no validator or very short output
        if not self._validator_available or len(str(raw_output)) < 20:
            return raw_output

        if message_callback:
            await message_callback({
                "type": "status",
                "message": "🔍 Main Agent validating output..."
            })

        validation_prompt = f"""You are a quality-assurance validator for an AI assistant.

The user asked: "{user_message}"

The specialist agent ({', '.join(agent_path)}) returned this result:
- Task type: {task_type}
- Success: {success}
- Output: {raw_output}
{f'- Error: {error}' if error else ''}

Your job:
1. If SUCCESS: Write a concise, friendly summary of what was accomplished. Keep it under 3 sentences. Include any important details (URLs, file paths, etc).
2. If FAILED: Explain what went wrong in plain language. Suggest what the user could try next.
3. Never mention internal agent names or technical routing details.
4. Be conversational and helpful, like a smart assistant.

Write your validated response now:"""

        try:
            response = self.validator_model.generate_content(validation_prompt)
            validated = response.text.strip()
            logger.info(f"✅ Validation complete ({len(validated)} chars)")
            return validated
        except Exception as e:
            logger.warning(f"⚠️ Validation failed, using raw output: {e}")
            return raw_output

    # ─── FALLBACKS ───────────────────────────────────────────────

    def _timeout_fallback(self, user_message: str, context: Dict) -> Dict[str, Any]:
        """Return a clean error when a specialist times out."""
        return {
            "success": False,
            "task_type": "timeout",
            "confidence": 0.0,
            "output": (
                "⏳ The specialist agent took too long to respond (>30s). "
                "This usually means the browser or desktop agent is busy or unreachable. "
                "Please try again in a moment."
            ),
            "agent_path": ["main_agent", "timeout"],
            "error": "Specialist timeout",
            "metadata": {"context": context},
        }

    def _error_fallback(self, user_message: str, error_msg: str) -> Dict[str, Any]:
        """Return a clean error when the assistant crashes."""
        return {
            "success": False,
            "task_type": "error",
            "confidence": 0.0,
            "output": f"❌ Something went wrong while processing your request: {error_msg}",
            "agent_path": ["main_agent", "error"],
            "error": error_msg,
            "metadata": {},
        }

    # ─── STRUCTURED LOGGING ──────────────────────────────────────

    def _emit_structured_log(self, result: Dict[str, Any], latency_ms: int):
        """Emit a structured log line for observability."""
        log_entry = {
            "agent": "main_agent",
            "task_type": result.get("task_type", "unknown"),
            "success": result.get("success", False),
            "latency_ms": latency_ms,
            "agent_path": result.get("agent_path", []),
            "validated": result.get("validated", False),
            "error": result.get("error"),
        }
        if result.get("success"):
            logger.info(f"📊 {log_entry}")
        else:
            logger.warning(f"📊 {log_entry}")


# Global instance
main_agent = MainAgent()
