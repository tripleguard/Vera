import unittest

import numpy as np

from main.audio_utils import (
    MAX_TTS_PEAK,
    apply_tts_volume,
    resample_audio,
    should_speak_response,
)


class TtsVolumeTests(unittest.TestCase):
    def setUp(self):
        self.wav = np.array([[0.0, 0.1, -0.2, 0.35, -0.3]], dtype=np.float32)

    def test_mute_returns_silence(self):
        result = apply_tts_volume(self.wav, 0)
        self.assertTrue(np.all(result == 0))

    def test_output_never_clips(self):
        result = apply_tts_volume(self.wav, 100)
        self.assertLessEqual(float(np.max(np.abs(result))), MAX_TTS_PEAK + 1e-6)

    def test_higher_percent_is_louder(self):
        quiet = apply_tts_volume(self.wav, 25)
        normal = apply_tts_volume(self.wav, 50)
        self.assertGreater(
            float(np.sqrt(np.mean(normal ** 2))),
            float(np.sqrt(np.mean(quiet ** 2))),
        )

    def test_resample_audio_preserves_duration_and_channels(self):
        stereo = np.column_stack((np.linspace(-1, 1, 441), np.linspace(1, -1, 441)))

        result = resample_audio(stereo, 44100, 16000)

        self.assertEqual(result.shape, (160, 2))
        self.assertEqual(result.dtype, np.float32)

    def test_voice_only_is_the_default_response_mode(self):
        self.assertTrue(should_speak_response("voice_only", "voice"))
        self.assertFalse(should_speak_response("voice_only", "chat"))
        self.assertFalse(should_speak_response("invalid", "chat"))
        self.assertTrue(should_speak_response("all", "chat"))
        self.assertFalse(should_speak_response("off", "voice"))


if __name__ == "__main__":
    unittest.main()
