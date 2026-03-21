from __future__ import annotations

import types
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP_ROOT = PROJECT_ROOT / "backend" / "app"
if str(BACKEND_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_APP_ROOT))

if "aiohttp" not in sys.modules:
    fake_aiohttp = types.ModuleType("aiohttp")

    class _ClientConnectorError(Exception):
        pass

    class _ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _ClientSessionPlaceholder:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("aiohttp ClientSession should be patched in tests")

    fake_aiohttp.ClientConnectorError = _ClientConnectorError
    fake_aiohttp.ClientTimeout = _ClientTimeout
    fake_aiohttp.ClientSession = _ClientSessionPlaceholder
    sys.modules["aiohttp"] = fake_aiohttp

from skills.desktop_bridge import DesktopBridgeSkill  # noqa: E402


class _FakeResponse:
    def __init__(self, status: int, payload=None, text: str = "") -> None:
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class _FakeSession:
    def __init__(self, response: _FakeResponse, timeout=None) -> None:
        self._response = response
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json, headers):
        return self._response


class _BridgeUnderTest(DesktopBridgeSkill):
    def __init__(self, resumed_result):
        self.desktop_agent_url = "http://desktop-agent.test"
        self._api_key_paths = []
        self.timeout = None
        self._capabilities_logged = True
        self._canonical_tools_logged = set()
        self._required_tools = set()
        self._resumed_result = resumed_result
        self.provided = None

    def _get_api_key(self) -> str:
        return "test-api-key"

    async def provide_input(self, request_id: str, value: str):
        self.provided = (request_id, value)
        return self._resumed_result


class DesktopBridgeUserInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_nl_command_resumes_after_user_input_callback(self) -> None:
        paused_result = {
            "success": False,
            "response": "Please provide your GitHub password.",
            "actions_taken": [{"tool": "browser_request_user_input", "success": False}],
            "user_input_required": True,
            "input_request": {
                "request_id": "req-123",
                "session_id": "bridge-session",
                "field_description": "GitHub password",
                "input_type": "password",
                "reason": "login",
            },
            "browser_state": {"is_open": True},
            "requires_clarification": False,
            "question": "",
            "options": [],
        }
        resumed_result = {
            "success": True,
            "response": "Signed in successfully.",
            "actions_taken": [{"tool": "browser_type", "success": True}],
            "user_input_required": False,
            "browser_state": {"is_open": True, "current_title": "Dashboard"},
            "requires_clarification": False,
            "question": "",
            "options": [],
        }
        bridge = _BridgeUnderTest(resumed_result=resumed_result)
        seen_requests = []

        async def user_input_callback(input_request):
            seen_requests.append(input_request)
            return "super-secret"

        with patch(
            "skills.desktop_bridge.aiohttp.ClientSession",
            side_effect=lambda timeout=None: _FakeSession(
                _FakeResponse(status=200, payload=paused_result),
                timeout=timeout,
            ),
        ):
            result = await bridge.execute_nl_command(
                "Log in to GitHub",
                user_input_callback=user_input_callback,
                session_id="bridge-session",
            )

        self.assertEqual(seen_requests[0]["field_description"], "GitHub password")
        self.assertEqual(bridge.provided, ("req-123", "super-secret"))
        self.assertTrue(result["success"])
        self.assertEqual(result["response"], "Signed in successfully.")
        self.assertFalse(result["user_input_required"])
        self.assertEqual(result["browser_state"]["current_title"], "Dashboard")


if __name__ == "__main__":
    unittest.main()
