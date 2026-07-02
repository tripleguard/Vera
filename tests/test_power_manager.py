import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main.commands import power_manager


class PowerManagerTests(unittest.TestCase):
    def setUp(self):
        power_manager._scheduled_shutdown = None

    def test_immediate_shutdown_uses_argv_without_shell(self):
        with patch.object(power_manager, "_run_power_command") as run_power:
            response = power_manager.execute_power_command("выключи компьютер")

        self.assertEqual(response, "Выключаю компьютер.")
        run_power.assert_called_once_with(["shutdown", "/s", "/t", "0"])

    def test_scheduled_restart_uses_argv_seconds(self):
        with patch.object(power_manager, "_run_power_command") as run_power:
            response = power_manager.execute_power_command("перезагрузи компьютер через 10 минут")

        self.assertEqual(response, "Перезагрузка запланировано через 10 мин.")
        run_power.assert_called_once_with(["shutdown", "/r", "/t", "600"])

    def test_cancel_shutdown_uses_argv_without_shell(self):
        power_manager._scheduled_shutdown = "shutdown"
        completed = SimpleNamespace(returncode=0, stderr="")
        with patch.object(power_manager.subprocess, "run", return_value=completed) as run:
            response = power_manager.execute_power_command("отмени выключение")

        self.assertEqual(response, "Запланированное выключение отменено.")
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["shutdown", "/a"])
        self.assertNotIn("shell", kwargs)


if __name__ == "__main__":
    unittest.main()
