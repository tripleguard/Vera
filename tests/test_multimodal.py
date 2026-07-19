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
    encoding = None

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}

    def close(self):
        return None


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

        client = LlamaClient(port=9999)
        with patch.object(client._session, "post", return_value=_Response()) as post:
            result = client.create_chat_completion(messages=messages)

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(post.call_args.kwargs["json"]["messages"], messages)

    def test_client_sends_llama_cpp_thinking_budget(self):
        client = LlamaClient(port=9999)
        with patch.object(client._session, "post", return_value=_Response()) as post:
            client.create_chat_completion(
                messages=[{"role": "user", "content": "Привет"}],
                thinking_budget_tokens=768,
            )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["thinking_budget_tokens"], 768)

    def test_client_omits_thinking_budget_when_thinking_disabled(self):
        client = LlamaClient(port=9999)
        with patch.object(client._session, "post", return_value=_Response()) as post:
            client.create_chat_completion(
                messages=[{"role": "user", "content": "РџСЂРёРІРµС‚"}],
                chat_template_kwargs={"enable_thinking": False},
                thinking_budget_tokens=0,
            )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("thinking_budget_tokens", payload)

    def test_stream_parser_uses_low_latency_chunks_and_closes_response(self):
        class _StreamResponse(_Response):
            def __init__(self):
                self.iter_lines_kwargs = None
                self.closed = False

            def iter_lines(self, **kwargs):
                self.iter_lines_kwargs = kwargs
                yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
                yield "data: [DONE]"

            def close(self):
                self.closed = True

        response = _StreamResponse()
        chunks = list(LlamaClient(port=9999)._parse_stream(response))

        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "ok")
        self.assertEqual(
            response.iter_lines_kwargs,
            {"chunk_size": 64, "decode_unicode": True},
        )
        self.assertTrue(response.closed)

    def test_local_server_enables_prompt_cache_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llama-server.exe").write_bytes(b"")
            (root / "Qwen-2B.gguf").write_bytes(b"model")

            with (
                patch("main.llm_server.get_install_root", return_value=root),
                patch("main.llm_server.get_data_dir", return_value=root / "data"),
                patch("main.llm_server.get_config", return_value=_Config()),
                patch("main.llm_server.subprocess.Popen") as popen,
                patch.object(LlamaServer, "_wait_for_health", return_value=True),
                patch("main.llm_server._assign_to_job_object", return_value=0),
            ):
                process = popen.return_value
                process.poll.return_value = None
                server = LlamaServer()
                server.start()
                server.stop()

            command = popen.call_args.args[0]
            reuse_index = command.index("--cache-reuse")
            self.assertEqual(command[reuse_index + 1], "256")
            message_index = command.index("--reasoning-budget-message")
            self.assertIn("финальному ответу", command[message_index + 1])

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
