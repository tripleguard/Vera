import json
import os
import shutil
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from main.audit import AuditLogger
from .manifest import PluginManifest, PluginManifestError, parse_manifest
from .mcp_runtime import McpRuntimeManager
from .registry import PluginRecord, PluginRegistry


@dataclass
class PluginInstallResult:
    ok: bool
    plugin_id: str = ""
    reason: str = ""


class PluginManager:
    def __init__(
        self,
        data_dir: Path,
        cfg: Dict[str, Any],
        ws_send: Callable[[Dict[str, Any]], None],
        audit: AuditLogger,
    ):
        plugins_cfg = (cfg or {}).get("plugins", {}) or {}
        self.enabled = bool(plugins_cfg.get("enabled", True))
        self.trust_policy = str(plugins_cfg.get("trust_policy", "signed+sandbox")).strip().lower()
        inbox = plugins_cfg.get("inbox_path") or str((data_dir / "plugins" / "inbox"))
        self.inbox_path = Path(inbox)
        self.sandbox_defaults = dict(plugins_cfg.get("sandbox_defaults") or {"network": "restricted", "filesystem": "scoped"})

        self.data_dir = data_dir
        self.plugins_root = data_dir / "plugins"
        self.install_root = self.plugins_root / "installed"
        self.registry = PluginRegistry(self.plugins_root / "registry.json")
        self.mcp = McpRuntimeManager()
        self.ws_send = ws_send
        self.audit = audit

        self.server_entry = _discover_server_entry()

        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self.install_root.mkdir(parents=True, exist_ok=True)

        self._stop_event = threading.Event()
        self._watch_thread: Optional[threading.Thread] = None
        self._seen_candidates: set[str] = set()
        self._degraded_notified: set[str] = set()

        # tool_name -> list[{plugin_id, plugin_name, capability_id, capability_title, intents, trust_level, version}]
        self._tool_index: Dict[str, list[Dict[str, Any]]] = {}
        self._index_lock = threading.Lock()

        self._rebuild_capability_index()

    def start(self) -> None:
        if not self.enabled:
            return
        if self._watch_thread and self._watch_thread.is_alive():
            return
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        self._restore_enabled_plugins()

    def shutdown(self) -> None:
        self._stop_event.set()
        self.mcp.shutdown_all()

    def list_plugins(self):
        return self.registry.list_records()

    def get_tool_definitions(self) -> list[dict]:
        """Builds dynamic tool definitions from enabled plugin capabilities."""
        definitions: list[dict] = []
        seen: set[str] = set()
        with self._index_lock:
            for tool_name, providers in self._tool_index.items():
                if tool_name in seen:
                    continue
                if not providers:
                    continue
                provider = self._pick_best_provider(providers)
                intents = [str(v).strip() for v in (provider.get("intents") or []) if str(v).strip()]
                intents_hint = f" Intents: {', '.join(intents[:8])}." if intents else ""
                description = (
                    f"Plugin tool '{tool_name}' from {provider.get('plugin_name')}. "
                    f"Capability: {provider.get('capability_title')}. "
                    "Use when this external integration is the best fit for user intent."
                    f"{intents_hint}"
                )
                definitions.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": description,
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": True,
                            },
                        },
                    }
                )
                seen.add(tool_name)
        return definitions

    def is_plugin_tool(self, tool_name: str) -> bool:
        with self._index_lock:
            providers = self._tool_index.get(tool_name) or []
            return len(providers) > 0

    def resolve_tool(self, tool_name: str, user_text: str = "") -> Optional[Dict[str, Any]]:
        with self._index_lock:
            providers = list(self._tool_index.get(tool_name) or [])
        if not providers:
            return None
        providers = self._filter_usable_providers(providers)
        if not providers:
            return None
        provider = self._pick_best_provider(providers)
        rationale = (
            f"Выбран плагин {provider.get('plugin_name')} ({provider.get('plugin_id')}) "
            f"по capability '{provider.get('capability_title')}' для инструмента '{tool_name}'."
        )
        return {
            "plugin_id": provider.get("plugin_id"),
            "plugin_name": provider.get("plugin_name"),
            "capability_id": provider.get("capability_id"),
            "capability_title": provider.get("capability_title"),
            "rationale": rationale,
        }

    def invoke_tool(self, tool_name: str, args: Dict[str, Any], timeout_sec: float = 20.0) -> Dict[str, Any]:
        with self._index_lock:
            providers = list(self._tool_index.get(tool_name) or [])
        providers = self._filter_usable_providers(providers)
        if not providers:
            return {"ok": False, "error": "plugin_tool_not_found_or_unavailable"}

        primary = self._pick_best_provider(providers)
        ordered = [primary] + [p for p in providers if p is not primary]

        last_error: Dict[str, Any] | None = None
        for provider in ordered:
            plugin_id = str(provider.get("plugin_id") or "")
            if not plugin_id:
                continue

            if not self._ensure_plugin_runtime(plugin_id):
                last_error = {
                    "ok": False,
                    "error": "mcp_not_running",
                    "plugin_id": plugin_id,
                    "plugin_name": provider.get("plugin_name"),
                    "capability_id": provider.get("capability_id"),
                    "rationale": (
                        f"Плагин {provider.get('plugin_name')} ({plugin_id}) недоступен: MCP runtime не запущен."
                    ),
                }
                continue

            result = self.mcp.call_tool(plugin_id, tool_name, args or {}, timeout_sec=timeout_sec)
            result["plugin_id"] = plugin_id
            result["plugin_name"] = provider.get("plugin_name")
            result["capability_id"] = provider.get("capability_id")
            result["rationale"] = (
                f"Выбран плагин {provider.get('plugin_name')} ({plugin_id}) "
                f"по capability '{provider.get('capability_title')}' для инструмента '{tool_name}'."
            )
            if result.get("ok"):
                return result
            last_error = result

        return last_error or {"ok": False, "error": "plugin_call_failed"}

    def enable_plugin(self, plugin_id: str) -> bool:
        record = self.registry.records.get(plugin_id)
        if not record:
            return False

        if record.trust_level != "signed":
            self.audit.write_event(
                "plugin.unsigned_consent",
                {"plugin_id": plugin_id, "trust_level": record.trust_level, "sandbox": self.sandbox_defaults},
            )

        if not self.registry.set_enabled(plugin_id, True):
            return False

        self._activate(record)
        self._rebuild_capability_index()
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        if not self.registry.set_enabled(plugin_id, False):
            return False
        self.mcp.stop(plugin_id)
        self.ws_send({"type": "plugin_install_status", "plugin_id": plugin_id, "status": "disabled"})
        self.audit.write_event("plugin.disabled", {"plugin_id": plugin_id})
        self._rebuild_capability_index()
        return True

    def uninstall_plugin(self, plugin_id: str) -> bool:
        record = self.registry.records.get(plugin_id)
        if not record:
            return False
        self.mcp.stop(plugin_id)
        self.registry.remove(plugin_id)
        try:
            shutil.rmtree(record.install_path, ignore_errors=True)
        except Exception:
            pass
        self.ws_send({"type": "plugin_install_status", "plugin_id": plugin_id, "status": "uninstalled"})
        self.audit.write_event("plugin.uninstalled", {"plugin_id": plugin_id})
        self._rebuild_capability_index()
        return True

    def install_from_package(self, package_path: Path) -> PluginInstallResult:
        self.ws_send({"type": "plugin_discovered", "path": str(package_path)})
        self.audit.write_event("plugin.discovered", {"path": str(package_path)})

        extracted_root: Optional[Path] = None
        try:
            manifest, extracted_root = self._extract_and_load_manifest(package_path)

            trust_level = self._determine_trust(manifest)
            if self.trust_policy == "signed-only" and trust_level != "signed":
                reason = "Политика signed-only блокирует неподписанные плагины"
                self.ws_send({"type": "plugin_install_status", "status": "blocked", "plugin_id": manifest.plugin_id, "reason": reason})
                self.audit.write_event("plugin.install_blocked", {"plugin_id": manifest.plugin_id, "reason": reason})
                return PluginInstallResult(ok=False, plugin_id=manifest.plugin_id, reason=reason)

            target_dir = self.install_root / _safe_id(manifest.plugin_id) / manifest.version
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            shutil.copytree(extracted_root, target_dir, dirs_exist_ok=True)
            if not (target_dir / "manifest.json").exists():
                raise PluginManifestError("install_copy_failed: manifest missing after copy")

            capabilities = [
                {
                    "id": c.id,
                    "title": c.title,
                    "intents": list(c.intents),
                    "tool_names": list(c.tool_names),
                }
                for c in manifest.capabilities
            ]

            runtime_profile = self._runtime_profile(manifest.mcp or {})

            record = PluginRecord(
                plugin_id=manifest.plugin_id,
                name=manifest.name,
                version=manifest.version,
                install_path=str(target_dir),
                trust_level=trust_level,
                enabled=(trust_level == "signed"),
                capabilities=capabilities,
                permissions=dict(manifest.permissions or {}),
                runtime_profile=runtime_profile,
            )
            self.registry.upsert(record)
            self._rebuild_capability_index()

            self.ws_send(
                {
                    "type": "plugin_install_status",
                    "status": "installed",
                    "plugin_id": manifest.plugin_id,
                    "trust_level": trust_level,
                    "enabled": record.enabled,
                    "runtime_profile": runtime_profile,
                }
            )

            if trust_level != "signed":
                self.ws_send(
                    {
                        "type": "plugin_permission_request",
                        "plugin_id": manifest.plugin_id,
                        "message": "Плагин неподписан. Для активации требуется явное подтверждение пользователя.",
                        "permissions": record.permissions,
                        "sandbox": self.sandbox_defaults,
                    }
                )

            self.audit.write_event(
                "plugin.installed",
                {
                    "plugin_id": manifest.plugin_id,
                    "version": manifest.version,
                    "trust_level": trust_level,
                    "enabled": record.enabled,
                    "runtime_profile": runtime_profile,
                    "capabilities": capabilities,
                },
            )

            if record.enabled:
                self._activate(record)

            return PluginInstallResult(ok=True, plugin_id=manifest.plugin_id)

        except PluginManifestError as e:
            self.ws_send({"type": "plugin_install_status", "status": "failed", "path": str(package_path), "reason": str(e)})
            self.audit.write_event("plugin.install_failed", {"path": str(package_path), "reason": str(e)})
            return PluginInstallResult(ok=False, reason=str(e))
        except Exception as e:
            reason = f"Не удалось установить пакет плагина: {e}"
            self.ws_send({"type": "plugin_install_status", "status": "failed", "path": str(package_path), "reason": reason})
            self.audit.write_event("plugin.install_failed", {"path": str(package_path), "reason": reason})
            return PluginInstallResult(ok=False, reason=reason)
        finally:
            if extracted_root and extracted_root.exists():
                shutil.rmtree(extracted_root, ignore_errors=True)

    def _restore_enabled_plugins(self) -> None:
        for record in self.registry.list_records():
            if record.enabled:
                if not self._record_has_manifest(record):
                    self.registry.set_enabled(record.plugin_id, False)
                    self._emit_degraded_once(record.plugin_id, "manifest_not_found_or_invalid")
                    self.audit.write_event(
                        "plugin.auto_disabled",
                        {
                            "plugin_id": record.plugin_id,
                            "reason": "manifest_not_found_or_invalid",
                            "install_path": record.install_path,
                        },
                    )
                    continue
                self._activate(record)
        self._rebuild_capability_index()

    def _activate(self, record: PluginRecord) -> None:
        install_path = Path(record.install_path)
        manifest = self._read_installed_manifest(install_path)
        if manifest is None:
            self.ws_send(
                {
                    "type": "plugin_install_status",
                    "status": "degraded",
                    "plugin_id": record.plugin_id,
                    "reason": "manifest_not_found_or_invalid",
                }
            )
            return

        mcp_cfg = manifest.mcp or {}
        if str(mcp_cfg.get("transport") or "stdio") != "stdio":
            self.ws_send(
                {
                    "type": "plugin_install_status",
                    "status": "partial",
                    "plugin_id": record.plugin_id,
                    "reason": "Сейчас поддерживается только MCP stdio transport",
                }
            )
            return

        try:
            command, args, env_overrides, runtime_profile = self._resolve_launch(mcp_cfg, install_path)
        except Exception as e:
            self.ws_send(
                {
                    "type": "plugin_install_status",
                    "status": "degraded",
                    "plugin_id": record.plugin_id,
                    "reason": f"launch_resolve_failed: {e}",
                }
            )
            self.audit.write_event("plugin.activation_failed", {"plugin_id": record.plugin_id, "error": str(e)})
            return

        if record.runtime_profile != runtime_profile:
            record.runtime_profile = runtime_profile
            self.registry.upsert(record)

        started = self.mcp.start_stdio(record.plugin_id, command, args, install_path, env_overrides=env_overrides)
        self.ws_send(
            {
                "type": "plugin_install_status",
                "status": "active" if started else "degraded",
                "plugin_id": record.plugin_id,
                "runtime_profile": runtime_profile,
                "mcp_health": self.mcp.health(record.plugin_id),
            }
        )

        for cap in record.capabilities:
            self.ws_send(
                {
                    "type": "plugin_capability_added",
                    "plugin_id": record.plugin_id,
                    "capability": cap,
                }
            )

        self.audit.write_event(
            "plugin.activated",
            {
                "plugin_id": record.plugin_id,
                "runtime_profile": runtime_profile,
                "capabilities": record.capabilities,
            },
        )
        self._rebuild_capability_index()

    def _resolve_launch(self, mcp_cfg: Dict[str, Any], install_path: Path) -> tuple[str, list[str], Dict[str, str], str]:
        runtime_profile = self._runtime_profile(mcp_cfg)
        if runtime_profile == "vera_python":
            command, args, env = self._resolve_vera_python_launch(mcp_cfg, install_path)
            return command, args, env, runtime_profile

        command, args, env = self._resolve_external_launch(mcp_cfg, install_path)
        return command, args, env, runtime_profile

    def _runtime_profile(self, mcp_cfg: Dict[str, Any]) -> str:
        runtime = str(mcp_cfg.get("runtime") or mcp_cfg.get("launcher") or "").strip().lower()
        if runtime in {"vera_python", "vera", "vera-host", "vera_host"}:
            return "vera_python"
        return "external_command"

    def _resolve_vera_python_launch(self, mcp_cfg: Dict[str, Any], install_path: Path) -> tuple[str, list[str], Dict[str, str]]:
        entrypoint = self._expand_vars(str(mcp_cfg.get("entrypoint") or "plugin_entry.py"), install_path)
        entry_path = (install_path / entrypoint).resolve()
        if not entry_path.exists():
            raise RuntimeError(f"entrypoint not found: {entry_path}")
        env = self._base_launch_env(install_path)
        env["VERA_PLUGIN_ENTRYPOINT"] = str(entry_path)

        user_env = mcp_cfg.get("env") or {}
        if isinstance(user_env, dict):
            for key, value in user_env.items():
                env[str(key)] = self._expand_vars(str(value), install_path)

        if getattr(sys, "frozen", False):
            command = str(Path(sys.executable).resolve())
            args = [
                "--plugin-host",
                "--plugin-dir",
                str(install_path),
                "--entrypoint",
                entrypoint,
            ]
            return command, args, env

        if not self.server_entry or not self.server_entry.exists():
            raise RuntimeError("server.py entry not found for source runtime")

        command = str(Path(sys.executable).resolve())
        args = [
            str(self.server_entry),
            "--plugin-host",
            "--plugin-dir",
            str(install_path),
            "--entrypoint",
            entrypoint,
        ]
        return command, args, env

    def _resolve_external_launch(self, mcp_cfg: Dict[str, Any], install_path: Path) -> tuple[str, list[str], Dict[str, str]]:
        raw_command = str(mcp_cfg.get("command") or "").strip()
        if not raw_command:
            raise RuntimeError("mcp.command is required for external_command runtime")

        expanded_command = self._expand_vars(raw_command, install_path)
        command_path = Path(expanded_command)
        if not command_path.is_absolute() and ("/" in expanded_command or "\\" in expanded_command):
            candidate = (install_path / command_path).resolve()
            command = str(candidate) if candidate.exists() else expanded_command
        else:
            command = expanded_command

        args = [self._expand_vars(str(v), install_path) for v in (mcp_cfg.get("args") or [])]

        env = self._base_launch_env(install_path)
        user_env = mcp_cfg.get("env") or {}
        if isinstance(user_env, dict):
            for key, value in user_env.items():
                env[str(key)] = self._expand_vars(str(value), install_path)

        return command, args, env

    def _base_launch_env(self, install_path: Path) -> Dict[str, str]:
        env = {
            "VERA_PLUGIN_DIR": str(install_path),
            "VERA_DATA_DIR": str(self.data_dir),
            "VERA_INSTALL_ROOT": str(Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else self.server_entry.parent),
            "VERA_EXECUTABLE": str(Path(sys.executable).resolve()),
            "VERA_IS_FROZEN": "1" if getattr(sys, "frozen", False) else "0",
        }
        if self.server_entry:
            env["VERA_SERVER_ENTRY"] = str(self.server_entry)
        return env

    def _expand_vars(self, value: str, install_path: Path) -> str:
        mapping = self._base_launch_env(install_path)
        result = str(value)
        for key, mapped in mapping.items():
            result = result.replace("${" + key + "}", mapped)
            result = result.replace("{" + key + "}", mapped)
        return result

    def _extract_and_load_manifest(self, package_path: Path) -> tuple[PluginManifest, Path]:
        if package_path.suffix.lower() != ".vera-plugin":
            raise PluginManifestError("Поддерживаются только пакеты .vera-plugin")

        temp_root = self.plugins_root / ".tmp" / f"extract-{int(time.time() * 1000)}"
        temp_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(package_path, "r") as archive:
            archive.extractall(temp_root)

        manifest_path = temp_root / "manifest.json"
        if not manifest_path.exists():
            raise PluginManifestError("В пакете отсутствует manifest.json")

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = parse_manifest(payload)
        return manifest, temp_root

    def _determine_trust(self, manifest: PluginManifest) -> str:
        signature = manifest.signature or {}
        required = bool(signature.get("required", False))
        signed_flag = bool(signature.get("signed", False))

        if signed_flag:
            return "signed"
        if required:
            return "untrusted"
        return "unsigned"

    def _read_installed_manifest(self, install_path: Path) -> Optional[PluginManifest]:
        path = install_path / "manifest.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return parse_manifest(payload)
        except Exception:
            return None

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                for package in self.inbox_path.glob("*.vera-plugin"):
                    key = str(package.resolve())
                    if key in self._seen_candidates:
                        continue
                    self._seen_candidates.add(key)
                    self.install_from_package(package)
            except Exception as e:
                self.ws_send({"type": "plugin_install_status", "status": "watcher_error", "reason": str(e)})
            self._stop_event.wait(5.0)

    def _rebuild_capability_index(self) -> None:
        index: Dict[str, list[Dict[str, Any]]] = {}
        for record in self.registry.list_records():
            if not record.enabled:
                continue
            if not self._record_has_manifest(record):
                self.registry.set_enabled(record.plugin_id, False)
                self._emit_degraded_once(record.plugin_id, "manifest_not_found_or_invalid")
                self.audit.write_event(
                    "plugin.auto_disabled",
                    {
                        "plugin_id": record.plugin_id,
                        "reason": "manifest_not_found_or_invalid",
                        "install_path": record.install_path,
                    },
                )
                continue
            for cap in record.capabilities or []:
                tool_names = [str(v).strip() for v in (cap.get("tool_names") or []) if str(v).strip()]
                if not tool_names:
                    continue
                for tool_name in tool_names:
                    index.setdefault(tool_name, []).append(
                        {
                            "plugin_id": record.plugin_id,
                            "plugin_name": record.name,
                            "capability_id": str(cap.get("id") or tool_name),
                            "capability_title": str(cap.get("title") or cap.get("id") or tool_name),
                            "intents": list(cap.get("intents") or []),
                            "trust_level": record.trust_level,
                            "version": record.version,
                        }
                    )
        with self._index_lock:
            self._tool_index = index

    def _record_has_manifest(self, record: PluginRecord) -> bool:
        try:
            install_path = Path(record.install_path)
            manifest_path = install_path / "manifest.json"
            return install_path.exists() and manifest_path.exists() and manifest_path.is_file()
        except Exception:
            return False

    def _emit_degraded_once(self, plugin_id: str, reason: str) -> None:
        key = f"{plugin_id}:{reason}"
        if key in self._degraded_notified:
            return
        self._degraded_notified.add(key)
        self.ws_send(
            {
                "type": "plugin_install_status",
                "status": "degraded",
                "plugin_id": plugin_id,
                "reason": reason,
            }
        )

    def _filter_usable_providers(self, providers: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        usable: list[Dict[str, Any]] = []
        for provider in providers:
            plugin_id = str(provider.get("plugin_id") or "")
            record = self.registry.records.get(plugin_id)
            if not record or not record.enabled:
                continue
            if not self._record_has_manifest(record):
                continue
            usable.append(provider)
        return usable

    def _ensure_plugin_runtime(self, plugin_id: str) -> bool:
        health = self.mcp.health(plugin_id)
        if health == "running":
            return True
        record = self.registry.records.get(plugin_id)
        if not record or not record.enabled:
            return False
        if not self._record_has_manifest(record):
            return False
        self._activate(record)
        return self.mcp.health(plugin_id) == "running"

    def _pick_best_provider(self, providers: list[Dict[str, Any]]) -> Dict[str, Any]:
        if len(providers) == 1:
            return providers[0]

        def trust_rank(value: str) -> int:
            val = (value or "").strip().lower()
            if val == "signed":
                return 0
            if val == "unsigned":
                return 1
            return 2

        def version_tuple(value: str) -> tuple:
            raw = str(value or "")
            parts: list[int] = []
            for token in raw.replace("-", ".").split("."):
                token = token.strip()
                if not token:
                    continue
                if token.isdigit():
                    parts.append(int(token))
                else:
                    number = ""
                    for ch in token:
                        if ch.isdigit():
                            number += ch
                        else:
                            break
                    parts.append(int(number) if number else 0)
            if not parts:
                parts = [0]
            return tuple(parts)

        by_trust = sorted(providers, key=lambda p: trust_rank(str(p.get("trust_level") or "")))
        best_rank = trust_rank(str(by_trust[0].get("trust_level") or ""))
        same_rank = [p for p in by_trust if trust_rank(str(p.get("trust_level") or "")) == best_rank]
        same_rank.sort(key=lambda p: version_tuple(str(p.get("version") or "0")), reverse=True)
        return same_rank[0]


def _safe_id(value: str) -> str:
    sanitized = [ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value]
    return "".join(sanitized).strip("._") or "plugin"


def _discover_server_entry() -> Path:
    # main/plugins/manager.py -> project_root/server.py
    return Path(__file__).resolve().parents[2] / "server.py"
