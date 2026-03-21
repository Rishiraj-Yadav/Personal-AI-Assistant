import unittest

from app.services.browser_input_service import BrowserInputService


class BrowserInputServiceTests(unittest.TestCase):
    def test_create_and_resolve_pending_request(self):
        service = BrowserInputService()

        request = service.create_request(
            desktop_request_id="desktop-1",
            user_id="user-1",
            conversation_id="conv-1",
            channel="web",
            field_description="GitHub password",
            input_type="password",
            reason="Login required",
        )

        pending = service.get_pending_request(user_id="user-1", conversation_id="conv-1")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.browser_input_id, request.browser_input_id)

        resolved = service.resolve(request.browser_input_id, result={"success": True})
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "resolved")
        self.assertIsNone(service.get_pending_request(user_id="user-1", conversation_id="conv-1"))


if __name__ == "__main__":
    unittest.main()
