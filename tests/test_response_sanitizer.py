import unittest

from main.response_sanitizer import (
    clean_for_tts,
    might_be_thinking_markup_prefix,
    strip_emoji_for_tts,
    strip_markdown_for_tts,
    strip_thinking_markup,
)


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

    def test_thinking_budget_message_is_not_user_visible(self):
        cleaned = strip_thinking_markup(
            "Бюджет размышления исчерпан. Перехожу к финальному ответу.\n\n"
            "Я Вера, ваш персональный помощник."
        )
        self.assertEqual(cleaned.strip(), "Я Вера, ваш персональный помощник.")

    def test_partial_thinking_budget_message_is_removed(self):
        cleaned = strip_thinking_markup(
            "размышления исчерпан. Перехожу к финальному ответу.\n\n"
            "Все хорошо, я на связи."
        )
        self.assertEqual(cleaned.strip(), "Все хорошо, я на связи.")

    def test_thinking_budget_stream_prefix_is_buffered(self):
        self.assertTrue(might_be_thinking_markup_prefix("Бюджет размыш"))
        self.assertFalse(might_be_thinking_markup_prefix("Бро, все хорошо"))


if __name__ == "__main__":
    unittest.main()
