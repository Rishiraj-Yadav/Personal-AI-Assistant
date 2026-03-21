import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services.web_agent_service import WebAgentSession, WebAgentService


class WebAgentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_headless_launch_does_not_include_no_sandbox(self):
        fake_page = AsyncMock()
        fake_context = AsyncMock()
        fake_context.new_page = AsyncMock(return_value=fake_page)
        fake_browser = AsyncMock()
        fake_browser.new_context = AsyncMock(return_value=fake_context)
        fake_playwright = Mock()
        fake_playwright.chromium.launch = AsyncMock(return_value=fake_browser)
        fake_manager = Mock()
        fake_manager.start = AsyncMock(return_value=fake_playwright)

        with patch("app.services.web_agent_service.async_playwright", return_value=fake_manager):
            session = WebAgentSession("user-1")
            await session.start()

        launch_args = fake_playwright.chromium.launch.call_args.kwargs["args"]
        self.assertNotIn("--no-sandbox", launch_args)

    async def test_decide_next_action_attaches_latest_screenshot_metadata(self):
        service = WebAgentService()
        llm = Mock()
        llm.generate_response = AsyncMock(return_value={"response": '{"type":"done","summary":"Finished"}'})

        action = await service._decide_next_action(
            llm,
            user_message="Search for openclaw",
            page_info={"title": "Search", "url": "https://example.com", "visibleText": "openclaw results"},
            actions_taken=[],
            step=1,
            plan={"explanation": "Search for openclaw"},
            screenshot_base64="ZmFrZQ==",
        )

        self.assertEqual(action["type"], "done")
        messages = llm.generate_response.call_args.args[0]
        self.assertEqual(messages[-1].metadata["images"][0]["image_base64"], "ZmFrZQ==")


if __name__ == "__main__":
    unittest.main()
