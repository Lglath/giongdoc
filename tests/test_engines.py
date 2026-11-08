"""Tests for giongdoc.engines (no network; network test skipped unless GIONGDOC_NETWORK_TESTS=1)."""
from __future__ import annotations

import json
import os
import sys
import types

import numpy as np
import pytest

from giongdoc.core import AudioClip, EngineError, Language, ProsodySettings, TTSEngine, Voice
from giongdoc.engines import base, registry
from giongdoc.engines.custom import CustomEngine, CustomEngineConfig
from giongdoc.engines.custom_voices import (
    CONSENT_TEXT_VI, ConsentRecord, CustomVoiceStore,
)
from giongdoc.engines.edge import EdgeEngine, builtin_voices, run_coroutine_sync
from giongdoc.engines.macsay import MacSayEngine, parse_say_voices


# ---------------------------------------------------------------- fake codec
@pytest.fixture
def fake_codec(monkeypatch):
    state = {"duration": 10.0, "decoded": []}
    mod = types.ModuleType("giongdoc.audio.codec")

    def decode_bytes(data: bytes) -> AudioClip:
        state["decoded"].append(data)
        return AudioClip(np.zeros(2400, dtype=np.float32))

    def load_file(path) -> AudioClip:
        return AudioClip(np.full(int(24000 * state["duration"]), 0.5, dtype=np.float32))

    mod.decode_bytes = decode_bytes
    mod.load_file = load_file
    import giongdoc.audio as audio_pkg  # namespace or real package
    monkeypatch.setitem(sys.modules, "giongdoc.audio.codec", mod)
    monkeypatch.setattr(audio_pkg, "codec", mod, raising=False)
    return state


# ---------------------------------------------------------------- base
@pytest.mark.parametrize("rate,exp", [(1.2, "+20%"), (1.0, "+0%"), (0.8, "-20%"), (3.0, "+100%"), (0.1, "-50%")])
def test_rate_to_percent(rate, exp):
    assert base.rate_to_percent(rate) == exp


def test_volume_and_pitch():
    assert base.volume_to_percent(1.5) == "+50%"
    assert base.volume_to_percent(0.0) == "-100%"
    assert base.pitch_to_hz(0) == "+0Hz"
    assert base.pitch_to_hz(12, base_hz=100) == "+100Hz"
    assert base.pitch_to_hz(-12, base_hz=100) == "-50Hz"
    assert base.pitch_to_percent(2) == "+12%"
    assert base.rate_to_wpm(1.0) == 175 and base.rate_to_wpm(2.0) == 350


def test_cache_key_stable_and_sensitive():
    v = Voice("edge:vi-VN-HoaiMyNeural", "x", Language.VI, "edge")
    k1 = base.cache_key("edge", v, "Xin chào", ProsodySettings())
    assert k1 == base.cache_key("edge", v.id, "Xin chào", ProsodySettings(pause_scale=2.0))
    assert k1 != base.cache_key("edge", v, "Xin chào", ProsodySettings(rate=1.1))
    assert k1 != base.cache_key("edge", v, "Xin chao")
    assert len(k1) == 64


# ---------------------------------------------------------------- edge
def test_edge_voices_curated():
    vs = builtin_voices()
    ids = {v.id for v in vs}
    for sn in ["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural", "ko-KR-SunHiNeural", "ko-KR-InJoonNeural",
               "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-CN-YunjianNeural", "zh-CN-XiaoyiNeural",
               "en-US-AriaNeural", "en-GB-SoniaNeural"]:
        assert f"edge:{sn}" in ids
    assert {v.language for v in vs} == set(Language)
    assert all(v.gender in ("male", "female") and not v.offline for v in vs)
    assert isinstance(EdgeEngine(), TTSEngine)


def test_edge_params():
    p = EdgeEngine.params(ProsodySettings(rate=1.2, pitch=0, volume=0.8))
    assert p == {"rate": "+20%", "pitch": "+0Hz", "volume": "-20%"}


class _FakeCommunicate:
    calls: list = []
    fail_times = 0

    def __init__(self, text, voice, **kw):
        _FakeCommunicate.calls.append((text, voice, kw))

    async def stream(self):
        if _FakeCommunicate.fail_times > 0:
            _FakeCommunicate.fail_times -= 1
            raise ConnectionError("boom")
        yield {"type": "WordBoundary"}
        yield {"type": "audio", "data": b"ID3"}
        yield {"type": "audio", "data": b"mp3"}


