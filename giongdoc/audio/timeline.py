"""Assembly with per-segment timing (for SRT export and UI highlighting).

``smoothing.assemble`` is a thin wrapper around :func:`assemble_with_timeline`.
"""
from __future__ import annotations

import math

import numpy as np

from ..core import AudioClip
from . import dsp
from .smoothing import SmoothingSettings

Timeline = list[tuple[float, float, str]]

_ROOM_PERIOD = 1 << 18  # ~10.9 s at 24 kHz; FFT noise is periodic -> seamless tiling


def _shaped_noise(n: int, rng: np.random.Generator, sr: int, tilt: float = -0.5,
                  lo: float = 40.0, hi: float | None = None) -> np.ndarray:
    """Periodic noise with spectrum ~ f**tilt between lo..hi Hz, unit RMS."""
    spec = rng.standard_normal(n // 2 + 1) + 1j * rng.standard_normal(n // 2 + 1)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    shape = np.where(f > 0, np.power(np.maximum(f, 1.0), tilt), 0.0)
    shape *= 1.0 / (1.0 + (lo / np.maximum(f, 1e-6)) ** 4)          # soft high-pass
    if hi:
        shape *= 1.0 / (1.0 + (f / hi) ** 4)                          # soft low-pass
    y = np.fft.irfft(spec * shape, n)
    r = float(np.sqrt(np.mean(y * y)))
    return (y / r if r > 0 else y).astype(np.float32)


def room_tone(n: int, level_db: float, sr: int, seed: int) -> np.ndarray:
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    rng = np.random.default_rng([seed, 1])
    base = _shaped_noise(min(_ROOM_PERIOD, max(1024, 1 << int(math.ceil(math.log2(n))))), rng, sr,
                         tilt=-0.5, lo=60.0, hi=6000.0)
    return (np.resize(base, n) * np.float32(dsp.db_to_lin(level_db))).astype(np.float32)


def breath_sound(n: int, rms_db: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """A soft, airy in-breath: band-limited noise with a slow rise / quick fall."""
    if n <= 16:
        return np.zeros(max(0, n), dtype=np.float32)
    nfft = 1 << int(math.ceil(math.log2(n)))
    y = _shaped_noise(nfft, rng, sr, tilt=-0.3, lo=500.0, hi=3500.0)[:n]
    rise = int(n * 0.6)
    env = np.concatenate([dsp.raised_cosine(rise), dsp.raised_cosine(n - rise)[::-1]])
    env = env ** 1.5
    y = y * env
    r = float(np.sqrt(np.mean(y.astype(np.float64) ** 2)))
    if r > 0:
        y *= dsp.db_to_lin(rms_db) / r
    return y.astype(np.float32)


def _prepare(clip: AudioClip, st: SmoothingSettings) -> np.ndarray:
    c = clip if clip.sample_rate == st.sample_rate else dsp.resample(clip, st.sample_rate)
    c = dsp.remove_dc(c)
    if st.normalize_each:
        c = dsp.gain(c, dsp.loudness_gain_db(c, st.target_lufs, max_gain_db=24.0))
    x = np.asarray(c.samples, dtype=np.float32)
    if st.trim:
        s, e = dsp.trim_bounds(x, st.sample_rate, st.trim_threshold_db, st.trim_keep_ms)
        x = x[s:e]
    return np.array(x, dtype=np.float32, copy=True)


def jittered_pauses(pauses_ms: list[int], settings: SmoothingSettings) -> list[int]:
    """Pause lengths in samples with deterministic +/- ``pause_jitter_pct`` variation."""
    rng = np.random.default_rng([settings.seed, 0])
    u = rng.uniform(-1.0, 1.0, size=len(pauses_ms))
    pct = max(0.0, float(settings.pause_jitter_pct)) / 100.0
    out = []
    for p, ui in zip(pauses_ms, u):
        p = max(0.0, float(p))
        ms = p * (1.0 + pct * ui) if p > 0 else 0.0
        out.append(int(round(ms * settings.sample_rate / 1000.0)))
    return out


def assemble_with_timeline(parts: list[tuple[AudioClip, int]], texts: list[str] | None = None,
                           settings: SmoothingSettings | None = None) -> tuple[AudioClip, Timeline]:
    """Assemble clips and return ``(clip, [(start_s, end_s, text), ...])``.

    Times refer to the final clip; for crossfaded joins the boundary is the
    midpoint of the overlap, so entries never overlap.
    """
    st = settings or SmoothingSettings()
    sr = int(st.sample_rate)
    if texts is not None and len(texts) != len(parts):
        raise ValueError("texts must have the same length as parts")
    texts = list(texts) if texts is not None else [""] * len(parts)
    if not parts:
        return AudioClip(np.zeros(0, dtype=np.float32), sr), []

    clips = [_prepare(c, st) for c, _ in parts]
    pauses = jittered_pauses([p for _, p in parts], st)
    n = len(clips)
    # join[i]: clip i crossfades into clip i+1
    join = [i < n - 1 and pauses[i] == 0 and len(clips[i]) > 0 and len(clips[i + 1]) > 0 for i in range(n)]

    fade_n = int(sr * st.fade_ms / 1000)
    xf_n = int(sr * st.crossfade_ms / 1000)
    total = sum(len(c) for c in clips) + sum(pauses)
    out = np.zeros(total, dtype=np.float32)
    starts = [0] * n
    ends = [0] * n
    breaths: list[tuple[int, int]] = []
    rng_breath = np.random.default_rng([st.seed, 2])
    cursor = 0

    for i, x in enumerate(clips):
        joined_in = i > 0 and join[i - 1]
        if not join[i]:
            dsp.fade_out_array(x, min(fade_n, len(x) // 2))
        if joined_in:
            ov = min(xf_n, len(clips[i - 1]) // 2, len(x) // 2)
            start = cursor - ov
            if ov > 0:
                t = (np.arange(ov, dtype=np.float64) + 0.5) / ov * (np.pi / 2)
                out[start:cursor] *= np.cos(t).astype(np.float32)
                x[:ov] *= np.sin(t).astype(np.float32)
            mid = start + ov // 2
            ends[i - 1] = mid
            starts[i] = mid
        else:
            dsp.fade_in_array(x, min(fade_n, len(x) // 2))
            start = cursor
            starts[i] = start
        out[start:start + len(x)] += x
        cursor = start + len(x)
        ends[i] = cursor
        pn = pauses[i]
        if st.breath and i < n - 1 and pn >= st.breath_min_pause_ms * sr / 1000 and len(clips[i + 1]):
            bl = int(min(0.32 * sr, 0.45 * pn))
            gap_before_next = int(min(0.07 * sr, 0.15 * pn))
            b0 = cursor + pn - gap_before_next - bl
            breaths.append((b0, bl))
        cursor += pn

    out = out[:cursor]
    for b0, bl in breaths:
        out[b0:b0 + bl] += breath_sound(bl, st.target_lufs + st.breath_db, sr, rng_breath)

    # final loudness + room tone + limiter
    clip = AudioClip(out, sr)
    clip = dsp.gain(clip, dsp.loudness_gain_db(clip, st.target_lufs, max_gain_db=24.0))
    y = np.asarray(clip.samples, dtype=np.float32).copy()
    if st.room_tone_db and st.room_tone_db < 0 and len(y):
        bed = room_tone(len(y), st.room_tone_db, sr, st.seed)
        edge = min(int(0.02 * sr), len(bed) // 2)
        dsp.fade_in_array(bed, edge)
        dsp.fade_out_array(bed, edge)
        y += bed
    clip = dsp.soft_limit(AudioClip(y, sr), st.peak_ceiling_db)

    timeline = [(starts[i] / sr, ends[i] / sr, texts[i]) for i in range(n)]
    return clip, timeline
