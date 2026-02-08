"""
UI Theme - GameCube Indigo Purple

Color constants and theme configuration for the NSO GameCube Controller Pairing App.
"""

import os
import sys

# ── Main purple palette ──────────────────────────────────────────
GC_PURPLE_DARK = "#535486"       # window/app background
GC_PURPLE_MID = "#4B2D8E"        # controller body, primary purple
GC_PURPLE_LIGHT = "#6B4EAE"      # accents, hover states
GC_PURPLE_SURFACE = "#5A3D9E"    # card/frame backgrounds
SURFACE_DARK = "#2A1A4E"         # darker inset panels

# ── Authentic GC button colors (default / unpressed) ─────────────
BTN_A_GREEN = "#2ECC40"
BTN_B_RED = "#CC2020"
BTN_XY_GRAY = "#C0C0C0"
CSTICK_YELLOW = "#FFD700"
BTN_START_GRAY = "#A0A0A0"
BTN_DPAD_GRAY = "#909090"
BTN_TRIGGER_GRAY = "#888888"
BTN_Z_BLUE = "#6070B0"
BTN_SHOULDER_GRAY = "#787878"

# ── Bright highlight variants (pressed state) ────────────────────
BTN_A_PRESSED = "#5FFF7F"
BTN_B_PRESSED = "#FF5050"
BTN_XY_PRESSED = "#FFFFFF"
CSTICK_PRESSED = "#FFED70"
BTN_START_PRESSED = "#FFFFFF"
BTN_DPAD_PRESSED = "#FFFFFF"
BTN_TRIGGER_PRESSED = "#FFFFFF"
BTN_Z_PRESSED = "#8090E0"
BTN_SHOULDER_PRESSED = "#FFFFFF"

# ── Text colors ──────────────────────────────────────────────────
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#C0A8E8"       # muted lavender
TEXT_DIM = "#8070A0"

# ── UI widget colors ─────────────────────────────────────────────
BTN_FG = "#FFFFFF"               # action button background
BTN_TEXT = "#3B1F6E"             # action button text (purple)
BTN_HOVER = "#E0D0FF"           # action button hover
RADIO_FG = "#FFFFFF"             # radio dot when selected
RADIO_BORDER = "#FFFFFF"         # radio border (white circle)
RADIO_HOVER = "#E0D0FF"         # radio hover

# ── Status indicator colors ──────────────────────────────────────
STATUS_CONNECTED = "#2ECC40"
STATUS_EMULATING = "#FFD700"
STATUS_DISCONNECTED = "#CC2020"
STATUS_READY = "#888888"

# ── Trigger bar colors ───────────────────────────────────────────
TRIGGER_FILL = "#06b025"
TRIGGER_BG = "#1A1040"
TRIGGER_BUMP_LINE = "#e6a800"
TRIGGER_MAX_LINE = "#cc0000"

# ── Stick gate colors ────────────────────────────────────────────
STICK_GATE_BG = "#1A1040"
STICK_DOT = "#FF3030"
STICK_OCTAGON = "#666666"
STICK_OCTAGON_LIVE = "#00aa00"
STICK_CIRCLE = "#999999"


# ── Font ────────────────────────────────────────────────────────
FONT_FAMILY = "Varela Round"
_BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
_FONT_DIR = os.path.join(_BASE_DIR, "gc_controller", "fonts") if hasattr(sys, '_MEIPASS') else os.path.join(_BASE_DIR, "fonts")
_FONT_FILE = os.path.join(_FONT_DIR, "VarelaRound-Regular.ttf")


def _register_font():
    """Register the bundled Varela Round font with Qt's font database."""
    if not os.path.isfile(_FONT_FILE):
        return
    try:
        from PyQt6.QtGui import QFontDatabase
        QFontDatabase.addApplicationFont(_FONT_FILE)
    except Exception:
        pass


