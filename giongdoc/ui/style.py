"""Small, palette-based stylesheet: follows macOS light/dark automatically."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

SPACING = 10
MARGIN = 14
PANEL_WIDTH = 284


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Blend colour a towards b by t (0..1)."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def tag_color(palette: QPalette) -> QColor:
    # muted blue that follows the system accent but never looks garish
    link = palette.color(QPalette.ColorRole.Link)
    text = palette.color(QPalette.ColorRole.Text)
    return mix(link, text, 0.25) if not is_dark(palette) else mix(QColor("#7fb2ff"), text, 0.15)


def tag_background(palette: QPalette) -> QColor:
    base = palette.color(QPalette.ColorRole.Base)
    return mix(base, tag_color(palette), 0.12)


def reading_highlight(palette: QPalette) -> QColor:
    """Soft background for the sentence being read."""
    base = palette.color(QPalette.ColorRole.Base)
    return mix(base, palette.color(QPalette.ColorRole.Highlight), 0.28)


def stylesheet(palette: QPalette) -> str:
    dark = is_dark(palette)
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    panel = mix(window, QColor("black" if dark else "white"), 0.25 if dark else 0.55)
    border = mix(window, text, 0.16).name()
    muted = mix(window, text, 0.55).name()
    accent = palette.color(QPalette.ColorRole.Highlight).name()
    return f"""
    QWidget#SidePanel {{ background: {panel.name()}; border-left: 1px solid {border}; }}
    QLabel#SectionTitle {{ font-weight: 600; color: {muted}; font-size: 11px; padding-top: 6px; }}
    QLabel#ValueLabel {{ color: {muted}; }}
    QLabel#Muted, QLabel#StatsLabel {{ color: {muted}; }}
    QLabel#Notice {{ color: {muted}; border: 1px solid {border}; border-radius: 6px; padding: 8px; }}
    QPlainTextEdit#Editor {{ border: none; selection-background-color: {accent}; }}
    QToolBar#EditToolbar {{ border: none; border-bottom: 1px solid {border}; spacing: 2px; padding: 3px 6px; }}
    QToolBar#EditToolbar QToolButton {{ padding: 2px 4px; border-radius: 5px; }}
    QToolBar#EditToolbar QToolButton:hover {{ background: {mix(window, text, 0.09).name()}; }}
    QFrame#FindBar {{ border-top: 1px solid {border}; }}
    QPushButton#PrimaryButton {{ background: {accent}; color: white; border: none;
                                 border-radius: 6px; padding: 7px 12px; font-weight: 600; }}
    QPushButton#PrimaryButton:disabled {{ background: {mix(window, text, 0.2).name()}; }}
    QPushButton#PrimaryButton:hover {{ background: {mix(QColor(accent), QColor('white'), 0.12).name()}; }}
    QProgressBar {{ border: none; border-radius: 3px; background: {mix(window, text, 0.1).name()};
                    max-height: 6px; }}
    QProgressBar::chunk {{ border-radius: 3px; background: {accent}; }}
    """
