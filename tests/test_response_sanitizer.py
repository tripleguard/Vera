import unittest

from main.response_sanitizer import clean_for_tts, strip_emoji_for_tts, strip_markdown_for_tts


class ResponseSanitizerTests(unittest.TestCase):
    def test_markdown_cleanup_keeps_human_text(self):
        text = "# Заголовок\n- **важный** [источник](https://example.com)\n```py\nprint(1)\n```"
        cleaned = strip_markdown_for_tts(text)
        self.assertIn("Заголовок", cleaned)
        self.assertIn("важный источник", cleaned)
        self.assertNotIn("print(1)", cleaned)
        self.assertNotIn("**", cleaned)

    def test_emoji_cleanup_removes_unicode_and_text_smiles(self):
        cleaned = strip_emoji_for_tts("Готово 🙂 :)")
        self.assertEqual(cleaned.strip(), "Готово")

    def test_clean_for_tts_removes_sources_and_urls(self):
        cleaned = clean_for_tts(
            "Ответ **готов** https://example.com/path (источники: https://example.com/path)"
        )
        self.assertIn("Ответ готов", cleaned)
        self.assertNotIn("http", cleaned)
        self.assertNotIn("источники", cleaned.lower())


if __name__ == "__main__":
    unittest.main()
