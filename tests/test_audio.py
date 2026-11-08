import math
import os

import numpy as np
import pytest

from giongdoc.audio import (SmoothingSettings, assemble, assemble_with_timeline, codec, dsp,
                            export_audio, export_srt, to_srt)
from giongdoc.audio.timeline import jittered_pauses
from giongdoc.core import SAMPLE_RATE, AudioClip

SR = SAMPLE_RATE
HAS_FFMPEG = codec.find_ffmpeg() is not None


def sine(freq, ms, amp=0.5, phase=0.3, sr=SR, lead_ms=0, tail_ms=0):
    n = int(sr * ms / 1000)
    t = np.arange(n) / sr
    x = (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
    # like real speech, sound next to engine silence padding has a soft onset/decay;
    # edges with no padding are left abrupt (worst case for joins)
    k = int(sr * 0.015)
    if lead_ms:
        x[:k] *= np.linspace(0, 1, k, dtype=np.float32)
    if tail_ms:
        x[-k:] *= np.linspace(1, 0, k, dtype=np.float32)
    lead = np.zeros(int(sr * lead_ms / 1000), np.float32)
    tail = np.zeros(int(sr * tail_ms / 1000), np.float32)
    return AudioClip(np.concatenate([lead, x, tail]), sr)


def noise(ms, amp=0.1, seed=0, sr=SR):
    rng = np.random.default_rng(seed)
    return AudioClip((amp * rng.standard_normal(int(sr * ms / 1000))).astype(np.float32), sr)


# ------------------------------------------------------------------ dsp

def test_resample_length_and_tone():
    c = sine(1000, 500, sr=44100)
    r = dsp.resample(c, SR)
    assert r.sample_rate == SR
    assert abs(len(r.samples) - SR // 2) <= 1
    # tone frequency preserved
    spec = np.abs(np.fft.rfft(r.samples))
    f = np.fft.rfftfreq(len(r.samples), 1 / SR)[np.argmax(spec)]
    assert abs(f - 1000) < 5
    lin = dsp.resample(c, SR, method="linear")
    assert abs(len(lin.samples) - len(r.samples)) <= 1


def test_trim_silence_keeps_margin():
    c = sine(300, 400, lead_ms=200, tail_ms=300)
    t = dsp.trim_silence(c, threshold_db=-45, keep_ms=30)
    assert abs(t.duration_s - 0.46) < 0.012
    assert len(dsp.trim_silence(AudioClip.silence(500)).samples) == 0


def test_fades_raised_cosine():
    c = sine(200, 200, amp=1.0, phase=math.pi / 2)
    f = dsp.fade_out(dsp.fade_in(c, 10), 10)
    assert abs(f.samples[0]) < 1e-6 and abs(f.samples[-1]) < 1e-6
    assert np.allclose(f.samples[1000:2000], c.samples[1000:2000])


def test_remove_dc_and_normalize():
    c = AudioClip(sine(200, 300).samples + 0.2)
    assert abs(np.mean(dsp.remove_dc(c).samples)) < 1e-4
    p = dsp.normalize_peak(sine(200, 300), -1.0)
    assert abs(dsp.lin_to_db(dsp.peak(p)) + 1.0) < 0.01
    n = dsp.normalize_loudness(noise(2000), -16.0)
    assert abs(dsp.integrated_loudness(n) + 16.0) < 0.5


def test_limiter_ceiling_and_smooth():
    c = AudioClip(sine(150, 1000, amp=1.6).samples)
    lim = dsp.soft_limit(c, -1.0)
    assert dsp.peak(lim) <= dsp.db_to_lin(-1.0) + 1e-6
    # no hard clipping steps: derivative bounded by the source's
    assert np.max(np.abs(np.diff(lim.samples))) <= np.max(np.abs(np.diff(c.samples))) * 1.05


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg missing")
def test_change_speed():
    c = sine(220, 2000)
    fast = dsp.change_speed(c, 1.5)
    assert abs(fast.duration_s - 2.0 / 1.5) < 0.05
    slow = dsp.change_speed(c, 0.4)  # chained atempo
    assert abs(slow.duration_s - 5.0) < 0.1


# ------------------------------------------------------------------ assembly

def _parts():
    return [
        (sine(220, 700, amp=0.6, phase=0.9, lead_ms=80, tail_ms=120), 400),
        (sine(330, 600, amp=0.2, phase=2.1, lead_ms=50), 0),         # crossfade join
        (sine(262, 500, amp=0.9, phase=1.3, tail_ms=200), 650),
        (sine(294, 650, amp=0.05, phase=0.4, sr=22050), 250),       # quiet + other rate
    ]


def test_no_clicks_at_joins():
    st = SmoothingSettings(room_tone_db=0)
    out = assemble(_parts(), st).samples
    pk = float(np.max(np.abs(out)))
    # a pure sine of the highest freq at this peak changes at most 2*pi*f/sr*peak per sample
    bound = 2 * np.pi * 330 / SR * pk * 1.6
    assert float(np.max(np.abs(np.diff(out)))) < bound
    assert abs(out[0]) < 1e-3 and abs(out[-1]) < 1e-3


def test_without_fades_would_click():
    # sanity: the test above is meaningful -- raw concatenation has jumps
    raw = np.concatenate([p[0].samples for p in _parts()[:3]])
    assert float(np.max(np.abs(np.diff(raw)))) > 2 * np.pi * 330 / SR * 0.9 * 1.6


def test_pause_lengths_within_jitter():
    st = SmoothingSettings(pause_jitter_pct=8, room_tone_db=0)
    parts = _parts()
    _, tl = assemble_with_timeline(parts, None, st)
    for i, (_, pause) in enumerate(parts[:-1]):
        gap_ms = (tl[i + 1][0] - tl[i][1]) * 1000
        if pause == 0:
            assert gap_ms == 0  # crossfaded: shared boundary
        else:
            assert pause * 0.92 - 0.1 <= gap_ms <= pause * 1.08 + 0.1
    # jitter really varies, and is deterministic
    p1 = jittered_pauses([500] * 20, st)
    assert len(set(p1)) > 5 and p1 == jittered_pauses([500] * 20, st)
    assert jittered_pauses([500] * 3, SmoothingSettings(pause_jitter_pct=0)) == [12000] * 3


def test_pause_is_quiet_in_waveform():
    st = SmoothingSettings(room_tone_db=-60)
    out, tl = assemble_with_timeline(_parts(), None, st)
    a = int(tl[0][1] * SR) + 10
    b = int(tl[1][0] * SR) - 10
    gap = out.samples[a:b]
    assert len(gap) > 0.3 * SR
    r = dsp.lin_to_db(float(np.sqrt(np.mean(gap.astype(np.float64) ** 2))))
    assert -66 < r < -54  # room tone present, not digital silence


def test_loudness_near_target_and_peak_ceiling():
    parts = [(noise(800, amp=0.02, seed=1), 300), (noise(900, amp=0.4, seed=2), 500),
             (sine(440, 800, amp=0.95), 0), (noise(700, amp=0.1, seed=3), 300)]
    out = assemble(parts, SmoothingSettings(target_lufs=-16))
    assert abs(dsp.integrated_loudness(out) + 16) < 1.0
    assert dsp.peak(out) <= dsp.db_to_lin(-1.0) + 1e-6


def test_per_clip_loudness_matched():
    st = SmoothingSettings(room_tone_db=0, pause_jitter_pct=0)
    parts = [(noise(1000, amp=0.01, seed=4), 500), (noise(1000, amp=0.3, seed=5), 0)]
    out, tl = assemble_with_timeline(parts, None, st)
    seg = [out.samples[int(a * SR) + 2400:int(b * SR) - 2400] for a, b, _ in tl]
    l1, l2 = (dsp.integrated_loudness_array(s, SR) for s in seg)
    assert abs(l1 - l2) < 1.0


def test_deterministic_and_breath():
    st = SmoothingSettings(breath=True)
    a = assemble(_parts(), st).samples
    b = assemble(_parts(), st).samples
    assert np.array_equal(a, b)
    no_breath = assemble(_parts(), SmoothingSettings(breath=False)).samples
    assert len(a) == len(no_breath) and not np.array_equal(a, no_breath)


def test_timeline_texts_and_edge_cases():
    out, tl = assemble_with_timeline([(sine(200, 300), 100), (AudioClip.silence(200), 100),
                                      (sine(250, 300), 0)], ["a", "", "c"])
    assert [t for *_, t in tl] == ["a", "", "c"]
    assert all(s <= e for s, e, _ in tl)
    assert all(tl[i][1] <= tl[i + 1][0] + 1e-9 for i in range(len(tl) - 1))
    assert abs(tl[-1][1] - out.duration_s) < 1e-6
    empty, tl2 = assemble_with_timeline([], [])
    assert len(empty.samples) == 0 and tl2 == []
    with pytest.raises(ValueError):
        assemble_with_timeline([(sine(200, 100), 0)], ["a", "b"])


# ------------------------------------------------------------------ codec / export

def test_wav_roundtrip(tmp_path):
    c = sine(440, 500, amp=0.7)
    p = export_audio(c, tmp_path / "x.wav", "wav")
    back = codec.load_file(p)
    assert back.sample_rate == SR and len(back.samples) == len(c.samples)
    assert np.max(np.abs(back.samples - c.samples)) < 2 / 32768
    back2 = codec.decode_bytes(p.read_bytes())
    assert np.array_equal(back.samples, back2.samples)
    assert codec.wav_bytes(c)[:4] == b"RIFF"


def test_wav_export_resampled_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(codec, "_SYSTEM_DIRS", ())
    monkeypatch.setenv("GIONGDOC_FFMPEG", "/nonexistent")
    assert codec.find_ffmpeg() is None
    p = export_audio(sine(440, 500), tmp_path / "y.wav", "wav", sample_rate=44100)
    import wave
    with wave.open(str(p)) as w:
        assert w.getframerate() == 44100 and abs(w.getnframes() - 22050) <= 1
    back = codec.load_file(p)  # stdlib path resamples back to 24 kHz
    assert abs(len(back.samples) - 12000) <= 1
    with pytest.raises(codec.AudioCodecError):
        export_audio(sine(440, 100), tmp_path / "z.mp3", "mp3")


def test_find_ffmpeg_env(tmp_path, monkeypatch):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("GIONGDOC_FFMPEG", str(fake))
    assert codec.find_ffmpeg() == str(fake)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg missing")
@pytest.mark.parametrize("fmt", ["mp3", "m4a"])
def test_lossy_export(tmp_path, fmt):
    c = assemble([(sine(440, 800), 300), (noise(600, seed=7), 0)])
    p = export_audio(c, tmp_path / f"out.{fmt}", fmt, bitrate="128k", sample_rate=44100,
                     metadata={"title": "Giọng Đọc thử", "artist": "GiongDoc"})
    assert p.exists() and p.stat().st_size > 1000
    assert not any(n.name.endswith(".part") for n in tmp_path.iterdir())
    back = codec.decode_bytes(p.read_bytes())
    assert abs(back.duration_s - c.duration_s) < 0.1
    assert abs(dsp.integrated_loudness(back) - dsp.integrated_loudness(c)) < 1.5
    import subprocess
    probe = subprocess.run([codec.find_ffmpeg(), "-hide_banner", "-i", str(p)],
                           capture_output=True, text=True).stderr
    assert "Giọng Đọc thử" in probe and "44100" in probe


def test_export_rejects_format(tmp_path):
    with pytest.raises(ValueError):
        export_audio(sine(440, 100), tmp_path / "a.ogg", "ogg")


# ------------------------------------------------------------------ SRT

def test_srt_format(tmp_path):
    segs = [(0.0, 1.2345, "Xin chào các bạn."), (1.5, 3661.002, "Second line   here"), (4000, 4001, "")]
    p = export_srt(segs, tmp_path / "s.srt")
    text = p.read_text(encoding="utf-8")
    assert text == ("1\n00:00:00,000 --> 00:00:01,234\nXin chào các bạn.\n\n"
                    "2\n00:00:01,500 --> 01:01:01,002\nSecond line here\n")
    wrapped = to_srt([(0, 1, "một hai ba bốn năm sáu bảy tám chín mười")], max_line_chars=12)
    body = wrapped.split("\n", 2)[2].strip().split("\n")
    assert len(body) > 1 and all(len(l) <= 12 for l in body)
    md = to_srt([(0, 0.2, "a"), (0.5, 1, "b")], min_duration_s=1.0)
    assert "00:00:00,000 --> 00:00:00,500" in md


def test_srt_from_timeline(tmp_path):
    _, tl = assemble_with_timeline(_parts(), ["Một.", "Hai", "Ba!", "Bốn?"])
    blocks = to_srt(tl).strip().split("\n\n")
    assert len(blocks) == 4 and blocks[3].startswith("4\n")
