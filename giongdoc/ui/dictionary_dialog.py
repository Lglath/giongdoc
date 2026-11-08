"""Pronunciation dictionary editor (từ gốc -> cách đọc, ngôn ngữ)."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

DICT_FILENAME = "pronunciation.json"
LANG_CHOICES = [("", "Mọi ngôn ngữ"), ("vi", "Tiếng Việt"), ("en", "English"),
                ("ko", "한국어"), ("zh", "中文")]
EXAMPLES = [("AI", "ây ai", "vi"), ("TikTok", "tíc tóc", "vi"), ("iPhone", "ai phôn", "vi")]


def dictionary_path() -> Path:
    from ..project.model import app_support_dir
    return app_support_dir() / DICT_FILENAME


def load_entries(path: Path | None = None) -> list[dict]:
    """Entries as [{"word", "reading", "language"}]; accepts a few JSON shapes."""
    p = path or dictionary_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict) and "entries" in raw:
        raw = raw["entries"]
    out = []
    if isinstance(raw, dict):  # {"AI": "ây ai"} or {"vi": {"AI": "ây ai"}}
        for k, v in raw.items():
            if isinstance(v, dict):
                out += [{"word": w, "reading": r, "language": k} for w, r in v.items()]
            else:
                out.append({"word": k, "reading": str(v), "language": ""})
    elif isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and e.get("word"):
                out.append({"word": str(e["word"]),
                            "reading": str(e.get("replacement", e.get("reading", ""))),
                            "language": str(e.get("language") or "")})
    return out


def save_entries(entries: list[dict], path: Path | None = None) -> Path:
    p = path or dictionary_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Same shape as text.dictionary.PronunciationDict.to_dict() so it can be loaded directly.
    data = {"version": 1, "entries": [
        {"word": e["word"], "replacement": e["reading"], "language": e.get("language") or None}
        for e in entries]}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


class DictionaryDialog(QDialog):
    saved = Signal(list)

    def __init__(self, parent=None, path: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Từ điển phát âm")
        self.resize(560, 480)
        self.path = path or dictionary_path()

        lay = QVBoxLayout(self)
        intro = QLabel("Dạy GiongDoc cách đọc tên riêng, từ viết tắt, từ mượn. "
                       "Ví dụ: “AI” → “ây ai”, “TikTok” → “tíc tóc”.")
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        lay.addWidget(intro)

        self.filter_edit = QLineEdit(placeholderText="Lọc…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Từ gốc", "Cách đọc", "Ngôn ngữ"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        add_btn = QPushButton("＋ Thêm")
        del_btn = QPushButton("－ Xóa")
        add_btn.clicked.connect(lambda: self.add_row())
        del_btn.clicked.connect(self.delete_selected)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addStretch(1)
        lay.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Lưu")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        entries = load_entries(self.path)
        if not entries and not self.path.exists():
            entries = [{"word": w, "reading": r, "language": l} for w, r, l in EXAMPLES]
        for e in entries:
            self.add_row(e["word"], e["reading"], e["language"])

    def add_row(self, word: str = "", reading: str = "", language: str = "") -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(word))
        self.table.setItem(r, 1, QTableWidgetItem(reading))
        combo = QComboBox()
        for code, label in LANG_CHOICES:
            combo.addItem(label, code)
        idx = combo.findData(language or "")
        combo.setCurrentIndex(max(idx, 0))
        self.table.setCellWidget(r, 2, combo)
        if not word:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(self.table.item(r, 0))
        return r

    def delete_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        for r in rows:
            self.table.removeRow(r)

    def entries(self) -> list[dict]:
        out, seen = [], set()
        for r in range(self.table.rowCount()):
            w = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            rd = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            combo = self.table.cellWidget(r, 2)
            lang = combo.currentData() if combo else ""
            if w and rd and (w, lang) not in seen:
                seen.add((w, lang))
                out.append({"word": w, "reading": rd, "language": lang or ""})
        return out

    def _apply_filter(self, text: str) -> None:
        t = text.strip().lower()
        for r in range(self.table.rowCount()):
            cells = [self.table.item(r, c).text().lower() if self.table.item(r, c) else ""
                     for c in (0, 1)]
            self.table.setRowHidden(r, bool(t) and not any(t in c for c in cells))

    def save(self) -> None:
        entries = self.entries()
        save_entries(entries, self.path)
        self.saved.emit(entries)
        self.accept()


def apply_entries_to(dictionary, entries: list[dict]) -> bool:
    """Merge user entries into a text.dictionary.PronunciationDict (in place).

    Entries applied by a previous call but no longer present are removed again.
    """
    if dictionary is None or not callable(getattr(dictionary, "add", None)):
        return False
    previous = getattr(dictionary, "_giongdoc_user_keys", set())
    current = {(e["word"], e.get("language") or None) for e in entries}
    remove = getattr(dictionary, "remove", None)
    for word, lang in previous - current:
        if callable(remove):
            try:
                remove(word, lang)
            except Exception:  # noqa: BLE001
                pass
    ok = True
    for e in entries:
        try:
            dictionary.add(e["word"], e["reading"], e.get("language") or None)
        except Exception:  # noqa: BLE001
            ok = False
    try:
        dictionary._giongdoc_user_keys = current
    except Exception:  # noqa: BLE001
        pass
    return ok


__all__ = ["DictionaryDialog", "load_entries", "save_entries", "dictionary_path",
           "apply_entries_to"]
