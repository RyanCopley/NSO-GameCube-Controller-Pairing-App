#!/usr/bin/env python3
"""
GameCube Controller Enabler - Python/Tkinter Version

Converts GameCube controllers to work with Steam and other applications.
Handles USB initialization, HID communication, and Xbox 360 controller emulation.
Supports up to 4 simultaneous controllers.

Requirements:
    pip install hidapi pyusb

Note: Windows users need ViGEmBus driver for Xbox 360 emulation
"""

import argparse
import base64
import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

try:
    import hid
    import usb.core
    import usb.util
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install hidapi pyusb")
    sys.exit(1)

from .virtual_gamepad import (
    is_emulation_available, get_emulation_unavailable_reason, ensure_dolphin_pipe,
)
from .controller_constants import DEFAULT_CALIBRATION, MAX_SLOTS
from .settings_manager import SettingsManager
from .calibration import CalibrationManager
from .connection_manager import ConnectionManager
from .emulation_manager import EmulationManager
from .input_processor import InputProcessor
from .controller_slot import ControllerSlot

# BLE support (optional — only available on Linux with bumble)
try:
    from .ble import is_ble_available
    _BLE_IMPORTS_OK = True
except ImportError:
    _BLE_IMPORTS_OK = False

    def is_ble_available():
        return False

# Create Dolphin pipe FIFOs early so they show up in Dolphin's device list
if sys.platform in ('darwin', 'linux'):
    for _pipe_idx in range(MAX_SLOTS):
        try:
            ensure_dolphin_pipe(f'gc_controller_{_pipe_idx + 1}')
        except Exception as e:
            print(f"Note: Could not create Dolphin pipe {_pipe_idx + 1}: {e}")


