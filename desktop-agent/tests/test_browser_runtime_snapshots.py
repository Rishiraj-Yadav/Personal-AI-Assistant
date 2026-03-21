from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from browser_runtime.snapshots import SnapshotEngine  # noqa: E402


class FakeLocator:
    def __init__(self, selector: str):
        self.selector = selector


class FakeLocatorFactory:
    def __init__(self, selector: str):
        self.first = FakeLocator(selector)


class FakeSnapshotPage:
    def __init__(self):
        self.last_args = None

    def evaluate(self, _script: str, args):
        self.last_args = args
        role_mode = bool(args[1])
        return {
            "title": "Test Page",
            "url": "https://example.com",
            "bodyText": "Welcome to the page",
            "headings": [{"tag": "h1", "text": "Example"}],
            "interactive": [
                {
                    "ref": "e1" if role_mode else "1",
                    "role": "button",
                    "label": "Submit",
                    "tag": "button",
                    "type": "",
                }
            ],
        }

    def locator(self, selector: str):
        return FakeLocatorFactory(selector)


class SnapshotEngineTests(unittest.TestCase):
    def test_snapshot_creates_ai_refs_and_text(self) -> None:
        engine = SnapshotEngine()
        page = FakeSnapshotPage()

        result = engine.snapshot(state_key="s1", page=page, tab_id="tab-1", mode="ai")

        self.assertEqual(result["format"], "ai")
        self.assertEqual(result["tab_id"], "tab-1")
        self.assertEqual(result["refs"][0]["ref"], "1")
        self.assertIn('Title: Test Page', result["text"])
        self.assertIn('[1] button "Submit"', result["text"])
        self.assertEqual(engine.ensure_ref(state_key="s1", tab_id="tab-1", ref="1")["label"], "Submit")

    def test_snapshot_creates_role_refs(self) -> None:
        engine = SnapshotEngine()
        page = FakeSnapshotPage()

        result = engine.snapshot(state_key="s2", page=page, tab_id="tab-9", mode="interactive")

        self.assertEqual(result["format"], "interactive")
        self.assertEqual(result["refs"][0]["ref"], "e1")
        self.assertEqual(engine.ensure_ref(state_key="s2", tab_id="tab-9", ref="e1")["role"], "button")

    def test_invalidate_makes_refs_stale(self) -> None:
        engine = SnapshotEngine()
        page = FakeSnapshotPage()
        engine.snapshot(state_key="s3", page=page, tab_id="tab-a", mode="ai")
        engine.invalidate("s3")
        with self.assertRaises(KeyError):
            engine.ensure_ref(state_key="s3", tab_id="tab-a", ref="1")

    def test_ref_locator_uses_data_attribute(self) -> None:
        engine = SnapshotEngine()
        page = FakeSnapshotPage()
        locator = engine.ref_locator(page, "e2")
        self.assertEqual(locator.selector, '[data-desktop-agent-ref="e2"]')
