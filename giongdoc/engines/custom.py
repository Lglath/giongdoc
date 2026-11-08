"""Custom (user-cloned) voices via zero-shot voice cloning — offline.

Voices come from :class:`giongdoc.engines.custom_voices.CustomVoiceStore` and
are consent-gated (see that module's ethics note: never clone celebrities or
any other person without their permission).

Backends (soft imports, tried in this order):

1. ``f5_tts``  – F5-TTS: ``F5TTS().infer(ref_file, ref_text, gen_text, ...)``
2. ``TTS``     – Coqui XTTS-v2: ``tts_to_file(text, speaker_wav=..., language=...)``

Vietnamese: the stock F5-TTS / XTTS-v2 checkpoints do not speak Vietnamese
well (XTTS-v2 does not support "vi" at all). For good Vietnamese quality point
the engine at a Vietnamese fine-tuned checkpoint, e.g. F5-TTS-Vietnamese or
viXTTS, through :class:`CustomEngineConfig` (or environment variables
``GIONGDOC_F5_CKPT``, ``GIONGDOC_F5_VOCAB``, ``GIONGDOC_F5_MODEL``,
``GIONGDOC_XTTS_MODEL_DIR``, ``GIONGDOC_XTTS_CONFIG``).

Models are loaded lazily on first synthesis and cached per process. Device is
``mps`` when ``torch.backends.mps`` is available, else ``cpu``.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from giongdoc.core import AudioClip, EngineError, Language, ProsodySettings, Voice
from giongdoc.engines.base import apply_gain, clamp
from giongdoc.engines.custom_voices import ENGINE_ID, CustomVoiceStore

log = logging.getLogger(__name__)

XTTS_DEFAULT_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
_XTTS_LANG = {Language.VI: "vi", Language.EN: "en", Language.KO: "ko", Language.ZH: "zh-cn"}


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def pick_device() -> str:
    try:
        import torch
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


@dataclass
class CustomEngineConfig:
    backend: str = "auto"                 # "auto" | "f5" | "xtts"
    f5_model: str = field(default_factory=lambda: os.environ.get("GIONGDOC_F5_MODEL", ""))
    f5_ckpt_file: str = field(default_factory=lambda: os.environ.get("GIONGDOC_F5_CKPT", ""))
    f5_vocab_file: str = field(default_factory=lambda: os.environ.get("GIONGDOC_F5_VOCAB", ""))
    xtts_model_name: str = XTTS_DEFAULT_MODEL
    xtts_model_dir: str = field(default_factory=lambda: os.environ.get("GIONGDOC_XTTS_MODEL_DIR", ""))
    xtts_config_path: str = field(default_factory=lambda: os.environ.get("GIONGDOC_XTTS_CONFIG", ""))
    device: str | None = None             # None = auto (mps/cpu)


class _F5Backend:
    name = "f5"

    def __init__(self, cfg: CustomEngineConfig, device: str):
        from f5_tts.api import F5TTS
        kwargs: dict = {"device": device}
        if cfg.f5_model:
            kwargs["model"] = cfg.f5_model
        if cfg.f5_ckpt_file:
            kwargs["ckpt_file"] = cfg.f5_ckpt_file
        if cfg.f5_vocab_file:
            kwargs["vocab_file"] = cfg.f5_vocab_file
        self.model = F5TTS(**kwargs)

    def synth_to_file(self, text: str, ref_wav: str, ref_text: str, language: Language,
                      speed: float, out_path: str) -> None:
        self.model.infer(ref_file=ref_wav, ref_text=ref_text, gen_text=text,
                         speed=speed, file_wave=out_path, remove_silence=False)


class _XTTSBackend:
    name = "xtts"

    def __init__(self, cfg: CustomEngineConfig, device: str):
        from TTS.api import TTS
        if cfg.xtts_model_dir:
            config = cfg.xtts_config_path or str(Path(cfg.xtts_model_dir) / "config.json")
            tts = TTS(model_path=cfg.xtts_model_dir, config_path=config)
        else:
            tts = TTS(cfg.xtts_model_name)
        try:
            self.model = tts.to(device)
        except Exception:  # noqa: BLE001  (some ops unsupported on mps)
            self.model = tts.to("cpu")

    def synth_to_file(self, text: str, ref_wav: str, ref_text: str, language: Language,
                      speed: float, out_path: str) -> None:
        self.model.tts_to_file(text=text, speaker_wav=ref_wav, language=_XTTS_LANG[language],
                               file_path=out_path, speed=speed)


_BACKENDS = {"f5": ("f5_tts", _F5Backend), "xtts": ("TTS", _XTTSBackend)}


class CustomEngine:
    id = ENGINE_ID
    display_name = "Giọng tùy chỉnh (offline, F5-TTS / XTTS)"

    _model_cache: dict[tuple, object] = {}
    _lock = threading.Lock()

    def __init__(self, store: CustomVoiceStore | None = None, config: CustomEngineConfig | None = None):
        self.store = store or CustomVoiceStore()
        self.config = config or CustomEngineConfig()

    # -- backend selection -------------------------------------------------
    def backend_order(self) -> list[str]:
        b = self.config.backend
        return [b] if b in _BACKENDS else ["f5", "xtts"]

    def available_backends(self) -> list[str]:
        return [b for b in self.backend_order() if _has(_BACKENDS[b][0])]

    def is_available(self) -> bool:
        return bool(self.available_backends())

    def _get_backend(self, name: str):
        device = self.config.device or pick_device()
        c = self.config
        key = (name, device, c.f5_model, c.f5_ckpt_file, c.f5_vocab_file,
               c.xtts_model_name, c.xtts_model_dir, c.xtts_config_path)
        with self._lock:
            if key not in self._model_cache:
                log.info("Loading custom-voice backend %s on %s", name, device)
                self._model_cache[key] = _BACKENDS[name][1](c, device)
            return self._model_cache[key]

    @classmethod
    def unload(cls) -> None:
        with cls._lock:
            cls._model_cache.clear()

    # -- TTSEngine ---------------------------------------------------------
    def list_voices(self) -> list[Voice]:
        return self.store.voices()

    def synthesize(self, text: str, voice: Voice, prosody: ProsodySettings) -> AudioClip:
        if not text.strip():
            raise EngineError("Empty text")
        rec = self.store.get(voice.id)
        if rec is None:
            raise EngineError(f"Không tìm thấy giọng tùy chỉnh (hoặc thiếu xác nhận đồng ý): {voice.id}")
        backends = self.available_backends()
        if not backends:
            raise EngineError("Chưa cài backend nhân bản giọng (pip install f5-tts hoặc coqui-tts)")
        from giongdoc.audio.codec import load_file
        speed = clamp(prosody.rate, 0.5, 2.0)
        errors = []
        for name in backends:
            if name == "xtts" and rec.language not in _XTTS_LANG:
                continue
            try:
                backend = self._get_backend(name)
                with tempfile.TemporaryDirectory(prefix="giongdoc_custom_") as tmp:
                    out = str(Path(tmp) / "out.wav")
                    backend.synth_to_file(text, str(rec.reference_path), rec.transcript,
                                          rec.language, speed, out)
                    clip = load_file(out)
                clip.samples = apply_gain(clip.samples, prosody.volume)
                return clip
            except Exception as e:  # noqa: BLE001
                log.warning("custom backend %s failed: %s", name, e)
                errors.append(f"{name}: {e}")
        raise EngineError("Tổng hợp giọng tùy chỉnh thất bại: " + "; ".join(errors))
