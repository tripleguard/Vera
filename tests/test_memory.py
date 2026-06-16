import tempfile
import unittest
import sys
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import user.memory as memory_module
from user.memory import MemoryManager, MAX_FACTS, is_location_sensitive_query


class MemoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.tmp.name) / "memory.json"
        self.manager = MemoryManager(self.memory_path)

    def tearDown(self):
        memory_module.MAX_FACTS = MAX_FACTS
        self.tmp.cleanup()

    def add_fact(self, text, timestamp, pinned=False, category="fact"):
        fact_id = self.manager.add_fact_structured({
            "text": text,
            "timestamp": timestamp,
            "pinned": pinned,
            "category": category,
            "source": "test",
        })
        self.assertIsNotNone(fact_id)
        return fact_id

    def test_fact_limit_keeps_newest_unpinned(self):
        memory_module.MAX_FACTS = 3

        self.add_fact("old fact", 1)
        self.add_fact("middle fact", 2)
        self.add_fact("new fact", 3)
        self.add_fact("newest fact", 4)

        texts = [fact["text"] for fact in self.manager.facts]
        self.assertNotIn("old fact", texts)
        self.assertEqual(texts, ["middle fact", "new fact", "newest fact"])

    def test_fact_limit_preserves_pinned(self):
        memory_module.MAX_FACTS = 3

        self.add_fact("pinned old fact", 1, pinned=True)
        self.add_fact("old regular fact", 2)
        self.add_fact("new regular fact", 3)
        self.add_fact("newest regular fact", 4)

        facts_by_text = {fact["text"]: fact for fact in self.manager.facts}
        self.assertIn("pinned old fact", facts_by_text)
        self.assertTrue(facts_by_text["pinned old fact"]["pinned"])
        self.assertNotIn("old regular fact", facts_by_text)
        self.assertEqual(len(self.manager.facts), 3)

    def test_duplicate_fact_is_ignored(self):
        self.manager.add_fact("Vera remembers tea")
        self.manager.add_fact("vera remembers tea")

        self.assertEqual(len(self.manager.facts), 1)

    def test_search_returns_relevant_fact(self):
        self.manager.add_fact_structured({
            "text": "The user is building Vera memory panel",
            "category": "project",
            "timestamp": 10,
        })
        self.manager.add_fact_structured({
            "text": "The user likes green tea",
            "category": "preference",
            "timestamp": 11,
        })

        hits = self.manager.search("memory panel", k=1)

        self.assertEqual(len(hits), 1)
        self.assertIn("memory panel", hits[0][0]["text"])

    def test_json_is_the_only_storage_and_drops_legacy_dialog_fields(self):
        self.memory_path.write_text(
            json.dumps({
                "profile": {"имя": "Тестовый пользователь"},
                "facts": [],
                "last_session_summary": "legacy",
                "last_dialog_messages": [{"role": "user", "content": "legacy"}],
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        manager = MemoryManager(self.memory_path)
        manager.save()
        stored = json.loads(self.memory_path.read_text(encoding="utf-8"))

        self.assertEqual(stored, {"profile": {"имя": "Тестовый пользователь"}, "facts": []})
        self.assertFalse((self.memory_path.parent / "MEMORY.md").exists())

    def test_city_profile_is_not_injected_into_unrelated_prompts(self):
        self.manager.set_profile("город", "Тестоград")

        context = self.manager.get_context_for_prompt("что можешь рассказать про кбгу")

        self.assertNotIn("Тестоград", context)

    def test_city_profile_is_available_for_location_prompts(self):
        self.manager.set_profile("город", "Тестоград")

        context = self.manager.get_context_for_prompt("какая погода")

        self.assertIn("Тестоград", context)

    def test_location_query_classifier(self):
        self.assertFalse(is_location_sensitive_query("что можешь рассказать про кбгу"))
        self.assertFalse(is_location_sensitive_query("интересный факт об эйнштейне"))
        self.assertTrue(is_location_sensitive_query("какая погода"))
        self.assertTrue(is_location_sensitive_query("что рядом со мной"))


if __name__ == "__main__":
    unittest.main()