@pytest.fixture
def fake_edge(monkeypatch):
    mod = types.ModuleType("edge_tts")
    mod.Communicate = _FakeCommunicate
    _FakeCommunicate.calls = []
    _FakeCommunicate.fail_times = 0
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    monkeypatch.setattr(EdgeEngine, "is_available", lambda self: True)
    return _FakeCommunicate


def test_edge_synthesize_with_retries(fake_edge, fake_codec):
    eng = EdgeEngine(retry_delay_s=0)
    v = builtin_voices()[0]
    fake_edge.fail_times = 2
    clip = eng.synthesize("Xin chào", v, ProsodySettings(rate=1.2))
    assert isinstance(clip, AudioClip)
    assert fake_codec["decoded"] == [b"ID3mp3"]
    assert len(fake_edge.calls) == 3
    assert fake_edge.calls[-1][1] == "vi-VN-HoaiMyNeural"
    assert fake_edge.calls[-1][2]["rate"] == "+20%"


def test_edge_raises_engine_error_after_retries(fake_edge, fake_codec):
    fake_edge.fail_times = 10
    with pytest.raises(EngineError):
        EdgeEngine(retry_delay_s=0).synthesize("Xin chào", builtin_voices()[0], ProsodySettings())
    assert len(fake_edge.calls) == 3


def test_run_coroutine_sync_inside_running_loop():
    import asyncio

    async def inner():
        return 42

    async def outer():
        return run_coroutine_sync(inner())

    assert asyncio.run(outer()) == 42
    assert run_coroutine_sync(inner()) == 42


# ---------------------------------------------------------------- macsay
SAY_SAMPLE = """\
Albert              en_US    # Hello! My name is Albert.
Alice               it_IT    # Ciao! Mi chiamo Alice.
Daniel              en_GB    # Hello! My name is Daniel.
Eddy (English (US)) en_US    # Hello! My name is Eddy.
Eddy (Chinese (China mainland)) zh_CN    # 你好！我叫Eddy。
Karen               en_AU    # Hello! My name is Karen.
Linh                vi_VN    # Xin chào, tên tôi là Linh.
Meijia              zh_TW    # 你好，我叫美佳。
Samantha            en_US    # Hello! My name is Samantha.
Sinji               zh_HK    # 你好！我叫善怡。
Thomas              fr_FR    # Bonjour, je m’appelle Thomas.
Tingting            zh_CN    # 你好，我叫婷婷。
Yuna                ko_KR    # 안녕하세요. 제 이름은 유나입니다.

garbage line without locale
"""


def test_parse_say_voices():
    vs = parse_say_voices(SAY_SAMPLE)
    by = {v.meta["say_name"]: v for v in vs}
    assert "Alice" not in by and "Thomas" not in by
    assert by["Linh"].language == Language.VI and by["Linh"].gender == "female"
    assert by["Samantha"].language == Language.EN
    assert by["Yuna"].language == Language.KO
    assert by["Tingting"].language == Language.ZH and by["Sinji"].language == Language.ZH
    assert by["Eddy (Chinese (China mainland))"].language == Language.ZH
    assert by["Eddy (English (US))"].meta["locale"] == "en_US"
    assert by["Daniel"].gender == "male"
    assert by["Linh"].id == "macsay:Linh" and all(v.offline for v in vs)
    assert len(vs) == 11


