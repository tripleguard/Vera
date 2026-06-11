import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from main.prompt_builder import build_runtime_context, build_system_prompt


class PromptBuilderTests(unittest.TestCase):
    def test_core_replaces_legacy_prompt_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CORE.md").write_text("# Core\n\nКороткое ядро.", encoding="utf-8")
            (root / "IDENTITY.md").write_text("СТАРАЯ ИДЕНТИЧНОСТЬ", encoding="utf-8")
            (root / "SOUL.md").write_text("СТАРЫЙ СТИЛЬ", encoding="utf-8")
            (root / "TOOLS.md").write_text("ДЛИННЫЕ ИНСТРУКЦИИ", encoding="utf-8")

            prompt = build_system_prompt(
                root,
                force_reload=True,
                runtime_context="Тестовый runtime.",
            )

        self.assertIn("Короткое ядро.", prompt)
        self.assertIn("Тестовый runtime.", prompt)
        self.assertNotIn("СТАРАЯ ИДЕНТИЧНОСТЬ", prompt)
        self.assertNotIn("ДЛИННЫЕ ИНСТРУКЦИИ", prompt)

    def test_legacy_identity_and_soul_are_fallback_without_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "IDENTITY.md").write_text("# Identity\n\nВера.", encoding="utf-8")
            (root / "SOUL.md").write_text("# Soul\n\nКратко.", encoding="utf-8")
            prompt = build_system_prompt(
                root,
                force_reload=True,
                runtime_context="",
            )

        self.assertEqual(prompt, "Вера.\n\nКратко.")

    def test_runtime_context_uses_supplied_date(self):
        value = build_runtime_context(
            datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
        )
        self.assertIn("2026-06-11", value)
        self.assertIn("UTC", value)


if __name__ == "__main__":
    unittest.main()
