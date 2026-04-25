"""Centralized visual styling for Loci."""

from __future__ import annotations


DARK_STYLE = """
QMainWindow, QWidget {
    background: #101218;
    color: #E8ECF3;
    font-family: Inter, "SF Pro Display", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #171B24;
    border: 1px solid #2A3140;
    border-radius: 10px;
    padding: 8px;
    selection-background-color: #3C6DF0;
}
QPushButton {
    background: #24304A;
    border: 1px solid #34415E;
    border-radius: 10px;
    padding: 8px 12px;
}
QPushButton:hover { background: #2D3C5F; }
QPushButton:pressed { background: #1C263B; }
QTreeWidget, QListWidget, QTextBrowser {
    background: #141821;
    border: 1px solid #252C3A;
    border-radius: 14px;
}
QTreeWidget::item { padding: 6px; }
QTreeWidget::item:selected { background: #263A66; border-radius: 8px; }
QSplitter::handle { background: #202635; }
QLabel#PaneTitle {
    font-size: 16px;
    font-weight: 700;
    color: #F7F9FC;
}
QLabel#Badge {
    background: #263A66;
    color: #BFD0FF;
    border-radius: 8px;
    padding: 3px 7px;
}
"""


LIGHT_STYLE = """
QMainWindow, QWidget {
    background: #F6F7FB;
    color: #20242C;
    font-family: Inter, "SF Pro Display", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #FFFFFF;
    border: 1px solid #D9DFEA;
    border-radius: 10px;
    padding: 8px;
    selection-background-color: #4D7CFE;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #CBD3E2;
    border-radius: 10px;
    padding: 8px 12px;
}
QPushButton:hover { background: #EDF2FF; }
QTreeWidget, QListWidget, QTextBrowser {
    background: #FFFFFF;
    border: 1px solid #DDE3EF;
    border-radius: 14px;
}
QTreeWidget::item { padding: 6px; }
QTreeWidget::item:selected { background: #DCE7FF; border-radius: 8px; }
QSplitter::handle { background: #D9DFEA; }
QLabel#PaneTitle {
    font-size: 16px;
    font-weight: 700;
    color: #101828;
}
QLabel#Badge {
    background: #E5EDFF;
    color: #2247A6;
    border-radius: 8px;
    padding: 3px 7px;
}
"""


def stylesheet(dark: bool = True) -> str:
    return DARK_STYLE if dark else LIGHT_STYLE
