"""Inline markup parser.

Supported (see docs/ARCHITECTURE.md):
    [pause 800] / [ngat 800]          silence of 800 ms
    [voice:edge:vi-VN-NamMinhNeural]...[/voice]
    [lang:ko]...[/lang]               force language
    [rate 0.8]...[/rate]              relative speaking rate
    *word*                            emphasis
Tags may nest; unclosed tags run to the end; stray closing tags are ignored;
unknown bracket text is kept as plain text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from giongdoc.core import Language

_TAG_RE = re.compile(
    r"""
    \[\s*(?:pause|ngat|ngắt|ngừng|break)\s*[:=]?\s*(?P<pause>\d+)\s*(?:ms)?\s*\]
  | \[\s*voice\s*[:=]\s*(?P<voice>[^\]\s][^\]]*?)\s*\]
  | \[\s*/\s*voice\s*\]
  | \[\s*lang\s*[:=]\s*(?P<lang>[A-Za-z_-]+)\s*\]
  | \[\s*/\s*lang\s*\]
  | \[\s*rate\s*[:=]?\s*(?P<rate>\d+(?:\.\d+)?)\s*\]
  | \[\s*/\s*rate\s*\]
  | (?<![*\w])\*{1,2}(?=\S)(?P<emph>[^*\n]+?)(?<=\S)\*{1,2}(?![*\w])
    """,
    re.I | re.X,
)

_LANG_ALIASES = {"vi": Language.VI, "vn": Language.VI, "en": Language.EN, "ko": Language.KO,
                 "kr": Language.KO, "kor": Language.KO, "zh": Language.ZH, "cn": Language.ZH,
                 "cmn": Language.ZH}


def parse_language(code: str | None) -> Language | None:
    """Map 'vi', 'vi-VN', 'kr', 'zh_CN'... to a Language (None if unknown)."""
    if not code:
        return None
    code = code.strip().lower().replace("_", "-")
    return _LANG_ALIASES.get(code) or _LANG_ALIASES.get(code.split("-")[0])


@dataclass
class Span:
    """A run of text sharing the same attributes, or a pause marker (text == '')."""
    text: str
    language: Language | None = None
    voice_id: str | None = None
    rate: float | None = None
    emphasis: bool = False
    pause_ms: int | None = None

    @property
    def is_pause(self) -> bool:
        return self.pause_ms is not None

    def same_style(self, other: "Span") -> bool:
        return (self.language, self.voice_id, self.rate, self.emphasis) == (
            other.language, other.voice_id, other.rate, other.emphasis)


def parse_markup(text: str) -> list[Span]:
    """Parse inline markup into a flat list of spans."""
    spans: list[Span] = []
    voices: list[str] = []
    langs: list[Language | None] = []
    rates: list[float] = []

    def emit(chunk: str, emphasis: bool = False) -> None:
        if not chunk:
            return
        span = Span(chunk, langs[-1] if langs else None, voices[-1] if voices else None,
                    rates[-1] if rates else None, emphasis)
        if spans and not spans[-1].is_pause and spans[-1].same_style(span):
            spans[-1].text += chunk
        else:
            spans.append(span)

    pos = 0
    for m in _TAG_RE.finditer(text or ""):
        emit(text[pos:m.start()])
        pos = m.end()
        tag = m.group(0).lower().replace(" ", "")
        if m.group("pause") is not None:
            spans.append(Span("", pause_ms=int(m.group("pause"))))
        elif m.group("voice") is not None:
            voices.append(m.group("voice"))
        elif m.group("lang") is not None:
            langs.append(parse_language(m.group("lang")))
        elif m.group("rate") is not None:
            rates.append(min(4.0, max(0.25, float(m.group("rate")))))
        elif m.group("emph") is not None:
            emit(m.group("emph"), emphasis=True)
        elif tag == "[/voice]":
            voices and voices.pop()
        elif tag == "[/lang]":
            langs and langs.pop()
        elif tag == "[/rate]":
            rates and rates.pop()
    emit((text or "")[pos:])
    return spans


def strip_markup(text: str) -> str:
    """Return the plain text without any markup (pauses become spaces)."""
    return "".join(s.text if not s.is_pause else " " for s in parse_markup(text))
