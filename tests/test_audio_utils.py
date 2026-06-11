import unittest

import numpy as np

from main.audio_utils import MAX_TTS_PEAK, apply_tts_volume


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


if __name__ == "__main__":
    unittest.main()
