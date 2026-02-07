"""
UI BLE Dialog - BLE Device Picker

Modal dialog for choosing a BLE device from scan results,
styled with customtkinter.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional

import customtkinter

from . import ui_theme as T


class BLEDevicePickerDialog:
    """Modal dialog for choosing a BLE device from a scan result list.

    Shows a Treeview with Name, Address, Signal columns.
    Returns the chosen address or None.
    """

    def __init__(self, parent, devices: list[dict]):
        """Create the picker dialog.

        Args:
            parent: The parent window (CTk or Tk).
            devices: List of dicts with keys: address, name, rssi.
        """
        self._result: Optional[str] = None

        self._dlg = customtkinter.CTkToplevel(parent)
        self._dlg.title("Select BLE Controller")
        self._dlg.resizable(False, False)
        self._dlg.transient(parent)
        self._dlg.grab_set()
        self._dlg.configure(fg_color=T.GC_PURPLE_DARK)

        frame = customtkinter.CTkFrame(self._dlg, fg_color=T.GC_PURPLE_DARK)
        frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        customtkinter.CTkLabel(
            frame, text="Select a controller to connect:",
            text_color=T.TEXT_PRIMARY, font=("", 14),
        ).pack(anchor=tk.W, pady=(0, 8))

        # Style the Treeview for dark theme
        style = ttk.Style()
        style.theme_use('default')
        style.configure('BLE.Treeview',
                        background=T.SURFACE_DARK,
                        foreground=T.TEXT_PRIMARY,
                        fieldbackground=T.SURFACE_DARK,
                        borderwidth=0,
                        font=("", 11))
        style.configure('BLE.Treeview.Heading',
                        background=T.GC_PURPLE_MID,
                        foreground=T.TEXT_PRIMARY,
                        borderwidth=0,
                        font=("", 11, "bold"))
        style.map('BLE.Treeview',
                  background=[('selected', T.GC_PURPLE_LIGHT)],
                  foreground=[('selected', T.TEXT_PRIMARY)])

        # Treeview
        cols = ("name", "address", "signal")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings",
                                  height=min(len(devices), 12),
                                  style='BLE.Treeview')
        self._tree.heading("name", text="Name")
        self._tree.heading("address", text="Address")
        self._tree.heading("signal", text="Signal")
        self._tree.column("name", width=180)
        self._tree.column("address", width=160)
        self._tree.column("signal", width=60, anchor=tk.CENTER)

        # Sort by RSSI descending (strongest first)
        sorted_devices = sorted(devices, key=lambda d: d.get('rssi', -999),
                                reverse=True)
        for dev in sorted_devices:
            rssi = dev.get('rssi', -999)
            signal = f"{rssi} dBm" if rssi > -999 else "?"
            name = dev.get('name', '') or '(unknown)'
            self._tree.insert("", tk.END, values=(
                name, dev['address'], signal))

        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", lambda _: self._on_connect())

        # Buttons
        btn_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill=tk.X, pady=(12, 0))

        customtkinter.CTkButton(
            btn_frame, text="Cancel",
            command=self._on_cancel,
            fg_color=T.GC_PURPLE_SURFACE,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, width=100,
        ).pack(side=tk.RIGHT)

        self._connect_btn = customtkinter.CTkButton(
            btn_frame, text="Connect",
            command=self._on_connect,
            fg_color=T.GC_PURPLE_MID,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, width=100,
        )
        self._connect_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self._dlg.protocol("WM_DELETE_WINDOW", self._on_cancel)

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

    def _on_connect(self):
        sel = self._tree.selection()
        if sel:
            values = self._tree.item(sel[0], "values")
            self._result = values[1]  # address column
            self._dlg.destroy()

    def _on_cancel(self):
        self._result = None
        self._dlg.destroy()

    def show(self) -> Optional[str]:
        """Show the dialog and block until closed. Returns address or None."""
        self._dlg.wait_window()
        return self._result
