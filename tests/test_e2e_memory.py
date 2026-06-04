"""End-to-end integration test: full memory flow used by main/agent.py.

Simulates the actual integration path:
- extract_from_remember_command(text) -> (key, value, category)
- extract_facts(text) -> List[(key, value, category)]
- MemoryManager.set_profile / add_fact(category=...) / get_context_for_prompt
- JSON round-trip + pin persistence
"""
import sys
import tempfile
import unittest
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from user.memory import MemoryManager
from user.memory_extractor import (
    extract_from_remember_command,
    should_extract_facts,
    extract_facts,
)


class RememberCommandFlowTests(unittest.TestCase):
    """Simulates user 'запомни <X>' commands (after wake-word strip in agent.py)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vera_e2e_"))
        self.mem_path = self.tmp / "MEMORY.md"
        self.m = MemoryManager(self.mem_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_remember_name(self):
        pk, val, cat = extract_from_remember_command("запомни меня зовут Тимур")
        self.assertEqual(pk, "имя")
        self.assertEqual(val, "Тимур")
        self.assertIsNone(cat)
        self.m.set_profile(pk, val)
        self.assertEqual(self.m.get_name(), "Тимур")

    def test_remember_preference(self):
        pk, val, cat = extract_from_remember_command("запомни я люблю тёмный шоколад")
        self.assertIsNone(pk)
        self.assertEqual(cat, "preference")
        self.m.add_fact(val, category=cat)
        self.assertEqual(self.m.facts[0]["category"], "preference")

    def test_remember_email_as_profile(self):
        pk, val, cat = extract_from_remember_command("запомни мой email timur@vera.ru")
        # 'мой email ...' matches the "мой X: Y" profile pattern
        self.assertEqual(pk, "email")
        self.assertEqual(val, "timur@vera.ru")
        self.assertIsNone(cat)
        self.m.set_profile(pk, val)
        self.assertEqual(self.m.profile["email"], "timur@vera.ru")

    def test_remember_project(self):
        pk, val, cat = extract_from_remember_command("запомни работаю над проектом Vera")
        self.assertIsNone(pk)
        self.assertEqual(cat, "project")
        self.m.add_fact(val, category=cat)
        self.assertEqual(self.m.facts[0]["category"], "project")

    def test_recall_info(self):
        self.m.set_profile("имя", "Тимур")
        info = self.m.get_all_info()
        self.assertIn("Тимур", info)


class AutoExtractFlowTests(unittest.TestCase):
    """Simulates auto-extraction from chat messages (line 932 in agent.py)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vera_e2e_"))
        self.mem_path = self.tmp / "MEMORY.md"
        self.m = MemoryManager(self.mem_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_auto_extract_chat_message(self):
        chat = "Привет! Меня зовут Тимур, я живу в Москве, я люблю программировать"
        self.assertTrue(should_extract_facts(chat))
        facts = extract_facts(chat)
        for pk, val, cat in facts:
            if pk:
                self.m.set_profile(pk, val)
            else:
                self.m.add_fact(val, category=cat)
        self.assertEqual(self.m.profile.get("имя"), "Тимур")
        self.assertEqual(self.m.profile.get("город"), "Москве")
        categories = [f["category"] for f in self.m.facts]
        self.assertIn("preference", categories)

    def test_skips_unrelated_text(self):
        self.assertFalse(should_extract_facts("погода в москве"))
        self.assertFalse(should_extract_facts("запусти калькулятор"))


class ContextPromptFlowTests(unittest.TestCase):
    """Simulates the get_context_for_prompt() call at line 1310 of agent.py."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vera_e2e_"))
        self.mem_path = self.tmp / "MEMORY.md"
        self.m = MemoryManager(self.mem_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_context_uses_last_user_message_for_recall(self):
        self.m.set_profile("имя", "Тимур")
        self.m.set_profile("город", "Москве")
        self.m.add_fact("Любит программировать", category="preference")
        self.m.add_dialog_message("user", "расскажи мне про Москву")
        self.m.add_dialog_message("assistant", "Москва — столица России.")
        ctx = self.m.get_context_for_prompt()
        self.assertIn("Тимур", ctx)
        self.assertIn("Москве", ctx)

    def test_pinned_always_surfaced(self):
        self.m.set_profile("имя", "Тимур")
        self.m.add_fact("Аллергия на орехи")
        fid = self.m.facts[0]["id"]
        self.m.pin(fid)
        self.m.add_dialog_message("user", "привет, как дела")
        ctx = self.m.get_context_for_prompt()
        self.assertIn("Закреплено", ctx)
        self.assertIn("Аллергия", ctx)

    def test_empty_state(self):
        ctx = self.m.get_context_for_prompt()
        self.assertEqual(ctx, "")


class PersistenceFlowTests(unittest.TestCase):
    """Simulates save()/load() across app restarts."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vera_e2e_"))
        self.mem_path = self.tmp / "MEMORY.md"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_round_trip(self):
        m1 = MemoryManager(self.mem_path)
        m1.set_profile("имя", "Тимур")
        m1.add_fact("Любит пиццу", category="preference")
        m1.add_fact("Живёт в Москве", category="fact")
        m1.add_dialog_message("user", "привет")
        m1.save()

        m2 = MemoryManager(self.mem_path)
        self.assertEqual(m2.profile.get("имя"), "Тимур")
        self.assertEqual(len(m2.facts), 2)
        self.assertEqual(m2.last_dialog_messages[-1]["content"], "привет")

    def test_pin_survives_reload(self):
        m1 = MemoryManager(self.mem_path)
        m1.add_fact("Критично: аллергия на орехи", category="fact")
        fid = m1.facts[0]["id"]
        m1.pin(fid)
        m1.save()

        m2 = MemoryManager(self.mem_path)
        self.assertTrue(m2.facts[0]["pinned"])


class DeleteAndClearFlowTests(unittest.TestCase):
    """Simulates 'забудь' commands (line 833 of agent.py)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vera_e2e_"))
        self.mem_path = self.tmp / "MEMORY.md"
        self.m = MemoryManager(self.mem_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_delete_fact_by_fragment(self):
        self.m.add_fact("Любит тёмный шоколад")
        self.m.add_fact("Живёт в Москве")
        self.assertTrue(self.m.delete_fact("шоколад"))
        self.assertEqual(len(self.m.facts), 1)
        self.assertIn("Москве", self.m.facts[0]["text"])

    def test_clear_all(self):
        self.m.set_profile("имя", "Тимур")
        self.m.add_fact("Любит пиццу")
        self.m.clear_all()
        self.assertEqual(self.m.profile, {})
        self.assertEqual(self.m.facts, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
