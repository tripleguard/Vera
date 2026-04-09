import json
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class McpProcessHandle:
    plugin_id: str
    command: str
    args: List[str]
    cwd: Path
    process: subprocess.Popen


class McpRuntimeManager:
    """Minimal stdio MCP process manager foundation (transport orchestration + tools/call bridge)."""

    def __init__(self):
        self._handles: Dict[str, McpProcessHandle] = {}
        self._lock = threading.Lock()

    def start_stdio(
        self,
        plugin_id: str,
        command: str,
        args: List[str],
        cwd: Path,
        env_overrides: Dict[str, str] | None = None,
    ) -> bool:
        with self._lock:
            existing = self._handles.get(plugin_id)
            if existing and existing.process.poll() is None:
                return True

            try:
                child_env = os.environ.copy()
                if env_overrides:
                    for key, value in env_overrides.items():
                        child_env[str(key)] = str(value)
                proc = subprocess.Popen(
                    [command, *args],
                    cwd=str(cwd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=child_env,
                )
            except Exception:
                return False

            self._handles[plugin_id] = McpProcessHandle(
                plugin_id=plugin_id,
                command=command,
                args=list(args),
                cwd=cwd,
                process=proc,
            )
            return True

    def call_tool(self, plugin_id: str, tool_name: str, args: Dict[str, Any], timeout_sec: float = 15.0) -> Dict[str, Any]:
        """Best-effort MCP stdio tools/call request with timeout and JSON-RPC response parsing."""
        with self._lock:
            handle = self._handles.get(plugin_id)
            if not handle:
                return {"ok": False, "error": "mcp_not_running"}
            process = handle.process

        if process.poll() is not None or not process.stdin or not process.stdout:
            return {"ok": False, "error": "mcp_not_running"}

        request_id = f"vera-{uuid.uuid4()}"
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args or {}},
        }

        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except Exception as e:
            return {"ok": False, "error": f"write_failed: {e}"}

        deadline = time.monotonic() + max(1.0, timeout_sec)
        while time.monotonic() < deadline:
            remaining = max(0.2, deadline - time.monotonic())
            line = self._read_line_with_timeout(process.stdout, remaining)
            if line is None:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            try:
                response = json.loads(stripped)
            except Exception:
                # Some MCP servers may log plaintext to stdout; skip and continue.
                continue

            if str(response.get("id")) != request_id:
                continue
            if "error" in response:
                return {"ok": False, "error": response.get("error")}
            return {"ok": True, "result": response.get("result")}

        return {"ok": False, "error": "timeout"}

    def _read_line_with_timeout(self, stream, timeout_sec: float) -> str | None:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(stream.readline)
            try:
                return future.result(timeout=max(0.1, timeout_sec))
            except FutureTimeout:
                return None
            except Exception:
                return None

    def stop(self, plugin_id: str) -> bool:
        with self._lock:
            handle = self._handles.get(plugin_id)
            if not handle:
                return False
            try:
                if handle.process.poll() is None:
                    handle.process.terminate()
                    handle.process.wait(timeout=3)
            except Exception:
                try:
                    handle.process.kill()
                except Exception:
                    pass
            self._handles.pop(plugin_id, None)
            return True

    def health(self, plugin_id: str) -> str:
        with self._lock:
            handle = self._handles.get(plugin_id)
            if not handle:
                return "stopped"
            if handle.process.poll() is None:
                return "running"
            return "crashed"

    def shutdown_all(self) -> None:
        for plugin_id in list(self._handles.keys()):
            self.stop(plugin_id)
