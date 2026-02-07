"""
UI Settings Dialog - Global Settings

Modal dialog for global settings: emulation mode, trigger mode,
auto-connect, start/stop emulation, and test rumble.
"""

import sys
import tkinter as tk
from typing import Callable, Optional

import customtkinter

from . import ui_theme as T

IS_MACOS = sys.platform == "darwin"


class SettingsDialog:
    """Modal settings dialog accessible via the gear icon.

    Contains global settings that apply to all controllers:
    - Emulation mode (Xbox 360 / Dolphin Pipe)
    - Trigger mode (100% at bump / 100% at press)
    - Auto-connect at startup
    - Start/Stop Emulation (all controllers)
    - Test Rumble (all emulating controllers)
    """

    def __init__(self, parent,
                 emu_mode_var: tk.StringVar,
                 trigger_mode_var: tk.BooleanVar,
                 auto_connect_var: tk.BooleanVar,
                 on_emulate_all: Callable,
                 on_test_rumble_all: Callable,
                 is_any_emulating: Callable[[], bool]):
        self._parent = parent
        self._emu_mode_var = emu_mode_var
        self._trigger_mode_var = trigger_mode_var
        self._auto_connect_var = auto_connect_var
        self._on_emulate_all = on_emulate_all
        self._on_test_rumble_all = on_test_rumble_all
        self._is_any_emulating = is_any_emulating

        self._dlg = customtkinter.CTkToplevel(parent)
        self._dlg.title("Settings")
        self._dlg.resizable(False, False)
        self._dlg.transient(parent)
        self._dlg.configure(fg_color=T.GC_PURPLE_DARK)

        frame = customtkinter.CTkFrame(self._dlg, fg_color=T.GC_PURPLE_DARK)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ── Emulation Mode ──
        customtkinter.CTkLabel(
            frame, text="Emulation Mode",
            text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 4))

        radio_kwargs = dict(
            fg_color=T.RADIO_FG,
            border_color=T.RADIO_BORDER,
            hover_color=T.RADIO_HOVER,
            text_color=T.TEXT_PRIMARY,
            border_width_unchecked=11,
            border_width_checked=3,
            radiobutton_width=22,
            radiobutton_height=22,
            font=(T.FONT_FAMILY, 14),
        )

        xbox_state = 'disabled' if IS_MACOS else 'normal'
        customtkinter.CTkRadioButton(
            frame, text="Xbox 360",
            variable=self._emu_mode_var, value='xbox360',
            state=xbox_state, **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        customtkinter.CTkRadioButton(
            frame, text="Dolphin Pipe",
            variable=self._emu_mode_var, value='dolphin_pipe',
            **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        # ── Trigger Mode ──
        customtkinter.CTkLabel(
            frame, text="Trigger Mode",
            text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(12, 4))

        customtkinter.CTkRadioButton(
            frame, text="100% at bump",
            variable=self._trigger_mode_var, value=True,
            **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        customtkinter.CTkRadioButton(
            frame, text="100% at press",
            variable=self._trigger_mode_var, value=False,
            **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        # ── Auto-connect ──
        customtkinter.CTkCheckBox(
            frame, text="Auto-connect at startup",
            variable=self._auto_connect_var,
            fg_color=T.RADIO_FG,
            hover_color=T.RADIO_HOVER,
            checkmark_color=T.BTN_TEXT,
            border_color=T.RADIO_BORDER,
            text_color=T.TEXT_PRIMARY,
            font=(T.FONT_FAMILY, 14),
        ).pack(anchor=tk.W, pady=(12, 4))

        # ── Separator ──
        sep = customtkinter.CTkFrame(frame, fg_color=T.GC_PURPLE_MID, height=2)
        sep.pack(fill=tk.X, pady=(12, 12))

        btn_kwargs = dict(
            fg_color=T.BTN_FG,
            hover_color=T.BTN_HOVER,
            text_color=T.BTN_TEXT,
            corner_radius=12, height=36,
            width=220,
            font=(T.FONT_FAMILY, 14),
        )

        # ── Start/Stop Emulation ──
        emu_text = "Stop Emulation" if self._is_any_emulating() else "Start Emulation"
        self._emulate_btn = customtkinter.CTkButton(
            frame, text=emu_text,
            command=self._on_emulate_click,
            **btn_kwargs,
        )
        self._emulate_btn.pack(anchor=tk.W, pady=4)

        # ── Test Rumble ──
        self._rumble_btn = customtkinter.CTkButton(
            frame, text="Test Rumble",
            command=self._on_test_rumble_all,
            **btn_kwargs,
        )
        self._rumble_btn.pack(anchor=tk.W, pady=4)

        # ── Close button ──
        customtkinter.CTkButton(
            frame, text="Close",
            command=self._dlg.destroy,
            fg_color=T.GC_PURPLE_SURFACE,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, height=36, width=220,
            font=(T.FONT_FAMILY, 14),
        ).pack(anchor=tk.W, pady=(12, 0))

        self._dlg.protocol("WM_DELETE_WINDOW", self._dlg.destroy)

        # Center on parent
        self._dlg.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        dw = self._dlg.winfo_width()
        dh = self._dlg.winfo_height()
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        self._dlg.geometry(f"+{x}+{y}")

        # grab_set after window is visible to avoid TclError
        self._dlg.after(10, self._dlg.grab_set)

    def _on_emulate_click(self):
        self._on_emulate_all()
        # Update button text after toggle
        emu_text = "Stop Emulation" if self._is_any_emulating() else "Start Emulation"
        self._emulate_btn.configure(text=emu_text)

    def update_emulate_button(self):
        """Update the emulate button text based on current state."""
        try:
            emu_text = "Stop Emulation" if self._is_any_emulating() else "Start Emulation"
            self._emulate_btn.configure(text=emu_text)
        except Exception:
            pass
