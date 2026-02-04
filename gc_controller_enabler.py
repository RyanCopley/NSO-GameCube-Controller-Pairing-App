#!/usr/bin/env python3
"""
GameCube Controller Enabler - Python/Tkinter Version

Converts GameCube controllers to work with Steam and other applications.
Handles USB initialization, HID communication, and Xbox 360 controller emulation.

Requirements:
    pip install hidapi pyusb
    
Note: Windows users need ViGEmBus driver for Xbox 360 emulation
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
import os
from typing import Optional, Dict, Any
import math
import sys

try:
    import hid
    import usb.core
    import usb.util
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install hidapi pyusb")
    sys.exit(1)

# Virtual gamepad platform abstraction (Xbox 360 emulation)
from virtual_gamepad import (
    GamepadButton, VirtualGamepad, create_gamepad,
    is_emulation_available, get_emulation_unavailable_reason,
)
EMULATION_AVAILABLE = is_emulation_available()
if not EMULATION_AVAILABLE:
    print("Xbox 360 emulation unavailable: " + get_emulation_unavailable_reason())


class ButtonInfo:
    """Represents a GameCube controller button mapping"""
    def __init__(self, byte_index: int, mask: int, name: str):
        self.byte_index = byte_index
        self.mask = mask
        self.name = name


class GCControllerEnabler:
    """Main application class for GameCube Controller Enabler"""
    
    # GameCube controller USB IDs
    VENDOR_ID = 0x057e
    PRODUCT_ID = 0x2073
    
    # USB initialization commands
    DEFAULT_REPORT_DATA = bytes([0x03, 0x91, 0x00, 0x0d, 0x00, 0x08,
                                0x00, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    SET_LED_DATA = bytes([0x09, 0x91, 0x00, 0x07, 0x00, 0x08,
                         0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GameCube Controller Enabler")
        self.root.resizable(False, False)
        
        # Controller state
        self.device: Optional[hid.device] = None
        self.is_reading = False
        self.is_emulating = False
        self.read_thread: Optional[threading.Thread] = None
        self.emulation_thread: Optional[threading.Thread] = None
        self.stop_reading = threading.Event()
        self.stop_emulation = threading.Event()
        
        # Xbox 360 emulation
        self.gamepad: Optional[VirtualGamepad] = None
        
        # Button mapping for GameCube controller
        self.buttons = [
            ButtonInfo(3, 0x01, "B"),
            ButtonInfo(3, 0x02, "A"), 
            ButtonInfo(3, 0x04, "Y"),
            ButtonInfo(3, 0x08, "X"),
            ButtonInfo(3, 0x10, "R"),
            ButtonInfo(3, 0x20, "Z"),
            ButtonInfo(3, 0x40, "Start/Pause"),
            ButtonInfo(4, 0x01, "Dpad Down"),
            ButtonInfo(4, 0x02, "Dpad Right"),
            ButtonInfo(4, 0x04, "Dpad Left"),
            ButtonInfo(4, 0x08, "Dpad Up"),
            ButtonInfo(4, 0x10, "L"),
            ButtonInfo(4, 0x20, "ZL"),
            ButtonInfo(5, 0x01, "Home"),
            ButtonInfo(5, 0x02, "Capture"),
            ButtonInfo(5, 0x04, "GR"),
            ButtonInfo(5, 0x08, "GL"),
            ButtonInfo(5, 0x10, "Chat"),
        ]
        
        # Calibration values
        self.calibration = {
            'left_base': 32.0,
            'left_bump': 190.0,
            'left_max': 230.0,
            'right_base': 32.0,
            'right_bump': 190.0,
            'right_max': 230.0,
            'bump_100_percent': False,
            'emulation_mode': 'xbox360',
            'stick_left_center_x': 2048, 'stick_left_range_x': 2048,
            'stick_left_center_y': 2048, 'stick_left_range_y': 2048,
            'stick_right_center_x': 2048, 'stick_right_range_x': 2048,
            'stick_right_center_y': 2048, 'stick_right_range_y': 2048,
            'auto_connect': False,
            'stick_left_octagon': None,
            'stick_right_octagon': None,
        }

        # UI throttling
        self._ui_update_counter = 0

        # Stick calibration state
        self.stick_calibrating = False
        self.stick_cal_min = {}
        self.stick_cal_max = {}
        self.stick_cal_octagon_points = {'left': [(0, 0)] * 8, 'right': [(0, 0)] * 8}
        self.stick_cal_octagon_dists = {'left': [0.0] * 8, 'right': [0.0] * 8}

        # Trigger calibration wizard state
        self.trigger_cal_step = 0
        self.trigger_cal_last_left = 0
        self.trigger_cal_last_right = 0

        self.load_settings()
        self.setup_ui()
        
        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Auto-connect if enabled
        if self.calibration['auto_connect']:
            self.root.after(100, self.auto_connect_and_emulate)
    
    def setup_ui(self):
        """Create the user interface"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Connection section
        connection_frame = ttk.LabelFrame(main_frame, text="Connection", padding="10")
        connection_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.connect_btn = ttk.Button(connection_frame, text="Connect", command=self.connect_controller)
        self.connect_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.emulate_btn = ttk.Button(connection_frame, text="Emulate Xbox 360",
                                     command=self.start_emulation, state='disabled')
        self.emulate_btn.grid(row=0, column=1)

        if not EMULATION_AVAILABLE:
            self.emulate_btn.config(state='disabled', text="Emulation Unavailable")

        self.auto_connect_var = tk.BooleanVar(value=self.calibration['auto_connect'])
        ttk.Checkbutton(connection_frame, text="Connect and Emulate at startup",
                        variable=self.auto_connect_var).grid(row=0, column=2, padx=(10, 0))

        # Progress bar
        self.progress = ttk.Progressbar(connection_frame, length=300, mode='determinate')
        self.progress.grid(row=1, column=0, columnspan=3, pady=(10, 0), sticky=(tk.W, tk.E))

        # Status label
        self.status_label = ttk.Label(connection_frame, text="Ready to connect")
        self.status_label.grid(row=2, column=0, columnspan=3, pady=(5, 0))
        
        # Left column container to stack Button Configuration + Analog Sticks
        left_column = ttk.Frame(main_frame)
        left_column.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N), padx=(0, 10))

        # Button visualization
        controller_frame = ttk.LabelFrame(left_column, text="Button Configuration", padding="10")
        controller_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        # Button indicators
        buttons_frame = ttk.Frame(controller_frame)
        buttons_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        self.button_labels = {}
        button_names = ["A", "B", "X", "Y", "L", "R", "Z", "ZL", "Start/Pause", "Home", "Capture", "Chat"]

        for i, btn_name in enumerate(button_names):
            row = i // 4
            col = i % 4
            label = ttk.Label(buttons_frame, text=btn_name, width=8, relief='raised')
            label.grid(row=row, column=col, padx=2, pady=2)
            self.button_labels[btn_name] = label

        # D-pad
        dpad_frame = ttk.LabelFrame(buttons_frame, text="D-Pad")
        dpad_frame.grid(row=3, column=0, columnspan=4, pady=(10, 0))

        self.dpad_labels = {}
        for direction in ["Up", "Down", "Left", "Right"]:
            label = ttk.Label(dpad_frame, text=direction, width=6, relief='raised')
            self.dpad_labels[direction] = label

        self.dpad_labels["Up"].grid(row=0, column=1)
        self.dpad_labels["Left"].grid(row=1, column=0)
        self.dpad_labels["Right"].grid(row=1, column=2)
        self.dpad_labels["Down"].grid(row=2, column=1)

        # Analog sticks visualization
        sticks_frame = ttk.LabelFrame(left_column, text="Analog Sticks", padding="10")
        sticks_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

        # Right column container to stack Analog Triggers + Emulation Mode + Save
        right_column = ttk.Frame(main_frame)
        right_column.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N))

        # Analog triggers section
        calibration_frame = ttk.LabelFrame(right_column, text="Analog Triggers", padding="10")
        calibration_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        # Left stick
        left_stick_frame = ttk.Frame(sticks_frame)
        left_stick_frame.grid(row=0, column=0, padx=10)
        ttk.Label(left_stick_frame, text="Left Stick").grid(row=0, column=0)
        self.left_stick_canvas = tk.Canvas(left_stick_frame, width=80, height=80, bg='lightgray')
        self.left_stick_canvas.grid(row=1, column=0)
        self.left_stick_dot = self.left_stick_canvas.create_oval(37, 37, 43, 43, fill='red')
        self._init_stick_canvas(self.left_stick_canvas, self.left_stick_dot, 'left')

        # Right stick
        right_stick_frame = ttk.Frame(sticks_frame)
        right_stick_frame.grid(row=0, column=1, padx=10)
        ttk.Label(right_stick_frame, text="Right Stick").grid(row=0, column=0)
        self.right_stick_canvas = tk.Canvas(right_stick_frame, width=80, height=80, bg='lightgray')
        self.right_stick_canvas.grid(row=1, column=0)
        self.right_stick_dot = self.right_stick_canvas.create_oval(37, 37, 43, 43, fill='red')
        self._init_stick_canvas(self.right_stick_canvas, self.right_stick_dot, 'right')

        # Stick calibration (inside Analog Sticks frame)
        stick_cal_frame = ttk.LabelFrame(sticks_frame, text="Calibration", padding="5")
        stick_cal_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky=(tk.W, tk.E))

        self.stick_cal_btn = ttk.Button(stick_cal_frame, text="Calibrate Sticks",
                                        command=self.toggle_stick_calibration)
        self.stick_cal_btn.grid(row=0, column=0, padx=5, pady=2)

        self.stick_cal_status = ttk.Label(stick_cal_frame, text="Using saved calibration")
        self.stick_cal_status.grid(row=0, column=1, padx=5, pady=2)

        # Trigger visualizers
        triggers_frame = ttk.Frame(calibration_frame)
        triggers_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        self._trigger_bar_width = 150
        self._trigger_bar_height = 20

        ttk.Label(triggers_frame, text="Left Trigger").grid(row=0, column=0)
        self.left_trigger_canvas = tk.Canvas(triggers_frame,
                                             width=self._trigger_bar_width,
                                             height=self._trigger_bar_height,
                                             bg='#e0e0e0', highlightthickness=1,
                                             highlightbackground='#999999')
        self.left_trigger_canvas.grid(row=0, column=1, padx=(5, 10))
        self.left_trigger_label = ttk.Label(triggers_frame, text="0")
        self.left_trigger_label.grid(row=0, column=2)

        ttk.Label(triggers_frame, text="Right Trigger").grid(row=1, column=0)
        self.right_trigger_canvas = tk.Canvas(triggers_frame,
                                              width=self._trigger_bar_width,
                                              height=self._trigger_bar_height,
                                              bg='#e0e0e0', highlightthickness=1,
                                              highlightbackground='#999999')
        self.right_trigger_canvas.grid(row=1, column=1, padx=(5, 10))
        self.right_trigger_label = ttk.Label(triggers_frame, text="0")
        self.right_trigger_label.grid(row=1, column=2)

        # Draw initial calibration markers
        self._draw_trigger_markers()

        # Trigger calibration wizard
        trigger_cal_frame = ttk.LabelFrame(calibration_frame, text="Calibration", padding="5")
        trigger_cal_frame.grid(row=1, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        self.trigger_cal_btn = ttk.Button(trigger_cal_frame, text="Calibrate Triggers",
                                          command=self.trigger_cal_next_step)
        self.trigger_cal_btn.grid(row=0, column=0, padx=5, pady=2)

        self.trigger_cal_status = ttk.Label(trigger_cal_frame, text="Using saved calibration")
        self.trigger_cal_status.grid(row=0, column=1, padx=5, pady=2)

        # Trigger mode
        mode_frame = ttk.LabelFrame(calibration_frame, text="Trigger Mode", padding="5")
        mode_frame.grid(row=2, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        self.trigger_mode_var = tk.BooleanVar(value=self.calibration['bump_100_percent'])
        ttk.Radiobutton(mode_frame, text="100% at bump",
                       variable=self.trigger_mode_var, value=True).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(mode_frame, text="100% at press",
                       variable=self.trigger_mode_var, value=False).grid(row=1, column=0, sticky=tk.W)

        # Emulation mode
        emu_frame = ttk.LabelFrame(right_column, text="Emulation Mode", padding="5")
        emu_frame.grid(row=1, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        self.emu_mode_var = tk.StringVar(value=self.calibration['emulation_mode'])
        ttk.Radiobutton(emu_frame, text="Xbox 360",
                       variable=self.emu_mode_var, value='xbox360').grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(emu_frame, text="DualShock (Not implemented)",
                       variable=self.emu_mode_var, value='dualshock', state='disabled').grid(row=1, column=0, sticky=tk.W)

        # Save settings button
        ttk.Button(right_column, text="Save Settings",
                  command=self.save_settings).grid(row=2, column=0, pady=(10, 0))
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
    
    def initialize_via_usb(self) -> bool:
        """Initialize controller via USB"""
        try:
            self.update_status("Looking for device...")
            self.progress['value'] = 10
            
            # Find USB device
            dev = usb.core.find(idVendor=self.VENDOR_ID, idProduct=self.PRODUCT_ID)
            if dev is None:
                self.update_status("Device not found")
                return False
            
            self.update_status("Device found")
            self.progress['value'] = 30
            
            # Set configuration
            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass  # May already be configured
            
            # Claim interface
            try:
                usb.util.claim_interface(dev, 1)
            except usb.core.USBError:
                pass  # May already be claimed
            
            self.progress['value'] = 50
            
            # Send initialization commands
            self.update_status("Sending initialization data...")
            dev.write(0x02, self.DEFAULT_REPORT_DATA, 2000)
            
            self.progress['value'] = 70
            
            self.update_status("Sending LED data...")
            dev.write(0x02, self.SET_LED_DATA, 2000)
            
            self.progress['value'] = 90
            
            # Release interface
            try:
                usb.util.release_interface(dev, 1)
            except usb.core.USBError:
                pass
            
            self.update_status("USB initialization complete")
            return True
            
        except Exception as e:
            self.update_status(f"USB initialization failed: {e}")
            return False
    
    def init_hid_device(self) -> bool:
        """Initialize HID connection"""
        try:
            self.update_status("Connecting via HID...")
            
            # Open HID device
            self.device = hid.device()
            self.device.open(self.VENDOR_ID, self.PRODUCT_ID)
            
            if self.device:
                self.update_status("Connected via HID")
                self.progress['value'] = 100
                return True
            else:
                self.update_status("Failed to connect via HID")
                return False
                
        except Exception as e:
            self.update_status(f"HID connection failed: {e}")
            return False
    
    def auto_connect_and_emulate(self):
        """Auto-connect and start emulation on startup"""
        self.connect_controller()
        if self.is_reading and EMULATION_AVAILABLE:
            self.start_emulation()

    def connect_controller(self):
        """Connect to GameCube controller"""
        if self.is_reading:
            self.disconnect_controller()
            return
        
        self.progress['value'] = 0
        
        # Initialize via USB first
        if not self.initialize_via_usb():
            return
        
        # Then connect via HID
        if not self.init_hid_device():
            return
        
        # Start reading input
        self.start_reading()
        
        self.connect_btn.config(text="Disconnect")
        if EMULATION_AVAILABLE:
            self.emulate_btn.config(state='normal')
    
    def disconnect_controller(self):
        """Disconnect from controller"""
        self.stop_reading_input()
        self.stop_xbox_emulation()
        
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
        
        self.connect_btn.config(text="Connect")
        self.emulate_btn.config(state='disabled')
        self.progress['value'] = 0
        self.update_status("Disconnected")
        
        # Reset UI elements
        self.reset_ui_elements()
    
    def start_reading(self):
        """Start reading controller input"""
        if self.is_reading:
            return
        
        self.is_reading = True
        self.stop_reading.clear()
        self.read_thread = threading.Thread(target=self.read_hid_loop, daemon=True)
        self.read_thread.start()
    
    def stop_reading_input(self):
        """Stop reading controller input"""
        if not self.is_reading:
            return
        
        self.is_reading = False
        self.stop_reading.set()
        
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=1.0)
    
    def read_hid_loop(self):
        """Main HID reading loop"""
        try:
            while self.is_reading and not self.stop_reading.is_set():
                if not self.device:
                    break
                
                try:
                    # Read data from controller with shorter timeout for better responsiveness
                    data = self.device.read(64, timeout_ms=10)
                    if data:
                        self.process_controller_data(data)
                    
                    # Small sleep to prevent excessive CPU usage
                    time.sleep(0.001)
                        
                except Exception as e:
                    if self.is_reading:  # Only show error if we're still trying to read
                        print(f"Read error: {e}")
                    break
                    
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"Read loop error: {e}"))
        finally:
            self.is_reading = False
    
    def process_controller_data(self, data: list):
        """Process raw controller data and update UI"""
        if len(data) < 15:
            return
        
        # Extract analog stick values
        left_stick_x = data[6] | ((data[7] & 0x0F) << 8)
        left_stick_y = ((data[7] >> 4) | (data[8] << 4))
        right_stick_x = data[9] | ((data[10] & 0x0F) << 8)
        right_stick_y = ((data[10] >> 4) | (data[11] << 4))

        # Track min/max during stick calibration
        if self.stick_calibrating:
            axes = {
                'left_x': left_stick_x, 'left_y': left_stick_y,
                'right_x': right_stick_x, 'right_y': right_stick_y,
            }
            for axis, val in axes.items():
                if self.stick_cal_min.get(axis) is None or val < self.stick_cal_min[axis]:
                    self.stick_cal_min[axis] = val
                if self.stick_cal_max.get(axis) is None or val > self.stick_cal_max[axis]:
                    self.stick_cal_max[axis] = val

            # Track octagon sectors per stick
            cal = self.calibration
            for side, raw_x, raw_y in [('left', left_stick_x, left_stick_y),
                                        ('right', right_stick_x, right_stick_y)]:
                cx = cal[f'stick_{side}_center_x']
                cy = cal[f'stick_{side}_center_y']
                dx = raw_x - cx
                dy = raw_y - cy
                dist = math.hypot(dx, dy)
                if dist > 0:
                    angle_deg = math.degrees(math.atan2(dy, dx)) % 360
                    sector = round(angle_deg / 45) % 8
                    if dist > self.stick_cal_octagon_dists[side][sector]:
                        self.stick_cal_octagon_dists[side][sector] = dist
                        self.stick_cal_octagon_points[side][sector] = (raw_x, raw_y)

        # Normalize stick values (-1 to 1) using calibration
        cal = self.calibration
        left_x_norm = max(-1.0, min(1.0, (left_stick_x - cal['stick_left_center_x']) / max(cal['stick_left_range_x'], 1)))
        left_y_norm = max(-1.0, min(1.0, (left_stick_y - cal['stick_left_center_y']) / max(cal['stick_left_range_y'], 1)))
        right_x_norm = max(-1.0, min(1.0, (right_stick_x - cal['stick_right_center_x']) / max(cal['stick_right_range_x'], 1)))
        right_y_norm = max(-1.0, min(1.0, (right_stick_y - cal['stick_right_center_y']) / max(cal['stick_right_range_y'], 1)))
        
        # Process buttons first (most important for responsiveness)
        button_states = {}
        for button in self.buttons:
            if len(data) > button.byte_index:
                pressed = (data[button.byte_index] & button.mask) != 0
                button_states[button.name] = pressed
        
        # Extract trigger values
        left_trigger = data[13] if len(data) > 13 else 0
        right_trigger = data[14] if len(data) > 14 else 0

        # Store latest raw values for trigger calibration wizard
        self.trigger_cal_last_left = left_trigger
        self.trigger_cal_last_right = right_trigger
        
        # If emulating, prioritize sending to virtual controller (reduce lag)
        if self.is_emulating and self.gamepad:
            self.update_virtual_controller(left_x_norm, left_y_norm, right_x_norm, right_y_norm,
                                         left_trigger, right_trigger, button_states)
        
        # Update UI less frequently to reduce lag
        self._ui_update_counter += 1
        
        # Only update UI every 3rd frame to reduce lag
        if self._ui_update_counter % 3 == 0:
            self.root.after(0, lambda: self.update_stick_position(
                self.left_stick_canvas, self.left_stick_dot, left_x_norm, left_y_norm))
            self.root.after(0, lambda: self.update_stick_position(
                self.right_stick_canvas, self.right_stick_dot, right_x_norm, right_y_norm))
            self.root.after(0, lambda: self.update_trigger_display(left_trigger, right_trigger))
            self.root.after(0, lambda: self.update_button_display(button_states))

            # Live octagon preview during calibration
            if self.stick_calibrating:
                self.root.after(0, lambda: self._draw_octagon_live(
                    self.left_stick_canvas, self.left_stick_dot, 'left'))
                self.root.after(0, lambda: self._draw_octagon_live(
                    self.right_stick_canvas, self.right_stick_dot, 'right'))
        
    
    def update_stick_position(self, canvas, dot, x_norm, y_norm):
        """Update analog stick position on canvas"""
        # Clamp values
        x_norm = max(-1, min(1, x_norm))
        y_norm = max(-1, min(1, y_norm))
        
        # Convert to canvas coordinates
        center_x, center_y = 40, 40
        x_pos = center_x + (x_norm * 30)
        y_pos = center_y - (y_norm * 30)  # Invert Y axis
        
        # Update dot position
        canvas.coords(dot, x_pos-3, y_pos-3, x_pos+3, y_pos+3)
    
    def _init_stick_canvas(self, canvas, dot, side):
        """Draw dashed circle outline and octagon on a stick canvas, raise dot to top"""
        canvas.create_oval(10, 10, 70, 70, outline='#999999', dash=(3, 3), tag='circle')
        self._draw_octagon(canvas, side)
        canvas.tag_raise(dot)

    def _draw_octagon(self, canvas, side):
        """Draw/redraw the octagon polygon from calibration data on a stick canvas"""
        canvas.delete('octagon')
        cal_key = f'stick_{side}_octagon'
        octagon_data = self.calibration.get(cal_key)

        center = 40
        radius = 30  # matches the stick movement range

        if octagon_data:
            # Use calibrated octagon points (each is [x_norm, y_norm] in -1..1)
            coords = []
            for x_norm, y_norm in octagon_data:
                coords.append(center + x_norm * radius)
                coords.append(center - y_norm * radius)  # invert Y
        else:
            # Default regular octagon at full range
            coords = []
            for i in range(8):
                angle = math.radians(i * 45)
                coords.append(center + math.cos(angle) * radius)
                coords.append(center - math.sin(angle) * radius)

        canvas.create_polygon(coords, outline='#666666', fill='', width=2, tag='octagon')

    def _draw_octagon_live(self, canvas, dot, side):
        """Redraw octagon from in-progress calibration data (raw tracking points)"""
        canvas.delete('octagon')

        # Compute temporary center/range from in-progress min/max,
        # matching what finish_stick_calibration will produce
        mn_x = self.stick_cal_min.get(f'{side}_x')
        mx_x = self.stick_cal_max.get(f'{side}_x')
        mn_y = self.stick_cal_min.get(f'{side}_y')
        mx_y = self.stick_cal_max.get(f'{side}_y')

        if mn_x is not None and mx_x is not None and mx_x > mn_x:
            cx = (mn_x + mx_x) / 2.0
            rx = (mx_x - mn_x) / 2.0
        else:
            cx = self.calibration[f'stick_{side}_center_x']
            rx = max(self.calibration[f'stick_{side}_range_x'], 1)

        if mn_y is not None and mx_y is not None and mx_y > mn_y:
            cy = (mn_y + mx_y) / 2.0
            ry = (mx_y - mn_y) / 2.0
        else:
            cy = self.calibration[f'stick_{side}_center_y']
            ry = max(self.calibration[f'stick_{side}_range_y'], 1)

        center = 40
        radius = 30

        coords = []
        for i in range(8):
            dist = self.stick_cal_octagon_dists[side][i]
            if dist > 0:
                raw_x, raw_y = self.stick_cal_octagon_points[side][i]
                x_norm = max(-1.0, min(1.0, (raw_x - cx) / rx))
                y_norm = max(-1.0, min(1.0, (raw_y - cy) / ry))
            else:
                # No data yet for this sector — draw at center (zero)
                x_norm = 0.0
                y_norm = 0.0
            coords.append(center + x_norm * radius)
            coords.append(center - y_norm * radius)

        canvas.create_polygon(coords, outline='#00aa00', fill='', width=2, tag='octagon')
        canvas.tag_raise(dot)

    def update_trigger_display(self, left_trigger, right_trigger):
        """Update trigger canvas bars and labels"""
        w = self._trigger_bar_width
        h = self._trigger_bar_height

        for canvas, raw in [(self.left_trigger_canvas, left_trigger),
                            (self.right_trigger_canvas, right_trigger)]:
            canvas.delete('fill')
            fill_x = (raw / 255.0) * w
            if fill_x > 0:
                canvas.create_rectangle(0, 0, fill_x, h, fill='#06b025',
                                        outline='', tag='fill')
            # Keep markers on top
            canvas.tag_raise('bump_line')
            canvas.tag_raise('max_line')

        self.left_trigger_label.config(text=str(left_trigger))
        self.right_trigger_label.config(text=str(right_trigger))

    def _draw_trigger_markers(self):
        """Draw bump and max calibration marker lines on both trigger canvases"""
        w = self._trigger_bar_width
        h = self._trigger_bar_height
        cal = self.calibration

        for canvas, side in [(self.left_trigger_canvas, 'left'),
                             (self.right_trigger_canvas, 'right')]:
            canvas.delete('bump_line')
            canvas.delete('max_line')

            bump = cal[f'{side}_bump']
            max_val = cal[f'{side}_max']

            bump_x = (bump / 255.0) * w
            max_x = (max_val / 255.0) * w

            canvas.create_line(bump_x, 0, bump_x, h, fill='#e6a800',
                               width=2, tag='bump_line')
            canvas.create_line(max_x, 0, max_x, h, fill='#cc0000',
                               width=2, tag='max_line')
    
    def update_button_display(self, button_states: Dict[str, bool]):
        """Update button indicators"""
        # Reset all buttons
        for label in self.button_labels.values():
            label.config(relief='raised', background='')
        for label in self.dpad_labels.values():
            label.config(relief='raised', background='')
        
        # Update pressed buttons
        for button_name, pressed in button_states.items():
            if pressed:
                if button_name in self.button_labels:
                    self.button_labels[button_name].config(relief='sunken', background='lightgreen')
                elif button_name.startswith("Dpad "):
                    direction = button_name.split(" ")[1]
                    if direction in self.dpad_labels:
                        self.dpad_labels[direction].config(relief='sunken', background='lightgreen')
    
    def start_emulation(self):
        """Start Xbox 360 controller emulation"""
        if not EMULATION_AVAILABLE:
            messagebox.showerror("Error", "Xbox 360 emulation not available.\n" + get_emulation_unavailable_reason())
            return
        
        if self.is_emulating:
            self.stop_xbox_emulation()
            return
        
        try:
            self.gamepad = create_gamepad()
            self.is_emulating = True
            self.stop_emulation.clear()
            
            self.emulate_btn.config(text="Stop Emulation")
            self.update_status("Xbox 360 emulation active")
            
        except Exception as e:
            messagebox.showerror("Emulation Error", f"Failed to start emulation: {e}")
    
    def stop_xbox_emulation(self):
        """Stop Xbox 360 controller emulation"""
        if not self.is_emulating:
            return
        
        self.is_emulating = False
        self.stop_emulation.set()
        
        if self.gamepad:
            try:
                self.gamepad.close()
            except Exception:
                pass
            self.gamepad = None
        
        self.emulate_btn.config(text="Emulate Xbox 360")
        if self.is_reading:
            self.update_status("Connected via HID")
        else:
            self.update_status("Ready to connect")
    
    def update_virtual_controller(self, left_x, left_y, right_x, right_y, 
                                 left_trigger, right_trigger, button_states):
        """Update virtual Xbox 360 controller state"""
        if not self.gamepad:
            return
        
        try:
            # Set analog sticks (optimize by avoiding function calls)
            stick_scale = 32767
            left_x_scaled = int(max(-32767, min(32767, left_x * stick_scale)))
            left_y_scaled = int(max(-32767, min(32767, left_y * stick_scale)))
            right_x_scaled = int(max(-32767, min(32767, right_x * stick_scale)))
            right_y_scaled = int(max(-32767, min(32767, right_y * stick_scale)))
            
            self.gamepad.left_joystick(x_value=left_x_scaled, y_value=left_y_scaled)
            self.gamepad.right_joystick(x_value=right_x_scaled, y_value=right_y_scaled)
            
            # Process analog triggers with calibration (cache calibration values)
            if not hasattr(self, '_cached_calibration'):
                self._cached_calibration = self.calibration.copy()
            
            left_trigger_calibrated = self.calibrate_trigger_fast(left_trigger, 'left')
            right_trigger_calibrated = self.calibrate_trigger_fast(right_trigger, 'right')
            
            # Map buttons
            button_mapping = {
                'A': GamepadButton.A,
                'B': GamepadButton.B,
                'X': GamepadButton.X,
                'Y': GamepadButton.Y,
                'Z': GamepadButton.RIGHT_SHOULDER,
                'ZL': GamepadButton.LEFT_SHOULDER,
                'Start/Pause': GamepadButton.START,
                'Home': GamepadButton.GUIDE,
                'Capture': GamepadButton.BACK,
                'Chat': GamepadButton.BACK,
                'Dpad Up': GamepadButton.DPAD_UP,
                'Dpad Down': GamepadButton.DPAD_DOWN,
                'Dpad Left': GamepadButton.DPAD_LEFT,
                'Dpad Right': GamepadButton.DPAD_RIGHT,
            }
            
            # Update button states
            for button_name, xbox_button in button_mapping.items():
                pressed = button_states.get(button_name, False)
                if pressed:
                    self.gamepad.press_button(xbox_button)
                else:
                    self.gamepad.release_button(xbox_button)
            
            # Handle shoulder buttons and triggers
            l_pressed = button_states.get('L', False)
            r_pressed = button_states.get('R', False)
            
            if l_pressed:
                self.gamepad.left_trigger(255)
            else:
                self.gamepad.left_trigger(left_trigger_calibrated)
            
            if r_pressed:
                self.gamepad.right_trigger(255)
            else:
                self.gamepad.right_trigger(right_trigger_calibrated)
            
            # Update the virtual controller
            self.gamepad.update()
            
        except Exception as e:
            print(f"Virtual controller update error: {e}")
    
    def calibrate_trigger_fast(self, raw_value: int, side: str) -> int:
        """Fast trigger calibration using cached values"""
        base = self._cached_calibration[f'{side}_base']
        bump = self._cached_calibration[f'{side}_bump']
        max_val = self._cached_calibration[f'{side}_max']
        
        calibrated = raw_value - base
        if calibrated < 0:
            calibrated = 0
        
        if self._cached_calibration['bump_100_percent']:
            range_val = bump - base
        else:
            range_val = max_val - base
        
        if range_val <= 0:
            return 0
        
        result = int((calibrated / range_val) * 255)
        return max(0, min(255, result))
    
    def toggle_stick_calibration(self):
        """Toggle stick calibration on/off"""
        if self.stick_calibrating:
            self.finish_stick_calibration()
        else:
            self.start_stick_calibration()

    def start_stick_calibration(self):
        """Begin stick calibration - start tracking extremes"""
        self.stick_cal_min = {'left_x': None, 'left_y': None, 'right_x': None, 'right_y': None}
        self.stick_cal_max = {'left_x': None, 'left_y': None, 'right_x': None, 'right_y': None}
        self.stick_cal_octagon_points = {'left': [(0, 0)] * 8, 'right': [(0, 0)] * 8}
        self.stick_cal_octagon_dists = {'left': [0.0] * 8, 'right': [0.0] * 8}
        self.stick_calibrating = True
        self.stick_cal_btn.config(text="Finish Calibration")
        self.stick_cal_status.config(text="Move sticks to all extremes...")

    def finish_stick_calibration(self):
        """Finish stick calibration - compute center and range"""
        self.stick_calibrating = False

        axis_map = {
            'left_x': ('stick_left_center_x', 'stick_left_range_x'),
            'left_y': ('stick_left_center_y', 'stick_left_range_y'),
            'right_x': ('stick_right_center_x', 'stick_right_range_x'),
            'right_y': ('stick_right_center_y', 'stick_right_range_y'),
        }

        for axis, (center_key, range_key) in axis_map.items():
            mn = self.stick_cal_min.get(axis)
            mx = self.stick_cal_max.get(axis)
            if mn is not None and mx is not None and mx > mn:
                self.calibration[center_key] = (mn + mx) / 2.0
                self.calibration[range_key] = (mx - mn) / 2.0

        # Compute normalized octagon points for each stick
        cal = self.calibration
        for side in ('left', 'right'):
            cx = cal[f'stick_{side}_center_x']
            rx = max(cal[f'stick_{side}_range_x'], 1)
            cy = cal[f'stick_{side}_center_y']
            ry = max(cal[f'stick_{side}_range_y'], 1)

            octagon = []
            for i in range(8):
                raw_x, raw_y = self.stick_cal_octagon_points[side][i]
                dist = self.stick_cal_octagon_dists[side][i]
                if dist > 0:
                    x_norm = max(-1.0, min(1.0, (raw_x - cx) / rx))
                    y_norm = max(-1.0, min(1.0, (raw_y - cy) / ry))
                else:
                    # No data for this sector — use default regular octagon vertex
                    angle = math.radians(i * 45)
                    x_norm = math.cos(angle)
                    y_norm = math.sin(angle)
                octagon.append([x_norm, y_norm])

            cal[f'stick_{side}_octagon'] = octagon

        # Update cached calibration
        self._cached_calibration = self.calibration.copy()

        # Redraw octagons on canvases
        self._draw_octagon(self.left_stick_canvas, 'left')
        self.left_stick_canvas.tag_raise(self.left_stick_dot)
        self._draw_octagon(self.right_stick_canvas, 'right')
        self.right_stick_canvas.tag_raise(self.right_stick_dot)

        self.stick_cal_btn.config(text="Calibrate Sticks")
        self.stick_cal_status.config(text="Calibration complete!")

    def trigger_cal_next_step(self):
        """Advance the trigger calibration wizard one step"""
        step = self.trigger_cal_step

        if step == 0:
            # Start wizard: prompt user to release triggers
            self.trigger_cal_step = 1
            self.trigger_cal_btn.config(text="Record Unpressed")
            self.trigger_cal_status.config(text="Release both triggers, then click Record Unpressed")
        elif step == 1:
            # Record both bases
            self.calibration['left_base'] = float(self.trigger_cal_last_left)
            self.calibration['right_base'] = float(self.trigger_cal_last_right)
            self.trigger_cal_step = 2
            self.trigger_cal_btn.config(text="Record Left Bump")
            self.trigger_cal_status.config(text="Push LEFT trigger to analog max (before click)")
        elif step == 2:
            # Record left bump
            self.calibration['left_bump'] = float(self.trigger_cal_last_left)
            self.trigger_cal_step = 3
            self.trigger_cal_btn.config(text="Record Left Max")
            self.trigger_cal_status.config(text="Fully press LEFT trigger past the bump")
        elif step == 3:
            # Record left max
            self.calibration['left_max'] = float(self.trigger_cal_last_left)
            self.trigger_cal_step = 4
            self.trigger_cal_btn.config(text="Record Right Bump")
            self.trigger_cal_status.config(text="Push RIGHT trigger to analog max (before click)")
        elif step == 4:
            # Record right bump
            self.calibration['right_bump'] = float(self.trigger_cal_last_right)
            self.trigger_cal_step = 5
            self.trigger_cal_btn.config(text="Record Right Max")
            self.trigger_cal_status.config(text="Fully press RIGHT trigger past the bump")
        elif step == 5:
            # Record right max, finish wizard
            self.calibration['right_max'] = float(self.trigger_cal_last_right)
            self._cached_calibration = self.calibration.copy()
            self._draw_trigger_markers()
            self.trigger_cal_step = 0
            self.trigger_cal_btn.config(text="Calibrate Triggers")
            self.trigger_cal_status.config(text="Calibration complete!")

    def update_calibration_from_ui(self):
        """Update calibration values from UI"""
        self.calibration['bump_100_percent'] = self.trigger_mode_var.get()
        self.calibration['emulation_mode'] = self.emu_mode_var.get()
        self.calibration['auto_connect'] = self.auto_connect_var.get()

        # Update cached calibration for performance
        self._cached_calibration = self.calibration.copy()
    
    def save_settings(self):
        """Save calibration settings to file"""
        self.update_calibration_from_ui()
        
        try:
            settings_file = os.path.join(os.path.dirname(__file__), 'gc_controller_settings.json')
            with open(settings_file, 'w') as f:
                json.dump(self.calibration, f, indent=2)
            messagebox.showinfo("Settings", "Settings saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")
    
    def load_settings(self):
        """Load calibration settings from file"""
        try:
            settings_file = os.path.join(os.path.dirname(__file__), 'gc_controller_settings.json')
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    saved_settings = json.load(f)
                    self.calibration.update(saved_settings)
        except Exception as e:
            print(f"Failed to load settings: {e}")
    
    def reset_ui_elements(self):
        """Reset UI elements to default state"""
        # Reset button displays
        for label in self.button_labels.values():
            label.config(relief='raised', background='')
        for label in self.dpad_labels.values():
            label.config(relief='raised', background='')
        
        # Reset stick positions
        self.left_stick_canvas.coords(self.left_stick_dot, 37, 37, 43, 43)
        self.right_stick_canvas.coords(self.right_stick_dot, 37, 37, 43, 43)

        # Redraw octagons (uses saved calibration or default)
        self._draw_octagon(self.left_stick_canvas, 'left')
        self.left_stick_canvas.tag_raise(self.left_stick_dot)
        self._draw_octagon(self.right_stick_canvas, 'right')
        self.right_stick_canvas.tag_raise(self.right_stick_dot)
        
        # Reset trigger displays
        self.left_trigger_canvas.delete('fill')
        self.right_trigger_canvas.delete('fill')
        self._draw_trigger_markers()
        self.left_trigger_label.config(text="0")
        self.right_trigger_label.config(text="0")
    
    def update_status(self, message: str):
        """Update status label (thread-safe)"""
        self.root.after(0, lambda: self.status_label.config(text=message))
    
    def on_closing(self):
        """Handle application closing"""
        self.disconnect_controller()
        self.root.destroy()
    
    def run(self):
        """Start the application"""
        self.root.mainloop()


def main():
    """Main entry point"""
    app = GCControllerEnabler()
    app.run()


if __name__ == "__main__":
    main()