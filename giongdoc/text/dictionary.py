"""User pronunciation dictionary (whole-word, case-aware replacements)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from giongdoc.core import Language

_DEFAULT_VI = {
    "AI": "ây ai", "OK": "ô kê", "ok": "ô kê", "TikTok": "tíc tóc", "Facebook": "phây búc",
    "YouTube": "diu túp", "Google": "gu gồ", "Zalo": "da lô", "iPhone": "ai phôn",
    "email": "i meo", "online": "on lai", "offline": "óp lai", "wifi": "oai phai",
    "laptop": "láp tóp", "livestream": "lai xờ trim", "CEO": "xi i ô",
    "Instagram": "in xta gram", "internet": "in tơ nét", "selfie": "xeo phi",
    "ChatGPT": "chát gi pi ti", "website": "oép xai", "smartphone": "xmát phôn",
}


@dataclass(frozen=True)
class DictEntry:
    word: str
    replacement: str
    language: Language | None = None  # None = applies to every language
    case_sensitive: bool = True

    def to_dict(self) -> dict:
        return {"word": self.word, "replacement": self.replacement,
                "language": self.language.value if self.language else None,
                "case_sensitive": self.case_sensitive}


def _lang(language: Language | str | None) -> Language | None:
    return Language(language) if language else None


class PronunciationDict:
    """Whole-word replacements, global or per language.

    By default, all-uppercase keys (acronyms like "AI") match case-sensitively
    so the Vietnamese word "ai" is untouched; other keys ignore case.
    Language-specific entries override global ones for the same word.
    """

    def __init__(self, entries: Iterable[DictEntry] = ()) -> None:
        self._entries: dict[tuple[Language | None, str], DictEntry] = {}
        self._cache: dict[Language | None, tuple[re.Pattern | None, dict, dict]] = {}
        for e in entries:
            self._put(e)

    # -- editing -----------------------------------------------------------
    @staticmethod
    def _key(word: str, case_sensitive: bool) -> str:
        return word if case_sensitive else word.casefold()

    def _put(self, entry: DictEntry) -> None:
        # Drop any existing entry for the same word (either case mode).
        for cs in (True, False):
            self._entries.pop((entry.language, self._key(entry.word, cs)), None)
        self._entries[(entry.language, self._key(entry.word, entry.case_sensitive))] = entry
        self._cache.clear()

    def add(self, word: str, replacement: str, language: Language | str | None = None,
            case_sensitive: bool | None = None) -> DictEntry:
        """Add or replace an entry and return it."""
        word = word.strip()
        if not word:
            raise ValueError("empty word")
        if case_sensitive is None:
            case_sensitive = word.isupper()
        entry = DictEntry(word, replacement, _lang(language), case_sensitive)
        self._put(entry)
        return entry

    def remove(self, word: str, language: Language | str | None = None) -> bool:
        """Remove an entry; True if something was removed."""
        lang = _lang(language)
        removed = False
        for cs in (True, False):
            removed |= self._entries.pop((lang, self._key(word, cs)), None) is not None
        self._cache.clear()
        return removed

    def clear(self) -> None:
        self._entries.clear()
        self._cache.clear()

    def entries(self, language: Language | str | None = None) -> list[DictEntry]:
        """All entries, or only those stored for `language` (global ones excluded)."""
        if language is None:
            return list(self._entries.values())
        lang = _lang(language)
        return [e for e in self._entries.values() if e.language == lang]

    def lookup(self, word: str, language: Language | str | None = None) -> str | None:
        """Replacement for a single word as `apply` would use it, or None."""
        _, exact, folded = self._compiled(_lang(language))
        e = exact.get(word) or folded.get(word.casefold())
        return e.replacement if e else None

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, word: str) -> bool:
        return any(e.word == word or (not e.case_sensitive and e.word.casefold() == word.casefold())
                   for e in self._entries.values())

    # -- applying ----------------------------------------------------------
    def _compiled(self, language: Language | None):
        if language in self._cache:
            return self._cache[language]
        chosen = [e for e in self._entries.values() if e.language is None]
        if language:
            # Language-specific entries override global ones for the same word.
            spec = [e for e in self._entries.values() if e.language == language]
            folds = {e.word.casefold() for e in spec}
            chosen = [e for e in chosen if e.word.casefold() not in folds] + spec
        exact = {e.word: e for e in chosen if e.case_sensitive}
        folded = {e.word.casefold(): e for e in chosen if not e.case_sensitive}
        words = sorted({e.word for e in chosen}, key=lambda w: (-len(w), w))
        alts = []
        for w in words:
            esc = re.escape(w)
            alts.append(esc if w in exact else "(?i:" + esc + ")")
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)") if alts else None
        self._cache[language] = (pattern, exact, folded)
        return self._cache[language]

    def apply(self, text: str, language: Language | str | None = None) -> str:
        """Replace whole words in `text` using global + `language` entries."""
        pattern, exact, folded = self._compiled(_lang(language))
        if pattern is None or not text:
            return text

        def _rep(m: re.Match) -> str:
            e = exact.get(m.group(0)) or folded.get(m.group(0).casefold())
            return e.replacement if e else m.group(0)
        return pattern.sub(_rep, text)

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {"version": 1, "entries": [e.to_dict() for e in self._entries.values()]}

    @classmethod
    def from_dict(cls, data: dict) -> "PronunciationDict":
        d = cls()
        for item in data.get("entries", []):
            d.add(item["word"], item["replacement"], item.get("language"), item.get("case_sensitive"))
        return d

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "PronunciationDict":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def merge(self, other: "PronunciationDict") -> None:
        """Copy all entries of `other` into this dictionary (other wins)."""
        for e in other.entries():
            self._put(e)

    def copy(self) -> "PronunciationDict":
        return PronunciationDict(self.entries())

    @classmethod
    def default(cls) -> "PronunciationDict":
        """A small built-in Vietnamese set (brand names, loanwords, acronyms)."""
        d = cls()
        for word, rep in _DEFAULT_VI.items():
            d.add(word, rep, Language.VI)
        return d
