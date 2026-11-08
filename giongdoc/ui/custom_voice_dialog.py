"""'Giọng tùy chỉnh' manager: list/delete custom voices, add one from a consented sample."""
from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core import Language

MIN_REC_S, MAX_REC_S = 10, 20  # store accepts 5–30 s; 10–20 s gives the best clones
LANGS = [(Language.VI, "Tiếng Việt"), (Language.EN, "English"), (Language.KO, "한국어"),
         (Language.ZH, "中文")]
# (label, ConsentRecord.relationship value)
RELATIONSHIPS = [("Chính tôi", "self"),
                 ("Người khác – đã có đồng ý bằng văn bản", "consented_other")]
FALLBACK_CONSENT = ("Tôi xác nhận giọng nói trong mẫu là của chính tôi, hoặc tôi đã có sự đồng ý "
                    "bằng văn bản của người đó để tạo giọng tùy chỉnh. Tôi sẽ không dùng giọng "
                    "này để mạo danh, lừa đảo hay gây hại cho bất kỳ ai.")


def _custom_voices_module():
    try:
        from ..engines import custom_voices
        return custom_voices
    except Exception:  # noqa: BLE001 – package may be missing / broken
        return None


def consent_text() -> str:
    mod = _custom_voices_module()
    return getattr(mod, "CONSENT_TEXT_VI", None) or FALLBACK_CONSENT


def cloning_available() -> bool:
    try:
        from ..engines import registry
        eng = registry.get("custom")
        return bool(eng and eng.is_available())
    except Exception:  # noqa: BLE001
        return False


def default_store():
    mod = _custom_voices_module()
    if mod is None or not hasattr(mod, "CustomVoiceStore"):
        return None
    try:  # share the store the "custom" engine uses, so new voices show up immediately
        from ..engines import registry
        store = registry.custom_store()
        if store is not None:
            return store
    except Exception:  # noqa: BLE001
        pass
    return mod.CustomVoiceStore()


def _attr(obj, *names, default=""):
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


class Recorder(QWidget):
    """Microphone recorder (QMediaRecorder) — hidden gracefully if unavailable."""

    recorded = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("● Ghi âm")
        self.label = QLabel("")
        self.label.setObjectName("Muted")
        lay.addWidget(self.button)
        lay.addWidget(self.label, 1)
        self._session = self._recorder = self._input = None
        self._t0 = 0.0
        self._timer = QTimer(self, interval=200)
        self._timer.timeout.connect(self._tick)
        self._path = ""
        self.available = self._init_backend()
        if not self.available:
            self.button.setEnabled(False)
            self.label.setText("Không tìm thấy micro – hãy chọn tệp âm thanh.")
        self.button.clicked.connect(self.toggle)

    def _init_backend(self) -> bool:
        try:
            from PySide6.QtMultimedia import (QAudioInput, QMediaCaptureSession, QMediaDevices,
                                              QMediaRecorder)
            if not QMediaDevices.audioInputs():
                return False
            self._session = QMediaCaptureSession(self)
            self._input = QAudioInput(QMediaDevices.defaultAudioInput(), self)
            self._session.setAudioInput(self._input)
            self._recorder = QMediaRecorder(self)
            self._session.setRecorder(self._recorder)
            try:
                from PySide6.QtMultimedia import QMediaFormat
                fmt = QMediaFormat(QMediaFormat.FileFormat.Wave)
                self._recorder.setMediaFormat(fmt)
            except Exception:  # noqa: BLE001
                pass
            self._recorder.recorderStateChanged.connect(self._state_changed)
            return True
        except Exception:  # noqa: BLE001
            return False

    def toggle(self) -> None:
        if self._recorder is None:
            return
        if self._recorder.recorderState() == self._recorder.RecorderState.RecordingState:
            self.stop()
            return
        self._path = str(Path(tempfile.mkdtemp(prefix="giongdoc-rec-")) / "mau_giong.wav")
        self._recorder.setOutputLocation(QUrl.fromLocalFile(self._path))
        self._recorder.record()
        self._t0 = time.monotonic()
        self._timer.start()
        self.button.setText("■ Dừng ghi")

    def stop(self) -> None:
        self._timer.stop()
        if self._recorder is not None:
            self._recorder.stop()
        self.button.setText("● Ghi âm")

    def _tick(self) -> None:
        s = time.monotonic() - self._t0
        hint = "tiếp tục…" if s < MIN_REC_S else "đủ dài, có thể dừng"
        self.label.setText(f"Đang ghi {s:4.1f}s / {MAX_REC_S}s – {hint}")
        if s >= MAX_REC_S:
            self.stop()

    def _state_changed(self, state) -> None:
        if state == self._recorder.RecorderState.StoppedState and self._path:
            secs = time.monotonic() - self._t0
            actual = self._recorder.actualLocation().toLocalFile() or self._path
            if secs < MIN_REC_S:
                self.label.setText(f"Mẫu quá ngắn ({secs:.0f}s). Cần {MIN_REC_S}–{MAX_REC_S} giây.")
            else:
                self.label.setText(f"Đã ghi {secs:.0f}s.")
                self.recorded.emit(actual)
            self._path = ""


