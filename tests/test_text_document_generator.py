import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from main.tools.text_document_generator import (
    execute_text_document_creation,
    extract_document_topic,
    infer_document_format,
    is_text_document_request,
)


class TextDocumentGeneratorTests(unittest.TestCase):
    def test_recognizes_reports_but_not_presentations(self):
        self.assertTrue(is_text_document_request("Создай текстовый документ по теме Dota 2"))
        self.assertTrue(is_text_document_request("Подготовь доклад про локальные модели"))
        self.assertFalse(is_text_document_request("Создай презентацию про локальные модели"))

    def test_extracts_topic_and_format(self):
        text = "Создай текстовый документ по теме Dota 2"
        self.assertEqual(extract_document_topic(text), "Dota 2")
        self.assertEqual(infer_document_format(text), "txt")
        self.assertEqual(infer_document_format("Сделай отчет в Word про ИИ"), "docx")

    def test_pipeline_saves_once_and_returns_real_path(self):
        calls = []

        class FakeLlm:
            def create_chat_completion(self, messages, **kwargs):
                calls.append((messages, kwargs))
                return {
                    "choices": [{
                        "message": {
                            "content": (
                                "# Dota 2\n\nВведение.\n\n"
                                + "Содержательный раздел о развитии игры. " * 12
                                + "\n\nВывод."
                            )
                        }
                    }]
                }

        with TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "dota.txt"
            saves = []

            def save_txt(_filename, content):
                saves.append(content)
                target.write_text(content, encoding="utf-8")
                return f"Файл создан: {target}"

            message, file_path = execute_text_document_creation(
                "Создай текстовый документ по теме Dota 2",
                FakeLlm(),
                web_search_func=lambda _query: {
                    "text": "Проверенные сведения о Dota 2. " * 8,
                    "sources": ["https://example.com/dota"],
                },
                create_txt_func=save_txt,
            )

        self.assertEqual(len(saves), 1)
        self.assertEqual(file_path, str(target))
        self.assertIn("Файл создан:", message)
        self.assertIn("интернет-источников: 1", message)
        self.assertEqual(calls[0][1]["reasoning_budget"], 0)


if __name__ == "__main__":
    unittest.main()
