"""Small, vectorised DSP toolkit (numpy only; scipy used when present).

All functions take and return :class:`AudioClip` (mono float32) unless noted.
Array-level helpers (``*_array``) are exposed for internal reuse.
"""
from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from ..core import SAMPLE_RATE, AudioClip

try:  # optional accelerators
    from scipy import signal as _sps  # type: ignore
except Exception:  # pragma: no cover - scipy absent
    _sps = None

EPS = 1e-12


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def lin_to_db(x: float) -> float:
    return float(20.0 * math.log10(max(float(x), EPS)))


def _clip_like(clip: AudioClip, samples: np.ndarray) -> AudioClip:
    return AudioClip(np.asarray(samples, dtype=np.float32), clip.sample_rate)


def _f32(x) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(x, dtype=np.float32).reshape(-1))


# --------------------------------------------------------------------------- resample

def _resample_linear(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    n_out = int(round(len(x) * sr_out / sr_in))
    if n_out <= 0 or len(x) == 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n_out, dtype=np.float64) * (sr_in / sr_out)
    return np.interp(t, np.arange(len(x), dtype=np.float64), x).astype(np.float32)


def _resample_polyphase(x: np.ndarray, sr_in: int, sr_out: int, half_taps: int = 16,
                        beta: float = 8.0, chunk: int = 1 << 16) -> np.ndarray:
    """Kaiser-windowed sinc resampler with a polyphase coefficient table."""
    frac = Fraction(sr_out, sr_in)
    up, down = frac.numerator, frac.denominator
    n_out = int(round(len(x) * sr_out / sr_in))
    if n_out <= 0 or len(x) == 0:
        return np.zeros(0, dtype=np.float32)
    cutoff = min(1.0, sr_out / sr_in) * 0.94          # normalised to input Nyquist
    hw = int(math.ceil(half_taps / min(1.0, sr_out / sr_in)))  # half width (input samples)
    offs = np.arange(-hw + 1, hw + 1, dtype=np.int64)  # 2*hw taps
    xp = np.concatenate([np.zeros(hw, np.float64), x.astype(np.float64), np.zeros(hw + 1, np.float64)])

    def kernel(fr: np.ndarray) -> np.ndarray:  # fr: (...,) fractional position in [0,1)
        t = fr[..., None] - offs[None, :]
        w = np.clip(1.0 - (t / (hw + 1)) ** 2, 0.0, None)
        h = cutoff * np.sinc(cutoff * t) * np.i0(beta * np.sqrt(w)) / np.i0(beta)
        return h / np.sum(h, axis=-1, keepdims=True)

    table = kernel(np.arange(up, dtype=np.float64) / up) if up <= 4096 else None
    out = np.empty(n_out, dtype=np.float32)
    for s in range(0, n_out, chunk):
        n = np.arange(s, min(n_out, s + chunk), dtype=np.int64)
        pos = n * down
        base = pos // up
        phase = pos % up
        h = table[phase] if table is not None else kernel(phase / up)
        idx = base[:, None] + offs[None, :] + hw
        out[s:s + len(n)] = np.einsum("ij,ij->i", xp[idx], h)
    return out


def resample(clip: AudioClip, target_sr: int = SAMPLE_RATE, method: str = "polyphase") -> AudioClip:
    """Resample to ``target_sr``. ``method``: "polyphase" (default, band-limited) or "linear"."""
    sr_in = int(clip.sample_rate)
    target_sr = int(target_sr)
    x = _f32(clip.samples)
    if sr_in == target_sr or len(x) == 0:
        return AudioClip(x.copy(), target_sr)
    if method == "linear":
        y = _resample_linear(x, sr_in, target_sr)
    elif _sps is not None:
        frac = Fraction(target_sr, sr_in)
        y = _sps.resample_poly(x, frac.numerator, frac.denominator).astype(np.float32)
    else:
        y = _resample_polyphase(x, sr_in, target_sr)
    return AudioClip(y, target_sr)


# --------------------------------------------------------------------------- basic ops

def remove_dc(clip: AudioClip) -> AudioClip:
    x = _f32(clip.samples)
    if len(x) == 0:
        return _clip_like(clip, x)
    return _clip_like(clip, x - np.float32(np.mean(x, dtype=np.float64)))


def gain(clip: AudioClip, db: float) -> AudioClip:
    return _clip_like(clip, _f32(clip.samples) * np.float32(db_to_lin(db)))


