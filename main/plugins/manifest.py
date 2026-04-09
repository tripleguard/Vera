import json
from dataclasses import dataclass
from typing import Any, Dict, List


class PluginManifestError(Exception):
    pass


@dataclass
class PluginCapability:
    id: str
    title: str
    intents: List[str]
    tool_names: List[str]


@dataclass
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    compatibility: Dict[str, Any]
    capabilities: List[PluginCapability]
    permissions: Dict[str, Any]
    mcp: Dict[str, Any]
    healthcheck: Dict[str, Any]
    signature: Dict[str, Any]
    update_channel: Dict[str, Any]
    raw: Dict[str, Any]


REQUIRED_TOP_LEVEL = [
    "id",
    "version",
    "compatibility",
    "capabilities",
    "permissions",
    "mcp",
    "healthcheck",
    "signature",
    "update_channel",
]


def parse_manifest(payload: Dict[str, Any]) -> PluginManifest:
    if not isinstance(payload, dict):
        raise PluginManifestError("manifest must be a JSON object")

    missing = [key for key in REQUIRED_TOP_LEVEL if key not in payload]
    if missing:
        raise PluginManifestError(f"manifest missing required fields: {', '.join(missing)}")

    plugin_id = str(payload.get("id") or "").strip()
    if not plugin_id:
        raise PluginManifestError("manifest field 'id' must be non-empty")

    name = str(payload.get("name") or plugin_id).strip()
    version = str(payload.get("version") or "").strip()
    if not version:
        raise PluginManifestError("manifest field 'version' must be non-empty")

    capabilities_raw = payload.get("capabilities")
    if not isinstance(capabilities_raw, list):
        raise PluginManifestError("manifest field 'capabilities' must be an array")

    capabilities: List[PluginCapability] = []
    for item in capabilities_raw:
        if not isinstance(item, dict):
            raise PluginManifestError("each capability must be an object")
        cap_id = str(item.get("id") or "").strip()
        if not cap_id:
            raise PluginManifestError("capability.id must be non-empty")
        capabilities.append(
            PluginCapability(
                id=cap_id,
                title=str(item.get("title") or cap_id),
                intents=[str(v) for v in (item.get("intents") or [])],
                tool_names=[str(v) for v in (item.get("tool_names") or [])],
            )
        )

    return PluginManifest(
        plugin_id=plugin_id,
        name=name,
        version=version,
        compatibility=dict(payload.get("compatibility") or {}),
        capabilities=capabilities,
        permissions=dict(payload.get("permissions") or {}),
        mcp=dict(payload.get("mcp") or {}),
        healthcheck=dict(payload.get("healthcheck") or {}),
        signature=dict(payload.get("signature") or {}),
        update_channel=dict(payload.get("update_channel") or {}),
        raw=payload,
    )


def load_manifest_from_text(raw_json: str) -> PluginManifest:
    try:
        payload = json.loads(raw_json)
    except Exception as e:
        raise PluginManifestError(f"manifest is not valid JSON: {e}") from e
    return parse_manifest(payload)
