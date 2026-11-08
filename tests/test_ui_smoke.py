"""Offscreen smoke tests for giongdoc.ui (fake SynthesisService, no network/audio)."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from giongdoc.core import AudioClip, Language, Voice  # noqa: E402

SAMPLE = ("Xin chào! Đây là GiongDoc, ứng dụng đọc văn bản. [pause 600]\n"
          "Hôm nay trời *rất* đẹp, chúng ta đi dạo nhé.")

VOICES = [
    Voice("edge:vi-VN-HoaiMyNeural", "Hoài My", Language.VI, "edge", "female"),
    Voice("macsay:Linh", "Linh", Language.VI, "macsay", "female", offline=True),
    Voice("edge:en-US-AriaNeural", "Aria", Language.EN, "edge", "female"),
    Voice("custom:me", "Giọng của tôi", Language.VI, "custom", custom=True),
]


class FakeService:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.calls = []
        self.smoothing = SimpleNamespace(room_tone=True, crossfade_ms=25)
        self.dictionary = None

    @staticmethod
    def voices(language=None):
        return [v for v in VOICES if language is None or v.language == language]

    def render(self, text, voice_id, prosody=None, language=None, progress=None,
               is_cancelled=None):
        self.calls.append((text, voice_id, prosody, language))
        if self.fail:
            raise self.fail
        from giongdoc.service import RenderResult
        sentences = ["Xin chào!", "Đây là GiongDoc, ứng dụng đọc văn bản.",
                     "Hôm nay trời rất đẹp, chúng ta đi dạo nhé."]
        timeline, t = [], 0.0
        for i, s in enumerate(sentences):
            if progress:
                progress(i, len(sentences), s)
            timeline.append((t, t + 1.0, s))
            t += 1.2
        if progress:
            progress(len(sentences), len(sentences), "")
        return RenderResult(AudioClip(np.zeros(int(24000 * t), dtype=np.float32)), timeline, [])


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    from giongdoc.project.model import AppSettings
    from giongdoc.ui.main_window import MainWindow
    w = MainWindow(service=FakeService(), settings=AppSettings(), restore_draft=False)
    w.resize(1200, 760)
    w.show()
    qapp.processEvents()
    yield w
    w.editor.document().setModified(False)
    w.close()


def test_voice_combo_filters_and_tags(window):
    labels = [window.voice_combo.itemText(i) for i in range(window.voice_combo.count())]
    assert any(l.startswith("★") for l in labels)
    assert any("offline" in l for l in labels)
    window.lang_combo.setCurrentIndex(window.lang_combo.findData("en"))
    ids = [window.voice_combo.itemData(i) for i in range(window.voice_combo.count())]
    assert ids == [None, "edge:en-US-AriaNeural"]
    assert window.selected_voice_id() == "edge:en-US-AriaNeural"


def test_insert_pause_and_counts(window):
    window.editor.setPlainText("Xin chào các bạn")
    window.insert_pause(600)
    assert "[pause 600]" in window.editor.toPlainText()
    window.act_pause.trigger()  # Cmd+Shift+P action
    assert window.editor.toPlainText().count("[pause 600]") == 2
    window.pause_actions[300].trigger()
    assert "[pause 300]" in window.editor.toPlainText()
    assert window.stats["words"] == 4          # tags are not counted as words
    assert window.stats["duration_s"] > 1.9    # pauses add to the estimate
    assert "4 từ" in window.stats_label.text()
    window.editor.undo()
    assert "[pause 300]" not in window.editor.toPlainText()


def test_highlighter_marks_tags(window, qapp):
    window.editor.setPlainText("Một [pause 800] hai *ba* [lang:en]four[/lang]")
    qapp.processEvents()
    block = window.editor.document().firstBlock()
    ranges = {(r.start, r.length) for r in block.layout().formats()}
    text = block.text()
    assert (text.index("[pause"), len("[pause 800]")) in ranges
    assert (text.index("*ba*"), 4) in ranges
    assert (text.index("[lang:en]"), len("[lang:en]")) in ranges
    emph = [r for r in block.layout().formats() if r.start == text.index("*ba*")][0]
    assert emph.format.fontItalic()


def test_wrap_clean_find_replace(window):
    ed = window.editor
    ed.setPlainText("Chào  bạn 😀 xem https://example.com nhé .")
    assert ed.clean()
    assert ed.toPlainText().strip() == "Chào bạn xem nhé."
    ed.selectAll()
    ed.wrap_selection("[voice:edge:vi-VN-HoaiMyNeural]", "[/voice]")
    assert ed.toPlainText().startswith("[voice:edge:vi-VN-HoaiMyNeural]Chào")
    window.find_bar.find_edit.setText("bạn")
    window.find_bar.replace_edit.setText("cậu")
    assert window.find_bar.replace_all() == 1
    assert "cậu" in ed.toPlainText()


def test_render_worker_and_reading_highlight(window):
    from giongdoc.ui.text_tools import map_timeline
    from giongdoc.ui.workers import RenderWorker
    window.editor.setPlainText(SAMPLE)
    got = []
    w = RenderWorker(window.service, SAMPLE, None, window.prosody(), None)
    w.finished.connect(got.append)
    w.run()  # synchronous for the test
    assert got and len(got[0].timeline) == 3
    window._play_map = map_timeline(SAMPLE, got[0].timeline)
    s, e = window.highlight_at(1.5)
    assert SAMPLE[s:e].startswith("Đây là GiongDoc")
    assert window.editor.extraSelections()
    s, e = window.highlight_at(2.5)
    assert "Hôm nay" in SAMPLE[s:e]


def test_worker_error_is_vietnamese(qapp):
    from giongdoc.ui.workers import NETWORK_MSG, RenderWorker
    errs = []
    w = RenderWorker(FakeService(fail=ConnectionError("Cannot connect to host")), "abc",
                     None, None, None)
    w.failed.connect(lambda m, d: errs.append(m))
    w.run()
    assert errs == [NETWORK_MSG]


def test_project_roundtrip_and_preview_text(window, tmp_path):
    window.editor.setPlainText(SAMPLE)
    window.rate_slider.setValue(1.3)
    p = tmp_path / "demo.giongdoc"
    window.current_path = str(p)
    assert window.save_project()
    window.editor.setPlainText("")
    window.rate_slider.setValue(1.0)
    assert window.open_path(str(p))
    assert window.editor.toPlainText() == SAMPLE
    assert abs(window.prosody().rate - 1.3) < 1e-6
    c = window.editor.textCursor()
    c.setPosition(SAMPLE.index("trời"))
    window.editor.setTextCursor(c)
    text, base = window.editor.selection_or_sentence()
    assert text.startswith("Hôm nay") and base == SAMPLE.index("Hôm nay")


def test_dictionary_and_custom_voice_dialogs(qapp, tmp_path):
    from giongdoc.ui.custom_voice_dialog import CustomVoiceDialog
    from giongdoc.ui.dictionary_dialog import DictionaryDialog, load_entries
    path = tmp_path / "dict.json"
    d = DictionaryDialog(path=path)
    d.add_row("GPU", "gi pi iu", "vi")
    d.save()
    words = {e["word"] for e in load_entries(path)}
    assert {"AI", "GPU"} <= words

    class Store:
        def list(self):
            return []

    dlg = CustomVoiceDialog(store=Store(), backend_available=False)
    dlg.name_edit.setText("Tôi")
    dlg.audio_edit.setText(str(path))
    dlg.speaker_edit.setText("Nguyễn Văn A")
    dlg.transcript_edit.setPlainText("Xin chào")
    assert not dlg.add_btn.isEnabled()
    dlg.consent_box.setChecked(True)
    assert dlg.add_btn.isEnabled()
