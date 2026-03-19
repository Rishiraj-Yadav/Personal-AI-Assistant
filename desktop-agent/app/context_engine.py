"""
Context Engine
Manages conversation history, token limits, and short-term memory logic
for the desktop agent, allowing the Router and Agent Brain to remain lean.
"""
from typing import List, Dict, Any
import google.generativeai as genai
from loguru import logger

class ContextEngine:
    def __init__(self, max_history: int = 20):
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history
        logger.info(f"🧠 Context Engine initialized (Max history: {self._max_history})")

    def add_message(self, role: str, content: str):
        """Append a message to the short-term context and prune if necessary."""
        self._history.append({"role": role, "content": content})
        self._prune_history()

    def _prune_history(self):
        """Ensure the history does not exceed the maximum allowed messages."""
        if len(self._history) > self._max_history * 2:
            logger.debug(f"Pruning context history from {len(self._history)} to {self._max_history}")
            self._history = self._history[-self._max_history:]
            
            # Gemini strictly requires the history to start with a "user" message
            if self._history and self._history[0]["role"] != "user":
                self._history.pop(0)

    def get_gemini_history(self) -> list:
        """Convert the internal history to Gemini's expected protobuf format."""
        gemini_history = []
        for msg in self._history:
            # Map "assistant" to "model" for Gemini compatibility
            role = "model" if msg["role"] == "assistant" else msg["role"]
            gemini_history.append(
                genai.protos.Content(
                    role=role,
                    parts=[genai.protos.Part(text=msg["content"])],
                )
            )
        return gemini_history

    def get_raw_history(self) -> List[Dict[str, Any]]:
        """Return the raw history dictionary."""
        return self._history.copy()

    def clear(self):
        """Clear all short-term context."""
        self._history.clear()
        logger.info("🧠 Context Engine history cleared")

    def inject_long_term_memory(self, query: str) -> str:
        """
        Stub for RAG injection. In the future, this will query Qdrant
        and inject relevant past context into the prompt dynamically.
        """
        # TODO: Integrate Qdrant vector search here
        return ""
