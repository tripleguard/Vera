from typing import Any

import numpy as np


MAX_TTS_PEAK = 0.72
MAX_TTS_AMPLIFICATION = 10.0


def apply_tts_volume(wav: Any, volume_percent: float) -> np.ndarray:
    """Scale TTS audio to a clean target peak without digital clipping."""
    audio = np.asarray(wav, dtype=np.float32).copy()
    if audio.size == 0:
        return audio

    percent = max(0.0, min(100.0, float(volume_percent)))
    if percent == 0:
        return np.zeros_like(audio)

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    audio -= np.mean(audio, dtype=np.float64)
    peak = float(np.max(np.abs(audio)))
    if peak <= 1e-7:
        return audio

    # The curve gives useful control in the middle while keeping 100% clean.
    target_peak = MAX_TTS_PEAK * ((percent / 100.0) ** 1.35)
    gain = min(target_peak / peak, MAX_TTS_AMPLIFICATION)
    return np.ascontiguousarray(
        np.clip(audio * gain, -MAX_TTS_PEAK, MAX_TTS_PEAK),
        dtype=np.float32,
    )
