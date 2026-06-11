import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main.llm_server import LlamaClient, LlamaServer


class _Config:
    def get(self, *_args, **_kwargs):
        return "auto"


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class MultimodalTests(unittest.TestCase):
    def test_model_discovery_does_not_select_mmproj_as_main_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llama-server.exe").write_bytes(b"")
            (root / "mmproj-Qwen.gguf").write_bytes(b"projector")
            (root / "Qwen-2B.gguf").write_bytes(b"model")

            with (
                patch("main.llm_server.get_install_root", return_value=root),
                patch("main.llm_server.get_config", return_value=_Config()),
            ):
                server = LlamaServer()

            self.assertEqual(server.model_path.name, "Qwen-2B.gguf")
            self.assertEqual(server.mmproj_path.name, "mmproj-Qwen.gguf")

    def test_client_preserves_openai_multimodal_message_content(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Что на фото?"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ],
        }]

        with patch("main.llm_server.requests.post", return_value=_Response()) as post:
            result = LlamaClient(port=9999).create_chat_completion(messages=messages)

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(post.call_args.kwargs["json"]["messages"], messages)


if __name__ == "__main__":
    unittest.main()
