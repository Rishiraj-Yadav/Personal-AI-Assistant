from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from browser_runtime.safety import detect_sensitive_context, validate_remote_cdp_url  # noqa: E402


class FakePage:
    def __init__(self, url: str, fields: list[dict] | None = None):
        self.url = url
        self._fields = fields or []

    def evaluate(self, _script: str):
        return self._fields


class BrowserRuntimeSafetyTests(unittest.TestCase):
    def test_validate_remote_cdp_url_allows_localhost(self) -> None:
        self.assertIsNone(validate_remote_cdp_url("http://127.0.0.1:9222"))
        self.assertIsNone(validate_remote_cdp_url("ws://localhost:9222/devtools/browser/x"))

    def test_validate_remote_cdp_url_blocks_non_local_when_host_local_only(self) -> None:
        err = validate_remote_cdp_url("http://192.168.1.10:9222", host_local_only=True)
        self.assertIsNotNone(err)
        self.assertIn("host-local only", err)

    def test_validate_remote_cdp_url_blocks_private_remote_without_allow(self) -> None:
        err = validate_remote_cdp_url("http://192.168.1.10:9222", allow_private=False)
        self.assertIsNotNone(err)
        self.assertIn("private-network", err)

    def test_detect_sensitive_context_by_url(self) -> None:
        page = FakePage("https://example.com/login", [])
        result = detect_sensitive_context(page)
        self.assertTrue(result["sensitive"])
        self.assertIn("login", result["url"])

    def test_detect_sensitive_context_by_fields(self) -> None:
        page = FakePage(
            "https://example.com/",
            [{"type": "password", "name": "password", "placeholder": "", "autocomplete": ""}],
        )
        result = detect_sensitive_context(page)
        self.assertTrue(result["sensitive"])
        self.assertTrue(result["fields"])
