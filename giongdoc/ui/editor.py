"""Script editor: QPlainTextEdit with markup highlighting, helpers, drag & drop."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
                           QTextDocument)
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QPushButton, QTextEdit, QToolButton)

from . import style
from .text_tools import EMPHASIS_RE, clean_text, sentence_at

OPENABLE_EXT = (".txt", ".md", ".markdown", ".docx", ".giongdoc")


class MarkupHighlighter(QSyntaxHighlighter):
    """Colours [pause N], [voice:..]..[/voice], [lang:..], [rate ..] and *emphasis*."""

    RULES = [
        ("pause", re.compile(r"\[(?:pause|ngat)\s+\d+\s*\]", re.IGNORECASE)),
        ("tag", re.compile(r"\[/?(?:voice|lang|rate)\b[^\]\n]*\]", re.IGNORECASE)),
        ("emphasis", EMPHASIS_RE),
    ]

    def __init__(self, document: QTextDocument, palette=None):
        super().__init__(document)
        self.formats: dict[str, QTextCharFormat] = {}
        self.set_palette(palette)

    def set_palette(self, palette) -> None:
        from PySide6.QtWidgets import QApplication
        pal = palette or QApplication.palette()
        tag = QTextCharFormat()
        tag.setForeground(style.tag_color(pal))
        tag.setBackground(style.tag_background(pal))
        pause = QTextCharFormat(tag)
        pause.setFontWeight(QFont.Weight.DemiBold)
        emph = QTextCharFormat()
        emph.setFontWeight(QFont.Weight.Bold)
        emph.setFontItalic(True)
        self.formats = {"tag": tag, "pause": pause, "emphasis": emph}
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt API)
        for name, rx in self.RULES:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), self.formats[name])


class ScriptEditor(QPlainTextEdit):
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Editor")
        self.setAcceptDrops(True)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText(
            "Dán hoặc gõ văn bản cần đọc vào đây…\n\n"
            "Mẹo: [pause 600] để ngắt nghỉ, *từ* để nhấn mạnh, "
            "[voice:…]…[/voice] cho hội thoại nhiều giọng.\n"
            "Kéo thả tệp .txt, .md, .docx hoặc .giongdoc để mở.")
        f = self.font()
        f.setPointSize(max(f.pointSize(), 14))
        self.setFont(f)
        self.document().setDocumentMargin(10)
        self.highlighter = MarkupHighlighter(self.document(), self.palette())
        self._reading: QTextEdit.ExtraSelection | None = None

    # ---- helpers ------------------------------------------------------
    def insert_pause(self, ms: int) -> None:
        c = self.textCursor()
        before = self.document().characterAt(c.position() - 1) if c.position() > 0 else " "
        pre = "" if before.isspace() or c.position() == 0 else " "
        c.insertText(f"{pre}[pause {int(ms)}] ")
        self.setTextCursor(c)

    def wrap_selection(self, opening: str, closing: str) -> bool:
        """Wrap selection (or current sentence) with opening/closing markup."""
        c = self.textCursor()
        if not c.hasSelection():
            span = sentence_at(self.toPlainText(), c.position())
            if span is None:
                c.insertText(opening + closing)
                c.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor,
                               len(closing))
                self.setTextCursor(c)
                return False
            c.setPosition(span[0])
            c.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
        selected = c.selectedText().replace(" ", "\n")
        c.beginEditBlock()
        c.insertText(f"{opening}{selected}{closing}")
        c.endEditBlock()
        self.setTextCursor(c)
        return True

    def clean(self) -> bool:
        old = self.toPlainText()
        new = clean_text(old)
        if new == old:
            return False
        c = QTextCursor(self.document())
        c.beginEditBlock()
        c.select(QTextCursor.SelectionType.Document)
        c.insertText(new)
        c.endEditBlock()  # one undo step
        return True

    def selection_or_sentence(self) -> tuple[str, int]:
        """Text to preview and its start offset in the document."""
        c = self.textCursor()
        if c.hasSelection():
            return c.selectedText().replace(" ", "\n"), c.selectionStart()
        text = self.toPlainText()
        span = sentence_at(text, c.position())
        if span is None:
            return "", 0
        return text[span[0]:span[1]], span[0]

    # ---- reading highlight -------------------------------------------
    def set_reading_span(self, start: int | None, end: int | None = None) -> None:
        if start is None:
            self._reading = None
            self.setExtraSelections([])
            return
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(style.reading_highlight(self.palette()))
        c = QTextCursor(self.document())
        n = self.document().characterCount() - 1
        c.setPosition(max(0, min(start, n)))
        c.setPosition(max(0, min(end, n)), QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = c
        self._reading = sel
        self.setExtraSelections([sel])
        view = QTextCursor(c)
        view.setPosition(c.selectionStart())
        rect = self.cursorRect(view)
        if not self.viewport().rect().contains(rect.center()):
            old = self.textCursor()
            self.setTextCursor(view)
            self.centerCursor()
            self.setTextCursor(old)

    def reading_span(self) -> tuple[int, int] | None:
        if self._reading is None:
            return None
        c = self._reading.cursor
        return c.selectionStart(), c.selectionEnd()

    # ---- drag & drop --------------------------------------------------
    def _file_urls(self, mime) -> list[str]:
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(OPENABLE_EXT)]

    def dragEnterEvent(self, e):  # noqa: N802
        if self._file_urls(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):  # noqa: N802
        if self._file_urls(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):  # noqa: N802
        files = self._file_urls(e.mimeData())
        if files:
            e.acceptProposedAction()
            self.filesDropped.emit(files)
        else:
            super().dropEvent(e)

    def changeEvent(self, e):  # noqa: N802 – follow light/dark switches
        super().changeEvent(e)
        if e.type() == e.Type.PaletteChange:
            self.highlighter.set_palette(self.palette())


class FindBar(QFrame):
    """Inline find & replace (Cmd+F)."""

    def __init__(self, editor: ScriptEditor, parent=None):
        super().__init__(parent)
        self.setObjectName("FindBar")
        self.editor = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        self.find_edit = QLineEdit(placeholderText="Tìm…")
        self.replace_edit = QLineEdit(placeholderText="Thay bằng…")
        self.case_box = QCheckBox("Aa")
        self.case_box.setToolTip("Phân biệt hoa/thường")
        prev_btn = QPushButton("◀")
        next_btn = QPushButton("▶")
        prev_btn.setToolTip("Tìm trước")
        next_btn.setToolTip("Tìm tiếp")
        rep_btn = QPushButton("Thay")
        all_btn = QPushButton("Thay tất cả")
        close_btn = QToolButton(text="✕")
        close_btn.setAutoRaise(True)
        for w in (self.find_edit, prev_btn, next_btn, self.case_box, self.replace_edit,
                  rep_btn, all_btn, close_btn):
            lay.addWidget(w)
        self.find_edit.returnPressed.connect(self.find_next)
        next_btn.clicked.connect(self.find_next)
        prev_btn.clicked.connect(lambda: self.find_next(backward=True))
        rep_btn.clicked.connect(self.replace_one)
        all_btn.clicked.connect(self.replace_all)
        close_btn.clicked.connect(self.close_bar)
        self.hide()

    def open_bar(self):
        sel = self.editor.textCursor().selectedText()
        if sel and " " not in sel:
            self.find_edit.setText(sel)
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_bar(self):
        self.hide()
        self.editor.setFocus()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
        else:
            super().keyPressEvent(e)

    def _flags(self, backward=False):
        f = QTextDocument.FindFlag(0)
        if self.case_box.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        if backward:
            f |= QTextDocument.FindFlag.FindBackward
        return f

    def find_next(self, backward: bool = False) -> bool:
        needle = self.find_edit.text()
        if not needle:
            return False
        ok = self.editor.find(needle, self._flags(backward))
        if not ok:  # wrap around
            c = self.editor.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End if backward
                           else QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(c)
            ok = self.editor.find(needle, self._flags(backward))
        return ok

    def _matches(self, text: str) -> bool:
        needle = self.find_edit.text()
        return text == needle if self.case_box.isChecked() else text.lower() == needle.lower()

    def replace_one(self) -> None:
        c = self.editor.textCursor()
        if c.hasSelection() and self._matches(c.selectedText()):
            c.insertText(self.replace_edit.text())
        self.find_next()

    def replace_all(self) -> int:
        needle = self.find_edit.text()
        if not needle:
            return 0
        doc = self.editor.document()
        c = QTextCursor(doc)
        count = 0
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        while True:
            c = doc.find(needle, c, self._flags())
            if c.isNull():
                break
            c.insertText(self.replace_edit.text())
            count += 1
        edit.endEditBlock()
        return count
