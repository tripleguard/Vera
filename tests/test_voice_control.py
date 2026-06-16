import unittest

from main.voice_control import (
    is_bare_activation_command,
    is_voice_stop_command,
    strip_activation_phrase,
)


class VoiceControlTests(unittest.TestCase):
    def test_bare_activation_is_control_phrase(self):
        self.assertTrue(is_bare_activation_command("Вера"))
        self.assertTrue(is_voice_stop_command("вера"))

    def test_activation_plus_stop_is_control_phrase(self):
        self.assertTrue(is_voice_stop_command("Вера, стоп"))
        self.assertTrue(is_voice_stop_command("вера стоп"))
        self.assertEqual(strip_activation_phrase("Вера, стоп"), "стоп")

    def test_activation_plus_real_command_is_not_stop(self):
        self.assertFalse(is_voice_stop_command("Вера поставь таймер на пять минут"))
        self.assertFalse(is_bare_activation_command("Вера поставь таймер"))


if __name__ == "__main__":
    unittest.main()
