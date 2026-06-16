import unittest
from unittest.mock import Mock, patch

from main.commands.system_control import execute_ping_command


class PingCommandTests(unittest.TestCase):
    @patch("main.commands.system_control.subprocess.run")
    def test_ping_yandex_uses_four_requests_to_ya_ru(self, run_mock):
        run_mock.return_value = Mock(
            returncode=0,
            stdout="Среднее = 12мсек",
            stderr="",
        )

        response = execute_ping_command("пингани яндекс")

        self.assertIn("ya.ru отвечает", response)
        self.assertIn("12 мс", response)
        self.assertEqual(run_mock.call_args.args[0], ["ping", "-n", "4", "ya.ru"])

    @patch("main.commands.system_control.subprocess.Popen")
    def test_continuous_ping_uses_t_flag(self, popen_mock):
        response = execute_ping_command("пингуй яндекс")

        self.assertIn("непрерывный пинг ya.ru", response)
        self.assertEqual(popen_mock.call_args.args[0], ["ping", "-t", "ya.ru"])

    def test_ping_requires_a_valid_target(self):
        self.assertIn("Уточните адрес", execute_ping_command("пинг"))
        self.assertIn("Не удалось распознать", execute_ping_command("пингани && shutdown"))


if __name__ == "__main__":
    unittest.main()
