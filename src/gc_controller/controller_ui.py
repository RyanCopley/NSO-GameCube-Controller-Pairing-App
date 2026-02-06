"""
Controller UI

All Tkinter widget creation and UI update methods for the GameCube Controller Enabler.
Supports up to 4 controller tabs via ttk.Notebook.
"""

import math
import sys
import tkinter as tk
from tkinter import ttk
from typing import Dict, Callable, List, Optional

from .controller_constants import normalize, MAX_SLOTS
from .calibration import CalibrationManager

IS_MACOS = sys.platform == "darwin"


class SlotUI:
    """Holds all per-tab widget references for one controller slot."""

    def __init__(self):
        self.tab_frame: ttk.Frame = None
        self.connect_btn: ttk.Button = None
        self.emulate_btn: ttk.Button = None
        self.test_rumble_btn: Optional[ttk.Button] = None

        # BLE section
        self.pair_btn: Optional[ttk.Button] = None

        # Shared status label (below all 3 sections)
        self.status_label: Optional[ttk.Label] = None

        # Sticks
        self.left_stick_canvas: tk.Canvas = None
        self.left_stick_dot = None
        self.right_stick_canvas: tk.Canvas = None
        self.right_stick_dot = None

        # Triggers
        self.left_trigger_canvas: tk.Canvas = None
        self.left_trigger_label: ttk.Label = None
        self.right_trigger_canvas: tk.Canvas = None
        self.right_trigger_label: ttk.Label = None

        # Buttons
        self.button_labels: Dict[str, ttk.Label] = {}
        self.dpad_labels: Dict[str, ttk.Label] = {}

        # Calibration
        self.stick_cal_btn: ttk.Button = None
        self.stick_cal_status: ttk.Label = None
        self.trigger_cal_btn: ttk.Button = None
        self.trigger_cal_status: ttk.Label = None

        # Device selector
        self.device_var: tk.StringVar = None
        self.device_combo: ttk.Combobox = None
        self.device_paths: list = []  # parallel list: index 0 = None (Auto), rest = bytes paths

        # Modes
        self.trigger_mode_var: tk.BooleanVar = None
        self.emu_mode_var: tk.StringVar = None


