import tempfile
import unittest
from pathlib import Path

from user.session_store import MAX_CONTEXT_MESSAGES, SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name) / "vera.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_sessions_are_isolated_and_context_is_limited(self):
        first = self.store.create_session()
        second = self.store.create_session()

        for index in range(7):
            role = "user" if index % 2 == 0 else "assistant"
            self.store.add_message(first["id"], role, f"first-{index}")
        self.store.add_message(second["id"], "user", "second-only")

        first_context = self.store.get_context_messages(first["id"])
        second_context = self.store.get_context_messages(second["id"])

        self.assertEqual(len(first_context), MAX_CONTEXT_MESSAGES)
        self.assertEqual(
            [item["content"] for item in first_context],
            ["first-2", "first-3", "first-4", "first-5", "first-6"],
        )
        self.assertEqual(second_context, [{"role": "user", "content": "second-only"}])
        self.assertNotIn("second-only", str(first_context))

    def test_first_user_message_sets_title_and_preview(self):
        session = self.store.create_session()
        self.store.add_message(
            session["id"],
            "user",
            "Открой браузер и найди прогноз погоды на завтра",
        )

        updated = self.store.get_session(session["id"])

        self.assertEqual(updated["title"], "Открой браузер и найди прогноз погоды на завтра")
        self.assertEqual(updated["preview"], updated["title"])

    def test_update_archive_pin_and_delete(self):
        session = self.store.create_session("Работа с окнами")
        self.store.add_message(session["id"], "user", "Сверни браузер")

        updated = self.store.update_session(
            session["id"],
            title="Управление окнами",
            archived=True,
            pinned=True,
        )

        self.assertEqual(updated["title"], "Управление окнами")
        self.assertTrue(updated["archived"])
        self.assertTrue(updated["pinned"])
        self.assertEqual(self.store.list_sessions(), [])
        self.assertEqual(len(self.store.list_sessions(archived=True)), 1)
        self.assertTrue(self.store.delete_session(session["id"]))
        self.assertEqual(self.store.get_messages(session["id"]), [])

    def test_legacy_dialog_is_imported_once(self):
        legacy = [
            {"role": "user", "content": "Старый вопрос"},
            {"role": "assistant", "content": "Старый ответ"},
        ]

        imported_id = self.store.import_legacy_dialog(legacy)
        repeated = self.store.import_legacy_dialog(legacy)

        self.assertIsNotNone(imported_id)
        self.assertIsNone(repeated)
        self.assertEqual(len(self.store.list_sessions()), 1)
        self.assertEqual(
            [item["content"] for item in self.store.get_messages(imported_id)],
            ["Старый вопрос", "Старый ответ"],
        )


if __name__ == "__main__":
    unittest.main()
