"""Tests for MemoryManager. Run: python tests/test_memory.py"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add project root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from user.memory import (
    MemoryManager,
    MAX_CONTEXT_LENGTH,
    MAX_FACTS,
    CATEGORIES,
    infer_category,
)
from user import memory as memory_mod


class MemoryTestBase(unittest.TestCase):
    """Изолированный tmp-каталог для каждого теста, чтобы не трогать реальный data/."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.legacy_path = self.root / "MEMORY.md"
        self.json_path = self.root / "memory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def make_manager(self) -> MemoryManager:
        return MemoryManager(self.legacy_path)

    def write_legacy(self, content: str) -> None:
        self.legacy_path.write_text(content, encoding="utf-8")


class EmptyStateTests(MemoryTestBase):
    def test_empty_state_returns_empty_string(self):
        m = self.make_manager()
        self.assertEqual(m.get_context_for_prompt(), "")
        # get_all_info() в пустом состоянии возвращает подсказку (legacy поведение)
        self.assertIn("ничего не знаю", m.get_all_info().lower())
        self.assertEqual(m.search("что угодно"), [])
        self.assertEqual(m.facts, [])
        self.assertEqual(m.profile, {})

    def test_empty_creates_json_file(self):
        self.make_manager()
        self.assertTrue(self.json_path.exists())


class MigrationTests(MemoryTestBase):
    LEGACY = """# Память Веры

> Этот файл автоматически обновляется агентом.
> Можно редактировать вручную.

## Профиль

- **Имя:** Саша
- **Город:** Москва
- **Работа:** инженер

## Факты

- Любит тёмный шоколад
- Имеет кота по имени Барсик
- Проект: голосовой ассистент Vera

## Последний диалог

- **Вы:** привет
- **Вера:** Здравствуйте, Саша!
"""

    def test_migrates_profile(self):
        self.write_legacy(self.LEGACY)
        m = self.make_manager()
        self.assertEqual(m.profile.get("имя"), "Саша")
        self.assertEqual(m.profile.get("город"), "Москва")
        self.assertEqual(m.profile.get("работа"), "инженер")

    def test_migrates_facts_to_structured(self):
        self.write_legacy(self.LEGACY)
        m = self.make_manager()
        self.assertEqual(len(m.facts), 3)
        # Каждый факт — dict с нужными полями
        for f in m.facts:
            self.assertIn("id", f)
            self.assertIn("text", f)
            self.assertIn("category", f)
            self.assertIn("pinned", f)
            self.assertIn("timestamp", f)
            self.assertEqual(f["source"], "legacy")
            self.assertFalse(f["pinned"])

    def test_migrates_dialog(self):
        self.write_legacy(self.LEGACY)
        m = self.make_manager()
        self.assertEqual(len(m.last_dialog_messages), 2)
        self.assertEqual(m.last_dialog_messages[0]["role"], "user")
        self.assertEqual(m.last_dialog_messages[1]["role"], "assistant")

    def test_migrated_saves_as_json(self):
        self.write_legacy(self.LEGACY)
        m = self.make_manager()
        self.assertTrue(self.json_path.exists())
        # JSON содержит те же данные
        import json
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["profile"]["имя"], "Саша")
        self.assertEqual(len(data["facts"]), 3)

    def test_json_takes_precedence_over_legacy(self):
        # Если есть и JSON, и MEMORY.md — JSON выигрывает
        self.json_path.write_text('{"profile": {"имя": "Из JSON"}, "facts": []}', encoding="utf-8")
        self.write_legacy(self.LEGACY)
        m = self.make_manager()
        self.assertEqual(m.profile.get("имя"), "Из JSON")
        self.assertEqual(m.facts, [])


class CategoryInferenceTests(unittest.TestCase):
    def test_identity_from_name_patterns(self):
        self.assertEqual(infer_category("Меня зовут Дима"), "identity")
        self.assertEqual(infer_category("моё имя Алексей"), "identity")
        self.assertEqual(infer_category("Моё имя — Тимур"), "identity")

    def test_contact_from_email_or_phone(self):
        self.assertEqual(infer_category("Email: user@mail.ru"), "contact")
        self.assertEqual(infer_category("Телефон: +7 999 123-45-67"), "contact")

    def test_preference_from_likes(self):
        self.assertEqual(infer_category("Любит тёмный шоколад"), "preference")
        self.assertEqual(infer_category("Ненавидит громкую музыку"), "preference")
        self.assertEqual(infer_category("Предпочитаю чёрный кофе"), "preference")

    def test_project_from_work(self):
        self.assertEqual(infer_category("Работает над голосовым ассистентом"), "project")
        self.assertEqual(infer_category("Проект: Vera"), "project")

    def test_default_fact(self):
        self.assertEqual(infer_category("Живёт в Москве"), "fact")
        self.assertEqual(infer_category("Имеет кота"), "fact")

    def test_empty_defaults_to_fact(self):
        self.assertEqual(infer_category(""), "fact")


