from typing import Any

import numpy as np


MAX_TTS_PEAK = 0.72
MAX_TTS_AMPLIFICATION = 10.0
TTS_RESPONSE_MODES = {"voice_only", "all", "off"}


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


def resample_audio(audio: Any, source_rate: int, target_rate: int) -> np.ndarray:
    """Linearly resample mono or frames-first audio without another dependency."""
    samples = np.asarray(audio, dtype=np.float32)
    if samples.size == 0 or int(source_rate) == int(target_rate):
        return np.ascontiguousarray(samples)
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("Sample rates must be positive")

    was_mono = samples.ndim == 1
    frames = samples[:, None] if was_mono else samples
    if frames.ndim != 2:
        raise ValueError("Audio must be mono or a frames-first 2D array")
    output_frames = max(1, int(round(frames.shape[0] * target_rate / source_rate)))
    source_positions = np.arange(frames.shape[0], dtype=np.float64)
    target_positions = np.linspace(0, max(0, frames.shape[0] - 1), output_frames)
    result = np.empty((output_frames, frames.shape[1]), dtype=np.float32)
    for channel in range(frames.shape[1]):
        result[:, channel] = np.interp(target_positions, source_positions, frames[:, channel])
    return np.ascontiguousarray(result[:, 0] if was_mono else result)


def should_speak_response(mode: str, source: str) -> bool:
    normalized = mode if mode in TTS_RESPONSE_MODES else "voice_only"
    return normalized == "all" or (normalized == "voice_only" and source == "voice")