def test_macsay_availability_and_command(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    eng = MacSayEngine()
    assert eng.is_available() is False and eng.list_voices() == []
    v = parse_say_voices(SAY_SAMPLE)[0]
    cmd = MacSayEngine.command("/usr/bin/say", "/t/in.txt", v, ProsodySettings(rate=1.2), "/t/o.aiff")
    assert cmd == ["/usr/bin/say", "-v", "Albert", "-r", "210", "-o", "/t/o.aiff", "-f", "/t/in.txt"]


def test_macsay_synthesize_mocked(monkeypatch, fake_codec, tmp_path):
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("os.path.exists", lambda p: True)

    def fake_run(cmd, **kw):
        if cmd[1:3] == ["-v", "?"]:
            return subprocess.CompletedProcess(cmd, 0, SAY_SAMPLE, "")
        out = cmd[cmd.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(b"FORM")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    eng = MacSayEngine()
    assert eng.is_available()
    linh = [v for v in eng.list_voices() if v.meta["say_name"] == "Linh"][0]
    fake_codec["duration"] = 1.0
    clip = eng.synthesize("Xin chào", linh, ProsodySettings(volume=0.5))
    assert np.allclose(clip.samples, 0.25)


# ---------------------------------------------------------------- custom voices
def _consent(ok=True, rel="self"):
    return ConsentRecord(speaker_name="Nguyễn Văn A", relationship=rel,
                         confirmed_owns_or_has_written_consent=ok, note="test")


@pytest.fixture
def ref_file(tmp_path):
    p = tmp_path / "ref.m4a"
    p.write_bytes(b"fake")
    return p


def test_consent_text():
    assert "đồng ý bằng văn bản".upper() in CONSENT_TEXT_VI.upper()
    assert "người nổi tiếng" in CONSENT_TEXT_VI


def test_add_voice_requires_consent(tmp_path, ref_file, fake_codec):
    store = CustomVoiceStore(tmp_path / "voices")
    with pytest.raises(ValueError):
        store.add_voice("Giọng A", "vi", ref_file, "xin chào", _consent(ok=False))
    with pytest.raises(ValueError):
        store.add_voice("Giọng A", "vi", ref_file, "xin chào", _consent(rel="celebrity"))
    with pytest.raises(ValueError):
        store.add_voice("Giọng A", "vi", ref_file, "xin chào", None)  # type: ignore[arg-type]
    assert store.list() == []


@pytest.mark.parametrize("dur", [3.0, 31.0])
def test_add_voice_length_validation(tmp_path, ref_file, fake_codec, dur):
    fake_codec["duration"] = dur
    with pytest.raises(ValueError):
        CustomVoiceStore(tmp_path / "v").add_voice("A", Language.VI, ref_file, "x", _consent())


def test_add_list_get_delete(tmp_path, ref_file, fake_codec):
    store = CustomVoiceStore(tmp_path / "voices")
    rec = store.add_voice("Giọng Đức", Language.VI, ref_file, " xin chào các bạn ", _consent())
    assert rec.id.startswith("giong-duc-")
    d = tmp_path / "voices" / rec.id
    assert (d / "reference.wav").stat().st_size > 1000
    assert (d / "transcript.txt").read_text(encoding="utf-8") == "xin chào các bạn"
    meta = json.loads((d / "voice.json").read_text(encoding="utf-8"))
    assert meta["consent"]["confirmed_owns_or_has_written_consent"] is True
    assert meta["consent"]["speaker_name"] == "Nguyễn Văn A"
    vs = store.voices(Language.VI)
    assert len(vs) == 1 and vs[0].custom and vs[0].id == f"custom:{rec.id}"
    assert store.voices(Language.EN) == []
    assert store.get(vs[0].id).transcript == "xin chào các bạn"
    # a voice.json tampered to remove consent is not exposed
    meta["consent"]["confirmed_owns_or_has_written_consent"] = False
    (d / "voice.json").write_text(json.dumps(meta), encoding="utf-8")
    assert store.list() == []
    meta["consent"]["confirmed_owns_or_has_written_consent"] = True
    (d / "voice.json").write_text(json.dumps(meta), encoding="utf-8")
    assert store.delete(vs[0].id) and store.list() == []
    assert store.get("../etc") is None


def test_custom_engine_backend_and_synth(tmp_path, ref_file, fake_codec, monkeypatch):
    import giongdoc.engines.custom as custom
    store = CustomVoiceStore(tmp_path / "voices")
    rec = store.add_voice("A", "vi", ref_file, "xin chào", _consent())
    monkeypatch.setattr(custom, "_has", lambda m: False)
    eng = CustomEngine(store=store, config=CustomEngineConfig(device="cpu"))
    assert not eng.is_available()
    with pytest.raises(EngineError):
        eng.synthesize("hi", rec.to_voice(), ProsodySettings())

    calls = []

    class FakeBackend:
        name = "f5"
        loads = 0

        def __init__(self, cfg, device):
            FakeBackend.loads += 1
            assert device == "cpu"

        def synth_to_file(self, text, ref_wav, ref_text, language, speed, out_path):
            calls.append((text, ref_wav, ref_text, language, speed))
            open(out_path, "wb").write(b"RIFF")

    monkeypatch.setattr(custom, "_has", lambda m: m == "f5_tts")
    monkeypatch.setitem(custom._BACKENDS, "f5", ("f5_tts", FakeBackend))
    CustomEngine.unload()
    assert eng.is_available() and eng.available_backends() == ["f5"]
    fake_codec["duration"] = 1.0
    clip = eng.synthesize("Chào bạn", rec.to_voice(), ProsodySettings(rate=1.3))
    eng.synthesize("Lần hai", rec.to_voice(), ProsodySettings())
    assert FakeBackend.loads == 1  # model cached
    assert calls[0][2] == "xin chào" and calls[0][3] == Language.VI and calls[0][4] == 1.3
    assert calls[0][1].endswith("reference.wav")
    assert clip.duration_s == pytest.approx(1.0)
    CustomEngine.unload()


# ---------------------------------------------------------------- registry
class _StubEngine:
    def __init__(self, eid, avail, voices):
        self.id, self.display_name, self._a, self._v = eid, eid, avail, voices

    def is_available(self):
        return self._a

    def list_voices(self):
        return self._v

    def synthesize(self, text, voice, prosody):
        return AudioClip.silence(10)


@pytest.fixture
def stub_registry():
    def V(eid, name, lang, custom=False):
        return Voice(f"{eid}:{name}", name, lang, eid, custom=custom)
    edge = _StubEngine("edge", True, [V("edge", "E-vi", Language.VI), V("edge", "E-en", Language.EN)])
    mac = _StubEngine("macsay", True, [V("macsay", "M-vi", Language.VI), V("macsay", "M-ko", Language.KO)])
    cus = _StubEngine("custom", False, [V("custom", "C-vi", Language.VI, True)])
    registry.configure([edge, mac, cus])
    yield edge, mac, cus
    registry.reset()


def test_registry(stub_registry):
    edge, mac, cus = stub_registry
    assert [e.id for e in registry.all_engines()] == ["edge", "macsay", "custom"]
    assert registry.get("macsay") is mac
    with pytest.raises(EngineError):
        registry.get("nope")
    assert [v.name for v in registry.all_voices("vi")] == ["E-vi", "M-vi", "C-vi"]
    assert len(registry.all_voices()) == 5
    assert registry.find_voice("macsay:M-ko").language == Language.KO
    assert registry.find_voice("edge:missing") is None and registry.find_voice("zzz:x") is None
    assert registry.default_voice(Language.VI).id == "edge:E-vi"
    assert registry.default_voice(Language.KO).id == "macsay:M-ko"
    assert registry.default_voice(Language.ZH) is None
    edge._a = False
    assert registry.default_voice(Language.VI).id == "macsay:M-vi"
    assert [v.name for v in registry.all_voices("en")] == []


def test_registry_real_engines(tmp_path):
    registry.configure(custom_store=CustomVoiceStore(tmp_path))
    try:
        ids = {e.id for e in registry.all_engines()}
        assert ids == {"edge", "macsay", "custom"}
        for e in registry.all_engines():
            assert isinstance(e, TTSEngine)
        if registry.get("edge").is_available():
            assert registry.default_voice("vi").id == "edge:vi-VN-HoaiMyNeural"
            assert registry.find_voice("edge:zh-CN-XiaoxiaoNeural") is not None
    finally:
        registry.reset()


# ---------------------------------------------------------------- network (opt-in)
@pytest.mark.skipif(os.environ.get("GIONGDOC_NETWORK_TESTS") != "1",
                    reason="network test; set GIONGDOC_NETWORK_TESTS=1")
def test_edge_real_network():
    eng = EdgeEngine()
    if not eng.is_available():
        pytest.skip("edge-tts not installed")
    v = registry.find_voice("edge:vi-VN-HoaiMyNeural") or builtin_voices()[0]
    data = eng.fetch_mp3("Xin chào, đây là GiongDoc.", v, ProsodySettings(rate=1.1, pitch=1))
    assert len(data) > 1000