class SearchTests(MemoryTestBase):
    def setUp(self):
        super().setUp()
        self.m = self.make_manager()
        self.m.profile["имя"] = "Саша"
        self.m.add_fact("Любит синий цвет")
        self.m.add_fact("Живёт в Москве")
        self.m.add_fact("Работает программистом")
        self.m.add_fact("Имеет кота по имени Барсик")

    def test_keyword_ranking(self):
        # "любимый цвет" → "Любит синий цвет" выше, чем "Живёт в Москве"
        results = self.m.search("любимый цвет", k=3)
        self.assertGreater(len(results), 0)
        top_id, _ = results[0]
        # Должен быть факт про цвет, а не про Москву
        self.assertIn("синий", top_id["text"].lower())

    def test_returns_top_k(self):
        results = self.m.search("Москва", k=2)
        self.assertLessEqual(len(results), 2)

    def test_recency_matters(self):
        # 2 факта про шоколад, один год назад, другой сейчас.
        # С 5% hard-cap recency сигнал слабый → берём достаточно старый
        # timestamp, чтобы days*0.05 давал заметную разницу.
        older = self.m.add_fact_structured({
            "text": "Старый факт про шоколад",
            "category": "preference",
            "pinned": False,
            "timestamp": time.time() - 86400 * 365,  # 1 год назад
            "source": "user",
        })
        newer = self.m.add_fact_structured({
            "text": "Свежий факт про шоколад",
            "category": "preference",
            "pinned": False,
            "timestamp": time.time(),
            "source": "user",
        })
        results = self.m.search("шоколад", k=5)
        ids = [f["id"] for f, _ in results]
        # newer должен быть выше older
        self.assertLess(ids.index(newer), ids.index(older),
                        f"newer={ids.index(newer)} not less than older={ids.index(older)}; all ids={ids}")


class PinnedTests(MemoryTestBase):
    def test_pinned_appears_in_context(self):
        m = self.make_manager()
        m.add_fact("Нерелевантный факт про погоду")
        m.add_fact("Возраст: 25")
        m.pin(m.facts[1]["id"])
        ctx = m.get_context_for_prompt()
        # Pinned факт должен быть в контексте
        self.assertIn("25", ctx)
        self.assertIn("Закреплено", ctx)

    def test_pinned_score_zero_query_appears(self):
        """Pinned факт попадает в контекст даже если BM25 ничего не нашёл."""
        m = self.make_manager()
        m.add_fact("Меня зовут Тимур")
        m.pin(m.facts[0]["id"])
        # Запрос не про имя, BM25 ничего не даст, но pinned всё равно виден
        ctx = m.get_context_for_prompt()
        self.assertIn("Тимур", ctx)

    def test_pin_unpin_toggle(self):
        m = self.make_manager()
        m.add_fact("Тестовый факт")
        fid = m.facts[0]["id"]
        self.assertFalse(m.facts[0]["pinned"])
        self.assertTrue(m.pin(fid))
        self.assertTrue(m.facts[0]["pinned"])
        self.assertTrue(m.unpin(fid))
        self.assertFalse(m.facts[0]["pinned"])

    def test_pin_unknown_id_returns_false(self):
        m = self.make_manager()
        self.assertFalse(m.pin("f_doesnotexist"))


class ContextCapTests(MemoryTestBase):
    def test_context_under_cap(self):
        m = self.make_manager()
        # 20 фактов
        for i in range(20):
            m.add_fact(f"Факт номер {i}: длинный текст про что-то важное в жизни пользователя, " * 2)
        m.profile["имя"] = "Саша"
        m.profile["город"] = "Москва"
        # Закрепляем один
        m.pin(m.facts[0]["id"])
        ctx = m.get_context_for_prompt()
        # Контекст может включать pinned (всегда) и top-3 recalled.
        # Pinned без top-K ≤ MAX_CONTEXT_LENGTH + overhead от строки "[Закреплено]"
        # Но top-3 recalled может быть больше из-за лимитов
        # Гарантируем: общая длина разумна
        self.assertLessEqual(len(ctx), MAX_CONTEXT_LENGTH + 200,  # overhead толерантность
                             f"context too long: {len(ctx)} chars")

    def test_pinned_always_included_even_when_too_long(self):
        """Если pinned слишком длинный — он остаётся, top-3 обрезаются."""
        m = self.make_manager()
        # Большой pinned факт
        m.add_fact("Очень длинный закреплённый факт " * 20)
        m.pin(m.facts[0]["id"])
        # + ещё куча
        for i in range(10):
            m.add_fact(f"Факт {i} про что-то")
        m.add_dialog_message("user", "привет")
        ctx = m.get_context_for_prompt()
        # Главное: pinned всё равно присутствует
        self.assertIn("Очень длинный закреплённый факт", ctx)

    def test_pinned_first_above_recalled(self):
        m = self.make_manager()
        m.add_fact("Закреплённое")
        m.pin(m.facts[0]["id"])
        m.add_fact("Другой факт про вкус")
        m.add_dialog_message("user", "расскажи про вкус")
        ctx = m.get_context_for_prompt()
        # Закреплённое должно быть раньше
        pos_pinned = ctx.find("Закреплено")
        pos_other = ctx.find("Другой факт")
        self.assertGreater(pos_pinned, 0)
        self.assertGreater(pos_other, pos_pinned)


