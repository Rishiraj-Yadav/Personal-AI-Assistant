from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from browser_runtime.service import BrowserCommand, BrowserService  # noqa: E402


class FakeCandidate:
    def __init__(self, name: str, visible: bool):
        self.name = name
        self._visible = visible

    def is_visible(self) -> bool:
        return self._visible


class FakeLocatorGroup:
    def __init__(self, candidates: list[FakeCandidate]):
        self._candidates = candidates

    def count(self) -> int:
        return len(self._candidates)

    def nth(self, index: int) -> FakeCandidate:
        return self._candidates[index]

    @property
    def first(self) -> FakeCandidate:
        return self._candidates[0]


class FakePage:
    def __init__(self, locators: dict[str, FakeLocatorGroup]):
        self._locators = locators

    def locator(self, selector: str) -> FakeLocatorGroup:
        return self._locators.get(selector, FakeLocatorGroup([]))

    def get_by_label(self, label: str) -> FakeLocatorGroup:
        return self._locators.get(f"label:{label}", FakeLocatorGroup([]))

    def get_by_placeholder(self, placeholder: str) -> FakeLocatorGroup:
        return self._locators.get(f"placeholder:{placeholder}", FakeLocatorGroup([]))

    def get_by_role(self, role: str, name: str) -> FakeLocatorGroup:
        return self._locators.get(f"role:{role}:{name}", FakeLocatorGroup([]))

    def get_by_text(self, text: str, exact: bool = False) -> FakeLocatorGroup:
        key = f"text:{text}:{'exact' if exact else 'partial'}"
        return self._locators.get(key, FakeLocatorGroup([]))


class FakePressPage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def wait_for_timeout(self, value: int) -> None:
        self.calls.append(("timeout", value))

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.calls.append((state, timeout))


class BrowserRuntimeServiceTests(unittest.TestCase):
    def test_status_does_not_start_browser(self) -> None:
        service = BrowserService()
        result = service.execute(BrowserCommand(command="status", session_id="unit-status"))
        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["profile"], "openclaw")
        self.assertFalse(result["result"]["running"])

    def test_stop_without_start_succeeds(self) -> None:
        service = BrowserService()
        result = service.execute(BrowserCommand(command="stop", session_id="unit-stop"))
        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["closed"], True)

    def test_unknown_command_returns_unknown_tool(self) -> None:
        service = BrowserService()
        result = service.execute(BrowserCommand(command="totally-unknown", session_id="unit-unknown"))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "unknown_tool")

    def test_start_maps_playwright_loop_error_to_browser_launch_failed(self) -> None:
        service = BrowserService()
        with mock.patch.object(
            service,
            "_ensure_started_if_needed",
            side_effect=RuntimeError(
                "Failed to initialize Playwright for managed browser: It looks like you are using Playwright Sync API inside the asyncio loop."
            ),
        ):
            result = service.execute(BrowserCommand(command="start", session_id="unit-start"))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "browser_launch_failed")
        self.assertTrue(result["retryable"])

    def test_first_usable_locator_prefers_visible_candidate(self) -> None:
        service = BrowserService()
        hidden = FakeCandidate("hidden", False)
        visible = FakeCandidate("visible", True)
        selected = service._first_usable_locator([FakeLocatorGroup([hidden, visible])])
        self.assertIs(selected, visible)

    def test_compat_text_entry_locator_prefers_google_search_textarea(self) -> None:
        service = BrowserService()
        preferred = FakeCandidate("textarea-search", True)
        page = FakePage(
            {
                "textarea[aria-label='Search']": FakeLocatorGroup([preferred]),
                "[role='textbox']": FakeLocatorGroup([FakeCandidate("generic-textbox", True)]),
            }
        )
        selected = service._compat_text_entry_locator(page)
        self.assertIs(selected, preferred)

    def test_compat_text_entry_locator_falls_back_from_hidden_selector_to_visible_label(self) -> None:
        service = BrowserService()
        visible = FakeCandidate("visible-label", True)
        page = FakePage(
            {
                "#hidden-search": FakeLocatorGroup([FakeCandidate("hidden", False)]),
                "label:#hidden-search": FakeLocatorGroup([visible]),
            }
        )

        selected = service._compat_text_entry_locator(page, "#hidden-search")

        self.assertIs(selected, visible)

    def test_compat_click_locator_uses_aria_label_fallback(self) -> None:
        service = BrowserService()
        visible = FakeCandidate("search-button", True)
        page = FakePage(
            {
                '[aria-label="Search or jump to..."]': FakeLocatorGroup([FakeCandidate("hidden", False)]),
                "label:Search or jump to...": FakeLocatorGroup([visible]),
            }
        )

        selected = service._compat_click_locator(page, '[aria-label="Search or jump to..."]')

        self.assertIs(selected, visible)

    def test_sync_after_press_waits_for_navigation_on_enter(self) -> None:
        service = BrowserService()
        page = FakePressPage()
        service._sync_after_press(page, "Enter", 4000)
        self.assertEqual(
            page.calls,
            [("timeout", 250), ("domcontentloaded", 2500), ("networkidle", 1500)],
        )

    def test_sync_after_press_is_noop_for_non_navigation_keys(self) -> None:
        service = BrowserService()
        page = FakePressPage()
        service._sync_after_press(page, "Tab", 4000)
        self.assertEqual(page.calls, [])

    def test_enrich_snapshot_payload_appends_ocr_text_when_missing(self) -> None:
        service = BrowserService()
        payload = {
            "text": "Title: Example\nVisible text:\nDOM summary",
            "stats": {"chars": 10, "lines": 2},
        }

        enriched = service._enrich_snapshot_payload(
            payload,
            {
                "text": "DOM summary OCR visible text: canvas words",
                "ocr_text": "canvas words",
                "observation_mode": "dom+ocr",
            },
        )

        self.assertIn("OCR visible text:\ncanvas words", enriched["text"])
        self.assertEqual(enriched["visible_text"], "DOM summary OCR visible text: canvas words")
        self.assertEqual(enriched["observation_mode"], "dom+ocr")
