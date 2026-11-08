"""Shared helpers for GiongDoc TTS engines.

Converts :class:`giongdoc.core.ProsodySettings` into engine-specific
parameter strings and builds stable cache keys.
"""
from __future__ import annotations

import hashlib
import json
import math

from giongdoc.core import ProsodySettings, Voice

# Reference fundamental frequency used to turn semitones into a Hz offset
# (edge-tts only accepts "+NHz"). ~165 Hz sits between typical male/female F0.
REFERENCE_F0_HZ = 165.0
MACSAY_BASE_WPM = 175  # macOS `say` default speaking rate


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _signed(n: int, unit: str) -> str:
    return f"{'+' if n >= 0 else '-'}{abs(n)}{unit}"


def rate_to_percent(rate: float) -> str:
    """1.2 -> "+20%", 0.8 -> "-20%", 1.0 -> "+0%" (clamped to 0.5..2.0)."""
    rate = clamp(rate, 0.5, 2.0)
    return _signed(int(round((rate - 1.0) * 100)), "%")


def volume_to_percent(volume: float) -> str:
    """1.0 -> "+0%", 0.5 -> "-50%", 1.5 -> "+50%" (clamped to 0..2)."""
    volume = clamp(volume, 0.0, 2.0)
    return _signed(int(round((volume - 1.0) * 100)), "%")


def semitones_to_ratio(semitones: float) -> float:
    return 2.0 ** (semitones / 12.0)


def pitch_to_hz(semitones: float, base_hz: float = REFERENCE_F0_HZ) -> str:
    """Semitone offset -> Hz offset string, e.g. +2 st -> "+20Hz" (clamped -12..12)."""
    st = clamp(semitones, -12.0, 12.0)
    return _signed(int(round(base_hz * (semitones_to_ratio(st) - 1.0))), "Hz")


def pitch_to_percent(semitones: float) -> str:
    """Semitone offset -> relative percent string, e.g. +2 st -> "+12%"."""
    st = clamp(semitones, -12.0, 12.0)
    return _signed(int(round((semitones_to_ratio(st) - 1.0) * 100)), "%")


def rate_to_wpm(rate: float, base_wpm: int = MACSAY_BASE_WPM) -> int:
    """Speed multiplier -> words per minute for macOS `say -r`."""
    return int(round(base_wpm * clamp(rate, 0.5, 2.0)))


def cache_key(engine_id: str, voice: Voice | str, text: str,
              prosody: ProsodySettings | None = None, extra: dict | None = None) -> str:
    """Stable sha256 hex key for (engine, voice, text, prosody, extra).

    ``pause_scale`` is excluded: it does not affect a single synthesized clip.
    """
    p = prosody or ProsodySettings()
    payload = {
        "engine": engine_id,
        "voice": voice.id if isinstance(voice, Voice) else str(voice),
        "text": text,
        "rate": round(float(p.rate), 3),
        "pitch": round(float(p.pitch), 3),
        "volume": round(float(p.volume), 3),
        "extra": extra or {},
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def apply_gain(samples, volume: float):
    """Scale float32 samples by ``volume`` and clip to [-1, 1] (for engines without native volume)."""
    import numpy as np
    if math.isclose(volume, 1.0):
        return samples
    return np.clip(samples * float(clamp(volume, 0.0, 2.0)), -1.0, 1.0).astype(np.float32)
