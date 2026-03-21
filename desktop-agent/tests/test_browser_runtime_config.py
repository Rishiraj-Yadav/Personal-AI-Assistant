from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from browser_runtime.config import build_default_runtime_settings  # noqa: E402


class BrowserRuntimeConfigTests(unittest.TestCase):
    def test_build_default_runtime_settings_creates_expected_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"DESKTOP_AGENT_BROWSER_RUNTIME_ROOT": tmpdir}, clear=False):
                settings = build_default_runtime_settings()
                self.assertEqual(settings.default_profile, "openclaw")
                self.assertEqual(set(settings.profiles), {"openclaw", "user", "remote"})

                openclaw = settings.get_profile("openclaw")
                self.assertEqual(openclaw.driver, "managed")
                self.assertTrue(Path(openclaw.user_data_dir).exists())
                self.assertTrue(Path(openclaw.downloads_dir).exists())
                self.assertTrue(Path(openclaw.traces_dir).exists())

                user = settings.get_profile("user")
                self.assertEqual(user.driver, "existing-session")
                self.assertTrue(user.attach_only)

                remote = settings.get_profile("remote")
                self.assertEqual(remote.driver, "remote-cdp")
                self.assertTrue(remote.attach_only)

    def test_unknown_profile_raises_key_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"DESKTOP_AGENT_BROWSER_RUNTIME_ROOT": tmpdir}, clear=False):
                settings = build_default_runtime_settings()
                with self.assertRaises(KeyError):
                    settings.get_profile("does-not-exist")

    def test_resolve_profile_uses_session_scoped_paths_for_managed_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"DESKTOP_AGENT_BROWSER_RUNTIME_ROOT": tmpdir}, clear=False):
                settings = build_default_runtime_settings()
                alpha = settings.resolve_profile("session-alpha", "openclaw")
                beta = settings.resolve_profile("session-beta", "openclaw")
                self.assertNotEqual(alpha.user_data_dir, beta.user_data_dir)
                self.assertIn("session-alpha", alpha.user_data_dir)
                self.assertIn("session-beta", beta.user_data_dir)
                self.assertTrue(Path(alpha.user_data_dir).exists())
                self.assertTrue(Path(beta.user_data_dir).exists())

    def test_resolve_profile_keeps_attach_only_profiles_shared(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"DESKTOP_AGENT_BROWSER_RUNTIME_ROOT": tmpdir}, clear=False):
                settings = build_default_runtime_settings()
                alpha = settings.resolve_profile("session-alpha", "user")
                beta = settings.resolve_profile("session-beta", "user")
                self.assertEqual(alpha.user_data_dir, beta.user_data_dir)
