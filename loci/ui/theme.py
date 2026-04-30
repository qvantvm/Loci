"""Centralized visual styling for Loci."""

from __future__ import annotations


DARK_STYLE = """
QMainWindow, QDialog {
    background: #111318;
}
QWidget {
    background: transparent;
    color: #C7CBD3;
    font-family: Inter, "SF Pro Display", "Segoe UI", sans-serif;
    font-size: 11px;
}
QFrame#activityRail {
    background: #0D0F14;
    border-right: 1px solid #252932;
}
QLabel#railLogo {
    color: #F2F3F5;
    font-size: 14px;
    font-weight: 800;
}
QLabel#railItem {
    color: #7F8794;
    border-radius: 8px;
    padding: 8px 0;
}
QLabel#railItem:hover {
    background: #1B1F28;
    color: #F2F3F5;
}
QPushButton#railButton {
    background: transparent;
    border: 0;
    border-radius: 8px;
    color: #8D96A5;
    font-weight: 650;
    min-height: 34px;
    padding: 0;
}
QPushButton#railButton:hover {
    background: #1B1F28;
    color: #F2F3F5;
}
QPushButton#railButton:pressed {
    background: #26324A;
    color: #FFFFFF;
}
QToolBar#topBar {
    background: #111318;
    border: 0;
    border-bottom: 1px solid #252932;
    padding: 4px 8px;
    spacing: 8px;
}
QLabel#appCrumb {
    color: #8B93A1;
    font-size: 10px;
    font-weight: 650;
    padding: 0 8px;
}
QLineEdit#commandCenter {
    background: #1A1D24;
    border: 1px solid #2B303B;
    border-radius: 7px;
    color: #D7DAE0;
    min-height: 24px;
    padding: 3px 12px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: #9AA2AF;
    padding: 4px 8px;
}
QToolButton:hover {
    background: #1D212A;
    border-color: #2C323D;
    color: #F2F3F5;
}
QWidget#shell {
    background: #111318;
}
QWidget#sidebarPane {
    background: #151820;
    border-right: 1px solid #252932;
}
QWidget#editorPane {
    background: #1B1E27;
}
QWidget#agentPane {
    background: #151820;
    border-left: 1px solid #252932;
}
QFrame#panelHeader {
    background: #151820;
    border-bottom: 1px solid #252932;
}
QFrame#tabBar {
    background: #151820;
    border-bottom: 1px solid #252932;
}
QLabel#editorTab {
    background: #1B1E27;
    border-left: 1px solid #2A2F3A;
    border-right: 1px solid #2A2F3A;
    color: #D7DAE0;
    font-size: 20px;
    font-weight: 750;
    padding: 12px 16px;
}
QLabel#PaneTitle {
    color: #D7DAE0;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
}
QLabel#sectionTitle {
    color: #F2F3F5;
    font-size: 12px;
    font-weight: 650;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #10131A;
    border: 1px solid #2A2F3A;
    border-radius: 6px;
    color: #D7DAE0;
    padding: 7px 9px;
    selection-background-color: #2F5FD0;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #4C89FF;
}
QPushButton {
    background: #1B1F28;
    border: 1px solid #2C323D;
    border-radius: 6px;
    color: #C7CBD3;
    padding: 6px 10px;
}
QPushButton:hover {
    background: #242A35;
    border-color: #3A4352;
    color: #F2F3F5;
}
QPushButton#primaryButton {
    background: #243D68;
    border-color: #335489;
    color: #EAF2FF;
}
QTreeWidget, QListWidget {
    background: transparent;
    border: 0;
    border-radius: 0;
    outline: 0;
}
QTreeWidget::item {
    border-radius: 4px;
    color: #AEB5C2;
    margin: 0 1px;
    min-height: 20px;
    padding: 2px 5px;
}
QTreeWidget::item:hover {
    background: #202631;
    color: #F2F3F5;
}
QTreeWidget::item:selected {
    background: #26324A;
    color: #FFFFFF;
}
QTreeWidget::item:selected:active {
    background: #26324A;
}
QTreeWidget::item:selected:!active {
    background: #202631;
    color: #D7DAE0;
}
QTextBrowser {
    background: transparent;
    border: 0;
    color: #D7DAE0;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    border: 0;
    margin: 4px 2px;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #343B49;
    border-radius: 5px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: #465063;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    border: 0;
    height: 10px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #343B49;
    border-radius: 5px;
    min-width: 32px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QSplitter::handle {
    background: #252932;
    width: 1px;
}
QSplitter::handle:hover {
    background: #3A4250;
}
QLabel#cardTitle {
    color: #DDE1E8;
    font-size: 10px;
    font-weight: 700;
}
QLabel#metadataLabel {
    color: #7F8794;
    font-weight: 650;
}
QLabel#muted {
    color: #828A97;
}
QLabel#Badge {
    background: #1D2534;
    border: 1px solid #2F3B52;
    color: #AFCBFF;
    border-radius: 999px;
    padding: 2px 8px;
}
QLabel#Badge[kind="ai"] {
    background: #251F35;
    border-color: #40315B;
    color: #D2BEFF;
}
QFrame#card {
    background: #181B23;
    border: 1px solid #272C36;
    border-radius: 8px;
}
QFrame#card:hover {
    border-color: #353D4B;
}
QCheckBox {
    color: #AEB5C2;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border: 1px solid #3B4352;
    border-radius: 3px;
    background: #10131A;
}
QCheckBox::indicator:checked {
    background: #4C89FF;
    border-color: #4C89FF;
}
"""


