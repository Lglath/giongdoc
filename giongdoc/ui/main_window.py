"""GiongDoc main window: editor on the left, voice & playback panel on the right."""
from __future__ import annotations

import os
import tempfile
import wave
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QSlider, QSplitter, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

from ..core import Language, ProsodySettings
from ..project.model import PROJECT_EXT, AppSettings, Project, app_support_dir
from . import style
from .editor import FindBar, ScriptEditor
from .text_tools import count_words, estimate_duration_s, format_duration, map_timeline
from .workers import NETWORK_MSG, RenderWorker, TaskWorker, friendly_error, start_in_thread

LANG_ITEMS = [(None, "Tự động"), (Language.VI, "Tiếng Việt"), (Language.EN, "English"),
              (Language.KO, "한국어"), (Language.ZH, "中文")]
EXPORT_FORMATS = [("mp3", "MP3"), ("wav", "WAV"), ("m4a", "M4A (AAC)")]
DRAFT_NAME = "draft" + PROJECT_EXT
AUTOSAVE_MS = 20_000


# ---------------------------------------------------------------- helpers
def write_wav(clip, path: str) -> str:
    """Write an AudioClip to WAV (uses audio.codec if available)."""
    try:
        from ..audio.codec import write_wav as codec_write
        codec_write(clip, path)
        return path
    except ImportError:
        pass
    import numpy as np
    pcm = (np.clip(np.asarray(clip.samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(clip.sample_rate))
        w.writeframes(pcm.tobytes())
    return path


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(timeline, path: str) -> str:
    try:
        from ..audio.export import export_srt
        export_srt(timeline, path)
        return path
    except ImportError:
        pass
    lines = []
    for i, (a, b, t) in enumerate(timeline, 1):
        lines += [str(i), f"{_srt_time(a)} --> {_srt_time(b)}", t.strip(), ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return path


def read_text_file(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".docx":
        try:
            import docx  # python-docx (optional)
        except ImportError as exc:
            raise RuntimeError("Cần cài python-docx để mở tệp .docx "
                               "(pip install python-docx).") from exc
        d = docx.Document(str(p))
        return "\n\n".join(par.text for par in d.paragraphs if par.text.strip())
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class LabeledSlider(QWidget):
    """Horizontal slider with a live value label; value() returns a float."""

    def __init__(self, lo: float, hi: float, step: float, value: float, fmt, parent=None):
        super().__init__(parent)
        self.step, self.fmt, self.default = step, fmt, value
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(lo / step), round(hi / step))
        self.label = QLabel()
        self.label.setObjectName("ValueLabel")
        self.label.setMinimumWidth(56)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(self._update)
        self.setValue(value)
        self._update()
        self.slider.setToolTip("Nhấp đúp vào nhãn để đặt lại")

    def _update(self, *_):
        self.label.setText(self.fmt(self.value()))

    def value(self) -> float:
        return round(self.slider.value() * self.step, 4)

    def setValue(self, v: float) -> None:  # noqa: N802
        self.slider.setValue(round(float(v) / self.step))

    def reset(self) -> None:
        self.setValue(self.default)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.reset()


class ExportDialog(QDialog):
    def __init__(self, parent, default_dir: str, base_name: str, fmt: str = "mp3"):
        super().__init__(parent)
        self.setWindowTitle("Xuất file âm thanh")
        form = QFormLayout(self)
        self.fmt_combo = QComboBox()
        for code, label in EXPORT_FORMATS:
            self.fmt_combo.addItem(label, code)
        self.fmt_combo.setCurrentIndex(max(0, self.fmt_combo.findData(fmt)))
        self.bitrate_combo = QComboBox()
        for b in ("128k", "192k", "256k", "320k"):
            self.bitrate_combo.addItem(b.replace("k", " kbps"), b)
        self.bitrate_combo.setCurrentIndex(1)
        self.srt_box = QCheckBox("Kèm phụ đề .srt")
        self.path_edit = QLineEdit(str(Path(default_dir) / f"{base_name}.{fmt}"))
        browse = QPushButton("Chọn…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        form.addRow("Định dạng", self.fmt_combo)
        form.addRow("Chất lượng", self.bitrate_combo)
        form.addRow("Lưu tại", row)
        form.addRow("", self.srt_box)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Xuất")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.fmt_combo.currentIndexChanged.connect(self._fmt_changed)
        self._fmt_changed()
        self.resize(520, self.sizeHint().height())

    def _fmt_changed(self, *_):
        fmt = self.fmt()
        self.bitrate_combo.setEnabled(fmt != "wav")
        p = Path(self.path_edit.text())
        self.path_edit.setText(str(p.with_suffix("." + fmt)))

    def _browse(self):
        fmt = self.fmt()
        path, _ = QFileDialog.getSaveFileName(self, "Xuất file", self.path_edit.text(),
                                              f"{fmt.upper()} (*.{fmt})")
        if path:
            self.path_edit.setText(str(Path(path).with_suffix("." + fmt)))

    def fmt(self) -> str:
        return self.fmt_combo.currentData()

    def values(self) -> tuple[str, str, str, bool]:
        return self.path_edit.text(), self.fmt(), self.bitrate_combo.currentData(), \
            self.srt_box.isChecked()


# ---------------------------------------------------------------- window
class MainWindow(QMainWindow):
    def __init__(self, service=None, settings: AppSettings | None = None, restore_draft=True):
        super().__init__()
        self.settings = settings or AppSettings.load()
        self._service = service
        self._service_error: BaseException | None = None
        self.current_path: str | None = None
        self._job = None             # (thread, worker)
        self._job_kind = ""
        self._last_render = None     # (key, RenderResult)
        self._player = self._audio_out = None
        self._play_map: list[tuple[float, float, int, int]] = []
        self._tmp_dir = tempfile.mkdtemp(prefix="giongdoc-")
        self._threads: set = set()

        self.setWindowTitle("GiongDoc[*]")
        self.setUnifiedTitleAndToolBarOnMac(True)
        self.resize(1200, 760)
        self.setMinimumSize(QSize(820, 520))
        self._build_ui()
        self._build_menus()
        self.apply_style()
        self.populate_voices()
        self.update_stats()

        self._autosave = QTimer(self, interval=AUTOSAVE_MS)
        self._autosave.timeout.connect(self.autosave_draft)
        self._autosave.start()
        self._poll = QTimer(self, interval=60)
        self._poll.timeout.connect(self._poll_playback)
        if restore_draft:
            self._restore_draft()
        self._apply_smoothing()

    # ---- service ------------------------------------------------------
    @property
    def service(self):
        if self._service is None and self._service_error is None:
            try:
                from ..service import SynthesisService
                self._service = SynthesisService()
                from .dictionary_dialog import apply_entries_to, load_entries
                apply_entries_to(getattr(self._service, "dictionary", None), load_entries())
            except Exception as exc:  # noqa: BLE001
                self._service_error = exc
        return self._service

    # ---- UI construction ---------------------------------------------
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)

        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.setSpacing(0)
        self.editor = ScriptEditor()
        self.find_bar = FindBar(self.editor)
        self.edit_toolbar = self._build_edit_toolbar()
        llay.addWidget(self.edit_toolbar)
        llay.addWidget(self.editor, 1)
        llay.addWidget(self.find_bar)
        splitter.addWidget(left)
        splitter.addWidget(self._build_side_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1200 - style.PANEL_WIDTH, style.PANEL_WIDTH])

        self.editor.textChanged.connect(self.update_stats)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.document().modificationChanged.connect(self.setWindowModified)
        self.editor.filesDropped.connect(lambda files: self.open_path(files[0]))
        self.editor.cursorPositionChanged.connect(self._update_preview_label)

        sb = self.statusBar()
        self.stats_label = QLabel()
        self.stats_label.setObjectName("StatsLabel")
        sb.addPermanentWidget(self.stats_label)
        sb.setSizeGripEnabled(False)

    def _build_edit_toolbar(self) -> QToolBar:
        tb = QToolBar("Soạn thảo")
        tb.setObjectName("EditToolbar")
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.act_undo = QAction("↶", self, shortcut=QKeySequence.StandardKey.Undo,
                                toolTip="Hoàn tác (⌘Z)", triggered=lambda: self.editor.undo())
        self.act_redo = QAction("↷", self, shortcut=QKeySequence.StandardKey.Redo,
                                toolTip="Làm lại (⇧⌘Z)", triggered=lambda: self.editor.redo())
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)
        self.editor.undoAvailable.connect(self.act_undo.setEnabled)
        self.editor.redoAvailable.connect(self.act_redo.setEnabled)
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addSeparator()

        # pause buttons: 300 / 600 (⇧⌘P) / 1000 ms
        self.pause_actions = {}
        for ms in (300, 600, 1000):
            act = QAction(f"⏸ {ms}", self, toolTip=f"Chèn ngắt nghỉ [pause {ms}]",
                          triggered=lambda _=False, ms=ms: self.insert_pause(ms))
            self.pause_actions[ms] = act
            tb.addAction(act)
        self.act_pause = self.pause_actions[600]
        self.act_pause.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.act_pause.setToolTip("Chèn ngắt nghỉ [pause 600] (⇧⌘P)")
        tb.addSeparator()

        tb.addAction(QAction("🗣 Giọng", self, triggered=self.wrap_voice,
                             toolTip="Đọc đoạn chọn bằng giọng khác (hội thoại nhiều nhân vật)"))
        lang_btn = QToolButton(text="🌐 Ngôn ngữ")
        lang_btn.setToolTip("Ép ngôn ngữ cho đoạn chọn")
        lang_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        lm = QMenu(lang_btn)
        for lang, label in LANG_ITEMS[1:]:
            lm.addAction(label, lambda code=lang.value: self.editor.wrap_selection(
                f"[lang:{code}]", "[/lang]"))
        lang_btn.setMenu(lm)
        tb.addWidget(lang_btn)
        rate_btn = QToolButton(text="⏱ Tốc độ")
        rate_btn.setToolTip("Đổi tốc độ cho đoạn chọn")
        rate_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        rm = QMenu(rate_btn)
        for r in (0.7, 0.85, 1.15, 1.3, 1.5):
            rm.addAction(f"×{r:g}", lambda r=r: self.editor.wrap_selection(f"[rate {r:g}]",
                                                                           "[/rate]"))
        rate_btn.setMenu(rm)
        tb.addWidget(rate_btn)
        self.act_emph = QAction("Nhấn mạnh", self, shortcut=QKeySequence("Ctrl+E"),
                                toolTip="Nhấn mạnh *từ* (⌘E)",
                                triggered=lambda: self.editor.wrap_selection("*", "*"))
        f = self.act_emph.font()
        f.setBold(True)
        self.act_emph.setFont(f)
        tb.addAction(self.act_emph)
        tb.addSeparator()
        self.act_clean = QAction("✨ Làm sạch", self, triggered=self.clean_text,
                                 toolTip="Chuẩn hóa khoảng trắng, xóa emoji và đường link")
        tb.addAction(self.act_clean)
        self.act_find = QAction("🔍 Tìm", self, shortcut=QKeySequence.StandardKey.Find,
                                toolTip="Tìm & thay thế (⌘F)", triggered=self.find_bar.open_bar)
        tb.addAction(self.act_find)
        return tb

    def _section(self, lay: QVBoxLayout, title: str):
        lbl = QLabel(title)
        lbl.setObjectName("SectionTitle")
        lay.addWidget(lbl)

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("SidePanel")
        panel.setMinimumWidth(270)
        panel.setMaximumWidth(420)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(style.MARGIN, style.MARGIN, style.MARGIN, style.MARGIN)
        lay.setSpacing(6)

        self._section(lay, "Giọng đọc")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.lang_combo = QComboBox()
        for lang, label in LANG_ITEMS:
            self.lang_combo.addItem(label, lang.value if lang else None)
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumContentsLength(16)
        self.voice_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        form.addRow("Ngôn ngữ", self.lang_combo)
        form.addRow("Giọng", self.voice_combo)
        lay.addLayout(form)
        self.voice_hint = QLabel()
        self.voice_hint.setObjectName("Muted")
        self.voice_hint.setWordWrap(True)
        lay.addWidget(self.voice_hint)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)

        self._section(lay, "Điều chỉnh")
        adj = QFormLayout()
        adj.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.rate_slider = LabeledSlider(0.5, 2.0, 0.05, 1.0, lambda v: f"×{v:.2f}")
        self.pitch_slider = LabeledSlider(-6, 6, 0.5, 0.0, lambda v: f"{v:+.1f} st")
        self.volume_slider = LabeledSlider(0, 2.0, 0.05, 1.0, lambda v: f"{v * 100:.0f}%")
        self.pause_slider = LabeledSlider(0.5, 2.0, 0.05, 1.0, lambda v: f"×{v:.2f}")
        adj.addRow("Tốc độ", self.rate_slider)
        adj.addRow("Cao độ", self.pitch_slider)
        adj.addRow("Âm lượng", self.volume_slider)
        adj.addRow("Ngắt nghỉ", self.pause_slider)
        self.pause_slider.setToolTip("Độ dài ngắt nghỉ ở dấu câu")
        lay.addLayout(adj)
        self.smooth_box = QCheckBox("Làm mượt nâng cao")
        self.smooth_box.setToolTip("Thêm room tone nhẹ và crossfade giữa các câu "
                                   "cho cảm giác liền mạch")
        self.smooth_box.setChecked(bool(self.settings.room_tone))
        self.smooth_box.toggled.connect(self._apply_smoothing)
        lay.addWidget(self.smooth_box)
        reset = QPushButton("Đặt lại mặc định")
        reset.setFlat(True)
        reset.clicked.connect(self.reset_prosody)
        lay.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        for s in (self.rate_slider, self.pause_slider):
            s.slider.valueChanged.connect(self.update_stats)

        self._section(lay, "Nghe & xuất")
        self.preview_btn = QPushButton("▶ Nghe thử câu hiện tại")
        self.preview_btn.setShortcut(QKeySequence("Ctrl+Return"))
        self.preview_btn.setToolTip("Nghe đoạn đang chọn, hoặc câu tại con trỏ (⌘↩)")
        self.play_btn = QPushButton("▶ Đọc toàn bộ")
        self.play_btn.setObjectName("PrimaryButton")
        self.play_btn.setShortcut(QKeySequence("Ctrl+Shift+Return"))
        self.stop_btn = QPushButton("■ Dừng")
        self.stop_btn.setShortcut(QKeySequence("Ctrl+."))
        self.stop_btn.setEnabled(False)
        self.export_btn = QPushButton("Xuất file…")
        self.export_btn.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.export_btn.setToolTip("MP3 / WAV / M4A, kèm phụ đề .srt (⇧⌘E)")
        lay.addWidget(self.preview_btn)
        lay.addWidget(self.play_btn)
        row = QHBoxLayout()
        row.addWidget(self.stop_btn)
        row.addWidget(self.export_btn)
        lay.addLayout(row)
        self.preview_btn.clicked.connect(self.preview)
        self.play_btn.clicked.connect(self.play_all)
        self.stop_btn.clicked.connect(self.stop)
        self.export_btn.clicked.connect(self.export_dialog)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status_label = QLabel("Sẵn sàng")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        lay.addSpacing(4)
        lay.addWidget(self.progress)
        lay.addWidget(self.status_label)
        lay.addStretch(1)
        tips = QLabel("[pause 600] ngắt nghỉ · *từ* nhấn mạnh\n"
                      "[voice:…]…[/voice] đổi giọng · [lang:en]…[/lang]")
        tips.setObjectName("Muted")
        tips.setWordWrap(True)
        lay.addWidget(tips)
        return panel

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("Tệp")
        m.addAction("Mới", self.new_document, QKeySequence.StandardKey.New)
        m.addAction("Mở…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.recent_menu = m.addMenu("Mở gần đây")
        m.addSeparator()
        m.addAction("Lưu dự án", self.save_project, QKeySequence.StandardKey.Save)
        m.addAction("Lưu dự án thành…", lambda: self.save_project(ask=True),
                    QKeySequence.StandardKey.SaveAs)
        m.addSeparator()
        m.addAction("Xuất file âm thanh…", self.export_dialog)
        self._rebuild_recent_menu()

        e = mb.addMenu("Sửa")
        e.addAction(self.act_undo)
        e.addAction(self.act_redo)
        e.addSeparator()
        e.addAction(self.act_find)
        e.addAction(self.act_pause)
        e.addAction(self.act_emph)
        e.addAction(self.act_clean)

        t = mb.addMenu("Công cụ")
        t.addAction("Từ điển phát âm…", self.open_dictionary)
        t.addAction("Giọng tùy chỉnh…", self.open_custom_voices)
        t.addAction("Làm mới danh sách giọng", self.populate_voices)

        p = mb.addMenu("Phát")
        p.addAction("Nghe thử câu hiện tại", self.preview)
        p.addAction("Đọc toàn bộ", self.play_all)
        p.addAction("Dừng", self.stop)

    def apply_style(self):
        self.setStyleSheet(style.stylesheet(self.palette()))

    def changeEvent(self, e):  # noqa: N802 – live light/dark switch
        super().changeEvent(e)
        if e.type() == e.Type.PaletteChange:
            self.apply_style()

    # ---- voices -------------------------------------------------------
    def selected_language(self) -> Language | None:
        data = self.lang_combo.currentData()
        return Language(data) if data else None

    def selected_voice_id(self) -> str | None:
        return self.voice_combo.currentData()

    def _all_voices(self, language):
        svc = self.service
        if svc is None:
            return []
        try:
            return list(svc.voices(language))
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Không tải được danh sách giọng: {friendly_error(exc)}")
            return []

    @staticmethod
    def voice_label(v, show_lang: bool) -> str:
        parts = []
        if getattr(v, "custom", False):
            parts.append("★")
        if show_lang:
            parts.append(f"[{v.language.value.upper()}]")
        parts.append(v.name)
        label = " ".join(parts)
        if getattr(v, "offline", False):
            label += "  · offline"
        return label

    def populate_voices(self, select: str | None = None):
        lang = self.selected_language()
        current = select or self.voice_combo.currentData() \
            or self.settings.last_voice_by_lang.get(lang.value if lang else "auto")
        voices = self._all_voices(lang)
        voices.sort(key=lambda v: (not v.custom, v.language.value if lang is None else "",
                                   v.offline, v.name.lower()))
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        self.voice_combo.addItem("Mặc định (tự chọn theo ngôn ngữ)", None)
        for v in voices:
            self.voice_combo.addItem(self.voice_label(v, lang is None), v.id)
            self.voice_combo.setItemData(self.voice_combo.count() - 1,
                                         f"{v.id}\nEngine: {v.engine_id}"
                                         + (" · offline" if v.offline else " · cần Internet"),
                                         Qt.ItemDataRole.ToolTipRole)
        idx = self.voice_combo.findData(current) if current else -1
        if idx < 0:  # specific language: preselect its best voice; auto: let backend choose
            first = next((i for i, v in enumerate(voices) if not v.custom), 0)
            idx = first + 1 if (lang is not None and voices) else 0
        self.voice_combo.setCurrentIndex(max(idx, 0))
        self.voice_combo.blockSignals(False)
        self._voices = {v.id: v for v in voices}
        if self.service is None:
            self.voice_hint.setText("Chưa tải được bộ đọc: "
                                    + (friendly_error(self._service_error)
                                       if self._service_error else ""))
        elif not voices:
            self.voice_hint.setText("Không có giọng cho ngôn ngữ này.")
        else:
            n_off = sum(1 for v in voices if v.offline)
            self.voice_hint.setText(f"{len(voices)} giọng · {n_off} offline")
        self._on_voice_changed()

    def _on_language_changed(self, *_):
        self.populate_voices(select=self.settings.last_voice_by_lang.get(
            self.selected_language().value if self.selected_language() else "auto"))
        self._last_render = None

    def _on_voice_changed(self, *_):
        lang = self.selected_language()
        vid = self.selected_voice_id()
        key = lang.value if lang else "auto"
        if vid:
            self.settings.last_voice_by_lang[key] = vid
        self._last_render = None

    # ---- settings -----------------------------------------------------
    def prosody(self) -> ProsodySettings:
        return ProsodySettings(rate=self.rate_slider.value(), pitch=self.pitch_slider.value(),
                               volume=self.volume_slider.value(),
                               pause_scale=self.pause_slider.value())

    def set_prosody(self, p: ProsodySettings):
        self.rate_slider.setValue(p.rate)
        self.pitch_slider.setValue(p.pitch)
        self.volume_slider.setValue(p.volume)
        self.pause_slider.setValue(p.pause_scale)

    def reset_prosody(self):
        self.set_prosody(ProsodySettings())

    def _apply_smoothing(self, *_):
        on = self.smooth_box.isChecked()
        self.settings.room_tone = on
        sm = getattr(self.service, "smoothing", None) if self.service else None
        if sm is None:
            return
        if not hasattr(self, "_smooth_defaults"):
            self._smooth_defaults = {k: getattr(sm, k) for k in ("room_tone_db", "crossfade_ms")
                                     if hasattr(sm, k)}
        room = self._smooth_defaults.get("room_tone_db") or -60.0
        values = {"room_tone_db": room if on else 0.0,
                  "crossfade_ms": (self.settings.smoothing_crossfade_ms if on else 5.0),
                  "room_tone": on}
        for k, v in values.items():
            if hasattr(sm, k):
                try:
                    setattr(sm, k, v)
                except Exception:  # noqa: BLE001
                    pass
        self._last_render = None

    # ---- editing helpers ---------------------------------------------
    def insert_pause(self, ms: int):
        self.editor.insert_pause(ms)
        self.editor.setFocus()

    def wrap_voice(self):
        voices = list(getattr(self, "_voices", {}).values()) or self._all_voices(None)
        if not voices:
            QMessageBox.information(self, "Đổi giọng", "Chưa có giọng nào để chọn.")
            return
        labels = [self.voice_label(v, True) for v in voices]
        label, ok = QInputDialog.getItem(self, "Đổi giọng cho đoạn chọn",
                                         "Đọc đoạn đã chọn bằng giọng:", labels, 0, False)
        if ok:
            v = voices[labels.index(label)]
            self.editor.wrap_selection(f"[voice:{v.id}]", "[/voice]")

    def clean_text(self):
        if self.editor.clean():
            self.set_status("Đã làm sạch văn bản (⌘Z để hoàn tác).")
        else:
            self.set_status("Văn bản đã sạch.")

    def update_stats(self):
        text = self.editor.toPlainText()
        words = count_words(text)
        dur = estimate_duration_s(text, self.rate_slider.value(), self.pause_slider.value()) \
            if text.strip() else 0
        self.stats = {"words": words, "chars": len(text), "duration_s": dur}
        self.stats_label.setText(f"{words:,} từ · {len(text):,} ký tự · ≈ {format_duration(dur)}"
                                 .replace(",", "."))

    def _update_preview_label(self):
        has_sel = self.editor.textCursor().hasSelection()
        self.preview_btn.setText("▶ Nghe thử đoạn chọn" if has_sel else "▶ Nghe thử câu hiện tại")

    def _on_text_changed(self):
        self._last_render = None
        if self.editor.reading_span() and self._job_kind != "play":
            self.editor.set_reading_span(None)

    def set_status(self, text: str):
        self.status_label.setText(text)

    # ---- files --------------------------------------------------------
    def new_document(self):
        if not self._confirm_discard():
            return
        self.editor.setPlainText("")
        self.current_path = None
        self.editor.document().setModified(False)
        self._update_title()

    def open_dialog(self):
        if not self._confirm_discard():
            return
        start = str(Path(self.current_path).parent) if self.current_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở tệp", start,
            "Văn bản & dự án (*.txt *.md *.markdown *.docx *.giongdoc);;Tất cả (*)")
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        try:
            if path.lower().endswith(PROJECT_EXT):
                proj = Project.load(path)
                self.editor.setPlainText(proj.text)
                self._apply_project(proj)
                self.current_path = path
            else:
                self.editor.setPlainText(read_text_file(path))
                self.current_path = None  # saving creates a project next to it
                self._import_source = path
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Không mở được tệp", friendly_error(exc))
            return False
        self.editor.document().setModified(False)
        self.settings.add_recent(str(path))
        self._save_settings()
        self._rebuild_recent_menu()
        self._update_title(Path(path).name)
        self.set_status(f"Đã mở {Path(path).name}")
        return True

    def _apply_project(self, proj: Project):
        idx = self.lang_combo.findData(proj.language or None)
        self.lang_combo.setCurrentIndex(max(idx, 0))
        self.populate_voices(select=proj.voice_id)
        self.set_prosody(proj.prosody)

    def to_project(self) -> Project:
        lang = self.selected_language()
        return Project(text=self.editor.toPlainText(), voice_id=self.selected_voice_id(),
                       language=lang.value if lang else None, prosody=self.prosody(),
                       export_format=getattr(self, "_export_fmt", "mp3"))

    def save_project(self, ask: bool = False) -> bool:
        path = self.current_path
        if ask or not path:
            src = getattr(self, "_import_source", None)
            default = str(Path(src).with_suffix(PROJECT_EXT)) if src \
                else str(Path.home() / f"Không tên{PROJECT_EXT}")
            path, _ = QFileDialog.getSaveFileName(self, "Lưu dự án", default,
                                                  f"Dự án GiongDoc (*{PROJECT_EXT})")
            if not path:
                return False
        try:
            saved = self.to_project().save(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Không lưu được", friendly_error(exc))
            return False
        self.current_path = str(saved)
        self.editor.document().setModified(False)
        self.settings.add_recent(str(saved))
        self._save_settings()
        self._rebuild_recent_menu()
        self._update_title(saved.name)
        self.set_status(f"Đã lưu {saved.name}")
        return True

    def _update_title(self, name: str | None = None):
        name = name or (Path(self.current_path).name if self.current_path else "Không tên")
        self.setWindowTitle(f"{name}[*] — GiongDoc")
        self.setWindowFilePath(self.current_path or "")

    def _confirm_discard(self) -> bool:
        if not self.editor.document().isModified() or not self.editor.toPlainText().strip():
            return True
        r = QMessageBox.question(self, "Lưu thay đổi?", "Văn bản có thay đổi chưa lưu. Lưu lại?",
                                 QMessageBox.StandardButton.Save
                                 | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return r == QMessageBox.StandardButton.Discard

    def _rebuild_recent_menu(self):
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        files = [f for f in self.settings.recent_files if os.path.exists(f)]
        for f in files:
            self.recent_menu.addAction(Path(f).name, lambda f=f: self.open_path(f)) \
                .setToolTip(f)
        if not files:
            self.recent_menu.addAction("(trống)").setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Xóa danh sách", self._clear_recent)

    def _clear_recent(self):
        self.settings.recent_files = []
        self._save_settings()
        self._rebuild_recent_menu()

    def _save_settings(self):
        try:
            self.settings.save()
        except OSError:
            pass

    def draft_path(self) -> Path:
        return app_support_dir() / DRAFT_NAME

    def autosave_draft(self) -> bool:
        if not self.editor.toPlainText().strip():
            return False
        try:
            self.to_project().save(self.draft_path())
            return True
        except OSError:
            return False

    def _restore_draft(self):
        p = self.draft_path()
        if p.exists() and not self.editor.toPlainText():
            try:
                proj = Project.load(p)
                self.editor.setPlainText(proj.text)
                self._apply_project(proj)
                self.editor.document().setModified(False)
                self.set_status("Đã khôi phục bản nháp tự lưu.")
            except Exception:  # noqa: BLE001
                pass

    # ---- dialogs ------------------------------------------------------
    def open_dictionary(self):
        from .dictionary_dialog import DictionaryDialog, apply_entries_to
        dlg = DictionaryDialog(self)

        def saved(entries):
            ok = apply_entries_to(getattr(self.service, "dictionary", None), entries)
            self._last_render = None
            self.set_status(f"Đã lưu {len(entries)} mục từ điển"
                            + ("" if ok else " (áp dụng từ lần khởi động sau)"))
        dlg.saved.connect(saved)
        dlg.exec()

    def open_custom_voices(self):
        from .custom_voice_dialog import CustomVoiceDialog
        dlg = CustomVoiceDialog(self)
        dlg.voicesChanged.connect(lambda: self.populate_voices())
        dlg.exec()

    def show_error(self, message: str, details: str = ""):
        box = QMessageBox(QMessageBox.Icon.Warning, "GiongDoc", message,
                          QMessageBox.StandardButton.Ok, self)
        if message == NETWORK_MSG:
            box.setInformativeText("Giọng có nhãn “offline” đọc được không cần mạng.")
        if details:
            box.setDetailedText(details)
        box.exec()

    # ---- synthesis jobs ----------------------------------------------
    def _render_key(self, text: str):
        lang = self.selected_language()
        return (text, self.selected_voice_id(), tuple(asdict(self.prosody()).values()),
                lang.value if lang else None, self.smooth_box.isChecked())

    def busy(self) -> bool:
        return self._job is not None

    def _launch(self, worker, kind: str, status: str, **ctx):
        """Start a worker; results come back via bound slots (queued to the GUI thread)."""
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_job_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        self._job_kind = kind
        self._set_busy(True, status)
        self._job = {"worker": worker, "kind": kind, **ctx}
        thread = start_in_thread(worker, self)
        self._job["thread"] = thread
        self._threads.add(thread)
        thread.finished.connect(lambda t=thread: self._threads.discard(t))

    def _is_current(self) -> bool:
        snd = self.sender()
        return self._job is not None and (snd is None or snd is self._job["worker"])

    def _start_render(self, text: str, kind: str, base: int = 0, on_done=None):
        if self.busy():
            self.stop()
            self._job = None  # forget the cancelled job; its late signals are ignored
        if not text.strip():
            self.set_status("Không có văn bản để đọc.")
            return False
        svc = self.service
        if svc is None:
            self.show_error(friendly_error(self._service_error or RuntimeError("không rõ")))
            return False
        self.stop_playback()
        key = self._render_key(text)
        if self._last_render and self._last_render[0] == key:
            self._finish_render(self._last_render[1], base, text, on_done)
            return True
        worker = RenderWorker(svc, text, self.selected_voice_id(), self.prosody(),
                              self.selected_language(), tag=kind)
        self._launch(worker, kind, "Đang chuẩn bị…", base=base, text=text, on_done=on_done,
                     key=key)
        return True

    def _set_busy(self, busy: bool, status: str = ""):
        for b in (self.preview_btn, self.play_btn, self.export_btn):
            b.setEnabled(not busy)
        self.stop_btn.setEnabled(busy or self._is_playing())
        if busy:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        if status:
            self.set_status(status)

    def _on_progress(self, done: int, total: int, text: str):
        if not self._is_current():
            return
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        snippet = (text[:48] + "…") if len(text) > 48 else text
        self.set_status(f"Đang tổng hợp {min(done + 1, total)}/{total}: {snippet}"
                        if total and done < total else "Đang ghép âm thanh…")

    def _on_failed(self, message: str, details: str):
        if not self._is_current():
            return
        self._job = None
        self._set_busy(False, "Lỗi – " + message)
        self.show_error(message, details)

    def _on_cancelled(self):
        if not self._is_current():
            return
        self._job = None
        self._set_busy(False, "Đã dừng.")

    def _on_job_finished(self, result):
        if not self._is_current():
            return
        job, self._job = self._job, None
        self._set_busy(False, "Xong.")
        if job["kind"] == "export_write":
            self._export_done(result)
            return
        self._last_render = (job["key"], result)
        self._finish_render(result, job["base"], job["text"], job["on_done"])

    def _finish_render(self, result, base, text, on_done):
        if on_done:
            on_done(result)
        else:
            self._play_result(result, text, base)

    def preview(self):
        text, base = self.editor.selection_or_sentence()
        self._start_render(text, "preview", base)

    def play_all(self):
        self._start_render(self.editor.toPlainText(), "play", 0)

    def stop(self):
        if self._job is not None:
            self._job["worker"].cancel()
            self.set_status("Đang dừng…")
        self.stop_playback()

    # ---- playback -----------------------------------------------------
    def _ensure_player(self) -> bool:
        if self._player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
            self._player.playbackStateChanged.connect(self._on_playback_state)
            self._player.errorOccurred.connect(
                lambda _e, msg: self.set_status(f"Lỗi phát âm thanh: {msg}"))
            return True
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Không phát được âm thanh: {exc}")
            return False

    def _play_result(self, result, text: str, base: int):
        if result is None or result.clip.duration_s <= 0:
            self.set_status("Không có âm thanh để phát.")
            return
        self._play_map = map_timeline(text, result.timeline, base)
        path = os.path.join(self._tmp_dir, f"play-{id(result)}.wav")
        try:
            write_wav(result.clip, path)
        except Exception as exc:  # noqa: BLE001
            self.show_error(friendly_error(exc))
            return
        if not self._ensure_player():
            return
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        self._job_kind = "play"
        self._poll.start()
        self.stop_btn.setEnabled(True)
        self.set_status(f"Đang phát · {format_duration(result.clip.duration_s)}")

    def _is_playing(self) -> bool:
        if self._player is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _on_playback_state(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self._poll.stop()
            self.editor.set_reading_span(None)
            self._job_kind = ""
            self.stop_btn.setEnabled(self.busy())
            if self.status_label.text().startswith("Đang phát"):
                self.set_status("Đã đọc xong.")

    def highlight_at(self, seconds: float):
        """Highlight the sentence being read at ``seconds`` (also used by tests)."""
        for a, b, s, e in self._play_map:
            if a <= seconds < b:
                if self.editor.reading_span() != (s, e):
                    self.editor.set_reading_span(s, e)
                return s, e
        return None

    def _poll_playback(self):
        if self._player is not None:
            self.highlight_at(self._player.position() / 1000.0)

    def stop_playback(self):
        if self._player is not None:
            self._player.stop()
        self._poll.stop()
        self.editor.set_reading_span(None)

    # ---- export -------------------------------------------------------
    def export_dialog(self):
        text = self.editor.toPlainText()
        if not text.strip():
            self.set_status("Không có văn bản để xuất.")
            return
        base = Path(self.current_path or getattr(self, "_import_source", "") or "GiongDoc").stem
        default_dir = self.settings.export_dir
        Path(default_dir).mkdir(parents=True, exist_ok=True) if default_dir else None
        dlg = ExportDialog(self, default_dir, base, getattr(self, "_export_fmt", "mp3"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path, fmt, bitrate, srt = dlg.values()
        self._export_fmt = fmt
        self.settings.export_dir = str(Path(path).parent)
        self._save_settings()
        self._start_render(text, "export", 0,
                           on_done=lambda res: self._do_export(res, path, fmt, bitrate, srt))

    def _do_export(self, result, path, fmt, bitrate, srt):
        def task():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if fmt == "wav":
                write_wav(result.clip, path)
            else:
                from ..audio.export import export
                export(result.clip, path, fmt, bitrate)
            out = [path]
            if srt:
                srt_path = str(Path(path).with_suffix(".srt"))
                write_srt(result.timeline, srt_path)
                out.append(srt_path)
            return out

        self._launch(TaskWorker(task), "export_write", "Đang xuất file…")

    def _export_done(self, paths):
        self.set_status("Đã xuất: " + ", ".join(Path(p).name for p in paths))
        box = QMessageBox(QMessageBox.Icon.Information, "Xuất file", "Đã xuất xong:\n"
                          + "\n".join(paths), QMessageBox.StandardButton.Ok, self)
        reveal = box.addButton("Hiện trong Finder", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is reveal:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(paths[0]).parent)))

    # ---- lifecycle ----------------------------------------------------
    def closeEvent(self, e):  # noqa: N802
        if not self._confirm_discard():
            e.ignore()
            return
        self.stop()
        for t in list(self._threads):
            t.quit()
            t.wait(5000)
        if self.editor.toPlainText().strip():
            self.autosave_draft()
        else:
            try:
                self.draft_path().unlink(missing_ok=True)
            except OSError:
                pass
        self._save_settings()
        super().closeEvent(e)


__all__ = ["MainWindow", "write_wav", "write_srt", "read_text_file"]
