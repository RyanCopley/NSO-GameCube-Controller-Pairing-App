"""
Controller UI

All UI widget creation and update methods for the NSO GameCube Controller Pairing App.
Uses PyQt6 for modern widgets and a GameCube purple theme.
Supports up to 4 controller tabs via QTabWidget.
"""

import sys
from typing import Dict, Callable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel,
)

from .controller_constants import MAX_SLOTS
from .calibration import CalibrationManager
from . import ui_theme as T
from .ui_controller_canvas import GCControllerVisual

IS_MACOS = sys.platform == "darwin"


class SlotUI:
    """Holds all per-tab widget references for one controller slot."""

    def __init__(self):
        self.tab_widget = None
        self.connect_btn = None

        # BLE section
        self.pair_btn = None

        # Shared status label
        self.status_label = None

        # Controller visual
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

        # Settings values (plain Python — no Tk variables)
        emu_default = slot_calibrations[0]['emulation_mode']
        if IS_MACOS and emu_default == 'xbox360':
            emu_default = 'dolphin_pipe'
        self.emu_mode = emu_default
        self.trigger_bump_100 = slot_calibrations[0]['trigger_bump_100_percent']
        self.auto_connect = slot_calibrations[0]['auto_connect']
        self.minimize_to_tray = slot_calibrations[0].get('minimize_to_tray', False)

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

        self.slots: List[SlotUI] = []
        self._setup(on_connect, on_stick_cal, on_trigger_cal, on_save,
                    on_pair)

        self._initializing = False

    # ── Setup ────────────────────────────────────────────────────────

    def _setup(self, on_connect, on_stick_cal, on_trigger_cal, on_save,
               on_pair=None):
        """Create the user interface with tab widget."""
        outer = QWidget(self._root)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        self._root.setCentralWidget(outer)

        # Tab widget with corner icon buttons
        self.tabview = QTabWidget()
        outer_layout.addWidget(self.tabview)

        # Save + gear buttons as corner widget
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 4, 4, 4)
        corner_layout.setSpacing(4)

        save_btn = QPushButton("\U0001F5AB\uFE0E")
        save_btn.setProperty("cssClass", "icon-btn")
        save_btn.clicked.connect(on_save)
        corner_layout.addWidget(save_btn)

        gear_btn = QPushButton("\u2699\uFE0E")
        gear_btn.setProperty("cssClass", "icon-btn")
        gear_btn.clicked.connect(self.open_settings)
        corner_layout.addWidget(gear_btn)

        self.tabview.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        # Match tab bar height to corner widget so tabs vertically center
        self.tabview.tabBar().setFixedHeight(48)

        for i in range(MAX_SLOTS):
            tab_name = f"Controller {i + 1}"
            slot_ui = SlotUI()
            tab_widget = QWidget()
            slot_ui.tab_widget = tab_widget
            self.tabview.addTab(tab_widget, tab_name)

            self._build_tab(i, slot_ui, tab_widget, on_connect,
                            on_stick_cal, on_trigger_cal, on_pair)
            self.slots.append(slot_ui)

    def _build_tab(self, index: int, slot_ui: SlotUI, tab_widget: QWidget,
                   on_connect, on_stick_cal, on_trigger_cal,
                   on_pair=None):
        """Build one controller tab."""
        cal = self._slot_calibrations[index]
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(5, 5, 5, 5)

        # Controller Visual
        slot_ui.controller_visual = GCControllerVisual()
        layout.addWidget(slot_ui.controller_visual, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status label
        slot_ui.status_label = QLabel("Ready to connect")
        slot_ui.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slot_ui.status_label.setStyleSheet(
            f"color: {T.TEXT_PRIMARY}; font-family: '{T.FONT_FAMILY}'; font-size: 14px;")
        layout.addWidget(slot_ui.status_label)

        # Draw saved octagons
        for side in ('left', 'right'):
            cal_key = f'stick_{side}_octagon'
            octagon_data = cal.get(cal_key)
            slot_ui.controller_visual.draw_octagon(side, octagon_data)

        # Draw trigger bump markers
        for side in ('left', 'right'):
            bump_val = cal.get(f'trigger_{side}_bump', 190.0)
            slot_ui.controller_visual.draw_trigger_bump_line(side, bump_val)

        # Bottom button row
        btn_layout = QHBoxLayout()

        slot_ui.connect_btn = QPushButton("Connect USB")
        slot_ui.connect_btn.clicked.connect(lambda checked, i=index: on_connect(i))
        btn_layout.addWidget(slot_ui.connect_btn)

        if self._ble_available and on_pair:
            slot_ui.pair_btn = QPushButton("Connect Wireless")
            slot_ui.pair_btn.clicked.connect(lambda checked, i=index: on_pair(i))
            btn_layout.addWidget(slot_ui.pair_btn)

        slot_ui.stick_cal_btn = QPushButton("Calibrate Sticks")
        slot_ui.stick_cal_btn.clicked.connect(lambda checked, i=index: on_stick_cal(i))
        btn_layout.addWidget(slot_ui.stick_cal_btn)

        slot_ui.trigger_cal_btn = QPushButton("Calibrate Triggers")
        slot_ui.trigger_cal_btn.clicked.connect(lambda checked, i=index: on_trigger_cal(i))
        btn_layout.addWidget(slot_ui.trigger_cal_btn)

        layout.addLayout(btn_layout)

        # Hidden status labels for calibration feedback
        slot_ui.stick_cal_status = QLabel("")
        slot_ui.stick_cal_status.setStyleSheet(
            f"color: {T.TEXT_DIM}; font-family: '{T.FONT_FAMILY}'; font-size: 12px;")
        slot_ui.stick_cal_status.setVisible(False)
        layout.addWidget(slot_ui.stick_cal_status)

        slot_ui.trigger_cal_status = QLabel("")
        slot_ui.trigger_cal_status.setStyleSheet(
            f"color: {T.TEXT_DIM}; font-family: '{T.FONT_FAMILY}'; font-size: 12px;")
        slot_ui.trigger_cal_status.setVisible(False)
        layout.addWidget(slot_ui.trigger_cal_status)

    # ── Settings dialog ─────────────────────────────────────────────

    def open_settings(self):
        """Open the global settings dialog."""
        from .ui_settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            self._root,
            emu_mode=self.emu_mode,
            trigger_bump_100=self.trigger_bump_100,
            auto_connect=self.auto_connect,
            minimize_to_tray=self.minimize_to_tray,
            on_emulate_all=self._on_emulate_all if self._on_emulate_all else lambda: None,
            on_test_rumble_all=self._on_test_rumble_all if self._on_test_rumble_all else lambda: None,
            is_any_emulating=lambda: any(self._slot_emulating),
            is_any_connected=lambda: any(self._slot_connected),
            on_save=self._on_save,
        )
        if dlg.exec():
            # Update values from dialog results
            old_emu = self.emu_mode
            old_trigger = self.trigger_bump_100
            old_auto = self.auto_connect
            old_tray = self.minimize_to_tray

            self.emu_mode = dlg.result_emu_mode
            self.trigger_bump_100 = dlg.result_trigger_bump_100
            self.auto_connect = dlg.result_auto_connect
            self.minimize_to_tray = dlg.result_minimize_to_tray

            if (self.emu_mode != old_emu or self.trigger_bump_100 != old_trigger
                    or self.auto_connect != old_auto or self.minimize_to_tray != old_tray):
                self.mark_slot_dirty(0)

    # ── UI update methods ────────────────────────────────────────────

    def update_stick_position(self, slot_index: int, side: str,
                              x_norm: float, y_norm: float):
        """Update analog stick position on the controller visual."""
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
        self.tabview.setTabText(slot_index, new_name)

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
            s.status_label.setText(message)

    def update_ble_status(self, slot_index: int, message: str):
        """Update status with a BLE message."""
        self.update_status(slot_index, message)

    def update_emu_status(self, slot_index: int, message: str):
        """Update status with an emulation message."""
        self.update_status(slot_index, message)
