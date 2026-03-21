import base64
import unittest

from app.models import Message, MessageRole

try:
    from app.core.llm import LLMAdapter
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-specific dependency guard
    LLMAdapter = None
    IMPORT_ERROR = exc


class _FakeGeminiResponse:
    text = "ok"


class _FakeGeminiModel:
    def __init__(self):
        self.calls = []

    def generate_content(self, contents, generation_config=None):
        self.calls.append((contents, generation_config))
        return _FakeGeminiResponse()


@unittest.skipIf(LLMAdapter is None, f"LLMAdapter unavailable: {IMPORT_ERROR}")
class GeminiMultimodalTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_gemini_attaches_inline_images(self):
        adapter = LLMAdapter.__new__(LLMAdapter)
        adapter._gemini_available = True
        adapter._gemini_model = _FakeGeminiModel()
        adapter.gemini_model_name = "gemini-test"
        adapter.gemini_temperature = 0.1
        adapter.gemini_max_tokens = 128

        image_base64 = base64.b64encode(b"fake-image-bytes").decode("ascii")
        result = await adapter._call_gemini(
            [
                Message(
                    role=MessageRole.USER,
                    content="Describe this page",
                    metadata={
                        "images": [
                            {
                                "image_base64": image_base64,
                                "mime_type": "image/png",
                            }
                        ]
                    },
                )
            ]
        )

        self.assertEqual(result["response"], "ok")
        contents, generation_config = adapter._gemini_model.calls[0]
        self.assertGreaterEqual(len(contents), 2)
        self.assertEqual(generation_config["max_output_tokens"], 128)
        user_content = contents[-1]
        self.assertEqual(user_content.role, "user")
        self.assertEqual(len(user_content.parts), 2)
        self.assertEqual(bytes(user_content.parts[1].inline_data.data), b"fake-image-bytes")


if __name__ == "__main__":
    unittest.main()
