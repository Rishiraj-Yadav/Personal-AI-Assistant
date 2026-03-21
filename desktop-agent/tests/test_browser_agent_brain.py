from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_brain import AgentBrain  # noqa: E402


class AgentBrainBrowserStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brain = AgentBrain.__new__(AgentBrain)
        self.brain._histories = {}
        self.brain._browser_states = {}
        self.brain._browser_visual_state = {}
        self.brain._pending_input_states = {}
        self.brain._pending_clarification = None
        self.brain._max_history = 20

    def test_non_browser_tools_do_not_overwrite_browser_title(self) -> None:
        self.brain._update_browser_state_from_result(
            "open_browser",
            {
                "result": {
                    "url": "https://www.google.com/search?q=OpenAI",
                    "title": "OpenAI - Google Search",
                    "visible_text": "OpenAI result page",
                },
                "observed_state": {
                    "is_open": True,
                    "profile": "openclaw",
                    "driver": "managed",
                    "transport": "managed-playwright",
                    "current_url": "https://www.google.com/search?q=OpenAI",
                    "current_title": "OpenAI - Google Search",
                    "tab_id": "tab-1",
                    "last_action_summary": "press",
                },
            },
            "brain-test",
        )
        self.brain._update_browser_state_from_result(
            "get_active_window",
            {
                "result": {"title": "OpenAI - Google Search - Google Chrome"},
                "observed_state": {"title": "OpenAI - Google Search - Google Chrome", "id": 123},
            },
            "brain-test",
        )

        state = self.brain._get_browser_state("brain-test")
        self.assertEqual(state["current_title"], "OpenAI - Google Search")
        self.assertEqual(state["current_url"], "https://www.google.com/search?q=OpenAI")
        self.assertEqual(state["last_observation_excerpt"], "OpenAI result page")

    def test_last_action_summary_tracks_browser_tools_only(self) -> None:
        actions_taken = [
            {"tool": "open_browser"},
            {"tool": "browser_press_key"},
            {"tool": "get_active_window"},
        ]

        self.brain._update_last_browser_action_summary("brain-summary", actions_taken)

        state = self.brain._get_browser_state("brain-summary")
        self.assertEqual(state["last_action_summary"], "open_browser; browser_press_key")

    def test_browser_context_prefix_includes_recent_visible_content(self) -> None:
        state = self.brain._get_browser_state("brain-context")
        state.update(
            {
                "is_open": True,
                "current_url": "https://example.com",
                "current_title": "Example",
                "last_observation_excerpt": "Leaderboard refreshed with Monkeytype words.",
            }
        )

        prefix = self.brain._get_browser_context_prefix("brain-context")

        self.assertIn("Recent visible content:", prefix)
        self.assertIn("Monkeytype words", prefix)

    def test_infer_resume_prompt_for_short_browser_answer(self) -> None:
        state = self.brain._get_browser_state("brain-resume")
        state["is_open"] = True
        self.brain._histories["brain-resume"] = [
            {"role": "user", "content": "Search for nickhasntlost profile"},
            {
                "role": "assistant",
                "content": "Can you describe the search bar's appearance and location on the GitHub page based on the screenshot?",
            },
        ]

        resume = self.brain._infer_resume_prompt_from_recent_browser_question(
            "brain-resume",
            "You have an input field type box there",
        )

        self.assertIsNotNone(resume)
        self.assertIn("Search for nickhasntlost profile", resume)
        self.assertIn("You have an input field type box there", resume)

    def test_should_convert_browser_text_to_clarification(self) -> None:
        state = self.brain._get_browser_state("brain-question")
        state["is_open"] = True

        should_convert = self.brain._should_convert_browser_text_to_clarification(
            final_text="Can you describe the search bar in the screenshot for me?",
            session_id="brain-question",
            actions_taken=[{"tool": "open_browser"}, {"tool": "browser_screenshot"}],
        )

        self.assertTrue(should_convert)

    def test_build_tool_feedback_parts_attaches_browser_observation(self) -> None:
        with mock.patch.object(
            self.brain,
            "_capture_browser_observation",
            return_value={
                "url": "https://example.com",
                "title": "Example",
                "visible_text": "Example page text",
                "observation_mode": "dom+ocr",
                "image_base64": "ZmFrZQ==",
            },
        ), mock.patch.object(
            self.brain,
            "_prepare_inline_image_part",
            return_value="image-part",
        ):
            parts = self.brain._build_tool_feedback_parts(
                tool_name="browser_click",
                tool_args={"session_id": "brain-visual"},
                result={"success": True, "result": {"url": "https://example.com"}},
                session_id="brain-visual",
            )

        self.assertEqual(len(parts), 3)
        self.assertIn("Browser observation after the last action", parts[1].text)
        self.assertEqual(parts[2], "image-part")


if __name__ == "__main__":
    unittest.main()