class ControllerUI:
    """Creates and manages all UI widgets for the controller application."""

    def __init__(self, root: tk.Tk,
                 slot_calibrations: List[dict],
                 slot_cal_mgrs: List[CalibrationManager],
                 on_connect: Callable[[int], None],
                 on_emulate: Callable[[int], None],
                 on_stick_cal: Callable[[int], None],
                 on_trigger_cal: Callable[[int], None],
                 on_save: Callable,
                 on_refresh: Callable,
                 on_pair: Optional[Callable[[int], None]] = None,
                 on_test_rumble: Optional[Callable[[int], None]] = None,
                 ble_available: bool = False):
        self._root = root
        self._slot_calibrations = slot_calibrations
        self._slot_cal_mgrs = slot_cal_mgrs
        self._ble_available = ble_available

        self._trigger_bar_width = 150
        self._trigger_bar_height = 20

        # Global UI variable
        self.auto_connect_var = tk.BooleanVar(value=slot_calibrations[0]['auto_connect'])

        # Dirty (unsaved changes) tracking per slot
        self._slot_dirty: List[bool] = [False] * MAX_SLOTS
        self._slot_connected: List[bool] = [False] * MAX_SLOTS
        self._slot_emulating: List[bool] = [False] * MAX_SLOTS
        self._initializing = True

        self._on_test_rumble = on_test_rumble

        self.slots: List[SlotUI] = []
        self._setup(on_connect, on_emulate, on_stick_cal, on_trigger_cal, on_save,
                    on_refresh, on_pair)

        self._initializing = False

    # ── Setup ────────────────────────────────────────────────────────

    def _setup(self, on_connect, on_emulate, on_stick_cal, on_trigger_cal, on_save,
               on_refresh, on_pair=None):
        """Create the user interface with notebook tabs."""
        outer_frame = ttk.Frame(self._root, padding="10")
        outer_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Notebook with 4 tabs
        self.notebook = ttk.Notebook(outer_frame)
        self.notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        for i in range(MAX_SLOTS):
            slot_ui = SlotUI()
            self._build_tab(i, slot_ui, on_connect, on_emulate,
                            on_stick_cal, on_trigger_cal, on_refresh, on_pair)
            self.slots.append(slot_ui)

        # Global controls below the notebook (centered)
        global_frame = ttk.Frame(outer_frame)
        global_frame.grid(row=1, column=0, pady=(5, 0))

        ttk.Button(global_frame, text="Save All Settings",
                   command=on_save).pack(side=tk.LEFT)

        # Track global setting changes (stored on slot 0)
        self.auto_connect_var.trace_add('write', lambda *_: self.mark_slot_dirty(0))

        outer_frame.columnconfigure(0, weight=1)

    def _build_tab(self, index: int, slot_ui: SlotUI,
                   on_connect, on_emulate, on_stick_cal, on_trigger_cal,
                   on_refresh, on_pair=None):
        """Build one controller tab."""
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text=f"Controller {index + 1}")
        slot_ui.tab_frame = tab

        cal = self._slot_calibrations[index]

        # Per-slot Tkinter variables
        slot_ui.trigger_mode_var = tk.BooleanVar(value=cal['trigger_bump_100_percent'])

        emu_default = cal['emulation_mode']
        if IS_MACOS and emu_default == 'xbox360':
            emu_default = 'dolphin_pipe'
        slot_ui.emu_mode_var = tk.StringVar(value=emu_default)

        # ── Top row: 3 equal-width sections ──
        top_frame = ttk.Frame(tab)
        top_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        top_frame.columnconfigure(0, weight=1)
        top_frame.columnconfigure(1, weight=1)
        top_frame.columnconfigure(2, weight=1)

        self._build_usb_section(top_frame, index, slot_ui, on_connect, on_refresh)
        self._build_ble_section(top_frame, index, slot_ui, on_pair)
        self._build_emu_section(top_frame, index, slot_ui, on_emulate)

        # Shared status label below the 3 sections
        slot_ui.status_label = ttk.Label(tab, text="Ready to connect")
        slot_ui.status_label.grid(row=1, column=0, columnspan=2, pady=(0, 5))

        # Left column
        left_column = ttk.Frame(tab)
        left_column.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N), padx=(0, 10))

        # Button visualization
        controller_frame = ttk.LabelFrame(left_column, text="Button Configuration", padding="10")
        controller_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        buttons_frame = ttk.Frame(controller_frame)
        buttons_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        slot_ui.button_labels = {}
        button_names = ["A", "B", "X", "Y", "L", "R", "Z", "ZL",
                        "Start/Pause", "Home", "Capture", "Chat"]

        for j, btn_name in enumerate(button_names):
            row = j // 4
            col = j % 4
            label = ttk.Label(buttons_frame, text=btn_name, width=8, relief='raised')
            label.grid(row=row, column=col, padx=2, pady=2)
            slot_ui.button_labels[btn_name] = label

        # D-pad
        dpad_frame = ttk.LabelFrame(buttons_frame, text="D-Pad")
        dpad_frame.grid(row=3, column=0, columnspan=4, pady=(10, 0))

        slot_ui.dpad_labels = {}
        for direction in ["Up", "Down", "Left", "Right"]:
            label = ttk.Label(dpad_frame, text=direction, width=6, relief='raised')
            slot_ui.dpad_labels[direction] = label

        slot_ui.dpad_labels["Up"].grid(row=0, column=1)
        slot_ui.dpad_labels["Left"].grid(row=1, column=0)
        slot_ui.dpad_labels["Right"].grid(row=1, column=2)
        slot_ui.dpad_labels["Down"].grid(row=2, column=1)

        # Analog sticks
        sticks_frame = ttk.LabelFrame(left_column, text="Analog Sticks", padding="10")
        sticks_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

        # Right column
        right_column = ttk.Frame(tab)
        right_column.grid(row=2, column=1, sticky=(tk.W, tk.E, tk.N))

        # Analog triggers section
        calibration_frame = ttk.LabelFrame(right_column, text="Analog Triggers", padding="10")
        calibration_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        # Left stick
        left_stick_frame = ttk.Frame(sticks_frame)
        left_stick_frame.grid(row=0, column=0, padx=10)
        ttk.Label(left_stick_frame, text="Left Stick").grid(row=0, column=0)
        slot_ui.left_stick_canvas = tk.Canvas(left_stick_frame, width=80, height=80, bg='lightgray')
        slot_ui.left_stick_canvas.grid(row=1, column=0)
        slot_ui.left_stick_dot = slot_ui.left_stick_canvas.create_oval(37, 37, 43, 43, fill='red')
        self._init_stick_canvas(slot_ui.left_stick_canvas, slot_ui.left_stick_dot, 'left', index)

        # Right stick
        right_stick_frame = ttk.Frame(sticks_frame)
        right_stick_frame.grid(row=0, column=1, padx=10)
        ttk.Label(right_stick_frame, text="Right Stick").grid(row=0, column=0)
        slot_ui.right_stick_canvas = tk.Canvas(right_stick_frame, width=80, height=80, bg='lightgray')
        slot_ui.right_stick_canvas.grid(row=1, column=0)
        slot_ui.right_stick_dot = slot_ui.right_stick_canvas.create_oval(37, 37, 43, 43, fill='red')
        self._init_stick_canvas(slot_ui.right_stick_canvas, slot_ui.right_stick_dot, 'right', index)

        # Stick calibration
        stick_cal_frame = ttk.LabelFrame(sticks_frame, text="Calibration", padding="5")
        stick_cal_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky=(tk.W, tk.E))

        slot_ui.stick_cal_btn = ttk.Button(
            stick_cal_frame, text="Calibrate Sticks",
            command=lambda i=index: on_stick_cal(i))
        slot_ui.stick_cal_btn.grid(row=0, column=0, padx=5, pady=2)

        slot_ui.stick_cal_status = ttk.Label(stick_cal_frame, text="Using saved calibration")
        slot_ui.stick_cal_status.grid(row=0, column=1, padx=5, pady=2)

        # Trigger visualizers
        triggers_frame = ttk.Frame(calibration_frame)
        triggers_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        w = self._trigger_bar_width
        h = self._trigger_bar_height

        ttk.Label(triggers_frame, text="Left Trigger").grid(row=0, column=0)
        slot_ui.left_trigger_canvas = tk.Canvas(triggers_frame, width=w, height=h,
                                                bg='#e0e0e0', highlightthickness=1,
                                                highlightbackground='#999999')
        slot_ui.left_trigger_canvas.grid(row=0, column=1, padx=(5, 10))
        slot_ui.left_trigger_label = ttk.Label(triggers_frame, text="0")
        slot_ui.left_trigger_label.grid(row=0, column=2)

        ttk.Label(triggers_frame, text="Right Trigger").grid(row=1, column=0)
        slot_ui.right_trigger_canvas = tk.Canvas(triggers_frame, width=w, height=h,
                                                 bg='#e0e0e0', highlightthickness=1,
                                                 highlightbackground='#999999')
        slot_ui.right_trigger_canvas.grid(row=1, column=1, padx=(5, 10))
        slot_ui.right_trigger_label = ttk.Label(triggers_frame, text="0")
        slot_ui.right_trigger_label.grid(row=1, column=2)

        # Draw initial calibration markers
        self._draw_trigger_markers(index)

        # Trigger calibration wizard
        trigger_cal_frame = ttk.LabelFrame(calibration_frame, text="Calibration", padding="5")
        trigger_cal_frame.grid(row=1, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        slot_ui.trigger_cal_btn = ttk.Button(
            trigger_cal_frame, text="Calibrate Triggers",
            command=lambda i=index: on_trigger_cal(i))
        slot_ui.trigger_cal_btn.grid(row=0, column=0, padx=5, pady=2)

        slot_ui.trigger_cal_status = ttk.Label(trigger_cal_frame, text="Using saved calibration")
        slot_ui.trigger_cal_status.grid(row=0, column=1, padx=5, pady=2)

        # Trigger mode
        mode_frame = ttk.LabelFrame(calibration_frame, text="Trigger Mode", padding="5")
        mode_frame.grid(row=2, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        ttk.Radiobutton(mode_frame, text="100% at bump",
                        variable=slot_ui.trigger_mode_var, value=True).grid(
                            row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(mode_frame, text="100% at press",
                        variable=slot_ui.trigger_mode_var, value=False).grid(
                            row=1, column=0, sticky=tk.W)

        # Rumble
        rumble_frame = ttk.LabelFrame(calibration_frame, text="Rumble", padding="5")
        rumble_frame.grid(row=3, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        slot_ui.test_rumble_btn = ttk.Button(
            rumble_frame, text="Test Rumble",
            command=lambda i=index: self._on_test_rumble(i) if self._on_test_rumble else None,
            state='disabled')
        slot_ui.test_rumble_btn.grid(row=0, column=0, padx=5, pady=2)

        # Track per-slot setting changes
        slot_ui.trigger_mode_var.trace_add('write', lambda *_, i=index: self.mark_slot_dirty(i))
        slot_ui.emu_mode_var.trace_add('write', lambda *_, i=index: self.mark_slot_dirty(i))

        # Configure grid weights
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

    # ── Top-row section builders ────────────────────────────────────

    def _build_usb_section(self, parent, index, slot_ui, on_connect, on_refresh):
        """Build the USB connection section."""
        frame = ttk.LabelFrame(parent, text="USB", padding="5")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 3))
        frame.columnconfigure(0, weight=1)

        # Connect + Refresh buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=0, column=0, sticky=tk.W)

        slot_ui.connect_btn = ttk.Button(
            btn_frame, text="Connect",
            command=lambda i=index: on_connect(i))
        slot_ui.connect_btn.pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(btn_frame, text="Refresh",
                   command=lambda: on_refresh()).pack(side=tk.LEFT)

        # Device selector
        dev_frame = ttk.Frame(frame)
        dev_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        dev_frame.columnconfigure(1, weight=1)

        ttk.Label(dev_frame, text="Device:").grid(
            row=0, column=0, padx=(0, 5), sticky=tk.W)
        slot_ui.device_var = tk.StringVar(value="Auto (first available)")
        slot_ui.device_combo = ttk.Combobox(dev_frame, textvariable=slot_ui.device_var,
                                            state='readonly')
        slot_ui.device_combo['values'] = ["Auto (first available)"]
        slot_ui.device_combo.grid(row=0, column=1, sticky=(tk.W, tk.E))
        slot_ui.device_paths = [None]

        # Auto-connect checkbox (USB-only feature, same var across all tabs)
        ttk.Checkbutton(frame, text="Auto-connect at startup",
                        variable=self.auto_connect_var).grid(
                            row=2, column=0, pady=(5, 0), sticky=tk.W)

    def _build_ble_section(self, parent, index, slot_ui, on_pair):
        """Build the Bluetooth section."""
        frame = ttk.LabelFrame(parent, text="Bluetooth", padding="5")
        frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=3)
        frame.columnconfigure(0, weight=1)

        if self._ble_available and on_pair:
            slot_ui.pair_btn = ttk.Button(
                frame, text="Pair Controller",
                command=lambda i=index: on_pair(i))
            slot_ui.pair_btn.grid(row=0, column=0, sticky=tk.W)
        else:
            ttk.Label(frame, text="Not available",
                      foreground='gray').grid(row=0, column=0, sticky=tk.W)


    def _build_emu_section(self, parent, index, slot_ui, on_emulate):
        """Build the Emulation section."""
        frame = ttk.LabelFrame(parent, text="Emulation", padding="5")
        frame.grid(row=0, column=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(3, 0))
        frame.columnconfigure(0, weight=1)

        slot_ui.emulate_btn = ttk.Button(
            frame, text="Start Emulation",
            command=lambda i=index: on_emulate(i), state='disabled')
        slot_ui.emulate_btn.grid(row=0, column=0, sticky=tk.W)

        # Emulation mode radios
        xbox_state = 'disabled' if IS_MACOS else 'normal'
        ttk.Radiobutton(frame, text="Xbox 360",
                        variable=slot_ui.emu_mode_var, value='xbox360',
                        state=xbox_state).grid(row=1, column=0, sticky=tk.W)
        ttk.Radiobutton(frame, text="Dolphin (Named Pipe)",
                        variable=slot_ui.emu_mode_var, value='dolphin_pipe').grid(
                            row=2, column=0, sticky=tk.W)


    # ── Device selector helpers ─────────────────────────────────────

    def set_device_list(self, slot_index: int, device_entries: list,
                        claimed_map: Dict[bytes, int]):
        """Update the device dropdown for a slot.

        device_entries: list of HID device info dicts (from hid.enumerate)
        claimed_map: {path_bytes: slot_index} for currently connected slots
        """
        s = self.slots[slot_index]
        values = ["Auto (first available)"]
        paths = [None]

        for dev in device_entries:
            path = dev['path']
            path_str = path.decode('utf-8', errors='replace')
            claimed_by = claimed_map.get(path)
            if claimed_by is not None and claimed_by != slot_index:
                label = f"{path_str}  [Slot {claimed_by + 1}]"
            elif claimed_by == slot_index:
                label = f"{path_str}  [Connected]"
            else:
                label = path_str
            values.append(label)
            paths.append(path)

        # Preserve current selection if still valid
        prev_path = self.get_selected_device_path(slot_index)
        s.device_combo['values'] = values
        s.device_paths = paths

        # Try to re-select the previously selected path
        if prev_path is not None and prev_path in paths:
            idx = paths.index(prev_path)
            s.device_var.set(values[idx])
        else:
            s.device_var.set(values[0])

    def get_selected_device_path(self, slot_index: int) -> Optional[bytes]:
        """Return the device path selected in the dropdown, or None for Auto."""
        s = self.slots[slot_index]
        if not s.device_paths:
            return None
        current = s.device_var.get()
        values = list(s.device_combo['values'])
        if current in values:
            idx = values.index(current)
            if idx < len(s.device_paths):
                return s.device_paths[idx]
        return None

    def select_device_by_path(self, slot_index: int, path: bytes):
        """Select a specific device path in the dropdown, if present."""
        s = self.slots[slot_index]
        if path in s.device_paths:
            idx = s.device_paths.index(path)
            values = list(s.device_combo['values'])
            if idx < len(values):
                s.device_var.set(values[idx])

    # ── Stick canvas helpers ─────────────────────────────────────────

    def _init_stick_canvas(self, canvas, dot, side, slot_index):
        """Draw dashed circle outline and octagon on a stick canvas, raise dot to top."""
        canvas.create_oval(10, 10, 70, 70, outline='#999999', dash=(3, 3), tag='circle')
        self._draw_octagon(canvas, side, slot_index)
        canvas.tag_raise(dot)

    def _draw_octagon(self, canvas, side, slot_index):
        """Draw/redraw the octagon polygon from calibration data on a stick canvas."""
        canvas.delete('octagon')
        cal = self._slot_calibrations[slot_index]
        cal_key = f'stick_{side}_octagon'
        octagon_data = cal.get(cal_key)

        center = 40
        radius = 30

        if octagon_data:
            coords = []
            for x_norm, y_norm in octagon_data:
                coords.append(center + x_norm * radius)
                coords.append(center - y_norm * radius)
        else:
            coords = []
            for i in range(8):
                angle = math.radians(i * 45)
                coords.append(center + math.cos(angle) * radius)
                coords.append(center - math.sin(angle) * radius)

        canvas.create_polygon(coords, outline='#666666', fill='', width=2, tag='octagon')

    def draw_octagon_live(self, slot_index: int, side: str):
        """Redraw octagon from in-progress calibration data."""
        s = self.slots[slot_index]
        if side == 'left':
            canvas, dot = s.left_stick_canvas, s.left_stick_dot
        else:
            canvas, dot = s.right_stick_canvas, s.right_stick_dot

        canvas.delete('octagon')

        cal_mgr = self._slot_cal_mgrs[slot_index]
        dists, points, cx, rx, cy, ry = cal_mgr.get_live_octagon_data(side)

        center = 40
        radius = 30

        coords = []
        for i in range(8):
            dist = dists[i]
            if dist > 0:
                raw_x, raw_y = points[i]
                x_norm = normalize(raw_x, cx, rx)
                y_norm = normalize(raw_y, cy, ry)
            else:
                x_norm = 0.0
                y_norm = 0.0
            coords.append(center + x_norm * radius)
            coords.append(center - y_norm * radius)

        canvas.create_polygon(coords, outline='#00aa00', fill='', width=2, tag='octagon')
        canvas.tag_raise(dot)

    # ── UI update methods ────────────────────────────────────────────

    def update_stick_position(self, canvas, dot, x_norm, y_norm):
        """Update analog stick position on canvas."""
        x_norm = max(-1, min(1, x_norm))
        y_norm = max(-1, min(1, y_norm))

        center_x, center_y = 40, 40
        x_pos = center_x + (x_norm * 30)
        y_pos = center_y - (y_norm * 30)

        canvas.coords(dot, x_pos - 3, y_pos - 3, x_pos + 3, y_pos + 3)

    def update_trigger_display(self, slot_index: int, left_trigger, right_trigger):
        """Update trigger canvas bars and labels for a specific slot."""
        s = self.slots[slot_index]
        w = self._trigger_bar_width
        h = self._trigger_bar_height

        for canvas, raw in [(s.left_trigger_canvas, left_trigger),
                            (s.right_trigger_canvas, right_trigger)]:
            canvas.delete('fill')
            fill_x = (raw / 255.0) * w
            if fill_x > 0:
                canvas.create_rectangle(0, 0, fill_x, h, fill='#06b025',
                                        outline='', tag='fill')
            canvas.tag_raise('bump_line')
            canvas.tag_raise('max_line')

        s.left_trigger_label.config(text=str(left_trigger))
        s.right_trigger_label.config(text=str(right_trigger))

    def update_button_display(self, slot_index: int, button_states: Dict[str, bool]):
        """Update button indicators for a specific slot."""
        s = self.slots[slot_index]

        for label in s.button_labels.values():
            label.config(relief='raised', background='')
        for label in s.dpad_labels.values():
            label.config(relief='raised', background='')

        for button_name, pressed in button_states.items():
            if pressed:
                if button_name in s.button_labels:
                    s.button_labels[button_name].config(relief='sunken', background='lightgreen')
                elif button_name.startswith("Dpad "):
                    direction = button_name.split(" ")[1]
                    if direction in s.dpad_labels:
                        s.dpad_labels[direction].config(relief='sunken', background='lightgreen')

    def _draw_trigger_markers(self, slot_index: int):
        """Draw bump and max calibration marker lines on both trigger canvases."""
        s = self.slots[slot_index] if slot_index < len(self.slots) else None
        cal = self._slot_calibrations[slot_index]
        w = self._trigger_bar_width
        h = self._trigger_bar_height

        # During initial setup, slot_ui may not be in the list yet;
        # called from _build_tab where we can access the canvas directly.
        if s is None:
            return

        for canvas, side in [(s.left_trigger_canvas, 'left'),
                             (s.right_trigger_canvas, 'right')]:
            canvas.delete('bump_line')
            canvas.delete('max_line')

            bump = cal[f'trigger_{side}_bump']
            max_val = cal[f'trigger_{side}_max']

            bump_x = (bump / 255.0) * w
            max_x = (max_val / 255.0) * w

            canvas.create_line(bump_x, 0, bump_x, h, fill='#e6a800',
                               width=2, tag='bump_line')
            canvas.create_line(max_x, 0, max_x, h, fill='#cc0000',
                               width=2, tag='max_line')

    def draw_trigger_markers(self, slot_index: int):
        """Public wrapper for redrawing trigger markers."""
        self._draw_trigger_markers(slot_index)

    # ── Tab status / dirty tracking ──────────────────────────────────

    def update_tab_status(self, slot_index: int, connected: bool, emulating: bool):
        """Update stored connection/emulation state and refresh tab title."""
        self._slot_connected[slot_index] = connected
        self._slot_emulating[slot_index] = emulating
        self._refresh_tab_title(slot_index)

    def _refresh_tab_title(self, slot_index: int):
        """Rebuild tab title from connection, emulation, and dirty state."""
        base = f"Controller {slot_index + 1}"
        if self._slot_emulating[slot_index]:
            suffix = " [EMU]"
        elif self._slot_connected[slot_index]:
            suffix = " [ON]"
        else:
            suffix = ""
        dirty = " *" if self._slot_dirty[slot_index] else ""
        self.notebook.tab(slot_index, text=base + suffix + dirty)

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

        for label in s.button_labels.values():
            label.config(relief='raised', background='')
        for label in s.dpad_labels.values():
            label.config(relief='raised', background='')

        s.left_stick_canvas.coords(s.left_stick_dot, 37, 37, 43, 43)
        s.right_stick_canvas.coords(s.right_stick_dot, 37, 37, 43, 43)

        self._draw_octagon(s.left_stick_canvas, 'left', slot_index)
        s.left_stick_canvas.tag_raise(s.left_stick_dot)
        self._draw_octagon(s.right_stick_canvas, 'right', slot_index)
        s.right_stick_canvas.tag_raise(s.right_stick_dot)

        s.left_trigger_canvas.delete('fill')
        s.right_trigger_canvas.delete('fill')
        self._draw_trigger_markers(slot_index)
        s.left_trigger_label.config(text="0")
        s.right_trigger_label.config(text="0")


    def redraw_octagons(self, slot_index: int):
        """Redraw both octagon polygons from calibration data for a slot."""
        s = self.slots[slot_index]
        self._draw_octagon(s.left_stick_canvas, 'left', slot_index)
        s.left_stick_canvas.tag_raise(s.left_stick_dot)
        self._draw_octagon(s.right_stick_canvas, 'right', slot_index)
        s.right_stick_canvas.tag_raise(s.right_stick_dot)

    # ── Status helpers ───────────────────────────────────────────────

    def update_status(self, slot_index: int, message: str):
        """Update the shared status label for a specific slot."""
        s = self.slots[slot_index]
        if s.status_label is not None:
            s.status_label.config(text=message)

    def update_ble_status(self, slot_index: int, message: str):
        """Update status with a BLE message."""
        self.update_status(slot_index, message)

    def update_emu_status(self, slot_index: int, message: str):
        """Update status with an emulation message."""
        self.update_status(slot_index, message)