def apply_gc_theme(app):
    """Configure PyQt6 QApplication for the GC dark-purple theme."""
    _register_font()
    app.setStyleSheet(f"""
        QMainWindow, QWidget {{
            background-color: {GC_PURPLE_DARK};
            color: {TEXT_PRIMARY};
            font-family: "{FONT_FAMILY}", sans-serif;
        }}
        QLabel {{
            color: {TEXT_PRIMARY};
            background: transparent;
        }}
        QPushButton {{
            background-color: {BTN_FG};
            color: {BTN_TEXT};
            border: none;
            border-radius: 12px;
            padding: 6px 12px;
            font-family: "{FONT_FAMILY}", sans-serif;
            font-size: 14px;
            min-height: 28px;
        }}
        QPushButton:hover {{
            background-color: {BTN_HOVER};
        }}
        QPushButton:disabled {{
            background-color: #888888;
            color: #555555;
        }}
        QPushButton[cssClass="icon-btn"] {{
            background-color: #463F6F;
            color: {TEXT_PRIMARY};
            border-radius: 8px;
            padding: 4px;
            min-width: 36px;
            max-width: 36px;
            min-height: 36px;
            max-height: 36px;
            font-size: 22px;
        }}
        QPushButton[cssClass="icon-btn"]:hover {{
            background-color: #5A5190;
        }}
        QPushButton[cssClass="settings-btn"] {{
            background-color: #463F6F;
            color: {TEXT_PRIMARY};
            border-radius: 12px;
            font-size: 14px;
        }}
        QPushButton[cssClass="settings-btn"]:hover {{
            background-color: #5A5190;
        }}
        QPushButton[cssClass="settings-action"] {{
            background-color: {BTN_FG};
            color: {BTN_TEXT};
            border-radius: 12px;
            font-size: 14px;
        }}
        QPushButton[cssClass="settings-action"]:hover {{
            background-color: {BTN_HOVER};
        }}
        QPushButton[cssClass="cancel-btn"] {{
            background-color: {GC_PURPLE_SURFACE};
            color: {TEXT_PRIMARY};
            border-radius: 12px;
        }}
        QPushButton[cssClass="cancel-btn"]:hover {{
            background-color: {GC_PURPLE_LIGHT};
        }}
        QPushButton[cssClass="connect-btn"] {{
            background-color: {GC_PURPLE_MID};
            color: {TEXT_PRIMARY};
            border-radius: 12px;
        }}
        QPushButton[cssClass="connect-btn"]:hover {{
            background-color: {GC_PURPLE_LIGHT};
        }}
        QTabWidget::pane {{
            background-color: {GC_PURPLE_DARK};
            border: none;
        }}
        QTabBar {{
            background-color: {GC_PURPLE_DARK};
            qproperty-drawBase: 0;
        }}
        QTabBar::tab {{
            background-color: {GC_PURPLE_DARK};
            color: {TEXT_PRIMARY};
            padding: 14px 16px;
            border: none;
            font-family: "{FONT_FAMILY}", sans-serif;
            font-size: 15px;
        }}
        QTabBar::tab:selected {{
            background-color: #463F6F;
            border-radius: 8px;
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {GC_PURPLE_MID};
            border-radius: 8px;
        }}
        QRadioButton {{
            color: {TEXT_PRIMARY};
            font-family: "{FONT_FAMILY}", sans-serif;
            font-size: 14px;
            spacing: 8px;
        }}
        QRadioButton::indicator {{
            width: 20px;
            height: 20px;
            border: 2px solid {RADIO_BORDER};
            border-radius: 12px;
            background-color: transparent;
        }}
        QRadioButton::indicator:checked {{
            border: 2px solid {RADIO_BORDER};
            border-radius: 12px;
            background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                stop:0 white, stop:0.4 white, stop:0.5 transparent, stop:1.0 transparent);
        }}
        QRadioButton::indicator:hover {{
            border-color: {RADIO_HOVER};
        }}
        QRadioButton:disabled {{
            color: {TEXT_DIM};
        }}
        QRadioButton::indicator:disabled {{
            border-color: {TEXT_DIM};
        }}
        QCheckBox {{
            color: {TEXT_PRIMARY};
            font-family: "{FONT_FAMILY}", sans-serif;
            font-size: 14px;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 20px;
            height: 20px;
            border: 2px solid {RADIO_BORDER};
            border-radius: 4px;
            background-color: transparent;
        }}
        QCheckBox::indicator:checked {{
            background-color: {RADIO_FG};
            border-color: {RADIO_BORDER};
        }}
        QCheckBox::indicator:hover {{
            border-color: {RADIO_HOVER};
        }}
        QTableWidget {{
            background-color: {SURFACE_DARK};
            color: {TEXT_PRIMARY};
            gridline-color: #333;
            border: none;
            font-size: 11px;
        }}
        QTableWidget::item {{
            padding: 4px;
        }}
        QTableWidget::item:selected {{
            background-color: {GC_PURPLE_LIGHT};
            color: {TEXT_PRIMARY};
        }}
        QHeaderView::section {{
            background-color: {GC_PURPLE_MID};
            color: {TEXT_PRIMARY};
            border: none;
            padding: 4px 8px;
            font-weight: bold;
            font-size: 11px;
        }}
        QFrame[cssClass="vsep"] {{
            background-color: #463F6F;
            max-width: 2px;
            min-width: 2px;
        }}
        QFrame[cssClass="hsep"] {{
            background-color: #463F6F;
            max-height: 2px;
            min-height: 2px;
        }}
        QMenu {{
            background-color: {GC_PURPLE_DARK};
            color: {TEXT_PRIMARY};
            border: 1px solid #463F6F;
        }}
        QMenu::item:selected {{
            background-color: {GC_PURPLE_LIGHT};
        }}
    """)
