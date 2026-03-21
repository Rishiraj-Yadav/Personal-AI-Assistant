from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import desktop_agent  # noqa: E402


class DesktopAgentUserInputApiTests(unittest.TestCase):
    def setUp(self) -> None:
        asyncio.run(desktop_agent.pending_input_store.clear())
        desktop_agent.brain.clear_history()

    def test_execute_nl_exposes_user_input_request(self) -> None:
        pause_result = {
            "response": "Please provide your GitHub password.",
            "actions_taken": [{"tool": "browser_request_user_input", "success": False}],
            "success": False,
            "browser_state": {"is_open": True, "current_url": "https://github.com/login"},
            "requires_clarification": False,
            "user_input_required": True,
            "pending_input": {
                "session_id": "login-session",
                "field_description": "GitHub password",
                "input_type": "password",
                "reason": "login",
            },
        }

        with patch.object(
            desktop_agent.brain,
            "process_command",
            AsyncMock(return_value=pause_result),
        ) as process_command:
            data = asyncio.run(
                desktop_agent.execute_natural_language(
                    desktop_agent.NLCommandRequest(
                        command="log in to GitHub",
                        session_id="login-session",
                    ),
                    api_key=desktop_agent.settings.API_KEY,
                )
            )

        self.assertTrue(data["user_input_required"])
        self.assertFalse(data["requires_clarification"])
        self.assertEqual(data["question"], "")
        self.assertEqual(data["input_request"]["field_description"], "GitHub password")
        self.assertEqual(data["input_request"]["input_type"], "password")
        self.assertEqual(data["input_request"]["reason"], "login")
        self.assertEqual(data["input_request"]["session_id"], "login-session")
        self.assertTrue(data["input_request"]["request_id"])
        process_command.assert_awaited_once_with(
            "log in to GitHub",
            session_id="login-session",
            context=None,
        )

        pending = asyncio.run(
            desktop_agent.get_pending_input(
                data["input_request"]["request_id"],
                api_key=desktop_agent.settings.API_KEY,
            )
        )
        self.assertEqual(pending["session_id"], "login-session")
        self.assertEqual(pending["field_description"], "GitHub password")

    def test_provide_input_resumes_same_session(self) -> None:
        request_id = asyncio.run(
            desktop_agent.pending_input_store.create(
                session_id="resume-session",
                field_description="GitHub password",
                input_type="password",
                reason="login",
            )
        )
        resumed_result = {
            "response": "Signed in successfully.",
            "actions_taken": [{"tool": "browser_type", "success": True}],
            "success": True,
            "browser_state": {
                "is_open": True,
                "current_url": "https://github.com/dashboard",
                "current_title": "Dashboard",
            },
            "requires_clarification": False,
            "user_input_required": False,
        }

        with patch.object(
            desktop_agent.brain,
            "process_command",
            AsyncMock(return_value=resumed_result),
        ) as process_command:
            data = asyncio.run(
                desktop_agent.provide_user_input(
                    desktop_agent.ProvideInputRequest(
                        request_id=request_id,
                        value="super-secret",
                    ),
                    api_key=desktop_agent.settings.API_KEY,
                )
            )
        self.assertEqual(data["request_id"], request_id)
        self.assertEqual(data["response"], "Signed in successfully.")
        self.assertTrue(data["success"])
        self.assertFalse(data["user_input_required"])
        self.assertNotIn("input_request", data)
        process_command.assert_awaited_once_with(
            "super-secret",
            session_id="resume-session",
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                desktop_agent.get_pending_input(
                    request_id,
                    api_key=desktop_agent.settings.API_KEY,
                )
            )
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
