"""GiongDoc audio: decode, DSP, smooth assembly, export.

Typical use::

    from giongdoc.audio import assemble_with_timeline, export_audio, export_srt
    clip, tl = assemble_with_timeline([(c1, 600), (c2, 250)], ["Câu một.", "Câu hai,"])
    export_audio(clip, "out.mp3", "mp3"); export_srt(tl, "out.srt")
"""
# NOTE: ``export`` stays the submodule (``audio.export.export(...)`` per ARCHITECTURE.md);
# the function is also available as ``export_audio``.
from . import codec, dsp, export, smoothing, timeline  # noqa: F401
from .codec import AudioCodecError, decode_bytes, find_ffmpeg, load_file, wav_bytes, write_wav
from .export import export as export_audio
from .export import export_srt, to_srt
from .smoothing import SmoothingSettings, assemble
from .timeline import assemble_with_timeline

__all__ = [
    "AudioCodecError", "SmoothingSettings", "assemble", "assemble_with_timeline", "codec",
    "decode_bytes", "dsp", "export", "export_audio", "export_srt", "find_ffmpeg", "load_file", "smoothing",
    "timeline", "to_srt", "wav_bytes", "write_wav",
]
