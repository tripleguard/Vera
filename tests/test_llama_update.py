import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from main import llama_update


class LlamaUpdateTests(unittest.TestCase):
    def setUp(self):
        llama_update._CACHE.update({"checked_at": 0.0, "payload": None})

    def test_parse_build_from_release_tag_and_version_output(self):
        self.assertEqual(llama_update.parse_llama_build("b9753"), 9753)
        self.assertEqual(
            llama_update.parse_llama_build("version: 9219 (45b455e66)"),
            9219,
        )
        self.assertIsNone(llama_update.parse_llama_build("unknown"))

    def test_update_is_available_when_latest_build_is_newer(self):
        release = {
            "tag_name": "b9753",
            "name": "b9753",
            "published_at": "2026-06-21T19:25:44Z",
            "assets": [{
                "name": "llama-b9753-bin-win-vulkan-x64.zip",
                "size": 123,
                "browser_download_url": "https://example.test/vulkan.zip",
            }],
        }
        response = Mock()
        response.json.return_value = release
        response.raise_for_status.return_value = None

        with (
            patch("main.llama_update.get_local_llama_version", return_value={
                "path": "llama-server.exe",
                "raw": "version: 9219",
                "build": 9219,
                "available": True,
            }),
            patch("main.llama_update.requests.get", return_value=response),
        ):
            payload = llama_update.check_llama_update(force_refresh=True)

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["update_available"])
        self.assertEqual(payload["latest"]["build"], 9753)
        self.assertEqual(payload["asset"]["name"], "llama-b9753-bin-win-vulkan-x64.zip")

    def test_local_version_runs_bundled_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "llama-server.exe"
            exe.write_bytes(b"")
            completed = Mock(
                stdout="version: 9219 (45b455e66)",
                stderr="",
                returncode=0,
            )
            with patch("main.llama_update.subprocess.run", return_value=completed) as run:
                payload = llama_update.get_local_llama_version(exe)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["build"], 9219)
        self.assertEqual(Path(run.call_args.args[0][0]).name, "llama-server.exe")
        self.assertEqual(run.call_args.args[0][1], "--version")

    def test_local_version_finds_inno_setup_runtime_above_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp) / "Vera"
            backend_root = app_root / "resources" / "backend"
            backend_root.mkdir(parents=True)
            exe = app_root / "llama-server.exe"
            exe.write_bytes(b"")
            completed = Mock(
                stdout="version: 9992 (6eddde06a)",
                stderr="",
                returncode=0,
            )
            with (
                patch("main.llama_update.get_install_root", return_value=backend_root),
                patch("main.llama_update.subprocess.run", return_value=completed) as run,
            ):
                payload = llama_update.get_local_llama_version()

        self.assertTrue(payload["available"])
        self.assertEqual(payload["build"], 9992)
        self.assertEqual(Path(payload["path"]), exe)
        self.assertEqual(Path(run.call_args.args[0][0]), exe)

    def test_install_latest_update_replaces_runtime_files_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llama-server.exe").write_bytes(b"old exe")
            (root / "llama.dll").write_bytes(b"old dll")

            update_payload = {
                "status": "ok",
                "update_available": True,
                "current": {"build": 9219},
                "latest": {"tag": "b9753", "build": 9753},
                "asset": {"download_url": "https://example.test/runtime.zip"},
            }
            post_payload = {
                "status": "ok",
                "update_available": False,
                "current": {"build": 9753},
                "latest": {"tag": "b9753", "build": 9753},
                "asset": None,
            }

            def write_archive(_asset, destination):
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr("bin/llama-server.exe", b"new exe")
                    archive.writestr("bin/llama.dll", b"new dll")
                    archive.writestr("bin/vulkan-1.dll", b"excluded")

            with (
                patch("main.llama_update.get_install_root", return_value=root),
                patch("main.llama_update.check_llama_update", side_effect=[update_payload, post_payload]),
                patch("main.llama_update._download_asset", side_effect=write_archive),
                patch("main.llama_update._stop_running_llama_server") as stop_server,
            ):
                payload = llama_update.install_latest_llama_update()

            self.assertEqual(payload["status"], "installed")
            self.assertTrue(payload["restart_required"])
            self.assertTrue(stop_server.called)
            self.assertEqual((root / "llama-server.exe").read_bytes(), b"new exe")
            self.assertEqual((root / "llama.dll").read_bytes(), b"new dll")
            self.assertFalse((root / "vulkan-1.dll").exists())
            backup_dir = Path(payload["backup_dir"])
            self.assertEqual((backup_dir / "llama-server.exe").read_bytes(), b"old exe")
            self.assertEqual((backup_dir / "llama.dll").read_bytes(), b"old dll")

    def test_download_asset_reports_github_status_and_asset_url(self):
        class Response:
            status_code = 404

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def raise_for_status(self):
                raise requests.HTTPError("404 Client Error")

        with tempfile.TemporaryDirectory() as tmp, patch("main.llama_update.requests.get", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, "HTTP 404.*llama-test.zip.*example.test"):
                llama_update._download_asset(
                    {
                        "name": "llama-test.zip",
                        "download_url": "https://example.test/llama-test.zip",
                    },
                    Path(tmp) / "runtime.zip",
                )


if __name__ == "__main__":
    unittest.main()
