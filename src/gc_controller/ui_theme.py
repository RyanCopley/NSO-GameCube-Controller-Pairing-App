"""
UI Theme - GameCube Indigo Purple

Color constants and theme configuration for the GameCube Controller Enabler.
"""

import ctypes
import os
import sys

import customtkinter

# ── Main purple palette ──────────────────────────────────────────
GC_PURPLE_DARK = "#3B1F6E"       # window/app background
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
    """Register the bundled Varela Round font with the OS so Tk can find it."""
    if not os.path.isfile(_FONT_FILE):
        return
    try:
        if sys.platform == "linux":
            fontconfig = ctypes.cdll.LoadLibrary("libfontconfig.so.1")
            fontconfig.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            fontconfig.FcConfigAppFontAddFile.restype = ctypes.c_int
            fontconfig.FcConfigAppFontAddFile(None, _FONT_FILE.encode("utf-8"))
        elif sys.platform == "win32":
            ctypes.windll.gdi32.AddFontResourceExW(_FONT_FILE, 0x10, 0)
        elif sys.platform == "darwin":
            from ctypes import util as _cu
            ct = ctypes.cdll.LoadLibrary(_cu.find_library("CoreText"))
            cf = ctypes.cdll.LoadLibrary(_cu.find_library("CoreFoundation"))
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cf.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
            cf.CFURLCreateWithFileSystemPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32, ctypes.c_bool]
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            s = cf.CFStringCreateWithCString(None, _FONT_FILE.encode("utf-8"), 0x08000100)
            url = cf.CFURLCreateWithFileSystemPath(None, s, 0, False)
            ct.CTFontManagerRegisterFontsForURL(url, 0, None)
            cf.CFRelease(url)
            cf.CFRelease(s)
    except Exception:
        pass


def apply_gc_theme():
    """Configure customtkinter for the GC dark-purple theme."""
    _register_font()
    customtkinter.set_appearance_mode("dark")
    customtkinter.set_default_color_theme("dark-blue")
