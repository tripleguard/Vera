import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main.llm_server import LlamaClient, LlamaServer


class _Config:
    def get(self, *_args, **_kwargs):
        return _kwargs.get("default", "auto")


class _Response:
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class MultimodalTests(unittest.TestCase):
    def test_model_discovery_does_not_select_mmproj_as_main_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llama-server.exe").write_bytes(b"")
            (root / "mmproj-Qwen-2B.gguf").write_bytes(b"projector")
            (root / "Qwen-2B.gguf").write_bytes(b"model")

            with (
                patch("main.llm_server.get_install_root", return_value=root),
                patch("main.llm_server.get_config", return_value=_Config()),
            ):
                server = LlamaServer()

            self.assertEqual(server.model_path.name, "Qwen-2B.gguf")
            self.assertEqual(server.mmproj_path.name, "mmproj-Qwen-2B.gguf")

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

    def test_incompatible_mmproj_is_not_attached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llama-server.exe").write_bytes(b"")
            (root / "mmproj-Qwen3.5-2B-BF16.gguf").write_bytes(b"projector")
            (root / "Qwen3.5-4B-Q4_K_S.gguf").write_bytes(b"model")

            with (
                patch("main.llm_server.get_install_root", return_value=root),
                patch("main.llm_server.get_config", return_value=_Config()),
            ):
                server = LlamaServer()

            self.assertIsNone(server.mmproj_path)

    def test_single_generic_mmproj_is_used_as_model_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llama-server.exe").write_bytes(b"")
            (root / "mmproj-F32.gguf").write_bytes(b"projector")
            (root / "Qwen3.5-4B-Q4_K_S.gguf").write_bytes(b"model")

            with (
                patch("main.llm_server.get_install_root", return_value=root),
                patch("main.llm_server.get_config", return_value=_Config()),
            ):
                server = LlamaServer()

            self.assertEqual(server.mmproj_path.name, "mmproj-F32.gguf")

    def test_projector_is_matched_by_model_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llama-server.exe").write_bytes(b"")
            (root / "Qwen2-VL-7B-mmproj-F16.gguf").write_bytes(b"projector")
            (root / "Llama-3.2-11B-Vision-mmproj-F16.gguf").write_bytes(b"projector")
            (root / "Llama-3.2-11B-Vision-Q4_K_M.gguf").write_bytes(b"model")

            with (
                patch("main.llm_server.get_install_root", return_value=root),
                patch("main.llm_server.get_config", return_value=_Config()),
            ):
                server = LlamaServer()

            self.assertEqual(
                server.mmproj_path.name,
                "Llama-3.2-11B-Vision-mmproj-F16.gguf",
            )

    def test_external_base_url_accepts_optional_v1_suffix(self):
        self.assertEqual(
            LlamaClient(base_url="http://127.0.0.1:1234")._chat_url,
            "http://127.0.0.1:1234/v1/chat/completions",
        )
        self.assertEqual(
            LlamaClient(base_url="http://127.0.0.1:1234/v1")._chat_url,
            "http://127.0.0.1:1234/v1/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
