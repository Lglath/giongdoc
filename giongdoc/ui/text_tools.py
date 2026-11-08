"""Pure-Python text helpers used by the editor (no Qt imports, easy to test)."""
from __future__ import annotations

import re
import unicodedata

# ---- markup -----------------------------------------------------------
PAUSE_RE = re.compile(r"\[(?:pause|ngat)\s+(\d+)\s*\]", re.IGNORECASE)
TAG_RE = re.compile(r"\[/?(?:pause|ngat|voice|lang|rate)\b[^\]\n]*\]", re.IGNORECASE)
EMPHASIS_RE = re.compile(r"\*([^*\n]+)\*")

URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # pictographs, emoticons, transport, symbols & pictographs ext.
    "\U00002600-\U000027BF"  # misc symbols, dingbats
    "\U0001F1E6-\U0001F1FF"  # flags
    "\U00002B00-\U00002BFF"  # arrows / stars
    "\U0000FE0F\U0000200D\U000020E3"  # VS16, ZWJ, keycap
    "]+"
)
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_SENT_END_RE = re.compile(r"(?<=[.!?…。！？])[\"'”’)\]]*\s+|\n+")


def strip_markup(text: str) -> str:
    """Text as it will be spoken (tags removed, emphasis stars removed)."""
    return EMPHASIS_RE.sub(r"\1", TAG_RE.sub(" ", text))


def clean_text(text: str) -> str:
    """'Làm sạch văn bản': remove URLs/emoji, normalize whitespace, keep markup."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = URL_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r"[  -​　]", " ", text)  # odd spaces
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" +([,.;:!?…])", r"\1", text)  # no space before punctuation
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)  # keep at most one blank line
    return text.strip() + ("\n" if text.strip() else "")


def count_words(text: str) -> int:
    plain = strip_markup(text)
    cjk = len(_CJK_RE.findall(plain))
    other = len(re.findall(r"[^\W_]+", _CJK_RE.sub(" ", plain)))
    return other + cjk


def estimate_duration_s(text: str, rate: float = 1.0, pause_scale: float = 1.0) -> float:
    """Rough spoken length: ~2.9 words (syllables) / s, CJK ~4.5 chars / s, plus pauses."""
    plain = strip_markup(text)
    cjk = len(_CJK_RE.findall(plain))
    words = len(re.findall(r"[^\W_]+", _CJK_RE.sub(" ", plain)))
    speech = (words / 2.9 + cjk / 4.5) / max(rate, 0.1)
    pauses = sum(int(m) for m in PAUSE_RE.findall(text)) / 1000.0
    punct = (plain.count(",") * 0.25 + len(re.findall(r"[.!?。！？]", plain)) * 0.6
             + plain.count("\n") * 0.7)
    return speech + pauses + punct * pause_scale


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) character spans of sentences, whitespace-trimmed."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END_RE.finditer(text):
        _add_span(text, start, m.start(), spans)
        start = m.end()
    _add_span(text, start, len(text), spans)
    return spans


def _add_span(text: str, a: int, b: int, out: list) -> None:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    if b > a:
        out.append((a, b))


def sentence_at(text: str, pos: int) -> tuple[int, int] | None:
    spans = sentence_spans(text)
    for a, b in spans:
        if a <= pos <= b:
            return a, b
    # cursor in whitespace between sentences: take the next one, else the last
    for a, b in spans:
        if a > pos:
            return a, b
    return spans[-1] if spans else None


def map_timeline(text: str, timeline, base: int = 0) -> list[tuple[float, float, int, int]]:
    """Map service timeline [(start_s, end_s, segment_text)] onto editor char spans.

    Segment text may be normalized (numbers spelled out...), so we look for the
    first words of each segment; if they are not found we fall back to the next
    sentence in order. Returns [(start_s, end_s, char_start, char_end)] with
    char positions offset by ``base``.
    """
    spans = sentence_spans(text)
    if not spans:
        return []
    low = text.lower()
    out = []
    pos = 0
    idx_sent = -1
    for start_s, end_s, seg_text in timeline:
        found = -1
        words = re.findall(r"[^\W_]+", (seg_text or "").lower())
        if words:
            key = " ".join(words[:3])
            m = re.search(r"[\W_]+".join(map(re.escape, key.split())), low[pos:])
            if m:
                found = pos + m.start()
        if found >= 0:
            j = next((k for k, (a, b) in enumerate(spans) if a <= found < b + 1), idx_sent + 1)
        else:
            j = idx_sent + 1
        j = min(max(j, 0), len(spans) - 1)
        idx_sent = j
        a, b = spans[j]
        pos = found + 1 if found >= 0 else a
        out.append((float(start_s), float(end_s), a + base, b + base))
    return out
