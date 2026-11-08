"""Text pipeline: raw text (with markup) -> list[Segment] ready for synthesis.

Steps per markup span: split by script (unless [lang:..] forces a language)
-> pronunciation dictionary -> normalization -> clause segmentation.
The pipeline is pure and deterministic.
"""
from __future__ import annotations

import unicodedata

from giongdoc.core import Language, ProsodySettings, Segment
from giongdoc.text.detect import detect_language, split_by_script
from giongdoc.text.dictionary import PronunciationDict
from giongdoc.text.markup import parse_markup, strip_markup
from giongdoc.text.normalize import normalize
from giongdoc.text.segmenter import split_clauses

_DEFAULT_DICT: PronunciationDict | None = None


def _default_dict() -> PronunciationDict:
    global _DEFAULT_DICT
    if _DEFAULT_DICT is None:
        _DEFAULT_DICT = PronunciationDict.default()
    return _DEFAULT_DICT


def prepare(text: str, default_language: Language | None = None,
            settings: ProsodySettings | None = None,
            dictionary: PronunciationDict | None = None) -> list[Segment]:
    """Turn raw text into segments with languages, pauses, voices and prosody.

    - default_language: None = auto-detect from the whole text.
    - settings: document prosody; its pause_scale scales punctuation pauses
      (explicit [pause N] values are used as written).
    - dictionary: None = built-in default Vietnamese set; pass an empty
      PronunciationDict() to disable replacements.
    """
    text = unicodedata.normalize("NFC", text or "")
    settings = settings or ProsodySettings()
    dictionary = _default_dict() if dictionary is None else dictionary
    if default_language is None:
        default_language = detect_language(strip_markup(text))

    segments: list[Segment] = []
    explicit: set[int] = set()  # indices whose pause was set by [pause N]

    def add_pause(ms: int, is_explicit: bool) -> None:
        if not segments:
            if not is_explicit:
                return  # a line break before any text means nothing
            segments.append(Segment("", default_language, 0))
        i = len(segments) - 1
        seg = segments[i]
        if is_explicit:
            # First explicit pause replaces the punctuation pause; more add up.
            seg.pause_after_ms = seg.pause_after_ms + ms if i in explicit else ms
            explicit.add(i)
        elif i not in explicit:
            seg.pause_after_ms = max(seg.pause_after_ms, ms)

    for span in parse_markup(text):
        if span.is_pause:
            add_pause(span.pause_ms, True)
            continue
        prosody = None
        if span.rate is not None:
            prosody = ProsodySettings(rate=settings.rate * span.rate, pitch=settings.pitch,
                                      volume=settings.volume, pause_scale=settings.pause_scale)
        if span.language is not None:
            runs = [(span.text, span.language)]
        else:
            runs = split_by_script(span.text, default_language)
        for run_text, lang in runs:
            cleaned = normalize(dictionary.apply(run_text, lang), lang)
            # normalize() keeps newlines, so line/paragraph pauses survive.
            for clause in split_clauses(cleaned, lang, settings.pause_scale):
                if not clause.text:
                    add_pause(clause.pause_ms, False)
                    continue
                segments.append(Segment(clause.text, lang, clause.pause_ms,
                                        voice_id=span.voice_id, prosody=prosody,
                                        emphasis=span.emphasis))
    return segments

