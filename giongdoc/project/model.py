"""Project file (.giongdoc, JSON) and app settings persistence."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core import ProsodySettings

PROJECT_EXT = ".giongdoc"


def app_support_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "GiongDoc"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "GiongDoc"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Project:
    text: str = ""
    voice_id: str | None = None
    language: str | None = None  # Language value or None = auto
    prosody: ProsodySettings = field(default_factory=ProsodySettings)
    export_format: str = "mp3"
    version: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, data: str) -> "Project":
        raw = json.loads(data)
        raw["prosody"] = ProsodySettings(**raw.get("prosody", {}))
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        if p.suffix != PROJECT_EXT:
            p = p.with_suffix(PROJECT_EXT)
        p.write_text(self.to_json(), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


@dataclass
class AppSettings:
    last_voice_by_lang: dict = field(default_factory=dict)
    recent_files: list = field(default_factory=list)
    export_dir: str = str(Path.home() / "Music" / "GiongDoc")
    smoothing_crossfade_ms: int = 25
    room_tone: bool = True

    @classmethod
    def path(cls) -> Path:
        return app_support_dir() / "settings.json"

    @classmethod
    def load(cls) -> "AppSettings":
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def add_recent(self, path: str) -> None:
        self.recent_files = [path] + [p for p in self.recent_files if p != path][:9]
