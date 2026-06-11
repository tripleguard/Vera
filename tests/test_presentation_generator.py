import unittest
import json

from main.tools.presentation_generator import (
    _deduplicate_content,
    _collect_online_research,
    _filter_unverified_stats,
    _normalize_slide,
    extract_presentation_topic,
    extract_slide_count,
)


class PresentationPlannerTests(unittest.TestCase):
    def test_skill_instructions_are_passed_to_planner(self):
        calls = []

        class FakeLlm:
            def create_chat_completion(self, messages, **_kwargs):
                calls.append(messages)
                return {
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "subtitle": "Подзаголовок",
                                "slides": [
                                    {
                                        "title": f"Вывод {index}",
                                        "key_message": f"Мысль {index}",
                                        "bullets": [f"Факт {index}", f"Пример {index}"],
                                        "visual": visual,
                                    }
                                    for index, visual in enumerate(
                                        ["overview", "comparison", "summary"],
                                        start=1,
                                    )
                                ],
                            }, ensure_ascii=False)
                        }
                    }]
                }

        from main.tools.presentation_generator import generate_presentation_plan

        plan = generate_presentation_plan(
            "локальные модели",
            FakeLlm(),
            total_slides=4,
            skill_instructions="ПРОВЕРЬ ИСТОЧНИКИ",
        )

        self.assertEqual(len(plan["slides"]), 3)
        self.assertIn("ПРОВЕРЬ ИСТОЧНИКИ", calls[0][0]["content"])

    def test_extracts_topic_and_removes_slide_count(self):
        self.assertEqual(
            extract_presentation_topic("Сделай презентацию про локальные модели на 8 слайдов"),
            "локальные модели",
        )

    def test_slide_count_is_bounded(self):
        self.assertEqual(extract_slide_count("Сделай 2 слайда", 6), 4)
        self.assertEqual(extract_slide_count("Сделай 8 слайдов", 6), 8)
        self.assertEqual(extract_slide_count("Сделай 99 слайдов", 6), 10)

    def test_normalization_limits_text_density(self):
        slide = _normalize_slide(
            {
                "title": "Очень длинный заголовок " * 10,
                "key_message": "Длинное объяснение " * 30,
                "bullets": ["Пункт " * 40] * 8,
                "visual": "unknown",
                "stats": [{"value": "42%", "label": "Показатель"}] * 5,
            },
            0,
        )
        self.assertIsNotNone(slide)
        self.assertLessEqual(len(slide["title"]), 65)
        self.assertLessEqual(len(slide["key_message"]), 171)
        self.assertEqual(len(slide["bullets"]), 4)
        self.assertEqual(len(slide["stats"]), 3)
        self.assertEqual(slide["visual"], "numbers")

    def test_editor_removes_repeated_bullets_and_unverified_stats(self):
        slides = [
            {
                "bullets": ["Локальная обработка", "Быстрый ответ"],
                "stats": [{"value": "90%", "label": "эффект"}],
                "visual": "overview",
                "quote": "Повтор",
            },
            {
                "bullets": ["Локальная обработка", "Приватность"],
                "stats": [{"value": "2 с", "label": "скорость"}],
                "visual": "comparison",
                "quote": "Повтор",
            },
        ]
        _deduplicate_content(slides)
        _filter_unverified_stats(slides, "В тесте подтверждено время 2 с.")
        self.assertEqual(slides[1]["bullets"], ["Приватность"])
        self.assertEqual(slides[0]["stats"], [])
        self.assertEqual(slides[1]["stats"][0]["value"], "2 с")
        self.assertEqual(slides[0]["quote"], "")

    def test_online_research_uses_multiple_queries_and_merges_sources(self):
        queries = []

        def fake_search(query):
            queries.append(query)
            return {
                "text": ("Подтверждённые сведения по теме. " * 12) + query,
                "sources": ["https://example.org/report", "https://data.example.com/facts"],
            }

        context, sources, online_used = _collect_online_research(
            "локальные языковые модели",
            fake_search,
        )
        self.assertTrue(online_used)
        self.assertEqual(len(queries), 3)
        self.assertIn("актуальные данные", context)
        self.assertEqual(len(sources), 2)

    def test_online_research_falls_back_when_pages_are_unavailable(self):
        context, sources, online_used = _collect_online_research(
            "тема",
            lambda _query: {"text": "Нет данных", "sources": []},
        )
        self.assertFalse(online_used)
        self.assertEqual(context, "")
        self.assertEqual(sources, [])


if __name__ == "__main__":
    unittest.main()
