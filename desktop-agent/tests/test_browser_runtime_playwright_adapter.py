from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from browser_runtime.playwright_adapter import PlaywrightAdapter  # noqa: E402


class FakeKeyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)


class FakePage:
    def __init__(self) -> None:
        self.keyboard = FakeKeyboard()


class FakeReadablePage:
    url = "https://example.com"

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def evaluate(self, script: str) -> object:
        return self._payload

    def title(self) -> str:
        return "Example page"


class PlaywrightAdapterTests(unittest.TestCase):
    def test_press_normalizes_common_key_aliases(self) -> None:
        adapter = PlaywrightAdapter()
        page = FakePage()

        adapter.press(page, "enter")
        adapter.press(page, "control+a")
        adapter.press(page, "pagedown")

        self.assertEqual(page.keyboard.pressed, ["Enter", "Control+A", "PageDown"])

    def test_read_page_includes_ocr_enriched_visible_text(self) -> None:
        adapter = PlaywrightAdapter()
        page = FakeReadablePage(
            {
                "title": "Example",
                "url": "https://example.com",
                "body_text": "DOM summary",
                "inputs": [],
                "buttons": [],
                "links": [],
            }
        )

        with mock.patch.object(
            adapter,
            "observe_visible_text",
            return_value={
                "text": "DOM summary OCR visible text: visual words",
                "dom_text": "DOM summary",
                "ocr_text": "visual words",
                "ocr_available": True,
                "observation_mode": "dom+ocr",
            },
        ):
            result = adapter.read_page(page)

        self.assertEqual(result["body_text"], "DOM summary OCR visible text: visual words")
        self.assertEqual(result["ocr_text"], "visual words")
        self.assertEqual(result["observation_mode"], "dom+ocr")

    def test_full_text_prefers_merged_visible_text(self) -> None:
        adapter = PlaywrightAdapter()
        page = FakeReadablePage("DOM summary")

        with mock.patch.object(
            adapter,
            "observe_visible_text",
            return_value={
                "text": "DOM summary OCR visible text: canvas words",
                "dom_text": "DOM summary",
                "ocr_text": "canvas words",
                "ocr_available": True,
                "observation_mode": "dom+ocr",
            },
        ):
            result = adapter.full_text(page)

        self.assertEqual(result["text"], "DOM summary OCR visible text: canvas words")
        self.assertEqual(result["ocr_text"], "canvas words")
        self.assertEqual(result["observation_mode"], "dom+ocr")


if __name__ == "__main__":
    unittest.main()
