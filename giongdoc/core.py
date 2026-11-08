"""Shared contracts for every GiongDoc module.

Every module depends only on this file (plus its own internals), so each
workstream can be maintained, tested and replaced independently.

Data flow:
    raw text --(text.pipeline.prepare)--> list[Segment]
    Segment  --(engines.registry.get(engine_id).synthesize)--> AudioClip
    list[AudioClip] + pauses --(audio.smoothing.assemble)--> AudioClip
    AudioClip --(audio.export.export)--> .wav / .mp3 / .m4a
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

import numpy as np

SAMPLE_RATE = 24000  # internal working sample rate (mono, float32 in [-1, 1])


class Language(str, Enum):
    VI = "vi"
    EN = "en"
    KO = "ko"
    ZH = "zh"


@dataclass
class ProsodySettings:
    """User-tunable reading style. Values are multipliers / offsets."""
    rate: float = 1.0          # 0.5 .. 2.0 speaking speed
    pitch: float = 0.0         # semitones, -6 .. +6
    volume: float = 1.0        # 0 .. 2
    pause_scale: float = 1.0   # multiplies every punctuation pause


@dataclass
class Segment:
    """One chunk of text to synthesize, followed by a pause."""
    text: str
    language: Language
    pause_after_ms: int = 0
    voice_id: str | None = None          # None = use document default voice
    prosody: ProsodySettings | None = None  # None = use document default
    emphasis: bool = False


@dataclass
class AudioClip:
    samples: np.ndarray  # float32 mono
    sample_rate: int = SAMPLE_RATE

    @property
    def duration_s(self) -> float:
        return len(self.samples) / float(self.sample_rate)

    @staticmethod
    def silence(ms: int, sample_rate: int = SAMPLE_RATE) -> "AudioClip":
        return AudioClip(np.zeros(int(sample_rate * ms / 1000), dtype=np.float32), sample_rate)


@dataclass
class Voice:
    id: str                 # globally unique, e.g. "edge:vi-VN-HoaiMyNeural"
    name: str               # display name
    language: Language
    engine_id: str
    gender: str = "unknown"
    offline: bool = False
    custom: bool = False    # user-created voice (consent-gated)
    meta: dict = field(default_factory=dict)


class EngineError(RuntimeError):
    pass


@runtime_checkable
class TTSEngine(Protocol):
    id: str
    display_name: str

    def is_available(self) -> bool: ...
    def list_voices(self) -> list[Voice]: ...
    def synthesize(self, text: str, voice: Voice, prosody: ProsodySettings) -> AudioClip: ...
