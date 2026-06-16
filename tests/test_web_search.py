import unittest
from unittest.mock import patch

from web.web_search import web_search_answer


class DummyLLM:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": self.content}}]}


class WebSearchAnswerTests(unittest.TestCase):
    def test_disables_thinking_and_strips_orphan_think_output(self):
        llm = DummyLLM("�������� ��������.</think>")
        urls = []
        cfg = {
            "max_sources": 1,
            "page_timeout_sec": 0.1,
            "cache_ttl_sec": 0,
            "total_context_limit": 500,
            "llm_max_tokens": 64,
        }

        with patch("web.web_search._get_search_links", return_value=["https://example.com/skfu"]), \
             patch("web.web_search.fetch_urls_parallel", return_value=[
                 ("https://example.com/skfu", "СКФУ — Северо-Кавказский федеральный университет.")
             ]):
            answer = web_search_answer("что такое скфу", cfg, "system", llm, urls)

        self.assertEqual(llm.calls[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(llm.calls[0]["thinking_budget_tokens"], 0)
        self.assertNotIn("<think", answer.lower())
        self.assertNotIn("</think", answer.lower())
        self.assertNotIn("�", answer)
        self.assertIn("Не удалось сформировать итоговый ответ", answer)
        self.assertIn("https://example.com/skfu", answer)


if __name__ == "__main__":
    unittest.main()
