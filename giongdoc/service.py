"""Orchestration: text -> segments -> engine audio -> smoothed clip.

The UI only talks to this module. It runs synchronously; the UI calls it from
a worker thread and passes `progress` / `is_cancelled` callbacks.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Callable

from .core import AudioClip, EngineError, Language, ProsodySettings, Segment, Voice


class Cancelled(Exception):
    pass


@dataclass
class RenderResult:
    clip: AudioClip
    timeline: list[tuple[float, float, str]] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)


class _LRU(OrderedDict):
    def __init__(self, maxsize: int = 512):
        super().__init__()
        self.maxsize = maxsize

    def put(self, key, value):
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.maxsize:
            self.popitem(last=False)


class SynthesisService:
    """Turns a document into audio. Caches per-sentence audio so editing one
    sentence and re-rendering only re-synthesizes what changed."""

    def __init__(self, dictionary=None, smoothing=None):
        from .audio.smoothing import SmoothingSettings
        from .text.dictionary import PronunciationDict

        self.dictionary = dictionary if dictionary is not None else PronunciationDict.default()
        self.smoothing = smoothing if smoothing is not None else SmoothingSettings()
        self._cache: _LRU = _LRU()

    # ---- voices -------------------------------------------------------
    @staticmethod
    def voices(language: Language | None = None) -> list[Voice]:
        from .engines import registry
        return registry.all_voices(language)

    # ---- core ---------------------------------------------------------
    def prepare(self, text: str, language: Language | None, prosody: ProsodySettings) -> list[Segment]:
        from .text.pipeline import prepare
        return prepare(text, default_language=language, settings=prosody, dictionary=self.dictionary)

    def _voice_for(self, seg: Segment, default_voice_id: str | None) -> Voice:
        from .engines import registry
        vid = seg.voice_id or default_voice_id
        voice = registry.find_voice(vid) if vid else None
        # If the segment is in another language than the chosen voice
        # (mixed text), switch to that language's default voice.
        if voice is None or voice.language != seg.language:
            if voice is not None and seg.voice_id:
                return voice  # explicit [voice:...] wins
            fallback = registry.default_voice(seg.language)
            if fallback is None:
                if voice is None:
                    raise EngineError(f"Không có giọng đọc cho ngôn ngữ {seg.language.value}")
                return voice
            voice = fallback
        return voice

    def _synth_segment(self, seg: Segment, voice: Voice, prosody: ProsodySettings) -> AudioClip:
        from .engines import registry
        key = hashlib.sha1(json.dumps(
            [seg.text, voice.id, asdict(prosody), seg.emphasis], ensure_ascii=False
        ).encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        engine = registry.get(voice.engine_id)
        p = prosody
        if seg.emphasis:  # slightly slower and louder for emphasis
            p = ProsodySettings(rate=prosody.rate * 0.92, pitch=prosody.pitch + 0.5,
                                volume=min(2.0, prosody.volume * 1.1), pause_scale=prosody.pause_scale)
        clip = engine.synthesize(seg.text, voice, p)
        self._cache.put(key, clip)
        return clip

    def render(
        self,
        text: str,
        voice_id: str | None,
        prosody: ProsodySettings | None = None,
        language: Language | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> RenderResult:
        from .audio.timeline import assemble_with_timeline
        from .engines import registry

        prosody = prosody or ProsodySettings()
        if language is None and voice_id:
            v = registry.find_voice(voice_id)
            language = v.language if v else None
        segments = self.prepare(text, language, prosody)
        parts: list[tuple[AudioClip, int]] = []
        texts: list[str] = []
        total = len(segments)
        for i, seg in enumerate(segments):
            if is_cancelled and is_cancelled():
                raise Cancelled()
            if progress:
                progress(i, total, seg.text)
            if not seg.text.strip():
                parts.append((AudioClip.silence(0), seg.pause_after_ms))
                texts.append("")
                continue
            voice = self._voice_for(seg, voice_id)
            clip = self._synth_segment(seg, voice, seg.prosody or prosody)
            parts.append((clip, seg.pause_after_ms))
            texts.append(seg.text)
        if progress:
            progress(total, total, "")
        if not parts:
            return RenderResult(AudioClip.silence(0), [], segments)
        clip, timeline = assemble_with_timeline(parts, texts, self.smoothing)
        timeline = [t for t in timeline if t[2]]
        return RenderResult(clip, timeline, segments)

    def preview_sentence(self, sentence: str, voice_id: str | None,
                         prosody: ProsodySettings | None = None) -> AudioClip:
        """Fast preview of a single selection (no full-document render)."""
        return self.render(sentence, voice_id, prosody).clip