def peak(clip: AudioClip) -> float:
    x = _f32(clip.samples)
    return float(np.max(np.abs(x))) if len(x) else 0.0


def rms(clip: AudioClip) -> float:
    x = _f32(clip.samples)
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def raised_cosine(n: int) -> np.ndarray:
    """Rising raised-cosine ramp of length n, 0 -> 1 (excludes the final 1)."""
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    return (0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)).astype(np.float32)


def fade_in_array(x: np.ndarray, n: int) -> np.ndarray:
    n = min(int(n), len(x))
    if n > 0:
        x[:n] *= raised_cosine(n)
    return x


def fade_out_array(x: np.ndarray, n: int) -> np.ndarray:
    n = min(int(n), len(x))
    if n > 0:
        x[len(x) - n:] *= raised_cosine(n)[::-1]
        x[-1] = 0.0
    return x


def fade_in(clip: AudioClip, ms: float = 8.0) -> AudioClip:
    x = _f32(clip.samples).copy()
    return _clip_like(clip, fade_in_array(x, int(clip.sample_rate * ms / 1000)))


def fade_out(clip: AudioClip, ms: float = 8.0) -> AudioClip:
    x = _f32(clip.samples).copy()
    return _clip_like(clip, fade_out_array(x, int(clip.sample_rate * ms / 1000)))


# --------------------------------------------------------------------------- trimming

def trim_bounds(x: np.ndarray, sample_rate: int, threshold_db: float = -45.0,
                keep_ms: float = 30.0, frame_ms: float = 10.0) -> tuple[int, int]:
    """Return (start, end) sample indices of the non-silent region (+keep_ms padding)."""
    n = len(x)
    if n == 0:
        return 0, 0
    frame = max(1, int(sample_rate * frame_ms / 1000))
    nf = int(math.ceil(n / frame))
    padded = np.zeros(nf * frame, dtype=np.float32)
    padded[:n] = x
    frms = np.sqrt(np.mean(np.square(padded.reshape(nf, frame), dtype=np.float64), axis=1))
    thr = db_to_lin(threshold_db)
    loud = np.nonzero(frms > thr)[0]
    if len(loud) == 0:
        return 0, 0
    # refine to sample precision within the first/last loud frame (+ neighbour)
    a0 = max(0, (loud[0] - 1) * frame)
    seg = np.nonzero(np.abs(x[a0:(loud[0] + 1) * frame]) > thr)[0]
    start = a0 + (int(seg[0]) if len(seg) else frame)
    b1 = min(n, (loud[-1] + 2) * frame)
    b0 = loud[-1] * frame
    seg = np.nonzero(np.abs(x[b0:b1]) > thr)[0]
    end = b0 + (int(seg[-1]) + 1 if len(seg) else 0)
    keep = int(sample_rate * keep_ms / 1000)
    return max(0, start - keep), min(n, end + keep)


def trim_silence(clip: AudioClip, threshold_db: float = -45.0, keep_ms: float = 30.0) -> AudioClip:
    """Remove leading/trailing silence below ``threshold_db`` dBFS, keeping ``keep_ms`` margin."""
    x = _f32(clip.samples)
    s, e = trim_bounds(x, clip.sample_rate, threshold_db, keep_ms)
    return _clip_like(clip, x[s:e].copy())


# --------------------------------------------------------------------------- loudness

def _biquad_high_shelf(fs: float, fc=1681.974450955533, gain_db=3.999843853973347, q=0.7071752369554196):
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * fc / fs
    alpha = math.sin(w0) / (2 * q)
    c = math.cos(w0)
    sa = 2 * math.sqrt(a) * alpha
    b = [a * ((a + 1) + (a - 1) * c + sa), -2 * a * ((a - 1) + (a + 1) * c), a * ((a + 1) + (a - 1) * c - sa)]
    den = [(a + 1) - (a - 1) * c + sa, 2 * ((a - 1) - (a + 1) * c), (a + 1) - (a - 1) * c - sa]
    return b, den


