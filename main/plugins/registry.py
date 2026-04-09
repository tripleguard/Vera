import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class PluginRecord:
    plugin_id: str
    name: str
    version: str
    install_path: str
    trust_level: str
    enabled: bool
    capabilities: List[Dict[str, Any]]
    permissions: Dict[str, Any]
    runtime_profile: str


class PluginRegistry:
    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.records: Dict[str, PluginRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.registry_path.exists():
            self.records = {}
            return
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            self.records = {}
            return

        records: Dict[str, PluginRecord] = {}
        for item in payload.get("plugins", []):
            try:
                record = PluginRecord(
                    plugin_id=str(item["plugin_id"]),
                    name=str(item["name"]),
                    version=str(item["version"]),
                    install_path=str(item["install_path"]),
                    trust_level=str(item.get("trust_level") or "untrusted"),
                    enabled=bool(item.get("enabled", False)),
                    capabilities=list(item.get("capabilities") or []),
                    permissions=dict(item.get("permissions") or {}),
                    runtime_profile=str(item.get("runtime_profile") or "external_command"),
                )
                records[record.plugin_id] = record
            except Exception:
                continue
        self.records = records

    def save(self) -> None:
        payload = {
            "plugins": [asdict(record) for record in self.records.values()]
        }
        self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, record: PluginRecord) -> None:
        self.records[record.plugin_id] = record
        self.save()

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        record = self.records.get(plugin_id)
        if not record:
            return False
        record.enabled = enabled
        self.save()
        return True

    def remove(self, plugin_id: str) -> bool:
        if plugin_id not in self.records:
            return False
        self.records.pop(plugin_id, None)
        self.save()
        return True

    def list_records(self) -> List[PluginRecord]:
        return list(self.records.values())
