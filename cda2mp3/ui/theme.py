"""深色现代主题(QSS)。"""

QSS = """
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #e6e9f2;
}
QMainWindow, QDialog {
    background: #12141c;
}
#HeaderBar {
    background: #161923;
    border-bottom: 1px solid #232838;
}
#AppTitle {
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
}
#AppSubtitle {
    font-size: 11px;
    color: #8b93a7;
}
QLabel { background: transparent; }

/* ---------- 卡片 ---------- */
#Card, #EmptyCard {
    background: #1a1e2a;
    border: 1px solid #262c3d;
    border-radius: 12px;
}
#CardTitle {
    font-size: 13px;
    font-weight: 700;
    color: #aab3c8;
}

/* ---------- 空状态 ---------- */
#EmptyIcon { font-size: 46px; }
#EmptyTitle { font-size: 18px; font-weight: 700; color: #ffffff; }
#EmptyText { color: #8b93a7; line-height: 150%; }

/* ---------- 表格 ---------- */
QTableWidget {
    background: #1a1e2a;
    alternate-background-color: #1d2230;
    border: 1px solid #262c3d;
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: #2c3350;
    selection-color: #ffffff;
}
QTableWidget::item { padding: 6px 8px; border: none; }
QHeaderView::section {
    background: #171b26;
    color: #8b93a7;
    border: none;
    border-bottom: 1px solid #262c3d;
    padding: 8px;
    font-weight: 600;
}
QTableCornerButton::section { background: #171b26; border: none; }

/* ---------- 输入控件 ---------- */
QComboBox, QLineEdit, QSpinBox {
    background: #141824;
    border: 1px solid #2a3042;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #4f6ef7;
}
QComboBox:hover, QLineEdit:hover { border-color: #3c4460; }
QComboBox:focus, QLineEdit:focus { border-color: #5b7cfa; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #1c2130;
    border: 1px solid #2a3042;
    selection-background-color: #2c3350;
    outline: none;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border: 1px solid #3c4460;
    border-radius: 5px;
    background: #141824;
}
QCheckBox::indicator:checked { background: #5b7cfa; border-color: #5b7cfa; }

/* ---------- 按钮 ---------- */
QPushButton {
    background: #232a3c;
    border: 1px solid #2f3750;
    border-radius: 9px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover { background: #2b3348; border-color: #3c4460; }
QPushButton:pressed { background: #20263a; }
QPushButton:disabled { color: #5a6178; background: #1c2130; border-color: #262c3d; }
#AccentButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5b7cfa, stop:1 #7c5cff);
    border: none;
    color: #ffffff;
    font-size: 14px;
    padding: 11px 18px;
}
#AccentButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6b8bff, stop:1 #8b6cff); }
#AccentButton:pressed { background: #4a6be8; }
#AccentButton:disabled { background: #2a3050; color: #5a6178; }
#DangerButton { color: #ff7a7a; }
#TransportButton {
    background: transparent;
    border: none;
    font-size: 20px;
    color: #c9d1e6;
    padding: 6px 10px;
    border-radius: 8px;
}
#TransportButton:hover { background: #232a3c; }
#PlayButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5b7cfa, stop:1 #7c5cff);
    border: none;
    font-size: 18px;
    color: #fff;
    padding: 10px 18px;
    border-radius: 20px;
}
#PlayButton:hover { background: #6b8bff; }

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {
    height: 5px;
    background: #262c3d;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5b7cfa, stop:1 #7c5cff);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 13px; height: 13px;
    margin: -4px 0;
    border-radius: 7px;
    background: #ffffff;
}
QSlider::groove:vertical { width: 5px; background: #262c3d; border-radius: 3px; }

/* ---------- 进度条 ---------- */
QProgressBar {
    background: #1c2130;
    border: none;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: #dfe4f2;
    font-size: 10px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5b7cfa, stop:1 #8b6cff);
    border-radius: 7px;
}

/* ---------- 日志 ---------- */
QPlainTextEdit {
    background: #141824;
    border: 1px solid #262c3d;
    border-radius: 10px;
    color: #9aa3ba;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    padding: 6px;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #2c3350; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3c4460; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2c3350; border-radius: 4px; min-width: 30px; }

QStatusBar { background: #161923; color: #8b93a7; border-top: 1px solid #232838; }
QToolTip {
    background: #1c2130;
    color: #e6e9f2;
    border: 1px solid #2f3750;
    padding: 4px 8px;
    border-radius: 6px;
}
"""
