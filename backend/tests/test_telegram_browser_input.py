import unittest
import sys
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

sys.modules.setdefault("aiohttp", SimpleNamespace(FormData=object, ClientSession=object))

from app.services.browser_input_service import browser_input_service
from app.services.telegram_bot_service import TelegramBotService


class TelegramBrowserInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_browser_input_bypasses_normal_routing_gate(self):
        service = TelegramBotService()
        service._send_typing = AsyncMock()
        service._send_text_response = AsyncMock()
        service._create_forum_topic_if_possible = AsyncMock(return_value=None)
        service._send_screenshot = AsyncMock()
        service._should_process = Mock(return_value=False)

        orchestrator = Mock()
        orchestrator.process = AsyncMock(
            return_value={
                "output": "Browser task resumed.",
                "browser_input_state": {},
                "approval_state": {},
                "clarification_state": {},
                "metadata": {},
            }
        )
        service._get_orchestrator = Mock(return_value=orchestrator)

        pending = browser_input_service.create_request(
            desktop_request_id="desktop-request-1",
            user_id="telegram_42",
            conversation_id="telegram_-99",
            channel="telegram",
            field_description="GitHub password",
            input_type="password",
            reason="Login required",
        )
        self.addCleanup(browser_input_service.remove, pending.browser_input_id)

        message = {
            "message_id": 100,
            "text": "super-secret",
            "chat": {"id": -99, "type": "group"},
            "from": {"id": 42},
        }

        await service._process_message(message)

        service._should_process.assert_not_called()
        orchestrator.process.assert_awaited_once()
        kwargs = orchestrator.process.await_args.kwargs
        self.assertEqual(kwargs["user_message"], "super-secret")
        self.assertEqual(kwargs["conversation_id"], "telegram_-99")
        service._send_text_response.assert_awaited()


if __name__ == "__main__":
    unittest.main()
