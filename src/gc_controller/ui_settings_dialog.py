"""
UI Settings Dialog - Global Settings

Modal dialog for global settings: emulation mode, trigger mode,
auto-connect, start/stop emulation, and test rumble.
"""

import sys
import tkinter as tk
import webbrowser
from typing import Callable, Optional

import customtkinter

from . import ui_theme as T
from .i18n import t

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
                 minimize_to_tray_var: tk.BooleanVar,
                 stick_deadzone_var: tk.DoubleVar = None,
                 auto_scan_ble_var: tk.BooleanVar = None,
                 run_at_startup_var: tk.BooleanVar = None,
                 on_emulate_all: Callable = lambda: None,
                 on_test_rumble_all: Callable = lambda: None,
                 is_any_emulating: Callable[[], bool] = lambda: False,
                 is_any_connected: Callable[[], bool] = lambda: False,
                 on_save: Optional[Callable] = None,
                 get_known_ble_devices: Optional[Callable] = None,
                 on_forget_ble_device: Optional[Callable] = None,
                 get_device_links: Optional[Callable] = None,
                 on_unlink_device: Optional[Callable] = None):
        self._parent = parent
        self._emu_mode_var = emu_mode_var
        self._trigger_mode_var = trigger_mode_var
        self._auto_connect_var = auto_connect_var
        self._minimize_to_tray_var = minimize_to_tray_var
        self._stick_deadzone_var = stick_deadzone_var
        self._auto_scan_ble_var = auto_scan_ble_var
        self._run_at_startup_var = run_at_startup_var
        self._on_emulate_all = on_emulate_all
        self._on_test_rumble_all = on_test_rumble_all
        self._is_any_emulating = is_any_emulating
        self._is_any_connected = is_any_connected
        self._on_save = on_save
        self._get_known_ble_devices = get_known_ble_devices
        self._on_forget_ble_device = on_forget_ble_device
        self._get_device_links = get_device_links
        self._on_unlink_device = on_unlink_device

        self._dlg = customtkinter.CTkToplevel(parent)
        self._dlg.title("Settings")
        self._dlg.resizable(False, False)
        self._dlg.transient(parent)
        self._dlg.configure(fg_color=T.GC_PURPLE_DARK)

        outer = customtkinter.CTkFrame(self._dlg, fg_color=T.GC_PURPLE_DARK)
        outer.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ── Two-column layout ──
        columns = customtkinter.CTkFrame(outer, fg_color="transparent")
        columns.pack(fill=tk.BOTH, expand=True)

        left = customtkinter.CTkFrame(columns, fg_color="transparent")
        left.pack(side=tk.LEFT, fill=tk.BOTH, anchor=tk.N, padx=(0, 16))

        vsep = customtkinter.CTkFrame(columns, fg_color="#463F6F", width=2)
        vsep.pack(side=tk.LEFT, fill=tk.Y, pady=4)

        right = customtkinter.CTkFrame(columns, fg_color="transparent")
        right.pack(side=tk.LEFT, fill=tk.BOTH, anchor=tk.N, padx=(16, 0))

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

        # ════════════════════════════════════════
        # LEFT COLUMN — Settings
        # ════════════════════════════════════════

        # ── Emulation Mode ──
        customtkinter.CTkLabel(
            left, text=t("settings.emulation_mode"),
            text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 4))

        xbox_state = 'disabled' if IS_MACOS else 'normal'
        customtkinter.CTkRadioButton(
            left, text="Xbox 360",
            variable=self._emu_mode_var, value='xbox360',
            state=xbox_state, **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        customtkinter.CTkRadioButton(
            left, text="Dolphin Pipe",
            variable=self._emu_mode_var, value='dolphin_pipe',
            **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        customtkinter.CTkRadioButton(
            left, text="DSU Server",
            variable=self._emu_mode_var, value='dsu',
            **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        # ── Trigger Mode ──
        customtkinter.CTkLabel(
            left, text=t("settings.trigger_mode"),
            text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(12, 4))

        customtkinter.CTkRadioButton(
            left, text="100% at bump",
            variable=self._trigger_mode_var, value=True,
            **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        customtkinter.CTkRadioButton(
            left, text="100% at press",
            variable=self._trigger_mode_var, value=False,
            **radio_kwargs,
        ).pack(anchor=tk.W, padx=16, pady=1)

        # ── Stick Deadzone ──
        if self._stick_deadzone_var is not None:
            customtkinter.CTkLabel(
                left, text=t("settings.stick_deadzone"),
                text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
            ).pack(anchor=tk.W, pady=(12, 4))

            dz_row = customtkinter.CTkFrame(left, fg_color="transparent")
            dz_row.pack(anchor=tk.W, fill=tk.X, padx=16)

            self._dz_label = customtkinter.CTkLabel(
                dz_row,
                text=f"{self._stick_deadzone_var.get():.0%}",
                text_color=T.TEXT_PRIMARY,
                font=(T.FONT_FAMILY, 13),
                width=40,
            )
            self._dz_label.pack(side=tk.RIGHT, padx=(4, 0))

            self._dz_slider = customtkinter.CTkSlider(
                dz_row,
                from_=0.0, to=0.20, number_of_steps=20,
                variable=self._stick_deadzone_var,
                command=self._on_deadzone_changed,
                fg_color=T.SURFACE_DARK,
                progress_color=T.GC_PURPLE_LIGHT,
                button_color=T.BTN_FG,
                button_hover_color=T.BTN_HOVER,
                width=160,
            )
            self._dz_slider.pack(side=tk.LEFT)

        # ── Auto-connect ──
        customtkinter.CTkCheckBox(
            left, text=t("settings.auto_connect_usb"),
            variable=self._auto_connect_var,
            fg_color=T.RADIO_FG,
            hover_color=T.RADIO_HOVER,
            checkmark_color=T.BTN_TEXT,
            border_color=T.RADIO_BORDER,
            text_color=T.TEXT_PRIMARY,
            font=(T.FONT_FAMILY, 14),
        ).pack(anchor=tk.W, pady=(12, 4))

        # ── Auto-scan BLE ──
        if self._auto_scan_ble_var is not None:
            customtkinter.CTkCheckBox(
                left, text=t("settings.auto_scan_ble"),
                variable=self._auto_scan_ble_var,
                fg_color=T.RADIO_FG,
                hover_color=T.RADIO_HOVER,
                checkmark_color=T.BTN_TEXT,
                border_color=T.RADIO_BORDER,
                text_color=T.TEXT_PRIMARY,
                font=(T.FONT_FAMILY, 14),
            ).pack(anchor=tk.W, pady=(4, 4))

        # ── Minimize to tray ──
        customtkinter.CTkCheckBox(
            left, text=t("settings.minimize_tray"),
            variable=self._minimize_to_tray_var,
            fg_color=T.RADIO_FG,
            hover_color=T.RADIO_HOVER,
            checkmark_color=T.BTN_TEXT,
            border_color=T.RADIO_BORDER,
            text_color=T.TEXT_PRIMARY,
            font=(T.FONT_FAMILY, 14),
        ).pack(anchor=tk.W, pady=(4, 4))

        # ── Run at startup ──
        if self._run_at_startup_var is not None:
            customtkinter.CTkCheckBox(
                left, text=t("settings.run_at_startup"),
                variable=self._run_at_startup_var,
                fg_color=T.RADIO_FG,
                hover_color=T.RADIO_HOVER,
                checkmark_color=T.BTN_TEXT,
                border_color=T.RADIO_BORDER,
                text_color=T.TEXT_PRIMARY,
                font=(T.FONT_FAMILY, 14),
            ).pack(anchor=tk.W, pady=(4, 4))

        # ── Save button ──
        customtkinter.CTkButton(
            left, text=t("btn.save"),
            command=self._on_save_click,
            fg_color="#463F6F",
            hover_color="#5A5190",
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, height=36, width=220,
            font=(T.FONT_FAMILY, 14),
        ).pack(anchor=tk.W, pady=(12, 0))

        # ════════════════════════════════════════
        # RIGHT COLUMN — Actions & About
        # ════════════════════════════════════════

        btn_kwargs = dict(
            fg_color=T.BTN_FG,
            hover_color=T.BTN_HOVER,
            text_color=T.BTN_TEXT,
            corner_radius=12, height=36,
            width=220,
            font=(T.FONT_FAMILY, 14),
        )

        # ── Start/Stop Emulation ──
        any_connected = self._is_any_connected()
        emu_text = "Stop Emulation" if self._is_any_emulating() else "Start Emulation"
        self._emulate_btn = customtkinter.CTkButton(
            right, text=emu_text,
            command=self._on_emulate_click,
            state="normal" if any_connected else "disabled",
            **btn_kwargs,
        )
        self._emulate_btn.pack(anchor=tk.W, pady=(0, 4))

        # ── Test Rumble ──
        self._rumble_btn = customtkinter.CTkButton(
            right, text=t("settings.test_rumble"),
            command=self._on_test_rumble_all,
            state="normal" if any_connected else "disabled",
            **btn_kwargs,
        )
        self._rumble_btn.pack(anchor=tk.W, pady=4)

        # ── Paired Controllers ──
        if self._get_known_ble_devices is not None:
            sep_ble = customtkinter.CTkFrame(right, fg_color="#463F6F", height=2)
            sep_ble.pack(fill=tk.X, pady=(12, 8))

            customtkinter.CTkLabel(
                right, text=t("settings.paired_controllers"),
                text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
            ).pack(anchor=tk.W, pady=(0, 4))

            self._device_list_frame = customtkinter.CTkFrame(
                right, fg_color="transparent")
            self._device_list_frame.pack(anchor=tk.W, fill=tk.X)
            self._build_device_list()

        # ── Device Links (USB ↔ BT) ──
        if self._get_device_links is not None:
            sep_links = customtkinter.CTkFrame(right, fg_color="#463F6F", height=2)
            sep_links.pack(fill=tk.X, pady=(12, 8))

            customtkinter.CTkLabel(
                right, text=t("settings.device_links"),
                text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
            ).pack(anchor=tk.W, pady=(0, 4))

            self._links_list_frame = customtkinter.CTkFrame(
                right, fg_color="transparent")
            self._links_list_frame.pack(anchor=tk.W, fill=tk.X)
            self._build_links_list()

        # ── About / Credits ──
        sep2 = customtkinter.CTkFrame(right, fg_color="#463F6F", height=2)
        sep2.pack(fill=tk.X, pady=(12, 8))

        customtkinter.CTkLabel(
            right, text=t("settings.about"),
            text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 4))

        src_link = customtkinter.CTkLabel(
            right, text=t("settings.source_code"),
            text_color=T.TEXT_SECONDARY, font=(T.FONT_FAMILY, 13, "underline"),
            cursor="hand2",
        )
        src_link.pack(anchor=tk.W, padx=4)
        src_link.bind("<Button-1>", lambda e: webbrowser.open(
            "https://github.com/RyanCopley/NSO-GameCube-Controller-Pairing-App"))

        customtkinter.CTkLabel(
            right, text=t("settings.credits"),
            text_color=T.TEXT_PRIMARY, font=(T.FONT_FAMILY, 14, "bold"),
        ).pack(anchor=tk.W, pady=(8, 2))

        credits = [
            ("GVNPWRS/NSO-GC-Controller-PC", "https://github.com/GVNPWRS/NSO-GC-Controller-PC"),
            ("Nohzockt/Switch2-Controllers", "https://github.com/Nohzockt/Switch2-Controllers"),
            ("isaacs-12/nso-gc-bridge", "https://github.com/isaacs-12/nso-gc-bridge"),
            ("darthcloud/BlueRetro", "https://github.com/darthcloud/BlueRetro"),
        ]
        for label_text, url in credits:
            lbl = customtkinter.CTkLabel(
                right, text=label_text,
                text_color=T.TEXT_SECONDARY, font=(T.FONT_FAMILY, 12, "underline"),
                cursor="hand2",
            )
            lbl.pack(anchor=tk.W, padx=12)
            lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

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

    def _build_device_list(self):
        """Rebuild the paired controllers list."""
        for widget in self._device_list_frame.winfo_children():
            widget.destroy()

        devices = self._get_known_ble_devices()
        if not devices:
            customtkinter.CTkLabel(
                self._device_list_frame, text=t("settings.no_paired"),
                text_color=T.TEXT_SECONDARY, font=(T.FONT_FAMILY, 13),
            ).pack(anchor=tk.W, padx=4, pady=2)
            return

        muted_btn = dict(
            fg_color="#463F6F",
            hover_color="#5A5190",
            text_color=T.TEXT_PRIMARY,
            corner_radius=8, height=28, width=70,
            font=(T.FONT_FAMILY, 12),
        )

        for mac in devices:
            row = customtkinter.CTkFrame(
                self._device_list_frame, fg_color="transparent")
            row.pack(anchor=tk.W, fill=tk.X, pady=1)

            customtkinter.CTkLabel(
                row, text=mac,
                text_color=T.TEXT_SECONDARY, font=(T.FONT_FAMILY, 13),
            ).pack(side=tk.LEFT, padx=(4, 8))

            customtkinter.CTkButton(
                row, text=t("settings.forget"),
                command=lambda m=mac: self._forget_device(m),
                **muted_btn,
            ).pack(side=tk.LEFT)

        if len(devices) >= 2:
            customtkinter.CTkButton(
                self._device_list_frame, text=t("settings.forget_all"),
                command=self._forget_all_devices,
                fg_color="#463F6F",
                hover_color="#5A5190",
                text_color=T.TEXT_PRIMARY,
                corner_radius=8, height=28, width=220,
                font=(T.FONT_FAMILY, 12),
            ).pack(anchor=tk.W, pady=(6, 0))

    def _forget_device(self, mac: str):
        """Forget a single paired controller and refresh the list."""
        if self._on_forget_ble_device:
            self._on_forget_ble_device(mac)
            self._build_device_list()

    def _forget_all_devices(self):
        """Forget all paired controllers and refresh the list."""
        if self._on_forget_ble_device and self._get_known_ble_devices:
            for mac in list(self._get_known_ble_devices().keys()):
                self._on_forget_ble_device(mac)
            self._build_device_list()

    def _build_links_list(self):
        """Rebuild the device links list."""
        for widget in self._links_list_frame.winfo_children():
            widget.destroy()

        links = self._get_device_links() if self._get_device_links else {}
        if not links:
            customtkinter.CTkLabel(
                self._links_list_frame, text=t("settings.no_links"),
                text_color=T.TEXT_SECONDARY, font=(T.FONT_FAMILY, 13),
            ).pack(anchor=tk.W, padx=4, pady=2)
            return

        muted_btn = dict(
            fg_color="#463F6F",
            hover_color="#5A5190",
            text_color=T.TEXT_PRIMARY,
            corner_radius=8, height=28, width=70,
            font=(T.FONT_FAMILY, 12),
        )

        shown = set()
        for key, val in links.items():
            pair = tuple(sorted([key, val]))
            if pair in shown:
                continue
            shown.add(pair)

            row = customtkinter.CTkFrame(
                self._links_list_frame, fg_color="transparent")
            row.pack(anchor=tk.W, fill=tk.X, pady=1)

            # Shorten identities for display
            short_a = key.replace('usbpath:', 'USB:').replace('usb:', 'USB:').replace('ble:', 'BT:')
            short_b = val.replace('usbpath:', 'USB:').replace('usb:', 'USB:').replace('ble:', 'BT:')
            label = f"{short_a} \u2194 {short_b}"

            customtkinter.CTkLabel(
                row, text=label,
                text_color=T.TEXT_SECONDARY, font=(T.FONT_FAMILY, 11),
                wraplength=200,
            ).pack(side=tk.LEFT, padx=(4, 8))

            if self._on_unlink_device:
                customtkinter.CTkButton(
                    row, text=t("settings.unlink"),
                    command=lambda k=key: self._unlink_device(k),
                    **muted_btn,
                ).pack(side=tk.LEFT)

    def _unlink_device(self, identity: str):
        """Remove a device link and refresh the list."""
        if self._on_unlink_device:
            self._on_unlink_device(identity)
            self._build_links_list()

    def _on_deadzone_changed(self, value):
        """Update the deadzone label when the slider moves."""
        self._dz_label.configure(text=f"{value:.0%}")

    def _on_save_click(self):
        if self._on_save:
            self._on_save()
        self._dlg.destroy()

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
