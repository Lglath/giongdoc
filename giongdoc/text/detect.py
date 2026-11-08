"""Language detection by Unicode script ranges and Vietnamese diacritics."""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from giongdoc.core import Language

# Letters that only (practically) occur in Vietnamese.
_VI_UNIQUE = set("ăâđêôơưĂÂĐÊÔƠƯ")
# Precomposed letters with tone marks shared with other Latin languages.
_VI_SHARED = set("àáãèéìíòóõùúýÀÁÃÈÉÌÍÒÓÕÙÚÝĩũĨŨ")


def _script(ch: str) -> str | None:
    """Return 'hangul', 'han', 'latin' or None (neutral: digits, punctuation, space)."""
    cp = ord(ch)
    if 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
        return "hangul"
    if (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF
            or 0x20000 <= cp <= 0x2FA1F or 0x3040 <= cp <= 0x30FF):
        return "han"  # kana is grouped here: Japanese is unsupported, closest is zh
    if ch.isalpha() and (cp < 0x0250 or 0x1E00 <= cp <= 0x1EFF):
        return "latin"
    return None


def is_cjk_char(ch: str) -> bool:
    """True for Hangul / Han / Kana characters."""
    return _script(ch) in ("hangul", "han")


def vietnamese_score(text: str) -> tuple[int, int]:
    """Return (unique, shared) counts of Vietnamese-marked letters in `text`."""
    unique = shared = 0
    for ch in text:
        cp = ord(ch)
        if ch in _VI_UNIQUE or 0x1EA0 <= cp <= 0x1EF9:
            unique += 1
        elif ch in _VI_SHARED:
            shared += 1
    return unique, shared


def _looks_vietnamese(text: str, latin_letters: int) -> bool:
    unique, shared = vietnamese_score(text)
    if unique >= 2 or (unique >= 1 and latin_letters <= 40):
        return True
    if shared >= 1 and latin_letters <= 20:
        return True  # short text: GiongDoc is Vietnamese-first
    score = 2 * unique + shared
    return latin_letters > 0 and score / latin_letters >= 0.05 and score >= 2


def detect_language(text: str, default: Language = Language.VI) -> Language:
    """Guess the dominant language of `text` (vi, en, ko, zh)."""
    text = unicodedata.normalize("NFC", text or "")
    counts = {"hangul": 0, "han": 0, "latin": 0}
    for ch in text:
        s = _script(ch)
        if s:
            counts[s] += 1
    if not any(counts.values()):
        return default
    hangul, han, latin = counts["hangul"], counts["han"], counts["latin"]
    # One Hangul syllable / Han character carries about two Latin letters.
    if max(hangul, han) * 2 >= latin:
        return Language.KO if hangul >= han and hangul > 0 else Language.ZH
    return Language.VI if _looks_vietnamese(text, latin) else Language.EN


_TERMINATOR_RE = re.compile(r"[.!?。！？…\n]")


class ScriptRun(NamedTuple):
    text: str
    language: Language


def _latin_language(run: str, default: Language) -> Language:
    letters = sum(1 for c in run if _script(c) == "latin")
    if default == Language.VI:
        return Language.VI
    if _looks_vietnamese(run, letters):
        return Language.VI
    if default == Language.EN:
        return Language.EN
    # Inside Korean/Chinese text, only switch for real phrases (>= 2 words).
    return Language.EN if len(re.findall(r"[A-Za-z]+", run)) >= 2 else default


def split_by_script(text: str, default: Language) -> list[ScriptRun]:
    """Split mixed text into runs of one language each.

    Neutral characters (spaces, digits, punctuation) between two runs are split
    at the first whitespace: punctuation glued to the previous run stays with
    it, the rest goes to the next run.
    """
    text = unicodedata.normalize("NFC", text or "")
    if not text:
        return []
    groups: list[list] = []  # [start, end, script]
    for i, ch in enumerate(text):
        s = _script(ch)
        if s is None:
            continue
        # Same script continues the group unless a sentence ends in between.
        if groups and groups[-1][2] == s and not _TERMINATOR_RE.search(text, groups[-1][1], i):
            groups[-1][1] = i + 1
        else:
            groups.append([i, i + 1, s])
    if not groups:
        return [ScriptRun(text, default)]

    merged: list[list] = []  # [start, end, language, script]
    for start, end, script in groups:
        if script == "hangul":
            lang = Language.KO
        elif script == "han":
            lang = Language.ZH
        else:
            lang = _latin_language(text[start:end], default)
        merged.append([start, end, lang, script])

    # A lone Latin word inside CJK text (a name like "我是Nam。") stays with the
    # CJK language instead of switching voice for one word.
    for i in range(1, len(merged)):
        start, end, lang, script = merged[i]
        prev = merged[i - 1]
        if script != "latin" or prev[3] == "latin" or vietnamese_score(text[start:end])[0]:
            continue
        if len(text[start:end].split()) > 1:
            continue
        after = text[end:merged[i + 1][0]] if i + 1 < len(merged) else text[end:]
        nxt_lang = merged[i + 1][2] if i + 1 < len(merged) else None
        if nxt_lang == prev[2] or re.match(r"\s*[。，、！？；：）」』]", after):
            merged[i][2] = prev[2]

    joined: list[list] = []
    for start, end, lang, _ in merged:
        if joined and joined[-1][2] == lang:
            joined[-1][1] = end
        else:
            joined.append([start, end, lang])
    merged = joined

    runs: list[ScriptRun] = []
    cut = 0
    for i, (start, end, lang) in enumerate(merged):
        if i + 1 < len(merged):
            gap = text[end:merged[i + 1][0]]
            head = re.match(r"\S*", gap).group(0)
            nxt = end + len(head)
        else:
            nxt = len(text)
        runs.append(ScriptRun(text[cut:nxt], lang))
        cut = nxt
    return runs
