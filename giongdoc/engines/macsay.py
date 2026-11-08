"""macOS system voices via ``/usr/bin/say`` (offline).

Voices are discovered by parsing ``say -v '?'``. Only vi/en/ko/zh locales are
kept (e.g. Linh, Samantha, Yuna, Tingting). Speed maps to ``say -r`` words per
minute; volume is applied as gain afterwards. Pitch is not supported by
modern ``say`` voices and is ignored.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from giongdoc.core import AudioClip, EngineError, Language, ProsodySettings, Voice
from giongdoc.engines.base import apply_gain, rate_to_wpm

ENGINE_ID = "macsay"
SAY_PATH = "/usr/bin/say"

_LOCALE_TO_LANG = {"vi": Language.VI, "en": Language.EN, "ko": Language.KO, "zh": Language.ZH}

# Known genders for common system voices (base name, before any " (" suffix).
_GENDERS = {
    "linh": "female", "samantha": "female", "karen": "female", "moira": "female",
    "tessa": "female", "victoria": "female", "allison": "female", "ava": "female",
    "susan": "female", "zoe": "female", "kate": "female", "serena": "female",
    "fiona": "female", "veena": "female", "nicky": "female", "martha": "female",
    "flo": "female", "sandy": "female", "shelley": "female", "grandma": "female",
    "yuna": "female", "sora": "female", "tingting": "female", "ting-ting": "female",
    "meijia": "female", "mei-jia": "female", "sinji": "female", "sin-ji": "female",
    "lili": "female", "yu-shu": "female", "lilian": "female",
    "alex": "male", "daniel": "male", "fred": "male", "tom": "male", "aaron": "male",
    "arthur": "male", "oliver": "male", "rishi": "male", "lee": "male", "gordon": "male",
    "eddy": "male", "reed": "male", "rocko": "male", "grandpa": "male", "ralph": "male",
    "albert": "male", "junior": "male", "bruce": "male", "evan": "male", "nathan": "male",
    "minsu": "male", "li-mu": "male", "limu": "male", "yaoyao": "female",
}

_LINE_RE = re.compile(
    r"^(?P<name>\S.*?)\s+(?P<locale>[a-z]{2,3}[_-][A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)?)\s+#\s?(?P<sample>.*)$"
)


def parse_say_voices(output: str) -> list[Voice]:
    """Parse ``say -v '?'`` output into :class:`Voice` objects (vi/en/ko/zh only).

    Example line: ``Samantha            en_US    # Hello, my name is Samantha.``
    or ``Eddy (English (US)) en_US    # Hello! My name is Eddy.``
    """
    voices: list[Voice] = []
    seen: set[str] = set()
    for line in output.splitlines():
        line = line.rstrip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        locale = m.group("locale").replace("-", "_")
        lang = _LOCALE_TO_LANG.get(locale.split("_")[0].lower())
        if lang is None or name in seen:
            continue
        seen.add(name)
        base = name.split(" (")[0].strip().lower()
        voices.append(Voice(
            id=f"{ENGINE_ID}:{name}", name=f"{name} ({locale})", language=lang,
            engine_id=ENGINE_ID, gender=_GENDERS.get(base, "unknown"), offline=True,
            meta={"say_name": name, "locale": locale, "sample": m.group("sample").strip()},
        ))
    return voices


class MacSayEngine:
    id = ENGINE_ID
    display_name = "macOS (offline)"

    def __init__(self, say_path: str = SAY_PATH):
        self.say_path = say_path
        self._voices: list[Voice] | None = None

    def is_available(self) -> bool:
        return sys.platform == "darwin" and (
            os.path.exists(self.say_path) or shutil.which("say") is not None)

    def _say(self) -> str:
        return self.say_path if os.path.exists(self.say_path) else (shutil.which("say") or self.say_path)

    def list_voices(self) -> list[Voice]:
        if self._voices is not None:
            return list(self._voices)
        if not self.is_available():
            return []
        try:
            out = subprocess.run([self._say(), "-v", "?"], capture_output=True, text=True,
                                 timeout=20, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        self._voices = parse_say_voices(out)
        return list(self._voices)

    def refresh(self) -> None:
        self._voices = None

    @staticmethod
    def command(say: str, text_file: str, voice: Voice, prosody: ProsodySettings, out: str) -> list[str]:
        name = (voice.meta or {}).get("say_name") or voice.id.split(":", 1)[-1]
        return [say, "-v", name, "-r", str(rate_to_wpm(prosody.rate)), "-o", out, "-f", text_file]

    def synthesize(self, text: str, voice: Voice, prosody: ProsodySettings) -> AudioClip:
        if not self.is_available():
            raise EngineError("Giọng hệ thống macOS (say) chỉ có trên macOS")
        if not text.strip():
            raise EngineError("Empty text")
        from giongdoc.audio.codec import load_file
        with tempfile.TemporaryDirectory(prefix="giongdoc_say_") as tmp:
            txt = Path(tmp) / "input.txt"
            txt.write_text(text, encoding="utf-8")
            out = Path(tmp) / "out.aiff"
            cmd = self.command(self._say(), str(txt), voice, prosody, str(out))
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            except (OSError, subprocess.SubprocessError) as e:
                raise EngineError(f"say failed: {e}") from e
            if res.returncode != 0 or not out.exists() or out.stat().st_size == 0:
                raise EngineError(f"say failed ({res.returncode}): {res.stderr.strip()}")
            try:
                clip = load_file(str(out))
            except Exception as e:  # noqa: BLE001
                raise EngineError(f"Không đọc được AIFF từ say: {e}") from e
        clip.samples = apply_gain(clip.samples, prosody.volume)
        return clip
