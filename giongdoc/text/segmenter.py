"""Sentence / clause segmentation with punctuation-driven pauses.

Each clause keeps its punctuation (engines use it for intonation) and gets a
pause from the table in docs/ARCHITECTURE.md, multiplied by `pause_scale`.
Overly long clauses are broken at conjunctions or spaces with a short pause.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from giongdoc.core import Language
from giongdoc.text.detect import is_cjk_char

# Default pauses in milliseconds (before pause_scale).
PAUSE_COMMA = 250
PAUSE_SEMICOLON = 400
PAUSE_COLON = 350
PAUSE_PERIOD = 600
PAUSE_QUESTION = 650
PAUSE_ELLIPSIS = 800
PAUSE_DASH = 300
PAUSE_LINE = 700
PAUSE_PARAGRAPH = 1100
PAUSE_SOFT_BREAK = 150  # inserted when a long clause is broken without punctuation

MAX_WEIGHT = 180  # ~180 Latin chars; CJK chars weigh 3 (≈ 60 chars)

_CLOSERS = "\"'”’»」』》）)]】"
_BOUNDARY_RE = re.compile(
    r"(?P<p>\.{2,}|…+|[!?！？]+[.…]*|[.。]+|[;；]|[：:]|[,，、]|\s[—–-]+(?=\s|$)|[—–]+)"
    r"(?P<c>[" + re.escape(_CLOSERS) + r"]*)"
)
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "e.g", "i.e", "approx", "no",
    "tp", "gs", "pgs", "ts", "ths", "bs", "ks", "p", "q", "tt", "ông", "bà", "cf", "fig",
}
_CONJUNCTIONS = (
    "và|nhưng|hoặc|hay|mà|thì|nên|vì|bởi vì|để|khi|nếu|rằng|tuy|song|cho nên|"
    "and|but|or|because|which|that|so|when|while|although|if|then|"
    "그리고|하지만|그러나|그래서|그런데|또는"
)
_CONJ_RE = re.compile(r"\s(?=(?:" + _CONJUNCTIONS + r")\b)", re.I)
_CJK_CONJ_RE = re.compile(r"(?=但是|因为|所以|而且|然后|如果|虽然|并且|或者|可是|不过)")


@dataclass
class Clause:
    text: str
    pause_ms: int = 0


def text_weight(s: str) -> int:
    """Length where CJK characters count 3 (they carry more speech per char)."""
    return sum(3 if is_cjk_char(c) else 1 for c in s)


def _pause_for(punct: str) -> int:
    if "…" in punct or ".." in punct:
        return PAUSE_ELLIPSIS
    if any(c in punct for c in "!?！？"):
        return PAUSE_QUESTION
    if any(c in punct for c in ".。"):
        return PAUSE_PERIOD
    if any(c in punct for c in ";；："):
        return PAUSE_SEMICOLON
    if ":" in punct:
        return PAUSE_COLON
    if any(c in punct for c in "—–-"):
        return PAUSE_DASH
    return PAUSE_COMMA


def _is_boundary(line: str, m: re.Match) -> bool:
    """Reject punctuation that does not end a clause (decimals, abbreviations, times)."""
    p = m.group("p")
    before, after = line[:m.start()], line[m.end():]
    prev_ch, next_ch = before[-1:], after[:1]
    if p in (".", ",", ":") and not m.group("c"):
        if prev_ch.isdigit() and next_ch.isdigit():
            return False  # 3.5, 1,000, 14:30
        if p != "," and next_ch and not next_ch.isspace():
            return False  # TP.HCM, x.com, 'lang:ko'
    if p == ".":
        word = re.search(r"(\S*)$", before).group(1)
        key = word.lower().lstrip("(\"'“")
        if key in _ABBREVIATIONS or re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]", word):
            return False
    return True


def _split_line(line: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    start = 0
    for m in _BOUNDARY_RE.finditer(line):
        if not _is_boundary(line, m):
            continue
        p = m.group("p")
        if p.strip() and set(p.strip()) <= set("—–-"):
            piece = line[start:m.start()] + m.group("c")
        else:
            piece = line[start:m.end()]
        out.append((piece.strip(), _pause_for(p)))
        start = m.end()
    tail = line[start:].strip()
    if tail:
        out.append((tail, 0))
    return out


def _find_cut(s: str, max_weight: int) -> int:
    """Index where a too-long clause should be cut."""
    w, limit, low = 0, len(s), 0
    for i, c in enumerate(s):
        w += 3 if is_cjk_char(c) else 1
        if not low and w >= max_weight * 0.4:
            low = i
        if w > max_weight:
            limit = i
            break
    for regex in (_CONJ_RE, _CJK_CONJ_RE):
        cuts = [m.start() for m in regex.finditer(s, low, limit) if m.start() > 0]
        if cuts:
            return cuts[-1]
    space = s.rfind(" ", low, limit)
    if space > 0:
        return space
    return max(1, limit)


def break_long(text: str, max_weight: int = MAX_WEIGHT) -> list[str]:
    """Break a clause longer than `max_weight` into natural-sounding pieces."""
    pieces = []
    while text_weight(text) > max_weight:
        cut = _find_cut(text, max_weight)
        head, text = text[:cut].strip(), text[cut:].strip()
        if head:
            pieces.append(head)
    if text:
        pieces.append(text)
    return pieces


def _speakable(text: str) -> bool:
    return re.search(r"\w", text) is not None


def split_clauses(text: str, language: Language | None = None, pause_scale: float = 1.0,
                  max_weight: int = MAX_WEIGHT) -> list[Clause]:
    """Split text into clauses with pauses.

    Clauses without speakable characters are dropped and their pause moves to
    the previous clause. If the text starts with a break, the result begins
    with an empty-text clause carrying that pause.
    """
    raw: list[tuple[str, int]] = []

    def add(piece: str, pause: int) -> None:
        if _speakable(piece):
            raw.append((piece, pause))
        elif raw:
            raw[-1] = (raw[-1][0], max(raw[-1][1], pause))
        elif pause:
            raw.append(("", pause))

    parts = re.split(r"(\n\s*)", text or "")
    for i, part in enumerate(parts):
        if i % 2:  # separator
            add("", PAUSE_PARAGRAPH if part.count("\n") >= 2 else PAUSE_LINE)
            continue
        for piece, pause in _split_line(part):
            sub = break_long(piece, max_weight) if text_weight(piece) > max_weight else [piece]
            for j, s in enumerate(sub):
                add(s, pause if j == len(sub) - 1 else PAUSE_SOFT_BREAK)

    scale = max(0.0, float(pause_scale))
    return [Clause(t, int(round(p * scale))) for t, p in raw]
