"""Application entry point: ``python -m giongdoc.ui.app [file]``."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from .. import __version__


class GiongDocApp(QApplication):
    """Handles macOS Finder 'open with' / double-click (QEvent.FileOpen)."""

    def __init__(self, argv):
        super().__init__(argv)
        self.window = None
        self._pending: list[str] = []

    def event(self, e):  # noqa: N802
        if e.type() == QEvent.Type.FileOpen:
            path = e.file()
            if self.window is not None:
                self.window.open_path(path)
            else:
                self._pending.append(path)
            return True
        return super().event(e)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # Qt 6 is always high-DPI; keep fractional scale factors crisp.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setApplicationName("GiongDoc")
    QApplication.setApplicationDisplayName("GiongDoc")
    QApplication.setOrganizationName("GiongDoc")
    QApplication.setOrganizationDomain("giongdoc.app")
    QApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or GiongDocApp(argv)

    from .main_window import MainWindow
    files = [a for a in argv[1:] if not a.startswith("-")]
    win = MainWindow(restore_draft=not files)
    if isinstance(app, GiongDocApp):
        app.window = win
        files += app._pending
    if files:
        win.open_path(files[-1])
    win.show()
    win.raise_()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
