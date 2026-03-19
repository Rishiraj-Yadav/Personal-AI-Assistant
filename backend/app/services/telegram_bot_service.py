"""
Telegram Bot Service for SonarBot.

Feature parity with the previous chat integration:
- Private chat support
- Group/channel support with mention/reply targeting
- Thread-like isolation via forum topics when available
- Slash commands
- Long-response chunking
- Screenshot attachment forwarding
"""
import asyncio
import base64
import io
import os
import re
from typing import Optional

import aiohttp
from loguru import logger


class TelegramBotService:
    """Telegram bot that forwards messages to SonarBot's orchestrator."""

    def __init__(self):
        self.token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self._base_url: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._offset = 0
        self._orchestrator = None

        self.bot_id: Optional[int] = None
        self.bot_username: str = ""

        # Optional hard allow-list for channel/group IDs (comma-separated).
        raw_allowed_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
        self.allowed_chat_ids = {
            x.strip() for x in raw_allowed_ids.split(",") if x.strip()
        }
        # Friendly defaults for username/title-based routing in groups/channels.
        self.allowed_chat_names = {"sonarbot", "ai-assistant", "general"}

        # Tracks forum topics created by this bot to keep context isolation.
        self._owned_topics: set[tuple[int, int]] = set()

    def _get_orchestrator(self):
        """Lazy import to avoid circular imports."""
        if self._orchestrator is None:
            from app.agents.langgraph_orchestrator import langgraph_orchestrator

            self._orchestrator = langgraph_orchestrator
        return self._orchestrator

    async def _api_post(
        self,
        method: str,
        payload: Optional[dict] = None,
        form: Optional[aiohttp.FormData] = None,
    ) -> dict:
        """Call Telegram Bot API and return decoded JSON response."""
        if not self._session or not self._base_url:
            raise RuntimeError("Telegram client not initialized")

        url = f"{self._base_url}/{method}"
        kwargs = {}
        if form is not None:
            kwargs["data"] = form
        else:
            kwargs["json"] = payload or {}

        async with self._session.post(url, **kwargs) as resp:
            data = await resp.json(content_type=None)
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API {method} failed: {data}")
            return data.get("result", {})

    async def _send_typing(self, chat_id: int, thread_id: Optional[int] = None) -> None:
        payload = {"chat_id": chat_id, "action": "typing"}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        try:
            await self._api_post("sendChatAction", payload=payload)
        except Exception as e:
            logger.debug(f"sendChatAction failed: {e}")

    @staticmethod
    def _split_message(text: str, limit: int = 4096) -> list[str]:
        """Split long text into Telegram-safe chunks."""
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")
        return chunks

    def _clean_content(self, text: str) -> str:
        """Normalize mentions and command aliases for internal processing."""
        content = (text or "").strip()
        if not content:
            return ""

        if self.bot_username:
            # Strip mentions like @my_bot in plain text.
            mention_pat = re.compile(rf"@{re.escape(self.bot_username)}\b", re.IGNORECASE)
            content = mention_pat.sub("", content).strip()
            # Normalize commands like /status@my_bot -> /status.
            if content.startswith("/"):
                content = re.sub(
                    rf"^(/[\w_]+)@{re.escape(self.bot_username)}\b",
                    r"\1",
                    content,
                    flags=re.IGNORECASE,
                ).strip()

        return content

    def _should_process(self, msg: dict) -> bool:
        """Apply routing policy similar to the old chat integration."""
        chat = msg.get("chat", {}) or {}
        chat_type = chat.get("type", "")
        chat_id = str(chat.get("id", ""))

        # Private chats: always process.
        if chat_type == "private":
            return True

        # If explicitly allow-listed, process directly.
        if chat_id and chat_id in self.allowed_chat_ids:
            return True

        # Process all messages inside bot-owned forum topics.
        thread_id = msg.get("message_thread_id")
        if thread_id is not None:
            try:
                topic_key = (int(chat.get("id")), int(thread_id))
                if topic_key in self._owned_topics:
                    return True
            except Exception:
                pass

        # Mention-based trigger.
        text = msg.get("text") or msg.get("caption") or ""
        if self.bot_username and f"@{self.bot_username.lower()}" in text.lower():
            return True

        # Reply-to-bot trigger.
        reply = msg.get("reply_to_message") or {}
        reply_from = (reply.get("from") or {})
        if self.bot_id is not None and reply_from.get("id") == self.bot_id:
            return True

        # Name-based trigger for convenience in common channels/groups.
        chat_username = (chat.get("username") or "").lower()
        chat_title = (chat.get("title") or "").lower()
        if chat_username in self.allowed_chat_names or chat_title in self.allowed_chat_names:
            return True

        return False

    async def _create_forum_topic_if_possible(self, msg: dict, content: str) -> Optional[int]:
        """Create a forum topic for a new conversation if this chat supports it."""
        chat = msg.get("chat", {}) or {}
        if chat.get("type") != "supergroup" or not chat.get("is_forum"):
            return None

        # If already in a topic, keep current one.
        if msg.get("message_thread_id") is not None:
            return int(msg["message_thread_id"])

        chat_id = int(chat["id"])
        topic_name = content[:40] + ("..." if len(content) > 40 else "")
        topic_name = f"SonarBot {topic_name}".strip()
        try:
            topic = await self._api_post(
                "createForumTopic",
                payload={"chat_id": chat_id, "name": topic_name},
            )
            thread_id = int(topic["message_thread_id"])
            self._owned_topics.add((chat_id, thread_id))
            logger.info(f"Created Telegram forum topic '{topic_name}' in chat {chat_id}")
            return thread_id
        except Exception as e:
            logger.warning(f"Forum topic creation failed; falling back to normal reply: {e}")
            return None

    async def _send_text_response(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        thread_id: Optional[int] = None,
    ) -> None:
        for chunk in self._split_message(text):
            payload = {"chat_id": chat_id, "text": chunk}
            if thread_id is not None:
                payload["message_thread_id"] = thread_id
            elif reply_to_message_id is not None:
                payload["reply_to_message_id"] = reply_to_message_id
            await self._api_post("sendMessage", payload=payload)

    async def _send_screenshot(
        self,
        chat_id: int,
        screenshot_b64: str,
        reply_to_message_id: Optional[int] = None,
        thread_id: Optional[int] = None,
    ) -> None:
        img_bytes = base64.b64decode(screenshot_b64)
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if thread_id is not None:
            form.add_field("message_thread_id", str(thread_id))
        elif reply_to_message_id is not None:
            form.add_field("reply_to_message_id", str(reply_to_message_id))
        form.add_field("caption", "Virtual Desktop Screenshot:")
        form.add_field(
            "photo",
            io.BytesIO(img_bytes),
            filename="screenshot.png",
            content_type="image/png",
        )
        await self._api_post("sendPhoto", form=form)

    async def _process_message(self, msg: dict) -> None:
        if not self._should_process(msg):
            return

        text = msg.get("text") or msg.get("caption") or ""
        content = self._clean_content(text)
        if not content:
            return

        chat = msg.get("chat", {}) or {}
        chat_id = int(chat["id"])
        message_id = int(msg["message_id"])
        from_user = msg.get("from") or {}
        sender_chat = msg.get("sender_chat") or {}
        user_id_numeric = from_user.get("id") or sender_chat.get("id") or chat_id
        user_id = f"telegram_{user_id_numeric}"

        logger.info(f"Telegram message from {user_id_numeric}: {content[:50]}...")

        # Conversation routing
        thread_id = msg.get("message_thread_id")
        if thread_id is not None:
            thread_id = int(thread_id)
            conversation_id = f"telegram_thread_{chat_id}_{thread_id}"
        elif chat.get("type") == "private":
            conversation_id = f"telegram_dm_{chat_id}"
        else:
            created_thread_id = await self._create_forum_topic_if_possible(msg, content)
            if created_thread_id is not None:
                thread_id = created_thread_id
                conversation_id = f"telegram_thread_{chat_id}_{thread_id}"
            else:
                conversation_id = f"telegram_{chat_id}"

        await self._send_typing(chat_id=chat_id, thread_id=thread_id)

        try:
            from app.services.slash_command_service import slash_command_service

            if slash_command_service.is_slash_command(content):
                result = await slash_command_service.execute(
                    message=content,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                response_text = result.get("response", "Command executed.")
            else:
                orchestrator = self._get_orchestrator()
                result = await orchestrator.process(
                    user_message=content,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    max_iterations=3,
                )
                response_text = result.get("output", "I couldn't generate a response.")

            screenshot_b64 = None
            if isinstance(result, dict):
                meta = result.get("metadata", {}) or {}
                screenshot_b64 = meta.get("screenshot_base64")

            await self._send_text_response(
                chat_id=chat_id,
                text=response_text,
                reply_to_message_id=message_id,
                thread_id=thread_id,
            )

            if screenshot_b64:
                await self._send_screenshot(
                    chat_id=chat_id,
                    screenshot_b64=screenshot_b64,
                    reply_to_message_id=message_id,
                    thread_id=thread_id,
                )
        except Exception as e:
            logger.error(f"Telegram processing error: {e}")
            error_msg = f"Sorry, I encountered an error: {str(e)[:200]}"
            await self._send_text_response(
                chat_id=chat_id,
                text=error_msg,
                reply_to_message_id=message_id,
                thread_id=thread_id,
            )

    async def start(self):
        """Start long-polling loop if token is configured."""
        if not self.token:
            logger.info("Telegram bot skipped (no TELEGRAM_BOT_TOKEN set)")
            return
        if self._running:
            return

        self._base_url = f"https://api.telegram.org/bot{self.token}"
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40))
        self._running = True

        try:
            me = await self._api_post("getMe", payload={})
            self.bot_id = me.get("id")
            self.bot_username = (me.get("username") or "").strip()
            logger.info(f"Telegram bot connected as @{self.bot_username}")
        except Exception as e:
            logger.error(f"Invalid Telegram bot token or getMe failure: {e}")
            self._running = False
            await self._session.close()
            self._session = None
            return

        logger.info("Starting Telegram bot polling...")
        while self._running:
            try:
                updates = await self._api_post(
                    "getUpdates",
                    payload={
                        "offset": self._offset + 1,
                        "timeout": 30,
                        "allowed_updates": ["message", "channel_post"],
                    },
                )
                for upd in updates or []:
                    self._offset = max(self._offset, int(upd.get("update_id", 0)))
                    msg = upd.get("message") or upd.get("channel_post")
                    if msg:
                        await self._process_message(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
                await asyncio.sleep(3)

    async def stop(self):
        """Gracefully stop polling and close HTTP session."""
        if not self._running:
            return
        logger.info("Stopping Telegram bot...")
        self._running = False
        if self._session:
            await self._session.close()
            self._session = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_configured(self) -> bool:
        return bool(self.token)


telegram_bot_service = TelegramBotService()

