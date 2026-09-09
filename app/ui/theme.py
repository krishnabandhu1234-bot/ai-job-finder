"""A single QSS stylesheet for the whole app, so every page looks
consistent without each widget hand-rolling colors."""

COLORS = {
    "bg": "#f5f6f8",
    "surface": "#ffffff",
    "sidebar": "#1b2333",
    "sidebar_hover": "#28324a",
    "sidebar_active": "#3457d5",
    "text": "#1b2333",
    "text_muted": "#6b7280",
    "text_inverse": "#f5f6f8",
    "border": "#e2e5ea",
    "accent": "#3457d5",
    "accent_hover": "#2a46b8",
    "success": "#1f9d55",
    "warning": "#d97706",
    "danger": "#dc2626",
}

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Segoe UI Semibold", sans-serif;
    font-size: 13px;
    color: {COLORS['text']};
}}

QMainWindow, #centralWidget {{
    background-color: {COLORS['bg']};
}}

/* --- Sidebar --- */
#sidebar {{
    background-color: {COLORS['sidebar']};
    min-width: 220px;
    max-width: 220px;
}}

#sidebarTitle {{
    color: {COLORS['text_inverse']};
    font-size: 16px;
    font-weight: 600;
    padding: 20px 16px 8px 16px;
}}

#sidebarSubtitle {{
    color: #8b93a7;
    font-size: 11px;
    padding: 0px 16px 16px 16px;
}}

QListWidget#navList {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 4px 8px;
}}

QListWidget#navList::item {{
    color: #c7cce0;
    padding: 10px 12px;
    border-radius: 6px;
    margin: 2px 0px;
}}

QListWidget#navList::item:hover {{
    background-color: {COLORS['sidebar_hover']};
}}

QListWidget#navList::item:selected {{
    background-color: {COLORS['sidebar_active']};
    color: white;
}}

/* --- Cards / surfaces --- */
.Card, QFrame#card {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}

QLabel#pageTitle {{
    font-size: 20px;
    font-weight: 600;
    color: {COLORS['text']};
}}

QLabel#pageSubtitle {{
    font-size: 12px;
    color: {COLORS['text_muted']};
}}

QLabel#statValue {{
    font-size: 28px;
    font-weight: 700;
    color: {COLORS['text']};
}}

QLabel#statLabel {{
    font-size: 12px;
    color: {COLORS['text_muted']};
}}

/* --- Buttons --- */
QPushButton {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 16px;
}}

QPushButton:hover {{
    background-color: #eef1f8;
}}

QPushButton#primaryButton {{
    background-color: {COLORS['accent']};
    color: white;
    border: none;
    font-weight: 600;
}}

QPushButton#primaryButton:hover {{
    background-color: {COLORS['accent_hover']};
}}

QPushButton#primaryButton:disabled {{
    background-color: #9aa7e0;
}}

/* --- Inputs --- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {COLORS['accent']};
}}

QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {COLORS['accent']};
}}

/* --- Tables --- */
QTableWidget {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    gridline-color: {COLORS['border']};
}}

QHeaderView::section {{
    background-color: #f0f2f6;
    padding: 8px;
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    font-weight: 600;
}}

QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    background-color: {COLORS['surface']};
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}

QStatusBar {{
    background-color: {COLORS['surface']};
    border-top: 1px solid {COLORS['border']};
}}
"""