class GCControllerEnabler:
    """Main application orchestrator for GameCube Controller Enabler"""

    def __init__(self):
        import tkinter as tk
        from tkinter import messagebox
        from .controller_ui import ControllerUI

        self._tk = tk
        self._messagebox = messagebox

        self.root = tk.Tk()
        self.root.title("GameCube Controller Enabler")
        self.root.resizable(False, False)

        # Per-slot calibration dicts
        self.slot_calibrations = [dict(DEFAULT_CALIBRATION) for _ in range(MAX_SLOTS)]

        # Settings
        self.settings_mgr = SettingsManager(self.slot_calibrations, os.getcwd())
        self.settings_mgr.load()

        # Create slots (each with own managers)
        self.slots: list[ControllerSlot] = []
        for i in range(MAX_SLOTS):
            slot = ControllerSlot(
                index=i,
                calibration=self.slot_calibrations[i],
                on_status=lambda msg, idx=i: self._schedule_status(idx, msg),
                on_progress=lambda val, idx=i: self._schedule_progress(idx, val),
                on_ui_update=lambda *args, idx=i: self._schedule_ui_update(idx, *args),
                on_error=lambda msg, idx=i: self.root.after(
                    0, lambda m=msg: self.ui.update_status(idx, m)),
                on_disconnect=lambda idx=i: self.root.after(
                    0, lambda: self._on_unexpected_disconnect(idx)),
            )
            self.slots.append(slot)

        # BLE state (lazy-initialized on first pair via privileged subprocess)
        self._ble_available = is_ble_available()
        self._ble_subprocess = None
        self._ble_reader_thread = None
        self._ble_initialized = False
        self._ble_init_event = threading.Event()
        self._ble_init_result = None
        self._ble_pair_mode = {}  # slot_index -> 'pair' | 'reconnect'

        # UI — pass list of cal_mgrs for live octagon drawing
        self.ui = ControllerUI(
            self.root,
            slot_calibrations=self.slot_calibrations,
            slot_cal_mgrs=[s.cal_mgr for s in self.slots],
            on_connect=self.connect_controller,
            on_emulate=self.toggle_emulation,
            on_stick_cal=self.toggle_stick_calibration,
            on_trigger_cal=self.trigger_cal_step,
            on_save=self.save_settings,
            on_refresh=self.refresh_devices,
            on_pair=self.pair_controller if self._ble_available else None,
            ble_available=self._ble_available,
        )

        # Now that UI is built, draw initial trigger markers for all slots
        for i in range(MAX_SLOTS):
            self.ui.draw_trigger_markers(i)

        # Populate device dropdowns and restore saved selections
        self.refresh_devices()
        for i in range(MAX_SLOTS):
            saved = self.slot_calibrations[i].get('preferred_device_path', '')
            if saved:
                self.ui.select_device_by_path(i, saved.encode('utf-8'))

        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Auto-connect if enabled
        if self.slot_calibrations[0]['auto_connect']:
            self.root.after(100, self.auto_connect_and_emulate)

    # ── Connection ───────────────────────────────────────────────────

    def connect_controller(self, slot_index: int):
        """Connect to GameCube controller on a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        if slot.is_connected:
            self.disconnect_controller(slot_index)
            return

        # Enumerate available HID devices
        all_hid = ConnectionManager.enumerate_devices()

        # Filter out paths already claimed by other slots
        claimed_paths = set()
        for i, s in enumerate(self.slots):
            if i != slot_index and s.is_connected and s.conn_mgr.device_path:
                claimed_paths.add(s.conn_mgr.device_path)

        # Check if user selected a specific device
        selected_path = self.ui.get_selected_device_path(slot_index)

        if selected_path is not None:
            # User picked a specific device
            if selected_path in claimed_paths:
                self.ui.update_status(slot_index,
                                      "Selected device is in use by another slot")
                return
            # Verify it still exists
            if not any(d['path'] == selected_path for d in all_hid):
                self.ui.update_status(slot_index,
                                      "Selected device not found — try Refresh")
                return
            target_path = selected_path
        else:
            # Auto — pick first unclaimed
            available = [d for d in all_hid if d['path'] not in claimed_paths]
            if not available:
                self.ui.update_status(slot_index, "No unclaimed controllers found")
                return
            target_path = available[0]['path']

        # Initialize all USB devices (send init data)
        usb_devices = ConnectionManager.enumerate_usb_devices()
        for usb_dev in usb_devices:
            slot.conn_mgr.initialize_via_usb(usb_device=usb_dev)

        # Open specific HID device by path
        if not slot.conn_mgr.init_hid_device(device_path=target_path):
            return

        slot.device_path = target_path

        # Save the path as the preferred device for this slot
        path_str = target_path.decode('utf-8', errors='replace')
        old_pref = self.slot_calibrations[slot_index].get('preferred_device_path', '')
        self.slot_calibrations[slot_index]['preferred_device_path'] = path_str
        if path_str != old_pref:
            self.ui.mark_slot_dirty(slot_index)

        slot.input_proc.start()

        sui.connect_btn.config(text="Disconnect")
        sui.emulate_btn.config(state='normal')
        self.ui.update_tab_status(slot_index, connected=True, emulating=False)
        self.refresh_devices()
        self.toggle_emulation(slot_index)

    def disconnect_controller(self, slot_index: int):
        """Disconnect from controller on a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        # If BLE-connected, use BLE disconnect path
        if slot.ble_connected:
            self._disconnect_ble(slot_index)
            return

        slot.input_proc.stop()
        slot.emu_mgr.stop()
        slot.conn_mgr.disconnect()
        slot.device_path = None

        sui.connect_btn.config(text="Connect")
        sui.emulate_btn.config(state='disabled')
        sui.emulate_btn.config(text="Start Emulation")
        self.ui.update_status(slot_index, "Disconnected")
        self.ui.reset_slot_ui(slot_index)
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)
        self.refresh_devices()

    # ── BLE subprocess helpers ────────────────────────────────────────

    def _start_ble_subprocess(self):
        """Start the privileged BLE subprocess via pkexec."""
        script_path = os.path.join(
            os.path.dirname(__file__), 'ble', 'ble_subprocess.py')
        python_path = os.pathsep.join(p for p in sys.path if p)

        self._ble_subprocess = subprocess.Popen(
            ['pkexec', sys.executable, script_path, python_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        self._ble_reader_thread = threading.Thread(
            target=self._ble_event_reader, daemon=True)
        self._ble_reader_thread.start()

    def _send_ble_cmd(self, cmd: dict):
        """Send a JSON-line command to the BLE subprocess."""
        if self._ble_subprocess and self._ble_subprocess.poll() is None:
            try:
                line = json.dumps(cmd, separators=(',', ':')) + '\n'
                self._ble_subprocess.stdin.write(line)
                self._ble_subprocess.stdin.flush()
            except Exception:
                pass

    def _wait_ble_init(self, timeout: float) -> dict | None:
        """Block until the next init event from the BLE subprocess."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ble_subprocess and self._ble_subprocess.poll() is not None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if self._ble_init_event.wait(timeout=min(remaining, 0.5)):
                result = self._ble_init_result
                self._ble_init_event.clear()
                return result
        return None

    def _cleanup_ble(self):
        """Clean up BLE subprocess."""
        if self._ble_subprocess:
            try:
                self._ble_subprocess.stdin.close()
            except Exception:
                pass
            try:
                self._ble_subprocess.terminate()
                self._ble_subprocess.wait(timeout=3)
            except Exception:
                try:
                    self._ble_subprocess.kill()
                except Exception:
                    pass
            self._ble_subprocess = None
        self._ble_initialized = False

    def _ble_event_reader(self):
        """Read events from the BLE subprocess stdout (runs in a thread)."""
        try:
            for line in self._ble_subprocess.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get('e')

                # Init-phase events: signal the main thread directly
                if not self._ble_initialized and etype in (
                        'ready', 'bluez_stopped', 'open_ok', 'error'):
                    self._ble_init_result = event
                    self._ble_init_event.set()
                    continue

                # Data events: put directly into slot queue (low latency)
                if etype == 'data':
                    si = event.get('s')
                    if si is not None and 0 <= si < len(self.slots):
                        data = base64.b64decode(event['d'])
                        self.slots[si].ble_data_queue.put(data)
                    continue

                # Other runtime events: dispatch to main (Tkinter) thread
                self.root.after(
                    0, lambda ev=event: self._handle_ble_event(ev))
        except Exception:
            pass

    def _handle_ble_event(self, event):
        """Handle a BLE runtime event on the main (Tkinter) thread."""
        etype = event.get('e')
        si = event.get('s')

        if etype == 'status' and si is not None:
            self.ui.update_ble_status(si, event.get('msg', ''))

        elif etype == 'connected' and si is not None:
            mac = event.get('mac')
            mode = self._ble_pair_mode.pop(si, 'pair')
            if mode == 'pair':
                self._on_pair_complete(si, mac)
            else:
                self._on_reconnect_complete(si, mac)

        elif etype == 'connect_error' and si is not None:
            msg = event.get('msg', 'Connection failed')
            mode = self._ble_pair_mode.pop(si, 'pair')
            if mode == 'pair':
                self._on_pair_complete(si, None, error=msg)
            else:
                self.root.after(
                    3000, lambda _si=si: self._attempt_ble_reconnect(_si))

        elif etype == 'disconnected' and si is not None:
            self._on_ble_disconnect(si)

        elif etype == 'error':
            self._messagebox.showerror(
                "BLE Error", event.get('msg', 'Unknown error'))

    # ── BLE ───────────────────────────────────────────────────────────

    def _init_ble(self) -> bool:
        """Lazy-initialize BLE subsystem on first pair attempt.

        Spawns a privileged subprocess via pkexec that handles all BLE
        operations (raw HCI access requires elevated privileges on Linux).
        Returns True on success.
        """
        if self._ble_initialized:
            return True

        if not shutil.which('pkexec'):
            self._messagebox.showerror(
                "BLE Error",
                "pkexec is required for Bluetooth LE.\n\n"
                "Install with:\n"
                "  sudo apt install policykit-1")
            return False

        try:
            self._start_ble_subprocess()
        except Exception as e:
            self._messagebox.showerror(
                "BLE Error", f"Failed to start BLE service:\n{e}")
            return False

        # Wait for subprocess to start (user authenticates via pkexec)
        result = self._wait_ble_init(timeout=60)
        if not result or result.get('e') != 'ready':
            self._cleanup_ble()
            self._messagebox.showerror(
                "BLE Error",
                "BLE service failed to start.\n\n"
                "Authentication may have been cancelled.")
            return False

        # Stop BlueZ (must release HCI adapter for Bumble)
        self._send_ble_cmd({"cmd": "stop_bluez"})
        result = self._wait_ble_init(timeout=15)
        if not result or result.get('e') != 'bluez_stopped':
            self._cleanup_ble()
            return False

        # Open HCI adapter
        self._send_ble_cmd({"cmd": "open"})
        result = self._wait_ble_init(timeout=15)
        if not result or result.get('e') == 'error':
            msg = result.get('msg', 'Unknown error') if result else 'Timeout'
            self._cleanup_ble()
            self._messagebox.showerror(
                "BLE Error",
                f"Failed to initialize BLE:\n{msg}\n\n"
                "Make sure a Bluetooth adapter is connected.")
            return False

        self._ble_initialized = True
        return True

    def pair_controller(self, slot_index: int):
        """Start BLE pairing for a controller slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        # If already BLE-connected, disconnect
        if slot.ble_connected:
            self._disconnect_ble(slot_index)
            return

        # If USB-connected, disconnect USB first
        if slot.is_connected and slot.connection_mode == 'usb':
            self.disconnect_controller(slot_index)

        # Init BLE subsystem
        if not self._init_ble():
            return

        # Disable pair button during pairing
        if sui.pair_btn:
            sui.pair_btn.config(state='disabled')
        self.ui.update_ble_status(slot_index, "Initializing...")

        # Drain any stale data from the queue
        while not slot.ble_data_queue.empty():
            try:
                slot.ble_data_queue.get_nowait()
            except Exception:
                break

        # Use saved address for direct connect, or None for scan
        target_addr = slot.ble_address if slot.ble_address else None

        self._ble_pair_mode[slot_index] = 'pair'
        self._send_ble_cmd({
            "cmd": "scan_connect",
            "slot_index": slot_index,
            "target_address": target_addr,
        })

    def _on_pair_complete(self, slot_index: int, mac: str | None,
                          error: str | None = None):
        """Handle completion of BLE pairing attempt."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        if mac:
            slot.ble_connected = True
            slot.ble_address = mac
            slot.connection_mode = 'ble'

            # Save address
            old_addr = self.slot_calibrations[slot_index].get('preferred_ble_address', '')
            self.slot_calibrations[slot_index]['preferred_ble_address'] = mac
            self.slot_calibrations[slot_index]['connection_mode'] = 'ble'
            if mac != old_addr:
                self.ui.mark_slot_dirty(slot_index)

            # Start input processor in BLE mode
            slot.input_proc.start(mode='ble')

            sui.emulate_btn.config(state='normal')
            if sui.pair_btn:
                sui.pair_btn.config(text="Disconnect BLE", state='normal')
            self.ui.update_ble_status(slot_index, f"Connected: {mac}")
            self.ui.update_status(slot_index, "Connected via BLE")
            self.ui.update_tab_status(slot_index, connected=True, emulating=False)
            self.toggle_emulation(slot_index)
        else:
            if sui.pair_btn:
                sui.pair_btn.config(state='normal')
            if error:
                self.ui.update_ble_status(slot_index, f"Error: {error}")
            # Status was already set by on_status callback

    def _disconnect_ble(self, slot_index: int):
        """Disconnect BLE on a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        slot.input_proc.stop()
        slot.emu_mgr.stop()

        if slot.ble_address and self._ble_subprocess:
            self._send_ble_cmd({
                "cmd": "disconnect",
                "slot_index": slot_index,
                "address": slot.ble_address,
            })

        # Drain queue
        while not slot.ble_data_queue.empty():
            try:
                slot.ble_data_queue.get_nowait()
            except Exception:
                break

        slot.ble_connected = False

        if sui.pair_btn:
            sui.pair_btn.config(text="Pair Controller", state='normal')
        sui.emulate_btn.config(state='disabled', text="Start Emulation")
        self.ui.update_status(slot_index, "Disconnected")
        self.ui.reset_slot_ui(slot_index)
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)

    def _on_ble_disconnect(self, slot_index: int):
        """Handle unexpected BLE disconnect."""
        slot = self.slots[slot_index]
        if not slot.ble_connected:
            return

        slot.reconnect_was_emulating = slot.emu_mgr.is_emulating
        slot.input_proc.stop()
        if slot.emu_mgr.is_emulating:
            slot.emu_mgr.stop()

        slot.ble_connected = False
        sui = self.ui.slots[slot_index]

        self.ui.update_status(slot_index, "BLE disconnected — reconnecting...")
        self.ui.update_ble_status(slot_index, "Reconnecting...")
        if sui.pair_btn:
            sui.pair_btn.config(state='disabled')
        sui.emulate_btn.config(state='disabled')
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)

        self._attempt_ble_reconnect(slot_index)

    def _attempt_ble_reconnect(self, slot_index: int):
        """Try to reconnect BLE. Retries every 3 seconds."""
        slot = self.slots[slot_index]

        # User clicked disconnect while we were waiting — abort
        if slot.input_proc.stop_event.is_set():
            self.ui.update_status(slot_index, "Disconnected")
            self.ui.update_ble_status(slot_index, "")
            self.ui.reset_slot_ui(slot_index)
            if self.ui.slots[slot_index].pair_btn:
                self.ui.slots[slot_index].pair_btn.config(
                    text="Pair Controller", state='normal')
            self.ui.update_tab_status(slot_index, connected=False, emulating=False)
            return

        if not self._ble_initialized or not self._ble_subprocess:
            self.root.after(3000, lambda: self._attempt_ble_reconnect(slot_index))
            return

        # Drain stale data
        while not slot.ble_data_queue.empty():
            try:
                slot.ble_data_queue.get_nowait()
            except Exception:
                break

        target_addr = slot.ble_address

        self._ble_pair_mode[slot_index] = 'reconnect'
        self._send_ble_cmd({
            "cmd": "scan_connect",
            "slot_index": slot_index,
            "target_address": target_addr,
        })

    def _on_reconnect_complete(self, slot_index: int, mac: str):
        """Handle successful BLE reconnection."""
        slot = self.slots[slot_index]
        if not mac:
            self.root.after(3000, lambda: self._attempt_ble_reconnect(slot_index))
            return

        slot.ble_connected = True
        slot.ble_address = mac
        slot.input_proc.start(mode='ble')

        sui = self.ui.slots[slot_index]
        sui.emulate_btn.config(state='normal')
        if sui.pair_btn:
            sui.pair_btn.config(text="Disconnect BLE", state='normal')
        self.ui.update_status(slot_index, "Reconnected via BLE")
        self.ui.update_ble_status(slot_index, f"Connected: {mac}")
        self.ui.update_tab_status(slot_index, connected=True, emulating=False)

        if slot.reconnect_was_emulating:
            slot.reconnect_was_emulating = False
            self.toggle_emulation(slot_index)

    def auto_connect_and_emulate(self):
        """Auto-connect all available controllers and start emulation.

        Respects preferred_device_path settings: if slot N has a saved preference
        and that device is available, it gets that device.
        """
        all_hid = ConnectionManager.enumerate_devices()
        if not all_hid:
            return

        # Initialize all USB devices first
        usb_devices = ConnectionManager.enumerate_usb_devices()
        for usb_dev in usb_devices:
            tmp = ConnectionManager(
                on_status=lambda msg: None,
                on_progress=lambda val: None,
            )
            tmp.initialize_via_usb(usb_device=usb_dev)

        all_paths = {d['path'] for d in all_hid}
        claimed_paths = set()

        # First pass: assign preferred devices to their slots
        for i in range(MAX_SLOTS):
            saved = self.slot_calibrations[i].get('preferred_device_path', '')
            if not saved:
                continue
            pref_bytes = saved.encode('utf-8')
            if pref_bytes in all_paths and pref_bytes not in claimed_paths:
                slot = self.slots[i]
                sui = self.ui.slots[i]
                if slot.conn_mgr.init_hid_device(device_path=pref_bytes):
                    claimed_paths.add(pref_bytes)
                    slot.device_path = pref_bytes
                    slot.input_proc.start()
                    sui.connect_btn.config(text="Disconnect")
                    sui.emulate_btn.config(state='normal')
                    self.ui.update_tab_status(i, connected=True, emulating=False)
                    self.toggle_emulation(i)

        # Second pass: fill remaining slots with unclaimed devices
        for i in range(MAX_SLOTS):
            if self.slots[i].is_connected:
                continue
            target = None
            for d in all_hid:
                if d['path'] not in claimed_paths:
                    target = d
                    break
            if target is None:
                break

            slot = self.slots[i]
            sui = self.ui.slots[i]
            path = target['path']

            if slot.conn_mgr.init_hid_device(device_path=path):
                claimed_paths.add(path)
                slot.device_path = path
                slot.input_proc.start()
                sui.connect_btn.config(text="Disconnect")
                sui.emulate_btn.config(state='normal')
                self.ui.update_tab_status(i, connected=True, emulating=False)
                self.toggle_emulation(i)

        self.refresh_devices()

    # ── Device enumeration ────────────────────────────────────────────

    def refresh_devices(self):
        """Refresh device dropdowns for all slots."""
        all_hid = ConnectionManager.enumerate_devices()

        # Build a map of claimed paths -> slot index
        claimed_map = {}
        for i, s in enumerate(self.slots):
            if s.is_connected and s.conn_mgr.device_path:
                claimed_map[s.conn_mgr.device_path] = i

        for i in range(MAX_SLOTS):
            self.ui.set_device_list(i, all_hid, claimed_map)

    # ── Auto-reconnect ──────────────────────────────────────────────

    def _on_unexpected_disconnect(self, slot_index: int):
        """Handle an unexpected controller disconnect on a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        if slot.conn_mgr.device:
            try:
                slot.conn_mgr.device.close()
            except Exception:
                pass
            slot.conn_mgr.device = None

        slot.reconnect_was_emulating = slot.emu_mgr.is_emulating

        if slot.emu_mgr.is_emulating:
            slot.emu_mgr.stop()

        self.ui.update_status(slot_index, "Controller disconnected — reconnecting...")
        sui.connect_btn.config(text="Connect")
        sui.emulate_btn.config(state='disabled')
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)

        self._attempt_reconnect(slot_index)

    def _attempt_reconnect(self, slot_index: int):
        """Try to reconnect controller on a specific slot. Retries every 2 seconds."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        # User clicked Disconnect while we were waiting — abort.
        if slot.input_proc.stop_event.is_set():
            self.ui.update_status(slot_index, "Disconnected")
            self.ui.reset_slot_ui(slot_index)
            self.ui.update_tab_status(slot_index, connected=False, emulating=False)
            return

        # Build set of paths claimed by other slots
        claimed_paths = set()
        for i, s in enumerate(self.slots):
            if i != slot_index and s.is_connected and s.conn_mgr.device_path:
                claimed_paths.add(s.conn_mgr.device_path)

        all_hid = ConnectionManager.enumerate_devices()
        all_paths = {d['path'] for d in all_hid}

        # Priority order: remembered runtime path, then saved preferred path, then any unclaimed
        target_path = None
        candidates = []
        if slot.device_path:
            candidates.append(slot.device_path)
        saved_pref = self.slot_calibrations[slot_index].get('preferred_device_path', '')
        if saved_pref:
            pref_bytes = saved_pref.encode('utf-8')
            if pref_bytes not in candidates:
                candidates.append(pref_bytes)

        for candidate in candidates:
            if candidate in all_paths and candidate not in claimed_paths:
                target_path = candidate
                break

        if target_path is None:
            for d in all_hid:
                if d['path'] not in claimed_paths:
                    target_path = d['path']
                    break

        if target_path:
            # Init all USB devices
            usb_devices = ConnectionManager.enumerate_usb_devices()
            for usb_dev in usb_devices:
                slot.conn_mgr.initialize_via_usb(usb_device=usb_dev)

            if slot.conn_mgr.init_hid_device(device_path=target_path):
                slot.device_path = target_path
                slot.input_proc.start()
                sui.connect_btn.config(text="Disconnect")
                sui.emulate_btn.config(state='normal')
                self.ui.update_status(slot_index, "Reconnected")
                self.ui.update_tab_status(slot_index, connected=True, emulating=False)
                self.refresh_devices()

                if slot.reconnect_was_emulating:
                    slot.reconnect_was_emulating = False
                    self.toggle_emulation(slot_index)
                return

        # Failed — retry after a delay
        self.ui.update_status(slot_index, "Controller disconnected — reconnecting...")
        self.root.after(2000, lambda: self._attempt_reconnect(slot_index))

    # ── Emulation ────────────────────────────────────────────────────

    def toggle_emulation(self, slot_index: int):
        """Start or stop controller emulation for a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        if slot.emu_mgr.is_emulating or getattr(slot, '_pipe_cancel', None):
            # Cancel a pending dolphin pipe wait, or stop active emulation.
            cancel = getattr(slot, '_pipe_cancel', None)
            if cancel is not None:
                cancel.set()
                slot._pipe_cancel = None
            slot.emu_mgr.stop()
            sui.emulate_btn.config(text="Start Emulation")
            self.ui.update_emu_status(slot_index, "")
            self.ui.update_tab_status(slot_index, connected=slot.is_connected, emulating=False)
        else:
            mode = sui.emu_mode_var.get()

            if not is_emulation_available(mode):
                self._messagebox.showerror(
                    "Error",
                    f"Emulation not available for mode '{mode}'.\n"
                    + get_emulation_unavailable_reason(mode))
                return

            if mode == 'dolphin_pipe':
                self._start_dolphin_pipe_emulation(slot_index)
            else:
                self._start_xbox360_emulation(slot_index)

    def _start_xbox360_emulation(self, slot_index: int):
        """Start Xbox 360 emulation synchronously."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]
        try:
            slot.emu_mgr.start('xbox360', slot_index=slot_index)
            sui.emulate_btn.config(text="Stop Emulation")
            self.ui.update_emu_status(slot_index, "Xbox 360 active")
            self.ui.update_tab_status(slot_index, connected=True, emulating=True)
        except Exception as e:
            self._messagebox.showerror("Emulation Error",
                                       f"Failed to start emulation: {e}")

    def _start_dolphin_pipe_emulation(self, slot_index: int):
        """Start Dolphin pipe emulation on a background thread.

        Polls until Dolphin opens the read end of the pipe.  The button
        switches to 'Cancel' so the user can abort the wait.
        """
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]
        pipe_name = f'gc_controller_{slot_index + 1}'

        cancel = threading.Event()
        slot._pipe_cancel = cancel
        sui.emulate_btn.config(text="Cancel")
        self.ui.update_emu_status(
            slot_index, f"Waiting for Dolphin to read {pipe_name}...")

        def _connect():
            try:
                slot.emu_mgr.start('dolphin_pipe', slot_index=slot_index,
                                   cancel_event=cancel)
                self.root.after(0, lambda: self._on_pipe_connected(slot_index))
            except Exception as e:
                self.root.after(0, lambda: self._on_pipe_failed(slot_index, e))

        threading.Thread(target=_connect, daemon=True).start()

    def _on_pipe_connected(self, slot_index: int):
        """Called on the main thread when a dolphin pipe successfully opens."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]
        slot._pipe_cancel = None
        pipe_name = f'gc_controller_{slot_index + 1}'
        sui.emulate_btn.config(text="Stop Emulation")
        self.ui.update_emu_status(
            slot_index, f"Dolphin pipe active ({pipe_name})")
        self.ui.update_tab_status(slot_index, connected=True, emulating=True)

    def _on_pipe_failed(self, slot_index: int, error: Exception):
        """Called on the main thread when dolphin pipe open fails or is cancelled."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]
        slot._pipe_cancel = None
        slot.emu_mgr.stop()
        sui.emulate_btn.config(text="Start Emulation")
        self.ui.update_emu_status(slot_index, "")
        self.ui.update_tab_status(slot_index, connected=slot.is_connected, emulating=False)
        if getattr(error, 'errno', None) != errno.ECANCELED:
            self._messagebox.showerror("Emulation Error",
                                       f"Failed to start pipe emulation: {error}")

    # ── Stick calibration ────────────────────────────────────────────

    def toggle_stick_calibration(self, slot_index: int):
        """Toggle stick calibration on/off for a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        if slot.cal_mgr.stick_calibrating:
            slot.cal_mgr.finish_stick_calibration()
            self.ui.redraw_octagons(slot_index)
            sui.stick_cal_btn.config(text="Calibrate Sticks")
            sui.stick_cal_status.config(text="Calibration complete!")
            self.ui.mark_slot_dirty(slot_index)
        else:
            slot.cal_mgr.start_stick_calibration()
            sui.stick_cal_btn.config(text="Finish Calibration")
            sui.stick_cal_status.config(text="Move sticks to all extremes...")

    # ── Trigger calibration ──────────────────────────────────────────

    def trigger_cal_step(self, slot_index: int):
        """Advance the trigger calibration wizard one step for a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        result = slot.cal_mgr.trigger_cal_next_step()
        if result is not None:
            step, btn_text, status_text = result
            sui.trigger_cal_btn.config(text=btn_text)
            sui.trigger_cal_status.config(text=status_text)
            if step == 0:
                # Wizard finished — redraw markers
                self.ui.draw_trigger_markers(slot_index)
                self.ui.mark_slot_dirty(slot_index)

    # ── Settings ─────────────────────────────────────────────────────

    def update_calibration_from_ui(self):
        """Update calibration values from UI variables for all slots."""
        for i in range(MAX_SLOTS):
            sui = self.ui.slots[i]
            cal = self.slot_calibrations[i]
            cal['trigger_bump_100_percent'] = sui.trigger_mode_var.get()
            cal['emulation_mode'] = sui.emu_mode_var.get()
            self.slots[i].cal_mgr.refresh_cache()

            # Save preferred device path from dropdown (or from last connection)
            selected = self.ui.get_selected_device_path(i)
            if selected is not None:
                cal['preferred_device_path'] = selected.decode('utf-8', errors='replace')

            # Save BLE state
            slot = self.slots[i]
            cal['connection_mode'] = slot.connection_mode
            if slot.ble_address:
                cal['preferred_ble_address'] = slot.ble_address

        # Global settings stored in slot 0's calibration
        self.slot_calibrations[0]['auto_connect'] = self.ui.auto_connect_var.get()

    def save_settings(self):
        """Save calibration settings for all slots to file."""
        self.update_calibration_from_ui()
        try:
            self.settings_mgr.save()
            self.ui.mark_all_clean()
            self._messagebox.showinfo("Settings", "Settings saved successfully!")
        except Exception as e:
            self._messagebox.showerror("Error", f"Failed to save settings: {e}")

    # ── Thread-safe bridges ──────────────────────────────────────────

    def _schedule_status(self, slot_index: int, message: str):
        """Thread-safe status update via root.after."""
        self.root.after(0, lambda: self.ui.update_status(slot_index, message))

    def _schedule_progress(self, slot_index: int, value: int):
        """No-op — progress bar replaced by log text area."""
        pass

    def _schedule_ui_update(self, slot_index: int, left_x, left_y, right_x, right_y,
                            left_trigger, right_trigger, button_states,
                            stick_calibrating):
        """Schedule a UI update from the input thread for a specific slot."""
        self.root.after(0, lambda: self._apply_ui_update(
            slot_index, left_x, left_y, right_x, right_y,
            left_trigger, right_trigger, button_states,
            stick_calibrating))

    def _apply_ui_update(self, slot_index: int, left_x, left_y, right_x, right_y,
                         left_trigger, right_trigger, button_states,
                         stick_calibrating):
        """Apply UI updates on the main thread for a specific slot."""
        s = self.ui.slots[slot_index]

        self.ui.update_stick_position(
            s.left_stick_canvas, s.left_stick_dot, left_x, left_y)
        self.ui.update_stick_position(
            s.right_stick_canvas, s.right_stick_dot, right_x, right_y)
        self.ui.update_trigger_display(slot_index, left_trigger, right_trigger)
        self.ui.update_button_display(slot_index, button_states)

        if stick_calibrating:
            self.ui.draw_octagon_live(slot_index, 'left')
            self.ui.draw_octagon_live(slot_index, 'right')

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_closing(self):
        """Handle application closing."""
        for i in range(MAX_SLOTS):
            slot = self.slots[i]
            slot.input_proc.stop()
            slot.emu_mgr.stop()
            slot.conn_mgr.disconnect()

        # Clean up BLE subprocess
        if self._ble_subprocess:
            try:
                self._send_ble_cmd({"cmd": "shutdown"})
                self._ble_subprocess.wait(timeout=5.0)
            except Exception:
                pass
            self._cleanup_ble()

        self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()


