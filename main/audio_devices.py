"""Audio device discovery and stable selection for PortAudio backends."""

from typing import Any, Optional


class AudioDeviceError(RuntimeError):
    pass


def _get_sounddevice(sd_module=None):
    if sd_module is not None:
        return sd_module
    import sounddevice as sd

    return sd


def normalize_device_selector(value: Any) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip()
    host_api = str(value.get("host_api") or "").strip()
    if not name or not host_api:
        return None
    return {"name": name, "host_api": host_api}


def list_audio_devices(sd_module=None) -> dict:
    """Return serializable input/output device lists with runtime-only indices."""
    sd = _get_sounddevice(sd_module)
    devices = list(sd.query_devices())
    host_apis = list(sd.query_hostapis())
    defaults = list(sd.default.device)
    default_input = defaults[0] if len(defaults) > 0 else -1
    default_output = defaults[1] if len(defaults) > 1 else -1

    inputs = []
    outputs = []
    for index, info in enumerate(devices):
        host_api_index = int(info.get("hostapi", -1))
        host_api = (
            str(host_apis[host_api_index].get("name") or "")
            if 0 <= host_api_index < len(host_apis)
            else "Unknown"
        )
        common = {
            "index": index,
            "name": str(info.get("name") or f"Device {index}"),
            "host_api": host_api,
            "default_samplerate": int(round(float(info.get("default_samplerate") or 0))),
        }
        input_channels = int(info.get("max_input_channels") or 0)
        if input_channels > 0:
            inputs.append({
                **common,
                "direction": "input",
                "channels": input_channels,
                "is_default": index == default_input,
            })
        output_channels = int(info.get("max_output_channels") or 0)
        if output_channels > 0:
            outputs.append({
                **common,
                "direction": "output",
                "channels": output_channels,
                "is_default": index == default_output,
            })

    def sort_key(device: dict):
        host_priority = {
            "windows wasapi": 0,
            "mme": 1,
            "windows directsound": 2,
            "windows wdm-ks": 3,
        }
        return (
            not device["is_default"],
            host_priority.get(device["host_api"].casefold(), 9),
            device["name"].casefold(),
        )

    inputs.sort(key=sort_key)
    outputs.sort(key=sort_key)
    return {"inputs": inputs, "outputs": outputs}


def preferred_audio_devices(device_lists: dict) -> dict:
    """Hide duplicate Windows endpoints exposed through legacy PortAudio APIs."""
    result = {}
    windows_apis = {
        "windows wasapi",
        "mme",
        "windows directsound",
        "windows wdm-ks",
    }
    for direction in ("inputs", "outputs"):
        devices = list(device_lists.get(direction) or [])
        host_apis = {device["host_api"].casefold() for device in devices}
        if not host_apis.intersection(windows_apis):
            result[direction] = devices
            continue

        wasapi = [
            device for device in devices
            if device["host_api"].casefold() == "windows wasapi"
        ]
        if wasapi:
            result[direction] = wasapi
            continue

        # Older Windows installations may not expose WASAPI. Keep one host API
        # instead of showing the same physical device through every backend.
        selected = []
        for host_api in ("mme", "windows directsound", "windows wdm-ks"):
            selected = [
                device for device in devices
                if device["host_api"].casefold() == host_api
            ]
            if selected:
                break
        result[direction] = selected or devices
    return result


def resolve_audio_device(
    kind: str,
    selector: Any = None,
    sd_module=None,
    available_devices: Optional[dict] = None,
) -> dict:
    """Resolve a saved name/host API selector, falling back safely to a default."""
    if kind not in {"input", "output"}:
        raise ValueError(f"Unsupported audio device kind: {kind}")

    device_lists = available_devices if available_devices is not None else list_audio_devices(sd_module)
    collection = device_lists[f"{kind}s"]
    if not collection:
        raise AudioDeviceError(
            "Не найдено ни одного устройства ввода"
            if kind == "input"
            else "Не найдено ни одного устройства воспроизведения"
        )

    normalized = normalize_device_selector(selector)
    if normalized:
        for device in collection:
            if (
                device["name"].casefold() == normalized["name"].casefold()
                and device["host_api"].casefold() == normalized["host_api"].casefold()
            ):
                return {**device, "fallback_reason": None}

    chosen = next((device for device in collection if device["is_default"]), collection[0])
    fallback_reason = None
    if normalized:
        fallback_reason = (
            f"Выбранное устройство недоступно: {normalized['name']} "
            f"({normalized['host_api']}); используется {chosen['name']} ({chosen['host_api']})"
        )
    elif not chosen["is_default"]:
        fallback_reason = (
            f"Системное устройство {kind} не задано; используется "
            f"{chosen['name']} ({chosen['host_api']})"
        )
    return {**chosen, "fallback_reason": fallback_reason}


def choose_input_samplerate(device: dict, preferred: int = 16000, sd_module=None) -> int:
    sd = _get_sounddevice(sd_module)
    rates = [int(preferred), int(device.get("default_samplerate") or 0)]
    last_error = None
    for rate in dict.fromkeys(rate for rate in rates if rate > 0):
        try:
            sd.check_input_settings(
                device=device["index"],
                channels=1,
                dtype="int16",
                samplerate=rate,
            )
            return rate
        except Exception as error:
            last_error = error
    raise AudioDeviceError(
        f"Микрофон {device['name']} не поддерживает подходящий формат: {last_error}"
    )


def choose_output_parameters(device: dict, source_rate: int, sd_module=None) -> dict:
    """Choose a supported output rate and shared WASAPI conversion settings."""
    sd = _get_sounddevice(sd_module)
    extra_settings = None
    if device["host_api"].casefold() == "windows wasapi":
        extra_settings = sd.WasapiSettings(exclusive=False, auto_convert=True)

    rates = [int(source_rate), int(device.get("default_samplerate") or 0)]
    last_error = None
    for rate in dict.fromkeys(rate for rate in rates if rate > 0):
        try:
            sd.check_output_settings(
                device=device["index"],
                channels=1,
                dtype="float32",
                samplerate=rate,
                extra_settings=extra_settings,
            )
            return {"samplerate": rate, "extra_settings": extra_settings}
        except Exception as error:
            last_error = error
    raise AudioDeviceError(
        f"Устройство {device['name']} не поддерживает воспроизведение: {last_error}"
    )
