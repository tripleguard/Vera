import unittest
from unittest.mock import patch

from main.feature_flags import TELEGRAM_DISABLED_MESSAGE
from main.tools import TOOLS, execute_telegram_tool as execute_registered_telegram_tool
from main.tools.telegram import execute_telegram_tool
from main.tools.telegram_mode import TelegramMode


class TelegramDisabledTests(unittest.TestCase):
    def test_tool_registry_does_not_expose_telegram(self):
        self.assertNotIn("telegram", TOOLS)

    def test_registered_executor_is_a_safe_noop(self):
        self.assertEqual(
            execute_registered_telegram_tool({"action": "send_message"}),
            TELEGRAM_DISABLED_MESSAGE,
        )

    def test_direct_executor_does_not_start_runtime(self):
        with patch("main.tools.telegram._run") as run:
            result = execute_telegram_tool(
                {"action": "send_message", "contact": "Маша", "message": "Тест"}
            )
        self.assertEqual(result, TELEGRAM_DISABLED_MESSAGE)
        run.assert_not_called()

    def test_mode_does_not_start_thread(self):
        mode = TelegramMode(lambda text: text, lambda query: [])
        with patch("main.tools.telegram_mode.threading.Thread") as thread:
            self.assertFalse(mode.start_in_background())
        thread.assert_not_called()
        self.assertFalse(mode.running)


if __name__ == "__main__":
    unittest.main()
