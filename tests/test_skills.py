import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from main.skills import list_installed_skills, load_builtin_skill


class SkillLoaderTests(unittest.TestCase):
    def test_presentation_skill_loads_without_frontmatter(self):
        skill = load_builtin_skill("presentations")
        self.assertIsNotNone(skill)
        self.assertIn("Создание презентации", skill)
        self.assertNotIn("allowed-tools:", skill)

    def test_document_skill_loads_without_frontmatter(self):
        skill = load_builtin_skill("documents")
        self.assertIsNotNone(skill)
        self.assertIn("Создание текстового документа", skill)
        self.assertIn("Не вызывай создание документа повторно", skill)

    def test_unsafe_skill_name_is_rejected(self):
        self.assertIsNone(load_builtin_skill("../presentations"))

    def test_lists_bundled_and_user_skills_with_user_override(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundled_root = root / "bundled"
            user_root = root / "user"
            (bundled_root / "presentations").mkdir(parents=True)
            (user_root / "presentations").mkdir(parents=True)
            (user_root / "documents").mkdir(parents=True)

            (bundled_root / "presentations" / "SKILL.md").write_text(
                "---\n"
                "name: presentations\n"
                "description: Bundled presentation skill\n"
                "allowed-tools: web_search create_presentation\n"
                "metadata:\n"
                "  vera.activation: builtin\n"
                "  vera.model-profile: small\n"
                "---\n"
                "# Presentation Builder\n",
                encoding="utf-8",
            )
            (user_root / "presentations" / "SKILL.md").write_text(
                "---\n"
                "name: presentations\n"
                "description: User presentation skill\n"
                "allowed-tools: create_presentation\n"
                "---\n"
                "# Custom Presentations\n",
                encoding="utf-8",
            )
            (user_root / "documents" / "SKILL.md").write_text(
                "---\n"
                "name: documents\n"
                "description: Document creation\n"
                "---\n"
                "# Documents\n",
                encoding="utf-8",
            )

            skills = list_installed_skills(bundled_root, user_root)

        self.assertEqual([skill["name"] for skill in skills], ["presentations", "documents"])
        presentation = next(skill for skill in skills if skill["name"] == "presentations")
        self.assertEqual(presentation["source"], "user")
        self.assertEqual(presentation["description"], "User presentation skill")
        self.assertEqual(presentation["allowed_tools"], ["create_presentation"])


if __name__ == "__main__":
    unittest.main()