class _BleHeadlessManager:
    """Manages the BLE subprocess for headless mode (no Tkinter)."""

    def __init__(self):
        self._subprocess = None
        self._reader_thread = None
        self._initialized = False
        self._init_event = threading.Event()
        self._init_result = None

    def start_subprocess(self):
        """Start the privileged BLE subprocess via pkexec."""
        script_path = os.path.join(
            os.path.dirname(__file__), 'ble', 'ble_subprocess.py')
        python_path = os.pathsep.join(p for p in sys.path if p)

        self._subprocess = subprocess.Popen(
            ['pkexec', sys.executable, script_path, python_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send_cmd(self, cmd: dict):
        """Send a JSON-line command to the BLE subprocess."""
        if self._subprocess and self._subprocess.poll() is None:
            try:
                line = json.dumps(cmd, separators=(',', ':')) + '\n'
                self._subprocess.stdin.write(line)
                self._subprocess.stdin.flush()
            except Exception:
                pass

    def _wait_init(self, timeout: float) -> dict | None:
        """Block until the next init event from the BLE subprocess."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._subprocess and self._subprocess.poll() is not None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if self._init_event.wait(timeout=min(remaining, 0.5)):
                result = self._init_result
                self._init_event.clear()
                return result
        return None

    def init_ble(self, on_data, on_event) -> bool:
        """Full init sequence: spawn → start reader → wait ready → stop_bluez → open HCI.

        The reader thread must be running before we wait for init events,
        so on_data and on_event callbacks are required upfront.
        Returns True on success, prints errors to stdout.
        """
        if self._initialized:
            return True

        if not shutil.which('pkexec'):
            print("BLE Error: pkexec is required for Bluetooth LE.")
            print("Install with: sudo apt install policykit-1")
            return False

        try:
            self.start_subprocess()
        except Exception as e:
            print(f"BLE Error: Failed to start BLE service: {e}")
            return False

        # Start reader thread immediately so it can receive init-phase events
        self.start_reader(on_data, on_event)

        # Wait for subprocess to start (user authenticates via pkexec)
        result = self._wait_init(timeout=60)
        if not result or result.get('e') != 'ready':
            self.shutdown()
            print("BLE Error: BLE service failed to start. "
                  "Authentication may have been cancelled.")
            return False

        # Stop BlueZ (must release HCI adapter for Bumble)
        self.send_cmd({"cmd": "stop_bluez"})
        result = self._wait_init(timeout=15)
        if not result or result.get('e') != 'bluez_stopped':
            self.shutdown()
            print("BLE Error: Failed to stop BlueZ.")
            return False

        # Open HCI adapter
        self.send_cmd({"cmd": "open"})
        result = self._wait_init(timeout=15)
        if not result or result.get('e') == 'error':
            msg = result.get('msg', 'Unknown error') if result else 'Timeout'
            self.shutdown()
            print(f"BLE Error: Failed to initialize BLE: {msg}")
            print("Make sure a Bluetooth adapter is connected.")
            return False

        self._initialized = True
        return True

    def start_reader(self, on_data, on_event):
        """Start the event reader thread.

        Args:
            on_data: callback(slot_index, data_bytes) for low-latency data events
            on_event: callback(event_dict) for runtime events (connected, disconnected, etc.)
        """
        self._reader_thread = threading.Thread(
            target=self._event_reader, args=(on_data, on_event), daemon=True)
        self._reader_thread.start()

    def _event_reader(self, on_data, on_event):
        """Read events from the BLE subprocess stdout (runs in a thread)."""
        try:
            for line in self._subprocess.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get('e')

                # Init-phase events: signal the main thread directly
                if not self._initialized and etype in (
                        'ready', 'bluez_stopped', 'open_ok', 'error'):
                    self._init_result = event
                    self._init_event.set()
                    continue

                # Data events: put directly into slot queue (low latency)
                if etype == 'data':
                    si = event.get('s')
                    if si is not None:
                        data = base64.b64decode(event['d'])
                        on_data(si, data)
                    continue

                # Other runtime events: dispatch to event queue
                on_event(event)
        except Exception:
            pass

    def shutdown(self):
        """Send shutdown, terminate process."""
        if self._subprocess:
            try:
                self.send_cmd({"cmd": "shutdown"})
                self._subprocess.wait(timeout=5.0)
            except Exception:
                pass
            try:
                self._subprocess.stdin.close()
            except Exception:
                pass
            try:
                self._subprocess.terminate()
                self._subprocess.wait(timeout=3)
            except Exception:
                try:
                    self._subprocess.kill()
                except Exception:
                    pass
            self._subprocess = None
        self._initialized = False

    @property
    def is_alive(self) -> bool:
        return (self._subprocess is not None
                and self._subprocess.poll() is None
                and self._initialized)


def run_headless(mode_override: str = None):
    """Run controller connection and emulation without the GUI.

    Connects up to 4 controllers (USB and/or BLE), each with its own
    emulation thread.
    """
    import queue as _queue

    slot_calibrations = [dict(DEFAULT_CALIBRATION) for _ in range(MAX_SLOTS)]

    settings_mgr = SettingsManager(slot_calibrations, os.getcwd())
    settings_mgr.load()

    # Use explicit --mode if given, otherwise honor the saved setting from slot 0
    mode = mode_override if mode_override else slot_calibrations[0].get('emulation_mode', 'xbox360')

    if not is_emulation_available(mode):
        print(f"Error: Emulation not available for mode '{mode}'.")
        print(get_emulation_unavailable_reason(mode))
        sys.exit(1)

    stop_event = threading.Event()
    disconnect_events = [threading.Event() for _ in range(MAX_SLOTS)]

    def _shutdown(signum, frame):
        stop_event.set()
        for de in disconnect_events:
            de.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Enumerate USB controllers
    all_hid = ConnectionManager.enumerate_devices()
    ble_available = is_ble_available()

    if not all_hid and not ble_available:
        print("No GameCube controllers found and no BLE adapter available.")
        sys.exit(1)

    # Initialize all USB devices
    if all_hid:
        usb_devices = ConnectionManager.enumerate_usb_devices()
        for usb_dev in usb_devices:
            tmp = ConnectionManager(on_status=lambda msg: None, on_progress=lambda val: None)
            tmp.initialize_via_usb(usb_device=usb_dev)

    all_paths = {d['path'] for d in all_hid}
    active_slots: list[dict] = []
    claimed_paths = set()

    # BLE state
    ble_mgr = None
    ble_event_queue = _queue.Queue()
    ble_data_queues: dict[int, _queue.Queue] = {}  # slot_index -> data queue
    ble_scanning_slot = None  # slot index currently being scanned for
    ble_pending_reconnects: dict[int, str] = {}  # slot_index -> MAC for disconnected controllers

    # Build slot -> preferred path mapping from settings
    slot_preferred: dict[int, bytes] = {}
    for i in range(MAX_SLOTS):
        saved = slot_calibrations[i].get('preferred_device_path', '')
        if saved:
            pref_bytes = saved.encode('utf-8')
            if pref_bytes in all_paths:
                slot_preferred[i] = pref_bytes

    if all_hid:
        print(f"Found {len(all_hid)} USB controller(s). "
              f"Connecting up to {min(MAX_SLOTS, len(all_hid))}...")

    def _connect_slot(i, path):
        """Helper to connect a single USB slot to a specific HID path."""
        cal = slot_calibrations[i]
        cal_mgr = CalibrationManager(cal)
        conn_mgr = ConnectionManager(
            on_status=lambda msg, idx=i: print(f"[slot {idx + 1}] {msg}"),
            on_progress=lambda val: None,
        )

        if not conn_mgr.init_hid_device(device_path=path):
            print(f"[slot {i + 1}] Failed to open HID device")
            return

        claimed_paths.add(path)

        emu_mgr = EmulationManager(cal_mgr)
        slot_mode = mode_override if mode_override else cal.get('emulation_mode', mode)

        mode_label = "Dolphin pipe" if slot_mode == 'dolphin_pipe' else "Xbox 360"
        print(f"[slot {i + 1}] Starting {mode_label} emulation...")
        try:
            emu_mgr.start(slot_mode, slot_index=i)
        except Exception as e:
            print(f"[slot {i + 1}] Failed to start emulation: {e}")
            conn_mgr.disconnect()
            return

        disc_event = disconnect_events[i]

        input_proc = InputProcessor(
            device_getter=lambda cm=conn_mgr: cm.device,
            calibration=cal,
            cal_mgr=cal_mgr,
            emu_mgr=emu_mgr,
            on_ui_update=lambda *args: None,
            on_error=lambda msg, idx=i: print(f"[slot {idx + 1}] {msg}"),
            on_disconnect=lambda de=disc_event: de.set(),
        )
        input_proc.start()

        active_slots.append({
            'index': i,
            'type': 'usb',
            'cal_mgr': cal_mgr,
            'conn_mgr': conn_mgr,
            'emu_mgr': emu_mgr,
            'input_proc': input_proc,
            'device_path': path,
            'disc_event': disc_event,
        })

    # First pass: assign preferred USB devices to their slots
    for i in range(MAX_SLOTS):
        pref = slot_preferred.get(i)
        if pref and pref not in claimed_paths:
            _connect_slot(i, pref)

    # Second pass: fill remaining slots with unclaimed USB devices
    for i in range(MAX_SLOTS):
        if any(s['index'] == i for s in active_slots):
            continue
        target = None
        for d in all_hid:
            if d['path'] not in claimed_paths:
                target = d
                break
        if target is None:
            break
        _connect_slot(i, target['path'])

    # ── BLE setup ──────────────────────────────────────────────────
    def _open_ble_slots() -> list[int]:
        """Return slot indices not occupied by any active connection."""
        used = {s['index'] for s in active_slots}
        return [i for i in range(MAX_SLOTS) if i not in used]

    def _on_ble_data(slot_index, data_bytes):
        """Low-latency callback from the reader thread for BLE data."""
        q = ble_data_queues.get(slot_index)
        if q is not None:
            try:
                q.put_nowait(data_bytes)
            except _queue.Full:
                pass

    def _on_ble_event(event):
        """Runtime event callback from the reader thread."""
        ble_event_queue.put(event)

    def _get_connected_ble_addresses() -> list[str]:
        """Return MACs of all currently connected + pending-reconnect BLE controllers."""
        addrs = []
        for s in active_slots:
            if s['type'] == 'ble' and s.get('ble_address'):
                addrs.append(s['ble_address'])
        for mac in ble_pending_reconnects.values():
            if mac not in addrs:
                addrs.append(mac)
        return addrs

    def _start_ble_scan():
        """Issue scan_connect for the first open slot not pending reconnect."""
        nonlocal ble_scanning_slot
        # Skip slots that have targeted reconnects already running
        open_slots = [i for i in _open_ble_slots()
                      if i not in ble_pending_reconnects]
        if not open_slots or not ble_mgr or not ble_mgr.is_alive:
            ble_scanning_slot = None
            return

        slot_idx = open_slots[0]
        ble_scanning_slot = slot_idx

        # Use saved BLE address if available (direct reconnect)
        saved_addr = slot_calibrations[slot_idx].get('preferred_ble_address', '') or None

        # Exclude controllers already on other slots so the scan
        # doesn't grab them if they briefly disconnect and re-advertise
        exclude = _get_connected_ble_addresses()

        print(f"[slot {slot_idx + 1}] BLE scanning"
              f"{' for ' + saved_addr if saved_addr else ''}...")

        ble_mgr.send_cmd({
            "cmd": "scan_connect",
            "slot_index": slot_idx,
            "target_address": saved_addr,
            "exclude_addresses": exclude if exclude else None,
        })

    def _handle_headless_ble_event(event):
        """Process a BLE runtime event in the main loop."""
        nonlocal ble_scanning_slot

        etype = event.get('e')
        si = event.get('s')

        if etype == 'status' and si is not None:
            print(f"[slot {si + 1}] BLE: {event.get('msg', '')}")

        elif etype == 'connected' and si is not None:
            mac = event.get('mac')
            if not mac:
                return

            was_reconnect = si in ble_pending_reconnects
            ble_pending_reconnects.pop(si, None)

            print(f"[slot {si + 1}] BLE {'reconnected' if was_reconnect else 'connected'}: {mac}")

            # Save address
            slot_calibrations[si]['preferred_ble_address'] = mac
            slot_calibrations[si]['connection_mode'] = 'ble'

            # Create per-slot data queue, input processor, and emulation
            cal = slot_calibrations[si]
            cal_mgr = CalibrationManager(cal)
            ble_q = _queue.Queue(maxsize=64)
            ble_data_queues[si] = ble_q

            emu_mgr = EmulationManager(cal_mgr)
            slot_mode = mode_override if mode_override else cal.get('emulation_mode', mode)
            mode_label = "Dolphin pipe" if slot_mode == 'dolphin_pipe' else "Xbox 360"
            print(f"[slot {si + 1}] Starting {mode_label} emulation...")

            try:
                emu_mgr.start(slot_mode, slot_index=si)
            except Exception as e:
                print(f"[slot {si + 1}] Failed to start emulation: {e}")
                ble_data_queues.pop(si, None)
                return

            disc_event = disconnect_events[si]

            input_proc = InputProcessor(
                device_getter=lambda: None,
                calibration=cal,
                cal_mgr=cal_mgr,
                emu_mgr=emu_mgr,
                on_ui_update=lambda *args: None,
                on_error=lambda msg, idx=si: print(f"[slot {idx + 1}] {msg}"),
                on_disconnect=lambda de=disc_event: de.set(),
                ble_queue=ble_q,
            )
            input_proc.start(mode='ble')

            active_slots.append({
                'index': si,
                'type': 'ble',
                'cal_mgr': cal_mgr,
                'conn_mgr': None,
                'emu_mgr': emu_mgr,
                'input_proc': input_proc,
                'device_path': None,
                'disc_event': disc_event,
                'ble_address': mac,
            })

            ble_scanning_slot = None

            # Scan for more controllers if open slots remain
            if _open_ble_slots():
                _start_ble_scan()
            else:
                print("All slots occupied.")

        elif etype == 'connect_error' and si is not None:
            msg = event.get('msg', 'Connection failed')
            print(f"[slot {si + 1}] BLE connect error: {msg}")

            if si in ble_pending_reconnects:
                # Targeted reconnect failed — retry after 3 seconds
                mac = ble_pending_reconnects[si]
                if not stop_event.is_set():
                    threading.Timer(3.0, lambda _si=si, _mac=mac:
                        ble_event_queue.put(
                            {'e': '_retry_reconnect', 's': _si, 'mac': _mac}
                        )).start()
            else:
                # General scan failed — retry after 3 seconds
                ble_scanning_slot = None
                if not stop_event.is_set():
                    threading.Timer(3.0, lambda: ble_event_queue.put(
                        {'e': '_retry_scan'})).start()

        elif etype == 'disconnected' and si is not None:
            # Find the active slot info
            slot_info = None
            for s in active_slots:
                if s['index'] == si and s['type'] == 'ble':
                    slot_info = s
                    break
            if not slot_info:
                return

            print(f"[slot {si + 1}] BLE disconnected — will reconnect...")

            # Stop input/emulation
            slot_info['input_proc'].stop()
            was_emulating = slot_info['emu_mgr'].is_emulating
            if was_emulating:
                slot_info['emu_mgr'].stop()
            slot_info['was_emulating'] = was_emulating

            # Remove from active slots so the slot is "open"
            active_slots.remove(slot_info)
            ble_data_queues.pop(si, None)

            # Cancel the current general scan so it doesn't grab this
            # controller on the wrong slot when it re-advertises
            if ble_scanning_slot is not None:
                ble_mgr.send_cmd({
                    "cmd": "disconnect",
                    "slot_index": ble_scanning_slot,
                })
                ble_scanning_slot = None

            # Issue targeted reconnect with saved MAC
            saved_mac = slot_info.get('ble_address')
            if saved_mac and ble_mgr and ble_mgr.is_alive:
                ble_pending_reconnects[si] = saved_mac
                print(f"[slot {si + 1}] BLE reconnecting to {saved_mac}...")
                ble_mgr.send_cmd({
                    "cmd": "scan_connect",
                    "slot_index": si,
                    "target_address": saved_mac,
                })

        elif etype == '_retry_reconnect' and si is not None:
            mac = event.get('mac')
            if not stop_event.is_set() and si in ble_pending_reconnects and mac:
                print(f"[slot {si + 1}] BLE retrying reconnect to {mac}...")
                ble_mgr.send_cmd({
                    "cmd": "scan_connect",
                    "slot_index": si,
                    "target_address": mac,
                })

        elif etype == '_retry_scan':
            if not stop_event.is_set() and _open_ble_slots():
                _start_ble_scan()

        elif etype == 'error':
            print(f"BLE Error: {event.get('msg', 'Unknown error')}")

    # ── Initialize BLE if needed ───────────────────────────────────
    if ble_available and _open_ble_slots():
        ble_mgr = _BleHeadlessManager()
        print("Initializing BLE...")
        if ble_mgr.init_ble(_on_ble_data, _on_ble_event):
            print("BLE initialized successfully.")
            _start_ble_scan()
        else:
            print("BLE initialization failed. Continuing with USB only.")
            ble_mgr = None

    if not active_slots and not (ble_mgr and ble_mgr.is_alive):
        print("No controllers connected and BLE not available.")
        sys.exit(1)

    usb_count = sum(1 for s in active_slots if s['type'] == 'usb')
    ble_status = " BLE scanning..." if (ble_mgr and ble_mgr.is_alive) else ""
    print(f"Headless mode active with {usb_count} USB controller(s).{ble_status} "
          f"Press Ctrl+C to stop.")

    # ── Main monitoring loop ───────────────────────────────────────
    while not stop_event.is_set():
        stop_event.wait(timeout=0.5)
        if stop_event.is_set():
            break

        # Process BLE events
        while True:
            try:
                ev = ble_event_queue.get_nowait()
                _handle_headless_ble_event(ev)
            except _queue.Empty:
                break

        # Monitor USB disconnects
        for slot_info in list(active_slots):
            if slot_info['type'] != 'usb':
                continue

            disc_event = slot_info['disc_event']
            if not disc_event.is_set():
                continue

            disc_event.clear()
            idx = slot_info['index']
            conn_mgr = slot_info['conn_mgr']
            emu_mgr = slot_info['emu_mgr']
            input_proc = slot_info['input_proc']

            if conn_mgr.device:
                try:
                    conn_mgr.device.close()
                except Exception:
                    pass
                conn_mgr.device = None

            was_emulating = emu_mgr.is_emulating
            if emu_mgr.is_emulating:
                emu_mgr.stop()

            print(f"[slot {idx + 1}] USB controller disconnected — reconnecting...")

            # USB reconnect loop for this slot
            while not stop_event.is_set():
                remembered = slot_info['device_path']
                saved_pref = slot_calibrations[idx].get('preferred_device_path', '')

                cur_hid = ConnectionManager.enumerate_devices()
                cur_paths = {d['path'] for d in cur_hid}
                cur_claimed = set()
                for other in active_slots:
                    if other['index'] != idx and other['type'] == 'usb' \
                            and other['conn_mgr'] and other['conn_mgr'].device:
                        if other['conn_mgr'].device_path:
                            cur_claimed.add(other['conn_mgr'].device_path)

                candidates = []
                if remembered:
                    candidates.append(remembered)
                if saved_pref:
                    pref_bytes = saved_pref.encode('utf-8')
                    if pref_bytes not in candidates:
                        candidates.append(pref_bytes)

                target_path = None
                for c in candidates:
                    if c in cur_paths and c not in cur_claimed:
                        target_path = c
                        break

                if target_path is None:
                    for d in cur_hid:
                        if d['path'] not in cur_claimed:
                            target_path = d['path']
                            break

                if target_path:
                    usb_devs = ConnectionManager.enumerate_usb_devices()
                    for usb_dev in usb_devs:
                        conn_mgr.initialize_via_usb(usb_device=usb_dev)

                    if conn_mgr.init_hid_device(device_path=target_path):
                        slot_info['device_path'] = target_path
                        input_proc.start()
                        print(f"[slot {idx + 1}] USB reconnected.")
                        if was_emulating:
                            slot_mode = mode_override if mode_override else \
                                slot_calibrations[idx].get('emulation_mode', mode)
                            try:
                                emu_mgr.start(slot_mode, slot_index=idx)
                                mode_label = "Dolphin pipe" if slot_mode == 'dolphin_pipe' \
                                    else "Xbox 360"
                                print(f"[slot {idx + 1}] {mode_label} emulation resumed.")
                            except Exception as e:
                                print(f"[slot {idx + 1}] Failed to resume emulation: {e}")
                        break

                # Also drain BLE events while waiting for USB reconnect
                while True:
                    try:
                        ev = ble_event_queue.get_nowait()
                        _handle_headless_ble_event(ev)
                    except _queue.Empty:
                        break

                stop_event.wait(timeout=2.0)

    print("\nShutting down...")
    for slot_info in active_slots:
        slot_info['input_proc'].stop()
        slot_info['emu_mgr'].stop()
        if slot_info['type'] == 'usb' and slot_info['conn_mgr']:
            slot_info['conn_mgr'].disconnect()
    if ble_mgr:
        ble_mgr.shutdown()
    print("Done.")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="GameCube Controller Enabler - "
                    "converts GC controllers to Xbox 360 for Steam and other apps"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without the GUI (connect and emulate in the background)",
    )
    parser.add_argument(
        "--mode",
        choices=["xbox360", "dolphin_pipe"],
        default=None,
        help="emulation mode for headless operation (default: use saved setting)",
    )
    args = parser.parse_args()

    if args.headless:
        run_headless(mode_override=args.mode)
    else:
        app = GCControllerEnabler()
        app.run()


if __name__ == "__main__":
    main()
