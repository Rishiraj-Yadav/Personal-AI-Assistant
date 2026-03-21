import unittest

try:
    from app.skills.desktop_bridge import DesktopBridgeSkill
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - optional dependency guard
    DesktopBridgeSkill = None
    IMPORT_ERROR = exc


@unittest.skipIf(DesktopBridgeSkill is None, f"Desktop bridge unavailable: {IMPORT_ERROR}")
class DesktopBridgeSkillTests(unittest.TestCase):
    def test_normalize_nl_result_promotes_browser_question_to_clarification(self):
        bridge = DesktopBridgeSkill.__new__(DesktopBridgeSkill)

        normalized = bridge._normalize_nl_result(
            {
                "success": False,
                "response": "Can you describe the search bar in the screenshot for me?",
                "browser_state": {"is_open": True},
            }
        )

        self.assertTrue(normalized["requires_clarification"])
        self.assertEqual(
            normalized["question"],
            "Can you describe the search bar in the screenshot for me?",
        )
        self.assertEqual(normalized["options"], [])


if __name__ == "__main__":
    unittest.main()
