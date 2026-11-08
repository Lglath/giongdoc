"""Microsoft Edge neural voices via the ``edge-tts`` package (online).

Most natural-sounding engine; requires an internet connection. The package is
imported softly: if it is missing, :meth:`EdgeEngine.is_available` is False.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import threading
import time

from giongdoc.core import AudioClip, EngineError, Language, ProsodySettings, Voice
from giongdoc.engines.base import pitch_to_hz, rate_to_percent, volume_to_percent

log = logging.getLogger(__name__)

ENGINE_ID = "edge"

# (ShortName, display name, language, gender)
_CURATED: list[tuple[str, str, Language, str]] = [
    # Vietnamese
    ("vi-VN-HoaiMyNeural", "Hoài My (Nữ, Việt Nam)", Language.VI, "female"),
    ("vi-VN-NamMinhNeural", "Nam Minh (Nam, Việt Nam)", Language.VI, "male"),
    # English (US)
    ("en-US-AriaNeural", "Aria (Female, US)", Language.EN, "female"),
    ("en-US-JennyNeural", "Jenny (Female, US)", Language.EN, "female"),
    ("en-US-AvaNeural", "Ava (Female, US)", Language.EN, "female"),
    ("en-US-EmmaNeural", "Emma (Female, US)", Language.EN, "female"),
    ("en-US-GuyNeural", "Guy (Male, US)", Language.EN, "male"),
    ("en-US-AndrewNeural", "Andrew (Male, US)", Language.EN, "male"),
    ("en-US-BrianNeural", "Brian (Male, US)", Language.EN, "male"),
    ("en-US-ChristopherNeural", "Christopher (Male, US)", Language.EN, "male"),
    # English (UK)
    ("en-GB-SoniaNeural", "Sonia (Female, UK)", Language.EN, "female"),
    ("en-GB-LibbyNeural", "Libby (Female, UK)", Language.EN, "female"),
    ("en-GB-RyanNeural", "Ryan (Male, UK)", Language.EN, "male"),
    ("en-GB-ThomasNeural", "Thomas (Male, UK)", Language.EN, "male"),
    # Korean
    ("ko-KR-SunHiNeural", "SunHi 선히 (Female, KR)", Language.KO, "female"),
    ("ko-KR-InJoonNeural", "InJoon 인준 (Male, KR)", Language.KO, "male"),
    ("ko-KR-HyunsuMultilingualNeural", "Hyunsu 현수 (Male, KR)", Language.KO, "male"),
    # Chinese (Mandarin, mainland)
    ("zh-CN-XiaoxiaoNeural", "Xiaoxiao 晓晓 (Female, CN)", Language.ZH, "female"),
    ("zh-CN-XiaoyiNeural", "Xiaoyi 晓伊 (Female, CN)", Language.ZH, "female"),
    ("zh-CN-YunxiNeural", "Yunxi 云希 (Male, CN)", Language.ZH, "male"),
    ("zh-CN-YunjianNeural", "Yunjian 云健 (Male, CN)", Language.ZH, "male"),
    ("zh-CN-YunyangNeural", "Yunyang 云扬 (Male, CN)", Language.ZH, "male"),
    ("zh-CN-YunxiaNeural", "Yunxia 云夏 (Male, CN)", Language.ZH, "male"),
    ("zh-CN-liaoning-XiaobeiNeural", "Xiaobei 晓北 (Female, Liaoning)", Language.ZH, "female"),
    ("zh-CN-shaanxi-XiaoniNeural", "Xiaoni 晓妮 (Female, Shaanxi)", Language.ZH, "female"),
]


def builtin_voices() -> list[Voice]:
    return [
        Voice(id=f"{ENGINE_ID}:{short}", name=name, language=lang, engine_id=ENGINE_ID,
              gender=gender, offline=False, meta={"short_name": short, "locale": short[:5]})
        for short, name, lang, gender in _CURATED
    ]


def short_name(voice: Voice) -> str:
    sn = voice.meta.get("short_name") if voice.meta else None
    if sn:
        return sn
    return voice.id.split(":", 1)[1] if ":" in voice.id else voice.id


def run_coroutine_sync(coro):
    """Run ``coro`` to completion in a fresh event loop.

    Safe from worker threads (QThread / ThreadPool). If the calling thread
    already runs a loop, the coroutine is executed in a helper thread.
    """
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False

    if not running:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    box: dict = {}

    def target():
        try:
            box["result"] = run_coroutine_sync(coro)
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box.get("result")


class EdgeEngine:
    id = ENGINE_ID
    display_name = "Microsoft Edge Neural (online)"

    def __init__(self, retries: int = 2, retry_delay_s: float = 0.8, timeout_s: float = 60.0,
                 proxy: str | None = None):
        self.retries = retries
        # aiohttp ignores proxy env vars, so honour HTTPS_PROXY explicitly.
        self.proxy = proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
        self.retry_delay_s = retry_delay_s
        self.timeout_s = timeout_s

    def is_available(self) -> bool:
        return importlib.util.find_spec("edge_tts") is not None

    def list_voices(self) -> list[Voice]:
        return builtin_voices()

    @staticmethod
    def params(prosody: ProsodySettings) -> dict:
        return {
            "rate": rate_to_percent(prosody.rate),
            "pitch": pitch_to_hz(prosody.pitch),
            "volume": volume_to_percent(prosody.volume),
        }

    async def _fetch(self, text: str, voice_name: str, params: dict) -> bytes:
        import edge_tts
        kw = dict(params)
        if self.proxy:
            kw["proxy"] = self.proxy
        comm = edge_tts.Communicate(text, voice_name, **kw)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    def fetch_mp3(self, text: str, voice: Voice, prosody: ProsodySettings) -> bytes:
        """Return raw MP3 bytes from the service (retries ``self.retries`` times)."""
        if not self.is_available():
            raise EngineError("edge-tts chưa được cài đặt (pip install edge-tts)")
        if not text.strip():
            raise EngineError("Empty text")
        params = self.params(prosody)
        name = short_name(voice)
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                data = run_coroutine_sync(
                    asyncio.wait_for(self._fetch(text, name, params), self.timeout_s))
                if not data:
                    raise EngineError("edge-tts returned no audio")
                return data
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("edge-tts attempt %d failed: %s", attempt + 1, e)
                if attempt < self.retries:
                    time.sleep(self.retry_delay_s * (attempt + 1))
        raise EngineError(f"Edge TTS thất bại (cần kết nối mạng?): {last}") from last

    def synthesize(self, text: str, voice: Voice, prosody: ProsodySettings) -> AudioClip:
        data = self.fetch_mp3(text, voice, prosody)
        from giongdoc.audio.codec import decode_bytes
        try:
            return decode_bytes(data)
        except Exception as e:  # noqa: BLE001
            raise EngineError(f"Không giải mã được audio từ Edge TTS: {e}") from e
