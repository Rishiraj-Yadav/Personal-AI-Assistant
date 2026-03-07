"""
Context Compaction Service - Summarizes old conversation messages to save tokens.
Inspired by OpenClaw's /compact command.
"""
from typing import Dict, Any
from loguru import logger
from datetime import datetime, timezone

from app.core.llm import llm_adapter
from app.models import Message, MessageRole
from app.services.enhanced_memory_service import enhanced_memory_service


class ContextCompactionService:
    """Compacts long conversations by summarizing older messages"""

    # Keep the last N messages verbatim; summarize everything before
    KEEP_RECENT = 6
    MIN_MESSAGES_TO_COMPACT = 10  # Don't compact if < 10 messages

    async def compact_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> Dict[str, Any]:
        """
        Compact a conversation:
        1. Load full history
        2. If long enough, summarize older messages via LLM
        3. Delete old messages from DB
        4. Insert a single summary message
        """
        history = enhanced_memory_service.get_conversation_history(
            conversation_id, limit=1000
        )

        if not history or len(history) < self.MIN_MESSAGES_TO_COMPACT:
            return {
                "compacted": False,
                "message": f"📝 Conversation has only {len(history) if history else 0} messages. "
                           f"Need at least {self.MIN_MESSAGES_TO_COMPACT} to compact.",
                "before": len(history) if history else 0,
                "after": len(history) if history else 0,
            }

        # Split: old messages to summarize, recent to keep
        old_messages = history[:-self.KEEP_RECENT]
        recent_messages = history[-self.KEEP_RECENT:]

        # Build text of old messages for summarization
        old_text_parts = []
        for msg in old_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            old_text_parts.append(f"{role}: {content}")

        old_text = "\n".join(old_text_parts)

        # Summarize via LLM
        summary = await self._summarize(old_text, len(old_messages))

        # Delete old messages from SQL DB
        self._delete_old_messages(conversation_id, len(old_messages))

        # Insert the summary as a system/assistant message at the start
        enhanced_memory_service.save_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=f"📋 **Conversation Summary (compacted {len(old_messages)} messages):**\n\n{summary}",
            metadata={"compacted": True, "original_count": len(old_messages)},
        )

        after_count = 1 + len(recent_messages)  # summary + recent

        return {
            "compacted": True,
            "message": (
                f"✅ **Conversation Compacted!**\n\n"
                f"**Before:** {len(history)} messages\n"
                f"**Summarized:** {len(old_messages)} older messages into 1 summary\n"
                f"**After:** {after_count} messages\n\n"
                f"Your recent messages are preserved. Older context is now a summary."
            ),
            "before": len(history),
            "after": after_count,
            "summarized": len(old_messages),
        }

    async def _summarize(self, conversation_text: str, msg_count: int) -> str:
        """Use LLM to summarize conversation history"""
        # Truncate if absurdly long
        if len(conversation_text) > 8000:
            conversation_text = conversation_text[:8000] + "\n...(truncated)"

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a conversation summarizer. Create a concise but comprehensive summary "
                    "of the following conversation. Preserve:\n"
                    "- Key decisions and outcomes\n"
                    "- Important facts mentioned (names, dates, preferences)\n"
                    "- Tasks completed or in progress\n"
                    "- Any errors or issues encountered\n\n"
                    "Keep the summary to 3-5 bullet points. Be specific, not vague."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=f"Summarize these {msg_count} messages:\n\n{conversation_text}",
            ),
        ]

        try:
            result = await llm_adapter.generate_response(messages, max_tokens=512)
            return result.get("response", "Summary unavailable.")
        except Exception as e:
            logger.error(f"❌ Summarization failed: {e}")
            return f"(Auto-summary failed: {e}. {msg_count} messages were compacted.)"

    def _delete_old_messages(self, conversation_id: str, count: int):
        """Delete the oldest N messages from SQL for this conversation"""
        from app.database.base import SessionLocal
        from app.database.models import Message as DBMessage

        session = SessionLocal()
        try:
            old_msgs = (
                session.query(DBMessage)
                .filter_by(conversation_id=conversation_id)
                .order_by(DBMessage.created_at.asc())
                .limit(count)
                .all()
            )
            for msg in old_msgs:
                session.delete(msg)
            session.commit()
            logger.info(f"🗑️ Deleted {len(old_msgs)} old messages from conversation {conversation_id}")
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error deleting old messages: {e}")
        finally:
            session.close()


context_compaction_service = ContextCompactionService()
