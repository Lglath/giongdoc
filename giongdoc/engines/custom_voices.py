"""Storage for user-created (cloned) voices, gated by explicit consent.

ETHICS GUARDRAIL
----------------
GiongDoc lets a user create a custom voice from a short reference recording
(zero-shot voice cloning). This feature must NOT be used to impersonate public
figures, celebrities, politicians or any other person without their permission.
A voice can only be added when the user confirms that the recording is their
own voice, or that they hold written consent from the speaker. The consent
record is stored next to the voice (``voice.json``) so it can be audited, and
:meth:`CustomVoiceStore.add_voice` raises :class:`ValueError` without it.
The UI must show :data:`CONSENT_TEXT_VI` and require an explicit checkbox.

Layout::

    <root>/<voice_id>/reference.wav    24 kHz mono 16-bit PCM
    <root>/<voice_id>/transcript.txt   exact transcript of reference.wav
    <root>/<voice_id>/voice.json       metadata + consent record
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
import uuid
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from giongdoc.core import Language, Voice

ENGINE_ID = "custom"
MIN_REF_SECONDS = 5.0
MAX_REF_SECONDS = 30.0
VALID_RELATIONSHIPS = ("self", "consented_other")

DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "GiongDoc" / "voices"

CONSENT_TEXT_VI = (
    "Cam kết sử dụng giọng nói có trách nhiệm\n\n"
    "Tôi xác nhận rằng đoạn ghi âm mẫu này là GIỌNG NÓI CỦA CHÍNH TÔI, hoặc tôi đã có "
    "SỰ ĐỒNG Ý BẰNG VĂN BẢN của người sở hữu giọng nói cho phép tạo và sử dụng giọng tùy chỉnh này.\n\n"
    "Tôi cam kết KHÔNG sao chép giọng của người nổi tiếng, nhân vật công chúng, chính trị gia "
    "hay bất kỳ người nào khác khi chưa được họ cho phép; KHÔNG dùng giọng tạo ra để mạo danh, "
    "lừa đảo, bôi nhọ, gây hiểu lầm hoặc vi phạm pháp luật.\n\n"
    "Tôi hiểu rằng tôi hoàn toàn chịu trách nhiệm về nội dung được tạo ra bằng giọng nói này, "
    "và thông tin xác nhận này sẽ được lưu kèm theo giọng nói."
)

CONSENT_CHECKBOX_VI = (
    "Tôi là chủ sở hữu giọng nói này hoặc có sự đồng ý bằng văn bản của người nói, "
    "và tôi sẽ không dùng nó để mạo danh người khác."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ConsentRecord:
    speaker_name: str
    relationship: str  # "self" | "consented_other"
    confirmed_owns_or_has_written_consent: bool
    timestamp: str = field(default_factory=_now_iso)
    note: str = ""

    def validate(self) -> None:
        if not self.confirmed_owns_or_has_written_consent:
            raise ValueError("Consent not confirmed: you must own the voice or have the "
                             "speaker's written consent (Chưa xác nhận đồng ý).")
        if self.relationship not in VALID_RELATIONSHIPS:
            raise ValueError(f"relationship must be one of {VALID_RELATIONSHIPS}")
        if not (self.speaker_name or "").strip():
            raise ValueError("speaker_name is required")

    @classmethod
    def from_dict(cls, d: dict) -> "ConsentRecord":
        return cls(speaker_name=d.get("speaker_name", ""), relationship=d.get("relationship", ""),
                   confirmed_owns_or_has_written_consent=bool(d.get("confirmed_owns_or_has_written_consent")),
                   timestamp=d.get("timestamp", ""), note=d.get("note", ""))


@dataclass
class CustomVoiceRecord:
    id: str
    name: str
    language: Language
    transcript: str
    consent: ConsentRecord
    duration_s: float
    created_at: str
    dir: Path

    @property
    def reference_path(self) -> Path:
        return self.dir / "reference.wav"

    @property
    def voice_id(self) -> str:
        return f"{ENGINE_ID}:{self.id}"

    def to_voice(self) -> Voice:
        return Voice(id=self.voice_id, name=f"{self.name} (tùy chỉnh)", language=self.language,
                     engine_id=ENGINE_ID, gender="unknown", offline=True, custom=True,
                     meta={"custom_id": self.id, "reference_wav": str(self.reference_path),
                           "transcript": self.transcript, "speaker_name": self.consent.speaker_name})


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).replace("đ", "d").replace("Đ", "D")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t[:32] or "voice"


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())


class CustomVoiceStore:
    def __init__(self, root_dir: str | Path | None = None):
        self.root = Path(root_dir) if root_dir else DEFAULT_ROOT

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def add_voice(self, name: str, language: Language | str, reference_audio_path: str | Path,
                  transcript: str, consent: ConsentRecord) -> CustomVoiceRecord:
        """Create a voice. Raises ValueError unless consent is confirmed and the
        reference audio is 5–30 s long. The audio is normalized to 24 kHz mono WAV."""
        if not isinstance(consent, ConsentRecord):
            raise ValueError("A ConsentRecord is required")
        consent.validate()
        if not (name or "").strip():
            raise ValueError("name is required")
        if not (transcript or "").strip():
            raise ValueError("transcript of the reference audio is required")
        lang = Language(language)
        src = Path(reference_audio_path)
        if not src.is_file():
            raise ValueError(f"Reference audio not found: {src}")

        from giongdoc.audio.codec import load_file
        try:
            clip = load_file(str(src))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Cannot read reference audio: {e}") from e
        dur = clip.duration_s
        if not (MIN_REF_SECONDS <= dur <= MAX_REF_SECONDS):
            raise ValueError(f"Reference audio must be {MIN_REF_SECONDS:.0f}–{MAX_REF_SECONDS:.0f} s "
                             f"long (got {dur:.1f} s)")

        self._ensure()
        vid = f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
        d = self.root / vid
        d.mkdir(parents=True)
        try:
            write_wav(d / "reference.wav", clip.samples, clip.sample_rate)
            (d / "transcript.txt").write_text(transcript.strip(), encoding="utf-8")
            rec = CustomVoiceRecord(id=vid, name=name.strip(), language=lang,
                                    transcript=transcript.strip(), consent=consent,
                                    duration_s=round(dur, 3), created_at=_now_iso(), dir=d)
            self._write_meta(rec)
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        return rec

    def _write_meta(self, rec: CustomVoiceRecord) -> None:
        meta = {"id": rec.id, "name": rec.name, "language": rec.language.value,
                "duration_s": rec.duration_s, "created_at": rec.created_at,
                "reference": "reference.wav", "transcript_file": "transcript.txt",
                "consent": asdict(rec.consent)}
        (rec.dir / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                            encoding="utf-8")

    def _load(self, d: Path) -> CustomVoiceRecord | None:
        try:
            meta = json.loads((d / "voice.json").read_text(encoding="utf-8"))
            consent = ConsentRecord.from_dict(meta.get("consent") or {})
            consent.validate()  # never expose a voice without a valid consent record
            transcript = (d / "transcript.txt").read_text(encoding="utf-8").strip()
            if not (d / "reference.wav").is_file():
                return None
            return CustomVoiceRecord(id=meta["id"], name=meta["name"], language=Language(meta["language"]),
                                     transcript=transcript, consent=consent,
                                     duration_s=float(meta.get("duration_s", 0)),
                                     created_at=meta.get("created_at", ""), dir=d)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None

    def list(self) -> list[CustomVoiceRecord]:
        if not self.root.is_dir():
            return []
        out = [r for d in sorted(self.root.iterdir()) if d.is_dir() and (r := self._load(d))]
        return sorted(out, key=lambda r: r.created_at)

    def get(self, voice_id: str) -> CustomVoiceRecord | None:
        vid = voice_id.split(":", 1)[1] if voice_id.startswith(f"{ENGINE_ID}:") else voice_id
        if not vid or "/" in vid or vid.startswith("."):
            return None
        d = self.root / vid
        return self._load(d) if d.is_dir() else None

    def delete(self, voice_id: str) -> bool:
        rec = self.get(voice_id)
        if rec is None:
            return False
        shutil.rmtree(rec.dir, ignore_errors=True)
        return True

    def rename(self, voice_id: str, new_name: str) -> CustomVoiceRecord:
        rec = self.get(voice_id)
        if rec is None:
            raise KeyError(voice_id)
        if not new_name.strip():
            raise ValueError("name is required")
        rec.name = new_name.strip()
        self._write_meta(rec)
        return rec

    def voices(self, language: Language | None = None) -> list[Voice]:
        return [r.to_voice() for r in self.list() if language is None or r.language == language]
