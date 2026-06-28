"""应用全局样式表（QSS — Qt Style Sheets）。

基于 Catppuccin Mocha 配色方案的暗色主题：
  - 背景：#1e1e2e（深蓝灰）
  - 强调色：#89b4fa（蓝）
  - 成功：#a6e3a1（绿）
  - 警告：#f9e2af（黄）
  - 错误：#f38ba8（红）

覆盖组件：
  QWidget, QMenuBar, QMenu, QPushButton, QLineEdit, QSpinBox, QComboBox,
  QProgressBar, QScrollBar, QStatusBar, QDialog, QGroupBox, QCheckBox,
  QSplitter, QTableWidget（#songTable）, 侧边栏（#sidebar）

自定义选择器：
  #sidebar, #sidebarTitle, #playlistCount — 侧边栏专用
  #songTable — 歌曲表格
  #secondaryBtn, #dangerBtn — 按钮变体
"""

DARK_THEME = """
/* ── Global ────────────────────────────── */
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}

/* ── Menu Bar ──────────────────────────── */
QMenuBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
    padding: 2px 0;
}
QMenuBar::item {
    padding: 6px 12px;
    background: transparent;
}
QMenuBar::item:selected {
    background-color: #45475a;
    border-radius: 4px;
}
QMenu {
    background-color: #1e1e2e;
    border: 1px solid #313244;
    padding: 4px;
}
QMenu::item {
    padding: 6px 30px 6px 15px;
}
QMenu::item:selected {
    background-color: #89b4fa;
    color: #1e1e2e;
    border-radius: 4px;
}

/* ── Sidebar ───────────────────────────── */
#sidebar {
    background-color: #181825;
    border-right: 1px solid #313244;
    min-width: 200px;
    max-width: 300px;
}
#sidebar QLabel#sidebarTitle {
    font-size: 12px;
    font-weight: bold;
    color: #a6adc8;
    padding: 10px 12px 4px;
    text-transform: uppercase;
}
#sidebar QListWidget {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px;
}
#sidebar QListWidget::item {
    padding: 8px 12px;
    border-radius: 6px;
    margin: 1px 4px;
}
#sidebar QListWidget::item:selected {
    background-color: #89b4fa;
    color: #1e1e2e;
}
#sidebar QListWidget::item:hover:!selected {
    background-color: #313244;
}
#sidebar QLabel#playlistCount {
    font-size: 11px;
    color: #6c7086;
    padding: 0 12px;
}

/* ── Song Table ────────────────────────── */
#songTable {
    background-color: #1e1e2e;
    border: none;
    gridline-color: #313244;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
    alternate-background-color: #232336;
}
#songTable QHeaderView::section {
    background-color: #181825;
    color: #a6adc8;
    padding: 8px 6px;
    border: none;
    border-bottom: 2px solid #313244;
    font-weight: bold;
}
#songTable QHeaderView::section:hover {
    background-color: #313244;
}

/* ── Buttons ───────────────────────────── */
QPushButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    padding: 8px 20px;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #b4d0fb;
}
QPushButton:pressed {
    background-color: #74a8f5;
}
QPushButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QPushButton#secondaryBtn {
    background-color: #313244;
    color: #cdd6f4;
}
QPushButton#secondaryBtn:hover {
    background-color: #45475a;
}
QPushButton#dangerBtn {
    background-color: #f38ba8;
    color: #1e1e2e;
}
QPushButton#dangerBtn:hover {
    background-color: #f5a0b8;
}

/* ── Inputs ────────────────────────────── */
QLineEdit, QSpinBox, QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    color: #cdd6f4;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #89b4fa;
}
QComboBox::drop-down {
    border: none;
    padding: 0 6px;
}
QComboBox QAbstractItemView {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}

/* ── Progress Bar ──────────────────────── */
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #a6e3a1;
    border-radius: 4px;
}

/* ── Scrollbars ────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    border: none;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #585b70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    border: none;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── Status Bar ────────────────────────── */
QStatusBar {
    background-color: #181825;
    border-top: 1px solid #313244;
    color: #a6adc8;
    padding: 2px 8px;
}

/* ── Dialogs ───────────────────────────── */
QDialog {
    background-color: #1e1e2e;
}
QGroupBox {
    border: 1px solid #313244;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px;
    font-weight: bold;
    color: #a6adc8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

/* ── Checkbox ──────────────────────────── */
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 2px solid #45475a;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}

/* ── Labels ────────────────────────────── */
QLabel#sectionLabel {
    font-size: 11px;
    color: #6c7086;
    font-weight: bold;
}

/* ── Splitter ──────────────────────────── */
QSplitter::handle {
    background-color: #313244;
    width: 1px;
}
"""

# Smaller light theme alternative
LIGHT_THEME = """
/* Light theme placeholder — could be toggled */
"""
