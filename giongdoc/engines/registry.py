"""Engine registry: one place to enumerate engines and voices."""
from __future__ import annotations

import threading

from giongdoc.core import EngineError, Language, TTSEngine, Voice
from giongdoc.engines.custom import CustomEngine
from giongdoc.engines.custom_voices import CustomVoiceStore
from giongdoc.engines.edge import EdgeEngine
from giongdoc.engines.macsay import MacSayEngine

DEFAULT_PREFERENCE = ("edge", "macsay")

_lock = threading.Lock()
_engines: dict[str, TTSEngine] | None = None


def _build(store: CustomVoiceStore | None = None) -> dict[str, TTSEngine]:
    engines: list[TTSEngine] = [EdgeEngine(), MacSayEngine(), CustomEngine(store=store)]
    return {e.id: e for e in engines}


def configure(engines: list[TTSEngine] | None = None, custom_store: CustomVoiceStore | None = None) -> None:
    """Replace the engine set (tests, or to point custom voices at another store)."""
    global _engines
    with _lock:
        _engines = {e.id: e for e in engines} if engines is not None else _build(custom_store)


def reset() -> None:
    global _engines
    with _lock:
        _engines = None


def _all() -> dict[str, TTSEngine]:
    global _engines
    with _lock:
        if _engines is None:
            _engines = _build()
        return _engines


def all_engines() -> list[TTSEngine]:
    return list(_all().values())


def get(engine_id: str) -> TTSEngine:
    try:
        return _all()[engine_id]
    except KeyError:
        raise EngineError(f"Unknown engine: {engine_id}") from None


def custom_store() -> CustomVoiceStore | None:
    eng = _all().get("custom")
    return getattr(eng, "store", None)


def all_voices(language: Language | str | None = None) -> list[Voice]:
    """Voices of available engines, plus custom voices (always listed so the user
    can manage them, even if no cloning backend is installed yet)."""
    lang = Language(language) if language is not None else None
    out: list[Voice] = []
    for eng in all_engines():
        if not (eng.is_available() or eng.id == "custom"):
            continue
        try:
            voices = eng.list_voices()
        except Exception:  # noqa: BLE001
            continue
        out.extend(v for v in voices if lang is None or v.language == lang)
    return out


def find_voice(voice_id: str) -> Voice | None:
    if not voice_id:
        return None
    engine_id = voice_id.split(":", 1)[0]
    eng = _all().get(engine_id)
    if eng is None:
        return None
    try:
        for v in eng.list_voices():
            if v.id == voice_id:
                return v
    except Exception:  # noqa: BLE001
        return None
    return None


def default_voice(language: Language | str) -> Voice | None:
    """First voice for ``language`` from edge, then macsay (available engines only)."""
    lang = Language(language)
    for eid in DEFAULT_PREFERENCE:
        eng = _all().get(eid)
        if eng is None or not eng.is_available():
            continue
        try:
            voices = [v for v in eng.list_voices() if v.language == lang]
        except Exception:  # noqa: BLE001
            continue
        if voices:
            return voices[0]
    return None
