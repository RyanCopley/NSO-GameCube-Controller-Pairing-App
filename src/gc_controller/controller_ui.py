"""
Controller UI

All UI widget creation and update methods for the NSO GameCube Controller Pairing App.
Uses customtkinter for modern rounded widgets and a GameCube purple theme.
Supports up to 4 controller tabs via CTkTabview.
"""

import sys
import tkinter as tk
from typing import Dict, Callable, List, Optional

import customtkinter

from .controller_constants import MAX_SLOTS
from .calibration import CalibrationManager
from . import ui_theme as T
from .ui_controller_canvas import GCControllerVisual

IS_MACOS = sys.platform == "darwin"


class SlotUI:
    """Holds all per-tab widget references for one controller slot."""

    def __init__(self):
        self.tab_frame = None
        self.connect_btn = None

        # BLE section
        self.pair_btn = None

        # Shared status label
        self.status_label = None

        # Controller visual (replaces separate stick/trigger/button widgets)
        self.controller_visual: Optional[GCControllerVisual] = None


        # Calibration
        self.stick_cal_btn = None
        self.stick_cal_status = None
        self.trigger_cal_btn = None
        self.trigger_cal_status = None


class ControllerUI:
    """Creates and manages all UI widgets for the controller application."""

    def __init__(self, root,
                 slot_calibrations: List[dict],
                 slot_cal_mgrs: List[CalibrationManager],
                 on_connect: Callable[[int], None],
                 on_stick_cal: Callable[[int], None],
                 on_trigger_cal: Callable[[int], None],
                 on_save: Callable,
                 on_pair: Optional[Callable[[int], None]] = None,
                 on_emulate_all: Optional[Callable] = None,
                 on_test_rumble_all: Optional[Callable] = None,
                 ble_available: bool = False):
        self._root = root
        self._slot_calibrations = slot_calibrations
        self._slot_cal_mgrs = slot_cal_mgrs
        self._ble_available = ble_available

        self._trigger_bar_width = 150
        self._trigger_bar_height = 20

        # Global UI variables
        self.auto_connect_var = tk.BooleanVar(value=slot_calibrations[0]['auto_connect'])

        emu_default = slot_calibrations[0]['emulation_mode']
        if IS_MACOS and emu_default == 'xbox360':
            emu_default = 'dolphin_pipe'
        self.emu_mode_var = tk.StringVar(value=emu_default)
        self.trigger_mode_var = tk.BooleanVar(value=slot_calibrations[0]['trigger_bump_100_percent'])

        # Callbacks for settings dialog
        self._on_emulate_all = on_emulate_all
        self._on_test_rumble_all = on_test_rumble_all
        self._on_save = on_save

        # Dirty (unsaved changes) tracking per slot
        self._slot_dirty: List[bool] = [False] * MAX_SLOTS
        self._slot_connected: List[bool] = [False] * MAX_SLOTS
        self._slot_emulating: List[bool] = [False] * MAX_SLOTS
        self._initializing = True

        # Settings dialog reference
        self._settings_dialog = None

        # Tab name tracking for CTkTabview rename
        self._tab_names: List[str] = []

        self.slots: List[SlotUI] = []
        self._setup(on_connect, on_stick_cal, on_trigger_cal, on_save,
                    on_pair)

        self._initializing = False

    # ── Setup ────────────────────────────────────────────────────────

    def _setup(self, on_connect, on_stick_cal, on_trigger_cal, on_save,
               on_pair=None):
        """Create the user interface with tabview tabs."""
        outer_frame = customtkinter.CTkFrame(self._root, fg_color="transparent")
        outer_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # Configure root grid
        self._root.grid_rowconfigure(0, weight=1)
        self._root.grid_columnconfigure(0, weight=1)

        # CTkTabview with 4 tabs
        self.tabview = customtkinter.CTkTabview(
            outer_frame,
            fg_color=T.GC_PURPLE_DARK,
            segmented_button_fg_color=T.GC_PURPLE_DARK,
            segmented_button_selected_color="#463F6F",
            segmented_button_unselected_color=T.GC_PURPLE_DARK,
            segmented_button_selected_hover_color=T.GC_PURPLE_LIGHT,
            segmented_button_unselected_hover_color=T.GC_PURPLE_MID,
            text_color=T.TEXT_PRIMARY,
            text_color_disabled=T.TEXT_DIM,
            corner_radius=12,
        )
        self.tabview._segmented_button.configure(font=(T.FONT_FAMILY, 15))
        self.tabview.grid(row=0, column=0, sticky="nsew")
        outer_frame.grid_rowconfigure(0, weight=1)
        outer_frame.grid_columnconfigure(0, weight=1)

        # Save + gear buttons overlaid in the top-right of the tabview
        icon_base = dict(
            fg_color="#463F6F",
            hover_color="#5A5190",
            text_color=T.TEXT_PRIMARY,
            corner_radius=8,
        )

        icon_frame = customtkinter.CTkFrame(self.tabview, fg_color="transparent")
        icon_frame.place(relx=1.0, y=0, anchor="ne")

        customtkinter.CTkButton(
            icon_frame, text="\U0001F5AB",
            command=on_save,
            width=40, height=40, font=("", 24),
            **icon_base,
        ).pack(side=tk.LEFT, padx=(0, 4))

        customtkinter.CTkButton(
            icon_frame, text="\u2699",
            command=self.open_settings,
            width=40, height=40, font=("", 24),
            **icon_base,
        ).pack(side=tk.LEFT)

        for i in range(MAX_SLOTS):
            tab_name = f"Controller {i + 1}"
            self.tabview.add(tab_name)
            self._tab_names.append(tab_name)

            slot_ui = SlotUI()
            self._build_tab(i, slot_ui, on_connect,
                            on_stick_cal, on_trigger_cal, on_pair)
            self.slots.append(slot_ui)

        # Track global setting changes
        self.auto_connect_var.trace_add('write', lambda *_: self.mark_slot_dirty(0))
        self.emu_mode_var.trace_add('write', lambda *_: self.mark_slot_dirty(0))
        self.trigger_mode_var.trace_add('write', lambda *_: self.mark_slot_dirty(0))

    def _build_tab(self, index: int, slot_ui: SlotUI,
                   on_connect, on_stick_cal, on_trigger_cal,
                   on_pair=None):
        """Build one controller tab."""
        tab_name = self._tab_names[index]
        tab = self.tabview.tab(tab_name)
        slot_ui.tab_frame = tab

        cal = self._slot_calibrations[index]

        # ── Controller Visual (center) with status bar inside ──
        visual_frame = customtkinter.CTkFrame(tab, fg_color="transparent")
        visual_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=(5, 8))

        slot_ui.controller_visual = GCControllerVisual(visual_frame)
        slot_ui.controller_visual.pack(padx=8, pady=(8, 0))

        slot_ui.status_label = customtkinter.CTkLabel(
            visual_frame, text="Ready to connect",
            text_color="#FFFFFF", font=(T.FONT_FAMILY, 14),
            anchor="center",
        )
        slot_ui.status_label.pack(fill=tk.X, padx=10, pady=(2, 8))

        # Draw saved octagons
        for side in ('left', 'right'):
            cal_key = f'stick_{side}_octagon'
            octagon_data = cal.get(cal_key)
            slot_ui.controller_visual.draw_octagon(side, octagon_data)

        # Draw trigger bump markers
        for side in ('left', 'right'):
            bump_val = cal.get(f'trigger_{side}_bump', 190.0)
            slot_ui.controller_visual.draw_trigger_bump_line(side, bump_val)

        # ── Bottom button row ──
        btn_frame = customtkinter.CTkFrame(tab, fg_color="transparent")
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                        padx=5, pady=(0, 5))

        btn_kwargs = dict(
            fg_color=T.BTN_FG,
            hover_color=T.BTN_HOVER,
            text_color=T.BTN_TEXT,
            corner_radius=12, height=32,
            font=(T.FONT_FAMILY, 14),
        )

        slot_ui.connect_btn = customtkinter.CTkButton(
            btn_frame, text="Connect USB",
            command=lambda i=index: on_connect(i),
            **btn_kwargs,
        )
        slot_ui.connect_btn.pack(side=tk.LEFT, padx=(0, 4), expand=True, fill=tk.X)

        if self._ble_available and on_pair:
            slot_ui.pair_btn = customtkinter.CTkButton(
                btn_frame, text="Connect Wireless",
                command=lambda i=index: on_pair(i),
                **btn_kwargs,
            )
            slot_ui.pair_btn.pack(side=tk.LEFT, padx=4, expand=True, fill=tk.X)

        slot_ui.stick_cal_btn = customtkinter.CTkButton(
            btn_frame, text="Calibrate Sticks",
            command=lambda i=index: on_stick_cal(i),
            **btn_kwargs,
        )
        slot_ui.stick_cal_btn.pack(side=tk.LEFT, padx=4, expand=True, fill=tk.X)

        slot_ui.trigger_cal_btn = customtkinter.CTkButton(
            btn_frame, text="Calibrate Triggers",
            command=lambda i=index: on_trigger_cal(i),
            **btn_kwargs,
        )
        slot_ui.trigger_cal_btn.pack(side=tk.LEFT, padx=(4, 0), expand=True, fill=tk.X)

        # Hidden status labels for calibration feedback
        slot_ui.stick_cal_status = customtkinter.CTkLabel(
            btn_frame, text="", text_color=T.TEXT_DIM, font=(T.FONT_FAMILY, 12),
        )
        slot_ui.trigger_cal_status = customtkinter.CTkLabel(
            btn_frame, text="", text_color=T.TEXT_DIM, font=(T.FONT_FAMILY, 12),
        )

        # Configure grid weights
        tab.grid_columnconfigure(0, weight=1)

    # ── Settings dialog ─────────────────────────────────────────────

    def open_settings(self):
        """Open the global settings dialog."""
        from .ui_settings_dialog import SettingsDialog
        self._settings_dialog = SettingsDialog(
            self._root,
            emu_mode_var=self.emu_mode_var,
            trigger_mode_var=self.trigger_mode_var,
            auto_connect_var=self.auto_connect_var,
            on_emulate_all=self._on_emulate_all if self._on_emulate_all else lambda: None,
            on_test_rumble_all=self._on_test_rumble_all if self._on_test_rumble_all else lambda: None,
            is_any_emulating=lambda: any(self._slot_emulating),
            is_any_connected=lambda: any(self._slot_connected),
            on_save=self._on_save,
        )

    # ── UI update methods ────────────────────────────────────────────

    def update_stick_position(self, slot_index: int, side: str,
                              x_norm: float, y_norm: float):
        """Update analog stick position on the controller visual.

        Args:
            slot_index: which controller slot.
            side: 'left' or 'right'.
            x_norm: normalized X in [-1, 1].
            y_norm: normalized Y in [-1, 1].
        """
        s = self.slots[slot_index]
        s.controller_visual.update_stick_position(side, x_norm, y_norm)

    def update_trigger_display(self, slot_index: int, left_trigger, right_trigger):
        """Update trigger fills and labels for a specific slot."""
        s = self.slots[slot_index]
        cal_mgr = self._slot_cal_mgrs[slot_index]
        s.controller_visual.update_trigger_fill('left', cal_mgr.calibrate_trigger_fast(left_trigger, 'left'))
        s.controller_visual.update_trigger_fill('right', cal_mgr.calibrate_trigger_fast(right_trigger, 'right'))

    def update_button_display(self, slot_index: int, button_states: Dict[str, bool]):
        """Update button indicators for a specific slot."""
        s = self.slots[slot_index]
        s.controller_visual.update_button_states(button_states)

    def draw_trigger_markers(self, slot_index: int):
        """Redraw trigger bump marker lines from calibration data."""
        s = self.slots[slot_index]
        cal_mgr = self._slot_cal_mgrs[slot_index]
        for side in ('left', 'right'):
            cal = self._slot_calibrations[slot_index]
            bump_raw = cal.get(f'trigger_{side}_bump', 190.0)
            bump_calibrated = cal_mgr.calibrate_trigger_fast(int(bump_raw), side)
            s.controller_visual.draw_trigger_bump_line(side, bump_calibrated)

    # ── Calibration mode ─────────────────────────────────────────

    def set_calibration_mode(self, slot_index: int, enabled: bool):
        """Toggle between graphic view and calibration view for a slot."""
        s = self.slots[slot_index]
        s.controller_visual.set_calibration_mode(enabled)

    # ── Octagon drawing ───────────────────────────────────────────

    def draw_octagon_live(self, slot_index: int, side: str):
        """Redraw octagon from in-progress calibration data."""
        s = self.slots[slot_index]
        cal_mgr = self._slot_cal_mgrs[slot_index]
        dists, points, cx, rx, cy, ry = cal_mgr.get_live_octagon_data(side)
        s.controller_visual.draw_octagon_live(side, dists, points, cx, rx, cy, ry)

    def redraw_octagons(self, slot_index: int):
        """Redraw both octagon polygons from calibration data for a slot."""
        s = self.slots[slot_index]
        cal = self._slot_calibrations[slot_index]
        for side in ('left', 'right'):
            cal_key = f'stick_{side}_octagon'
            octagon_data = cal.get(cal_key)
            s.controller_visual.draw_octagon(side, octagon_data)

    # ── Tab status / dirty tracking ──────────────────────────────────

    def update_tab_status(self, slot_index: int, connected: bool, emulating: bool):
        """Update stored connection/emulation state and refresh tab title."""
        self._slot_connected[slot_index] = connected
        self._slot_emulating[slot_index] = emulating
        self._refresh_tab_title(slot_index)

    def _refresh_tab_title(self, slot_index: int):
        """Rebuild tab title from connection, emulation, and dirty state."""
        prefix = "\u2713 " if self._slot_connected[slot_index] else ""
        base = f"Controller {slot_index + 1}"
        dirty = " *" if self._slot_dirty[slot_index] else ""
        new_name = prefix + base + dirty
        old_name = self._tab_names[slot_index]

        if new_name != old_name:
            try:
                self.tabview.rename(old_name, new_name)
                self._tab_names[slot_index] = new_name
                # Fix CTkTabview bug: rename() doesn't update _current_name
                if getattr(self.tabview, '_current_name', None) == old_name:
                    self.tabview._current_name = new_name
            except Exception:
                pass

    def mark_slot_dirty(self, slot_index: int):
        """Mark a slot as having unsaved changes."""
        if self._initializing:
            return
        if not self._slot_dirty[slot_index]:
            self._slot_dirty[slot_index] = True
            self._refresh_tab_title(slot_index)

    def mark_all_clean(self):
        """Clear unsaved-changes indicators on all slots."""
        self._slot_dirty = [False] * MAX_SLOTS
        for i in range(MAX_SLOTS):
            self._refresh_tab_title(i)

    # ── Reset ────────────────────────────────────────────────────────

    def reset_slot_ui(self, slot_index: int):
        """Reset UI elements for a specific slot to default state."""
        s = self.slots[slot_index]
        s.controller_visual.reset()

        # Redraw saved octagons
        cal = self._slot_calibrations[slot_index]
        for side in ('left', 'right'):
            cal_key = f'stick_{side}_octagon'
            octagon_data = cal.get(cal_key)
            s.controller_visual.draw_octagon(side, octagon_data)

    # ── Status helpers ───────────────────────────────────────────────

    def update_status(self, slot_index: int, message: str):
        """Update the shared status label for a specific slot."""
        s = self.slots[slot_index]
        if s.status_label is not None:
            s.status_label.configure(text=message)

    def update_ble_status(self, slot_index: int, message: str):
        """Update status with a BLE message."""
        self.update_status(slot_index, message)

    def update_emu_status(self, slot_index: int, message: str):
        """Update status with an emulation message."""
        self.update_status(slot_index, message)
