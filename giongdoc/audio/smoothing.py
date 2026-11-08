"""Join synthesized sentence clips into one smooth, human-sounding track."""
from __future__ import annotations

from dataclasses import dataclass

from ..core import SAMPLE_RATE, AudioClip


@dataclass
class SmoothingSettings:
    trim: bool = True                # cut leading/trailing engine silence
    trim_threshold_db: float = -45.0
    trim_keep_ms: float = 30.0       # breathing room kept around speech
    crossfade_ms: float = 25.0       # equal-power overlap when pause == 0
    fade_ms: float = 8.0             # raised-cosine fade at clip edges next to pauses
    normalize_each: bool = True      # loudness-match every clip before joining
    target_lufs: float = -16.0
    peak_ceiling_db: float = -1.0
    room_tone_db: float = -60.0      # RMS dBFS of a faint noise bed; 0 disables
    pause_jitter_pct: float = 8.0    # +/- variation of pause lengths (deterministic)
    breath: bool = False             # soft synthetic in-breath in longer pauses
    breath_min_pause_ms: int = 450
    breath_db: float = -30.0         # breath RMS relative to target loudness (dB)
    seed: int = 1234                 # makes jitter / room tone / breaths reproducible
    sample_rate: int = SAMPLE_RATE


def assemble(parts: list[tuple[AudioClip, int]], settings: SmoothingSettings | None = None) -> AudioClip:
    """Join ``(clip, pause_after_ms)`` pairs into one clip.

    Each clip is resampled, DC-removed, loudness-matched, trimmed and faded;
    pauses (with room tone, optional breaths and a small seeded jitter) are
    inserted, ``pause == 0`` joins use an equal-power crossfade, and the
    result is loudness-normalized and soft-limited. Deterministic.
    """
    from .timeline import assemble_with_timeline

    clip, _ = assemble_with_timeline(parts, None, settings)
    return clip
