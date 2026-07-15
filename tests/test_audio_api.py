import asyncio
import importlib.util
import json
import queue
import sys
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class FakeConfig:
    def __init__(self):
        self.audio = {"input_device": None, "output_device": None}
        self.saved = 0

    def get(self, *keys, default=None):
        current = {"audio": self.audio}
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def set(self, *keys, value):
        assert keys[0] == "audio"
        self.audio[keys[1]] = value

    def save(self):
        self.saved += 1


def load_server(fake_agent):
    spec = importlib.util.spec_from_file_location("vera_audio_test_server", ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"main.agent": fake_agent}):
        spec.loader.exec_module(module)
    return module


def make_agent():
    agent = types.ModuleType("main.agent")
    agent._ws_out_queue = queue.Queue()
    agent.queue_command = lambda *args, **kwargs: None
    agent.get_agent_readiness = lambda: {
        "audio_ready": True,
        "components": {
            "stt": {"status": "ready", "error": None},
            "audio": {"status": "ready", "error": None},
        },
    }
    return agent


def install_device_fakes(server, config):
    server.get_config = lambda: config
    server.list_audio_devices = lambda: {"inputs": [{}], "outputs": [{}]}
    server.resolve_audio_device = lambda kind, selector, available_devices=None: {
        "index": 4,
        "name": selector["name"] if selector else "System device",
        "host_api": selector["host_api"] if selector else "MME",
        "default_samplerate": 48000,
        "fallback_reason": None,
    }
    server.choose_input_samplerate = lambda device: 16000
    server.choose_output_parameters = lambda device, rate: {
        "samplerate": rate,
        "extra_settings": None,
    }


def test_output_device_is_persisted_and_applied_immediately():
    fake_agent = make_agent()
    fake_agent.reconfigure_audio_output = lambda selector: {
        "name": selector["name"],
        "host_api": selector["host_api"],
        "default_samplerate": 48000,
        "playback_samplerate": 44100,
    }
    server = load_server(fake_agent)
    config = FakeConfig()
    install_device_fakes(server, config)
    selector = {"name": "Speakers", "host_api": "Windows WASAPI"}

    with patch.dict(sys.modules, {"main.agent": fake_agent}):
        response = asyncio.run(server.set_audio_device_api({"kind": "output", "device": selector}))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["status"] == "applied"
    assert config.audio["output_device"] == selector
    assert config.saved == 1


def test_failed_input_switch_rolls_back_persisted_selector():
    fake_agent = make_agent()
    switch_count = 0

    def request_switch():
        nonlocal switch_count
        switch_count += 1

    def readiness():
        failed = switch_count == 1
        return {
            "audio_ready": not failed,
            "components": {
                "stt": {"status": "ready", "error": None},
                "audio": {"status": "error" if failed else "ready", "error": "device busy" if failed else None},
            },
        }

    fake_agent.request_audio_input_switch = request_switch
    fake_agent.wait_audio_input_switch = lambda timeout: True
    fake_agent.get_agent_readiness = readiness
    server = load_server(fake_agent)
    server.get_agent_readiness = readiness
    config = FakeConfig()
    install_device_fakes(server, config)
    selector = {"name": "Busy microphone", "host_api": "Windows WASAPI"}

    with patch.dict(sys.modules, {"main.agent": fake_agent}):
        response = asyncio.run(server.set_audio_device_api({"kind": "input", "device": selector}))

    payload = json.loads(response.body)
    assert response.status_code == 409
    assert payload["error"] == "device busy"
    assert config.audio["input_device"] is None
    assert config.saved == 2
    assert switch_count == 2
