"""Decoding / encoding helpers.

Everything is converted to the internal format: mono float32 in [-1, 1] at
``core.SAMPLE_RATE`` (24 kHz).  PCM WAV is read with the stdlib ``wave``
module (no ffmpeg needed); everything else goes through the ffmpeg binary
using pipes.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from ..core import SAMPLE_RATE, AudioClip


class AudioCodecError(RuntimeError):
    pass


# --------------------------------------------------------------------------- ffmpeg

_SYSTEM_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")


def _bundled_candidates() -> list[Path]:
    out: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        out += [base / "ffmpeg", base / "bin" / "ffmpeg"]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent  # .../Contents/MacOS
        contents = exe_dir.parent
        out += [
            exe_dir / "ffmpeg",
            contents / "Resources" / "bin" / "ffmpeg",
            contents / "Resources" / "ffmpeg",
            contents / "Frameworks" / "ffmpeg",
            contents / "Frameworks" / "bin" / "ffmpeg",
        ]
    return out


def _is_exe(p: Path | str) -> bool:
    return os.path.isfile(p) and os.access(p, os.X_OK)


def find_ffmpeg() -> str | None:
    """Locate an ffmpeg binary.

    Order: ``$GIONGDOC_FFMPEG`` -> bundled next to the frozen app -> ``PATH``
    -> ``/opt/homebrew/bin`` -> ``/usr/local/bin``.  Returns None if missing.
    """
    env = os.environ.get("GIONGDOC_FFMPEG")
    if env and _is_exe(env):
        return env
    for cand in _bundled_candidates():
        if _is_exe(cand):
            return str(cand)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for d in _SYSTEM_DIRS:
        cand = os.path.join(d, "ffmpeg")
        if _is_exe(cand):
            return cand
    return None


def require_ffmpeg() -> str:
    exe = find_ffmpeg()
    if not exe:
        raise AudioCodecError(
            "ffmpeg not found. Install it (brew install ffmpeg) or set GIONGDOC_FFMPEG."
        )
    return exe


def run_ffmpeg(args: list[str], input_bytes: bytes | None = None) -> bytes:
    """Run ffmpeg with ``args`` (without the binary), return stdout bytes."""
    exe = require_ffmpeg()
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y"]
    if input_bytes is None:
        cmd.append("-nostdin")
    cmd += args
    try:
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            stdin=None if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - exec failure
        raise AudioCodecError(f"cannot run ffmpeg: {exc}") from exc
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()[-800:]
        raise AudioCodecError(f"ffmpeg failed ({proc.returncode}): {msg}")
    return proc.stdout


_DECODE_OUT = ["-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"]


def _f32_to_clip(raw: bytes) -> AudioClip:
    samples = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=True)
    return AudioClip(samples, SAMPLE_RATE)


# --------------------------------------------------------------------------- WAV

def _pcm_to_float(frames: bytes, sampwidth: int, nchannels: int) -> np.ndarray:
    if sampwidth == 1:
        x = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 2:
        x = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 3:
        b = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        x = v.astype(np.float32) / 8388608.0
    elif sampwidth == 4:
        x = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise AudioCodecError(f"unsupported WAV sample width {sampwidth}")
    if nchannels > 1:
        x = x[: len(x) - len(x) % nchannels].reshape(-1, nchannels).mean(axis=1)
    return x.astype(np.float32, copy=False)


def _read_wav(fobj) -> AudioClip:
    """Stdlib fast path for integer PCM WAV. Raises wave.Error / EOFError otherwise."""
    with wave.open(fobj, "rb") as w:
        sr = w.getframerate()
        x = _pcm_to_float(w.readframes(w.getnframes()), w.getsampwidth(), w.getnchannels())
    clip = AudioClip(x, sr)
    if sr != SAMPLE_RATE:
        from .dsp import resample

        clip = resample(clip, SAMPLE_RATE)
    return clip


def write_wav(clip: AudioClip, path: str | os.PathLike, sample_width: int = 2) -> Path:
    """Write ``clip`` as mono integer PCM WAV (16-bit default, or 24-bit) using stdlib."""
    path = Path(path)
    x = np.clip(np.nan_to_num(np.asarray(clip.samples, dtype=np.float64)), -1.0, 1.0)
    if sample_width == 2:
        data = np.round(x * 32767.0).astype("<i2").tobytes()
    elif sample_width == 3:
        v = np.round(x * 8388607.0).astype(np.int32)
        b = np.empty((len(v), 3), dtype=np.uint8)
        b[:, 0] = v & 0xFF
        b[:, 1] = (v >> 8) & 0xFF
        b[:, 2] = (v >> 16) & 0xFF
        data = b.tobytes()
    else:
        raise ValueError("sample_width must be 2 or 3")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(sample_width)
        w.setframerate(int(clip.sample_rate))
        w.writeframes(data)
    return path


def wav_bytes(clip: AudioClip) -> bytes:
    """Encode ``clip`` as 16-bit WAV in memory (handy for Qt playback)."""
    buf = io.BytesIO()
    x = np.clip(np.nan_to_num(np.asarray(clip.samples, dtype=np.float64)), -1.0, 1.0)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(clip.sample_rate))
        w.writeframes(np.round(x * 32767.0).astype("<i2").tobytes())
    return buf.getvalue()


# --------------------------------------------------------------------------- public decode

def decode_bytes(data: bytes) -> AudioClip:
    """Decode any audio container (wav/mp3/m4a/ogg/...) held in memory."""
    if not data:
        return AudioClip(np.zeros(0, dtype=np.float32), SAMPLE_RATE)
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        try:
            return _read_wav(io.BytesIO(data))
        except (wave.Error, EOFError, AudioCodecError):
            pass  # float WAV / extensible etc. -> ffmpeg
    try:
        raw = run_ffmpeg(["-i", "pipe:0", *_DECODE_OUT], input_bytes=data)
        if raw:
            return _f32_to_clip(raw)
    except AudioCodecError:
        pass
    # Non-seekable pipes break some containers (mp4 with trailing moov): use a temp file.
    fd, tmp = tempfile.mkstemp(suffix=".audio")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return load_file(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def load_file(path: str | os.PathLike) -> AudioClip:
    """Load an audio file from disk into the internal format."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in (".wav", ".wave"):
        try:
            with open(path, "rb") as f:
                return _read_wav(f)
        except (wave.Error, EOFError, AudioCodecError):
            pass
    raw = run_ffmpeg(["-i", str(path), *_DECODE_OUT])
    return _f32_to_clip(raw)