def _biquad_high_pass(fs: float, fc=38.13547087602444, q=0.5003270373238773):
    w0 = 2 * math.pi * fc / fs
    alpha = math.sin(w0) / (2 * q)
    c = math.cos(w0)
    return [(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + alpha, -2 * c, 1 - alpha]


def _k_weight_power(n_fft: int, fs: float) -> np.ndarray:
    """|H(f)|^2 of the BS.1770 K-weighting filter at rfft bins."""
    w = 2 * np.pi * np.fft.rfftfreq(n_fft, d=1.0)  # rad/sample
    z1 = np.exp(-1j * w)
    resp = np.ones_like(z1)
    for b, a in (_biquad_high_shelf(fs), _biquad_high_pass(fs)):
        num = b[0] + b[1] * z1 + b[2] * z1 * z1
        den = a[0] + a[1] * z1 + a[2] * z1 * z1
        resp = resp * num / den
    return np.abs(resp) ** 2


def _k_weighted(x: np.ndarray, fs: int, chunk: int = 1 << 20) -> np.ndarray:
    """Zero-phase K-weighting (FFT magnitude) - fine for energy measurement."""
    out = np.empty(len(x), dtype=np.float64)
    resp_cache: dict[int, np.ndarray] = {}
    for s in range(0, len(x), chunk):
        seg = x[s:s + chunk].astype(np.float64)
        nfft = 1 << int(math.ceil(math.log2(max(2, len(seg)))))
        if nfft not in resp_cache:
            resp_cache[nfft] = np.sqrt(_k_weight_power(nfft, fs))
        spec = np.fft.rfft(seg, nfft) * resp_cache[nfft]
        out[s:s + len(seg)] = np.fft.irfft(spec, nfft)[: len(seg)]
    return out


def integrated_loudness_array(x: np.ndarray, sample_rate: int) -> float:
    """Approximate ITU-R BS.1770 integrated loudness (LUFS) of a mono signal."""
    x = _f32(x)
    if len(x) == 0 or not np.any(x):
        return float("-inf")
    y = _k_weighted(x, sample_rate)
    sq = np.square(y)
    block = int(0.4 * sample_rate)
    if len(x) < block:
        ms = float(np.mean(sq))
        return -0.691 + 10 * math.log10(max(ms, EPS))
    hop = block // 4
    cs = np.concatenate([[0.0], np.cumsum(sq)])
    starts = np.arange(0, len(x) - block + 1, hop)
    z = (cs[starts + block] - cs[starts]) / block
    lk = -0.691 + 10 * np.log10(np.maximum(z, EPS))
    z = z[lk > -70.0]
    if len(z) == 0:
        return float("-inf")
    rel = -0.691 + 10 * math.log10(float(np.mean(z))) - 10.0
    z = z[(-0.691 + 10 * np.log10(np.maximum(z, EPS))) > rel]
    if len(z) == 0:
        return float("-inf")
    return -0.691 + 10 * math.log10(float(np.mean(z)))


def integrated_loudness(clip: AudioClip) -> float:
    return integrated_loudness_array(clip.samples, clip.sample_rate)


def normalize_peak(clip: AudioClip, peak_db: float = -1.0) -> AudioClip:
    p = peak(clip)
    if p <= EPS:
        return _clip_like(clip, _f32(clip.samples).copy())
    return _clip_like(clip, _f32(clip.samples) * np.float32(db_to_lin(peak_db) / p))


def normalize_rms(clip: AudioClip, target_db: float = -20.0, max_gain_db: float = 30.0) -> AudioClip:
    r = rms(clip)
    if r <= EPS:
        return _clip_like(clip, _f32(clip.samples).copy())
    g = min(target_db - lin_to_db(r), max_gain_db)
    return gain(clip, g)


def loudness_gain_db(clip: AudioClip, target_lufs: float = -16.0, max_gain_db: float = 30.0) -> float:
    lufs = integrated_loudness(clip)
    if not math.isfinite(lufs):
        return 0.0
    return float(np.clip(target_lufs - lufs, -max_gain_db, max_gain_db))


def normalize_loudness(clip: AudioClip, target_lufs: float = -16.0, peak_ceiling_db: float | None = -1.0,
                       max_gain_db: float = 30.0, limit: bool = True) -> AudioClip:
    """Gain to approx ``target_lufs``; then keep peaks under ``peak_ceiling_db``.

    With ``limit=True`` overs are handled by :func:`soft_limit`, otherwise the
    gain is reduced so the peak meets the ceiling.
    """
    g = loudness_gain_db(clip, target_lufs, max_gain_db)
    out = gain(clip, g)
    if peak_ceiling_db is not None and peak(out) > db_to_lin(peak_ceiling_db):
        out = soft_limit(out, peak_ceiling_db) if limit else normalize_peak(out, peak_ceiling_db)
    return out


# --------------------------------------------------------------------------- limiter

def _sliding_min(x: np.ndarray, w: int) -> np.ndarray:
    """Centered running minimum with window ``w`` (odd), van Herk/Gil-Werman, vectorised."""
    if w <= 1 or len(x) == 0:
        return x.copy()
    r = w // 2
    n = len(x)
    pad = np.concatenate([np.full(r, np.inf), x, np.full(r, np.inf)])
    nb = int(math.ceil(len(pad) / w))
    full = np.full(nb * w, np.inf)
    full[: len(pad)] = pad
    blocks = full.reshape(nb, w)
    pre = np.minimum.accumulate(blocks, axis=1).reshape(-1)
    suf = np.minimum.accumulate(blocks[:, ::-1], axis=1)[:, ::-1].reshape(-1)
    i = np.arange(n)
    j = i + w - 1
    return np.minimum(suf[i], pre[np.minimum(j, len(pre) - 1)])


def _box(x: np.ndarray, m: int) -> np.ndarray:
    """Centered moving average of odd length m, edge-padded, O(n)."""
    r = m // 2
    p = np.concatenate([np.full(r, x[0]), x, np.full(r, x[-1])])
    cs = np.concatenate([[0.0], np.cumsum(p)])
    return (cs[m:] - cs[:-m]) / m


def _smooth(x: np.ndarray, w: int) -> np.ndarray:
    """Triangular smoothing (two boxes) with total support <= w samples."""
    m = max(1, ((w + 1) // 2) | 1)
    if m <= 1 or len(x) == 0:
        return x
    return _box(_box(x, m), m)


def soft_limit(clip: AudioClip, ceiling_db: float = -1.0, attack_ms: float = 5.0,
               release_ms: float = 60.0, knee_db: float = 2.0) -> AudioClip:
    """Look-ahead limiter with smooth gain (no clicks), then a hard safety clip.

    Gain reduction begins ``knee_db`` below the ceiling with a soft curve;
    the gain envelope is a running minimum over ``attack_ms`` smoothed by a
    raised-cosine window so it never overshoots the required reduction.
    """
    x = _f32(clip.samples).astype(np.float64)
    ceil = db_to_lin(ceiling_db)
    if len(x) == 0 or np.max(np.abs(x)) <= ceil * db_to_lin(-knee_db):
        return _clip_like(clip, x)
    a = np.abs(x)
    knee = ceil * db_to_lin(-knee_db)
    # soft-knee static curve: output = knee + (ceil-knee)*tanh((a-knee)/(ceil-knee))
    span = ceil - knee
    target = np.where(a > knee, knee + span * np.tanh((a - knee) / span), a)
    need = np.where(a > EPS, np.minimum(1.0, target / np.maximum(a, EPS)), 1.0)
    sr = clip.sample_rate
    wa = max(3, int(sr * attack_ms / 1000) | 1)
    g = _sliding_min(need, 2 * wa + 1)
    g = np.minimum(_smooth(g, wa), 1.0)
    # release: hold the minimum longer and smooth it, so the gain recovers
    # gently between words (min radius >= smoothing radius => never above g)
    wr = max(3, int(sr * release_ms / 1000) | 1)
    if wr > wa:
        g = _smooth(_sliding_min(g, wr), wr)
    y = x * g
    y = np.clip(y, -ceil, ceil)
    return _clip_like(clip, y)


# --------------------------------------------------------------------------- tempo

def _atempo_chain(factor: float) -> str:
    parts = []
    f = float(factor)
    while f > 2.0:
        parts.append(2.0)
        f /= 2.0
    while f < 0.5:
        parts.append(0.5)
        f /= 0.5
    parts.append(f)
    return ",".join(f"atempo={p:.6f}" for p in parts)


def change_speed(clip: AudioClip, factor: float) -> AudioClip:
    """Time-stretch by ``factor`` (>1 faster) keeping pitch, via ffmpeg ``atempo``.

    Raises :class:`codec.AudioCodecError` when ffmpeg is unavailable.
    """
    if factor <= 0:
        raise ValueError("factor must be > 0")
    if abs(factor - 1.0) < 1e-3 or len(clip.samples) == 0:
        return _clip_like(clip, _f32(clip.samples).copy())
    from .codec import run_ffmpeg

    sr = int(clip.sample_rate)
    raw = run_ffmpeg(
        ["-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-filter:a", _atempo_chain(factor),
         "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(sr), "pipe:1"],
        input_bytes=_f32(clip.samples).astype("<f4").tobytes(),
    )
    return AudioClip(np.frombuffer(raw, dtype="<f4").astype(np.float32), sr)
