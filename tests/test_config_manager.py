import unittest
import json
import tempfile
from pathlib import Path

from main.config_manager import ConfigManager


class ConfigManagerNormalizationTests(unittest.TestCase):
    def test_thinking_budget_is_clamped_to_supported_range(self):
        config = {"model": {"thinking_budget_tokens": 50000}}

        ConfigManager._normalize_model_config(config)

        self.assertEqual(config["model"]["thinking_budget_tokens"], 32768)

    def test_thinking_budget_default_is_added(self):
        config = {"model": {}}

        ConfigManager._normalize_model_config(config)

        self.assertEqual(config["model"]["thinking_budget_tokens"], 1024)

    def test_tts_response_mode_defaults_to_voice_only(self):
        config = {"tts": {}}

        ConfigManager._normalize_tts_config(config)

        self.assertEqual(config["tts"]["speak_responses"], "voice_only")

    def test_invalid_tts_response_mode_is_replaced(self):
        config = {"tts": {"speak_responses": "sometimes"}}

        ConfigManager._normalize_tts_config(config)

        self.assertEqual(config["tts"]["speak_responses"], "voice_only")

    def test_audio_device_selectors_are_normalized(self):
        config = {
            "audio": {
                "input_device": {"name": " Jabra ", "host_api": " Windows WASAPI "},
                "output_device": {"name": "", "host_api": "MME"},
            }
        }

        ConfigManager._normalize_audio_config(config)

        self.assertEqual(config["audio"]["input_device"], {
            "name": "Jabra",
            "host_api": "Windows WASAPI",
        })
        self.assertIsNone(config["audio"]["output_device"])

    def test_set_updates_runtime_and_persisted_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = object.__new__(ConfigManager)
            manager._config = {"audio": {"input_device": None}}
            manager._raw_config = {"audio": {"input_device": None}}
            manager._config_path = Path(temp_dir) / "config.json"

            selector = {"name": "Jabra", "host_api": "Windows WASAPI"}
            manager.set("audio", "input_device", value=selector)
            manager.save()

            self.assertEqual(manager.get("audio", "input_device"), selector)
            saved = json.loads(manager._config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["audio"]["input_device"], selector)


if __name__ == "__main__":
    unittest.main()