class CustomVoiceDialog(QDialog):
    voicesChanged = Signal()

    def __init__(self, parent=None, store=None, backend_available: bool | None = None):
        super().__init__(parent)
        self.setWindowTitle("Giọng tùy chỉnh")
        self.resize(600, 620)
        self.store = store if store is not None else default_store()
        self.backend_available = cloning_available() if backend_available is None \
            else backend_available

        lay = QVBoxLayout(self)
        if self.store is None:
            note = QLabel("Chưa có mô-đun giọng tùy chỉnh trong bản cài đặt này.")
            note.setObjectName("Notice")
            lay.addWidget(note)
        elif not self.backend_available:
            note = QLabel("Chưa cài bộ tạo giọng (F5-TTS / XTTS). Bạn vẫn có thể lưu mẫu giọng; "
                          "giọng sẽ dùng được khi cài thêm bộ tạo giọng.")
            note.setWordWrap(True)
            note.setObjectName("Notice")
            lay.addWidget(note)

        tabs = QTabWidget()
        lay.addWidget(tabs, 1)
        tabs.addTab(self._build_list_tab(), "Giọng đã lưu")
        tabs.addTab(self._build_add_tab(), "Thêm giọng mới")
        self.tabs = tabs

        close = QPushButton("Đóng")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()
        self._update_add_enabled()

    # ---- list tab -----------------------------------------------------
    def _build_list_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.delete_btn = QPushButton("Xóa giọng đã chọn")
        self.delete_btn.clicked.connect(self.delete_selected)
        row.addStretch(1)
        row.addWidget(self.delete_btn)
        lay.addLayout(row)
        return w

    def refresh(self) -> None:
        self.list.clear()
        voices = []
        if self.store is not None:
            try:
                voices = list(self.store.list())
            except Exception as exc:  # noqa: BLE001
                self.list.addItem(f"Không đọc được danh sách: {exc}")
        for v in voices:
            name = _attr(v, "name", default="?")
            lang = _attr(v, "language", default="")
            lang = getattr(lang, "value", lang)
            item = QListWidgetItem(f"★ {name}   ·   {str(lang).upper()}")
            item.setData(256, v)
            self.list.addItem(item)
        if not voices and self.store is not None:
            self.list.addItem("Chưa có giọng tùy chỉnh nào.")
        self.delete_btn.setEnabled(bool(voices))

    def delete_selected(self) -> None:
        item = self.list.currentItem()
        v = item.data(256) if item else None
        if v is None or self.store is None:
            return
        name = _attr(v, "name", default="")
        if QMessageBox.question(self, "Xóa giọng", f"Xóa giọng “{name}” và mẫu âm thanh của nó?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(_attr(v, "id", default="") or name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Không xóa được", str(exc))
        self.refresh()
        self.voicesChanged.emit()

    # ---- add tab ------------------------------------------------------
    def _build_add_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.name_edit = QLineEdit(placeholderText="Ví dụ: Giọng của tôi")
        self.lang_combo = QComboBox()
        for lang, label in LANGS:
            self.lang_combo.addItem(label, lang.value)
        self.audio_edit = QLineEdit(placeholderText="Tệp WAV/MP3/M4A 10–20 giây, rõ, ít tạp âm")
        browse = QPushButton("Chọn tệp…")
        browse.clicked.connect(self.choose_audio)
        arow = QHBoxLayout()
        arow.addWidget(self.audio_edit, 1)
        arow.addWidget(browse)
        self.recorder = Recorder()
        self.recorder.recorded.connect(self.audio_edit.setText)
        self.transcript_edit = QPlainTextEdit()
        self.transcript_edit.setPlaceholderText("Gõ chính xác nội dung được nói trong mẫu âm thanh")
        self.transcript_edit.setFixedHeight(80)
        self.speaker_edit = QLineEdit(placeholderText="Họ tên người có giọng trong mẫu")
        self.rel_combo = QComboBox()
        for label, value in RELATIONSHIPS:
            self.rel_combo.addItem(label, value)
        self.note_edit = QLineEdit(placeholderText="Ghi chú (tùy chọn)")
        self.consent_box = QCheckBox("Tôi đồng ý với cam kết trên")
        consent = QLabel(consent_text())
        consent.setWordWrap(True)
        consent.setObjectName("Notice")
        self.add_btn = QPushButton("Thêm giọng")
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.clicked.connect(self.add_voice)

        form.addRow("Tên giọng", self.name_edit)
        form.addRow("Ngôn ngữ", self.lang_combo)
        form.addRow("Mẫu âm thanh", arow)
        form.addRow("", self.recorder)
        form.addRow("Lời trong mẫu", self.transcript_edit)
        form.addRow("Người nói", self.speaker_edit)
        form.addRow("Quan hệ", self.rel_combo)
        form.addRow("Ghi chú", self.note_edit)
        form.addRow(consent)
        form.addRow(self.consent_box)
        form.addRow(self.add_btn)
        self.consent_box.toggled.connect(self._update_add_enabled)
        for e in (self.name_edit, self.audio_edit, self.speaker_edit):
            e.textChanged.connect(self._update_add_enabled)
        self.transcript_edit.textChanged.connect(self._update_add_enabled)
        return w

    def choose_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn mẫu giọng", str(Path.home()),
                                              "Âm thanh (*.wav *.mp3 *.m4a *.flac *.aiff)")
        if path:
            self.audio_edit.setText(path)

    def _update_add_enabled(self, *_):
        ready = (self.consent_box.isChecked() and self.store is not None
                 and bool(self.name_edit.text().strip()) and bool(self.audio_edit.text().strip())
                 and bool(self.speaker_edit.text().strip())
                 and bool(self.transcript_edit.toPlainText().strip()))
        self.add_btn.setEnabled(ready)
        if not self.consent_box.isChecked():
            self.add_btn.setToolTip("Cần đánh dấu xác nhận đồng ý trước khi thêm giọng")
        else:
            self.add_btn.setToolTip("")

    def add_voice(self) -> bool:
        if not self.consent_box.isChecked() or self.store is None:
            return False
        audio = self.audio_edit.text().strip()
        if not Path(audio).is_file():
            QMessageBox.warning(self, "Thiếu mẫu", "Không tìm thấy tệp âm thanh mẫu.")
            return False
        mod = _custom_voices_module()
        consent = mod.ConsentRecord(
            speaker_name=self.speaker_edit.text().strip(),
            relationship=self.rel_combo.currentData(),
            confirmed_owns_or_has_written_consent=True,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            note=self.note_edit.text().strip(),
        )
        try:
            self.store.add_voice(self.name_edit.text().strip(), Language(self.lang_combo.currentData()),
                                 audio, self.transcript_edit.toPlainText().strip(), consent)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Không thêm được giọng", str(exc))
            return False
        self.name_edit.clear()
        self.transcript_edit.clear()
        self.consent_box.setChecked(False)
        self.refresh()
        self.tabs.setCurrentIndex(0)
        self.voicesChanged.emit()
        return True
