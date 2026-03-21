from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.browser_agent import BrowserAgent  # noqa: E402


class BrowserAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = BrowserAgent()

    def test_browser_request_user_input_returns_expected_signal(self) -> None:
        result = self.agent.execute(
            "browser_request_user_input",
            {"field_description": "gmail password", "reason": "login", "input_type": "password"},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "user_input_required")
        self.assertEqual(result["observed_state"]["field_description"], "gmail password")

    def test_browser_alias_for_status_uses_canonical_browser_tool(self) -> None:
        with mock.patch("agents.browser_agent.browser_service.execute", return_value={"success": True, "result": {}}) as execute:
            self.agent.execute("browser", {"command": "status"})
        execute.assert_called_once()
        command = execute.call_args.args[0]
        self.assertEqual(command.command, "status")
        self.assertEqual(command.profile, "openclaw")
        self.assertEqual(command.session_id, "default")

    def test_open_browser_calls_status_then_start_then_navigate(self) -> None:
        with mock.patch(
            "agents.browser_agent.browser_service.execute",
            side_effect=[
                {"success": True, "result": {"running": False}},
                {"success": True, "result": {"running": True}},
                {"success": True, "result": {"url": "https://example.com"}},
            ],
        ) as execute:
            result = self.agent.execute("open_browser", {"url": "https://example.com", "session_id": "abc"})
        self.assertTrue(result["success"])
        self.assertEqual(execute.call_count, 3)
        status = execute.call_args_list[0].args[0]
        first = execute.call_args_list[1].args[0]
        second = execute.call_args_list[2].args[0]
        self.assertEqual(status.command, "status")
        self.assertEqual(first.command, "start")
        self.assertEqual(second.command, "navigate")
        self.assertEqual(second.url, "https://example.com")

    def test_open_browser_uses_new_tab_when_browser_is_running(self) -> None:
        with mock.patch(
            "agents.browser_agent.browser_service.execute",
            side_effect=[
                {"success": True, "result": {"running": True}},
                {"success": True, "result": {"url": "https://github.com"}},
            ],
        ) as execute:
            result = self.agent.execute("open_browser", {"url": "https://github.com", "session_id": "abc"})

        self.assertTrue(result["success"])
        self.assertEqual(execute.call_count, 2)
        status = execute.call_args_list[0].args[0]
        new_tab = execute.call_args_list[1].args[0]
        self.assertEqual(status.command, "status")
        self.assertEqual(new_tab.command, "tab_new")
        self.assertEqual(new_tab.url, "https://github.com")

    def test_browser_click_prefers_ref_then_selector_then_text(self) -> None:
        with mock.patch("agents.browser_agent.browser_service.execute", return_value={"success": True, "result": {}}) as execute:
            self.agent.execute("browser_click", {"ref": "1"})
            self.agent.execute("browser_click", {"selector": "#submit"})
            self.agent.execute("browser_click", {"text": "Submit"})

        commands = [call.args[0].command for call in execute.call_args_list]
        self.assertEqual(commands, ["click", "compat_click_selector", "compat_find_by_text"])

    def test_browser_commands_run_on_dedicated_thread(self) -> None:
        main_thread = threading.get_ident()
        executed_threads: list[int] = []

        def side_effect(command):
            executed_threads.append(threading.get_ident())
            return {"success": True, "result": {"command": command.command}}

        with mock.patch("agents.browser_agent.browser_service.execute", side_effect=side_effect):
            self.agent.execute("browser", {"command": "status"})
            self.agent.execute("browser", {"command": "status"})

        self.assertEqual(len(executed_threads), 2)
        self.assertNotEqual(executed_threads[0], main_thread)
        self.assertEqual(executed_threads[0], executed_threads[1])

    def test_browser_find_and_click_filters_unknown_description_field(self) -> None:
        with mock.patch("agents.browser_agent.browser_service.execute", return_value={"success": True, "result": {}}) as execute:
            self.agent.execute(
                "browser_find_and_click",
                {"description": "Search or jump to...", "session_id": "abc"},
            )

        command = execute.call_args.args[0]
        self.assertEqual(command.command, "compat_find_by_text")
        self.assertEqual(command.text, "Search or jump to...")
