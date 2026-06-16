import unittest

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


if __name__ == "__main__":
    unittest.main()