class FactsLimitTests(MemoryTestBase):
    def test_facts_limit_enforced(self):
        m = self.make_manager()
        for i in range(MAX_FACTS + 5):
            m.add_fact(f"Факт {i}")
        # Должно остаться ровно MAX_FACTS (с вытеснением старых)
        self.assertEqual(len(m.facts), MAX_FACTS)

    def test_pinned_preserved_when_evicting(self):
        m = self.make_manager()
        # Закрепляем один и добавляем много
        m.add_fact("Закреплённый факт")
        m.pin(m.facts[0]["id"])
        for i in range(MAX_FACTS + 5):
            m.add_fact(f"Обычный факт {i}")
        # Закреплённый должен остаться
        self.assertTrue(any(f.get("pinned") for f in m.facts))


class APIContractTests(MemoryTestBase):
    """Существующие вызовы в main/agent.py не должны ломаться."""

    def test_set_profile_still_works(self):
        m = self.make_manager()
        m.set_profile("город", "Москва")
        self.assertEqual(m.get_profile("город"), "Москва")
        self.assertEqual(m.profile.get("город"), "Москва")

    def test_set_name_get_name(self):
        m = self.make_manager()
        m.set_name("Дима")
        self.assertEqual(m.get_name(), "Дима")

    def test_add_fact_legacy_signature(self):
        """Совместимость со старой сигнатурой add_fact(fact: str)."""
        m = self.make_manager()
        m.add_fact("Любит пиццу")
        self.assertEqual(len(m.facts), 1)
        self.assertEqual(m.facts[0]["text"], "Любит пиццу")
        # Категория авто-определена
        self.assertEqual(m.facts[0]["category"], "preference")

    def test_add_fact_dedup(self):
        m = self.make_manager()
        m.add_fact("Любит пиццу")
        m.add_fact("любит пиццу")  # case-insensitive дубль
        self.assertEqual(len(m.facts), 1)

    def test_add_fact_empty_ignored(self):
        m = self.make_manager()
        m.add_fact("")
        m.add_fact("   ")
        self.assertEqual(len(m.facts), 0)

    def test_delete_fact_works(self):
        m = self.make_manager()
        m.add_fact("Любит суши")
        self.assertTrue(m.delete_fact("суши"))
        self.assertEqual(len(m.facts), 0)
        self.assertFalse(m.delete_fact("нет такого"))

    def test_clear_all(self):
        m = self.make_manager()
        m.add_fact("Факт")
        m.set_profile("город", "Москва")
        m.add_dialog_message("user", "привет")
        m.clear_all()
        self.assertEqual(m.facts, [])
        self.assertEqual(m.profile, {})
        self.assertEqual(m.last_dialog_messages, [])

    def test_add_dialog_message(self):
        m = self.make_manager()
        m.add_dialog_message("user", "привет")
        m.add_dialog_message("assistant", "здравствуйте")
        d = m.get_last_dialog()
        self.assertEqual(len(d), 2)
        self.assertEqual(d[0]["role"], "user")
        self.assertEqual(d[1]["role"], "assistant")

    def test_dialog_message_cap(self):
        m = self.make_manager()
        for i in range(10):
            m.add_dialog_message("user", f"msg {i}")
        self.assertLessEqual(len(m.get_last_dialog()), 5)

    def test_get_all_info(self):
        m = self.make_manager()
        m.add_fact("Любит кофе")
        m.set_profile("имя", "Тимур")
        info = m.get_all_info()
        self.assertIn("Тимур", info)
        self.assertIn("кофе", info)

    def test_update_session_summary(self):
        m = self.make_manager()
        m.update_session_summary("Обсуждали планы")
        self.assertIn("Обсуждали", m.last_session_summary)


class SearchReturnTypeTests(MemoryTestBase):
    def test_search_returns_tuples_of_fact_and_score(self):
        m = self.make_manager()
        m.add_fact("Любит тёмный шоколад")
        results = m.search("шоколад", k=3)
        self.assertEqual(len(results), 1)
        fact, score = results[0]
        self.assertIsInstance(fact, dict)
        self.assertIsInstance(score, float)
        self.assertGreater(score, 0.0)

    def test_search_pinned_included_with_low_keyword(self):
        m = self.make_manager()
        m.add_fact("Имя: Тимур")
        m.pin(m.facts[0]["id"])
        # Запрос совсем про другое
        results = m.search("где находится Эйфелева башня", k=3)
        # Pinned должен попасть (хотя бы с минимальным score)
        ids = [f["id"] for f, _ in results]
        self.assertIn(m.facts[0]["id"], ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