LIGHT_STYLE = """
QMainWindow, QDialog {
    background: #F5F6FA;
}
QWidget {
    background: transparent;
    color: #20242C;
    font-family: Inter, "SF Pro Display", "Segoe UI", sans-serif;
    font-size: 11px;
}
QToolBar#topBar {
    background: #F5F6FA;
    border: 0;
    border-bottom: 1px solid #DDE2EC;
    padding: 6px 10px;
    spacing: 8px;
}
QToolButton, QPushButton {
    background: #FFFFFF;
    border: 1px solid #D7DEEA;
    border-radius: 9px;
    color: #273041;
    padding: 8px 12px;
}
QToolButton:hover, QPushButton:hover {
    background: #EEF3FF;
    border-color: #B8C8F8;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #FFFFFF;
    border: 1px solid #D7DEEA;
    border-radius: 10px;
    color: #20242C;
    padding: 9px 10px;
    selection-background-color: #4D7DFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #4D7DFF;
}
QTreeWidget, QListWidget, QTextBrowser {
    background: #FFFFFF;
    border: 1px solid #DDE2EC;
    border-radius: 12px;
    outline: 0;
}
QTreeWidget::item {
    border-radius: 8px;
    color: #404A5C;
    margin: 2px 6px;
    padding: 8px;
}
QTreeWidget::item:hover {
    background: #F1F5FF;
}
QTreeWidget::item:selected {
    background: #E3EBFF;
    color: #18233A;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QSplitter::handle {
    background: #E5E9F1;
    margin: 12px 0;
}
QLabel#PaneTitle {
    font-size: 15px;
    font-weight: 700;
    color: #111827;
}
QLabel#sectionTitle {
    font-size: 12px;
    font-weight: 650;
    color: #111827;
}
QLabel#editorTab {
    color: #111827;
    font-size: 20px;
    font-weight: 750;
    padding: 12px 16px;
}
QLabel#cardTitle {
    color: #111827;
    font-weight: 650;
}
QLabel#metadataLabel, QLabel#muted {
    color: #697386;
}
QLabel#Badge {
    background: #EAF1FF;
    border: 1px solid #C8D9FF;
    color: #254DA0;
    border-radius: 8px;
    padding: 3px 8px;
}
QLabel#Badge[kind="ai"] {
    background: #F0EAFE;
    border-color: #D8C9FB;
    color: #5B35A6;
}
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #DDE2EC;
    border-radius: 14px;
}
"""


def stylesheet(dark: bool = True) -> str:
    return DARK_STYLE if dark else LIGHT_STYLE


def apply_theme(widget, dark: bool = True) -> None:
    """Apply the selected Loci stylesheet to a widget tree."""

    widget.setStyleSheet(stylesheet(dark))
