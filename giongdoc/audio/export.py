"""Write finished audio (WAV / MP3 / M4A) and subtitles (SRT)."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path
from typing import Iterable

import numpy as np

from ..core import AudioClip
from . import codec, dsp

FORMATS = ("wav", "mp3", "m4a")

_FFMPEG_FMT = {
    "wav": ["-c:a", "pcm_s16le", "-f", "wav"],
    "mp3": ["-c:a", "libmp3lame", "-f", "mp3"],
    "m4a": ["-c:a", "aac", "-movflags", "+faststart", "-f", "ipod"],
}


def _meta_args(metadata: dict | None) -> list[str]:
    args: list[str] = []
    for k, v in (metadata or {}).items():
        if v is None:
            continue
        key = str(k).strip().replace("=", "_")
        val = str(v).replace("\n", " ")
        if key:
            args += ["-metadata", f"{key}={val}"]
    return args


def export(clip: AudioClip, path: str | os.PathLike, fmt: str | None = "mp3", bitrate: str = "192k",
           sample_rate: int | None = None, metadata: dict | None = None) -> Path:
    """Export ``clip`` to ``path``.

    ``fmt`` in {"wav","mp3","m4a"} (None -> from the file extension).
    WAV is written with the stdlib (no ffmpeg) unless ``metadata`` is given
    and ffmpeg is available. MP3/M4A need ffmpeg. Writes atomically.
    Metadata keys follow ffmpeg names: title, artist, album, comment, date...
    """
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".") or "mp3").lower()
    if fmt not in FORMATS:
        raise ValueError(f"unsupported format {fmt!r}; use one of {FORMATS}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    sr_out = int(sample_rate or clip.sample_rate)

    try:
        if fmt == "wav" and not (metadata and codec.find_ffmpeg()):
            c = dsp.resample(clip, sr_out) if sr_out != clip.sample_rate else clip
            codec.write_wav(c, tmp)
        else:
            x = np.clip(np.asarray(clip.samples, dtype=np.float32), -1.0, 1.0)
            args = ["-f", "f32le", "-ar", str(int(clip.sample_rate)), "-ac", "1", "-i", "pipe:0",
                    "-ar", str(sr_out), "-ac", "1"]
            if fmt != "wav":
                args += ["-b:a", bitrate]
            args += _meta_args(metadata) + _FFMPEG_FMT[fmt] + [str(tmp)]
            codec.run_ffmpeg(args, input_bytes=x.astype("<f4").tobytes())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path


# --------------------------------------------------------------------------- subtitles

def srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: Iterable[tuple[float, float, str]], max_line_chars: int | None = None,
           min_duration_s: float = 0.0) -> str:
    """Build SRT text from ``(start_s, end_s, text)``. Empty texts are skipped.

    ``max_line_chars`` wraps long lines (e.g. 42 for TikTok/Reels captions);
    ``min_duration_s`` extends very short cues without overlapping the next.
    """
    segs = [(float(a), float(b), " ".join(str(t).split())) for a, b, t in segments]
    segs = [s for s in segs if s[2]]
    lines: list[str] = []
    for i, (a, b, text) in enumerate(segs):
        nxt = segs[i + 1][0] if i + 1 < len(segs) else None
        if b - a < min_duration_s:
            b = a + min_duration_s if nxt is None else min(a + min_duration_s, max(b, nxt))
        b = max(b, a + 0.001)
        if max_line_chars:
            text = "\n".join(textwrap.wrap(text, max_line_chars)) or text
        lines.append(f"{i + 1}\n{srt_timestamp(a)} --> {srt_timestamp(b)}\n{text}\n")
    return "\n".join(lines)


def export_srt(segments_with_times: Iterable[tuple[float, float, str]], path: str | os.PathLike,
               max_line_chars: int | None = None, min_duration_s: float = 0.0) -> Path:
    """Write an .srt subtitle file (UTF-8) from ``(start_s, end_s, text)`` tuples."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_srt(segments_with_times, max_line_chars, min_duration_s), encoding="utf-8")
    return path
