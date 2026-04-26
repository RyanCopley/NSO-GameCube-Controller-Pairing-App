#!/usr/bin/env python3
"""
NSO GameCube Controller Pairing App - Python/Tkinter Version

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
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)

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
from .controller_constants import (
    DEFAULT_CALIBRATION, MAX_SLOTS,
    make_ble_device_identity, make_usb_device_identity,
)
from .i18n import t
from .settings_manager import SettingsManager


def setup_logging(debug: bool = False):
    """Configure logging for the application.

    When debug is True, sets DEBUG level and logs to both stderr and a file.
    Otherwise, sets WARNING level (quiet by default).
    """
    root_logger = logging.getLogger('gc_controller')
    root_logger.setLevel(logging.DEBUG if debug else logging.WARNING)

    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    root_logger.addHandler(stderr_handler)

    if debug:
        try:
            log_dir = _get_settings_dir()
            log_file = os.path.join(log_dir, 'gc_controller_debug.log')
            file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
            file_handler.setFormatter(fmt)
            root_logger.addHandler(file_handler)
            print(f"Debug log: {log_file}", file=sys.stderr)
        except Exception:
            pass


def _get_settings_dir() -> str:
    """Return a writable directory for storing settings.

    When running as a frozen PyInstaller bundle the cwd may be read-only
    (e.g. ``/`` on macOS .app bundles), so we fall back to a platform-
    appropriate user data directory.  In development (non-frozen) we keep
    using cwd for backwards compatibility.
    """
    if getattr(sys, 'frozen', False):
        if sys.platform == 'darwin':
            base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
        elif sys.platform == 'win32':
            base = os.environ.get('APPDATA', os.path.expanduser('~'))
        else:
            base = os.environ.get('XDG_CONFIG_HOME', os.path.join(os.path.expanduser('~'), '.config'))
        settings_dir = os.path.join(base, 'NSO-GC-Controller')
        os.makedirs(settings_dir, exist_ok=True)
        return settings_dir
    return os.getcwd()


from .calibration import CalibrationManager
from .connection_manager import ConnectionManager
from .emulation_manager import EmulationManager
from .input_processor import InputProcessor
from .controller_slot import ControllerSlot, normalize_ble_address
from .ble.sw2_protocol import build_rumble_packet

# System tray support (optional).
# On macOS, pystray runs [NSApplication run] from a background thread which
# triggers a fatal "NSUpdateCycleInitialize() is called off the main thread"
# crash on macOS 26+.  The Dock icon (::tk::mac::ReopenApplication) provides
# window-restore without pystray, so we skip it entirely on Darwin.
if sys.platform == 'darwin':
    _TRAY_AVAILABLE = False
else:
    try:
        import pystray
        from PIL import Image as PILImage
        _TRAY_AVAILABLE = True
    except ImportError:
        _TRAY_AVAILABLE = False

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
    """Main application orchestrator for NSO GameCube Controller Pairing App"""

    def __init__(self, start_minimized: bool = False):
        import tkinter as tk
        from tkinter import messagebox
        import customtkinter
        from .controller_ui import ControllerUI
        from .ui_theme import apply_gc_theme

        self._tk = tk
        self._messagebox = messagebox

        apply_gc_theme()
        self.root = customtkinter.CTk(className='nso-gc-controller')
        self.root.title("NSO GameCube Controller Pairing App")
        self.root.configure(fg_color="#535486")
        self.root.minsize(720, 540)
        self._set_window_icon()

        # Per-slot calibration dicts
        self.slot_calibrations = [dict(DEFAULT_CALIBRATION) for _ in range(MAX_SLOTS)]

        # Settings
        self.settings_mgr = SettingsManager(self.slot_calibrations, _get_settings_dir())
        self.settings_mgr.load()

        # Ensure known_ble_devices exists in global config (slot 0)
        if 'known_ble_devices' not in self.slot_calibrations[0]:
            self.slot_calibrations[0]['known_ble_devices'] = {}

        # Ensure slot_assignments and device_links exist
        if 'slot_assignments' not in self.slot_calibrations[0]:
            self.slot_calibrations[0]['slot_assignments'] = {}
        if 'device_links' not in self.slot_calibrations[0]:
            self.slot_calibrations[0]['device_links'] = {}

        # Clear stale BLE slot_assignments from previous sessions.
        # On macOS, CoreBluetooth UUIDs are session-dependent and can change,
        # so persisting them across restarts causes wrong slot assignments.
        # Within a session, assignments are re-created as controllers connect,
        # preserving slot stability for disconnect/reconnect cycles.
        assignments = self.slot_calibrations[0]['slot_assignments']
        stale_ble = [k for k in assignments if k.startswith('ble:')]
        for k in stale_ble:
            del assignments[k]

        # Propagate per-slot global settings from slot 0 to all other slots
        for key in ('trigger_bump_100_percent', 'emulation_mode', 'stick_deadzone'):
            val = self.slot_calibrations[0].get(key)
            if val is not None:
                for i in range(1, MAX_SLOTS):
                    self.slot_calibrations[i][key] = val

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

        # Per-slot latest UI data — written by input threads, read by poll timer.
        # No Tk interaction from background threads; the main-thread timer
        # reads these at a fixed rate (~30 fps) so updates are naturally coalesced.
        self._latest_ui_data = [None] * MAX_SLOTS
        self._trigger_cal_live_timers: dict[int, str | None] = {}

        # BLE state (lazy-initialized on first pair via privileged subprocess)
        self._ble_available = is_ble_available()
        self._ble_subprocess = None
        self._ble_reader_thread = None
        self._ble_initialized = False
        self._ble_init_event = threading.Event()
        self._ble_init_result = None
        self._ble_pair_mode = {}  # slot_index -> 'pair' | 'reconnect' | 'autoscan'
        self._ble_slot_remap = {}  # subprocess_slot -> actual UI slot (when reassigned)
        self._diff_scan_callback = {}  # slot_index -> completion callback
        self._scan_stream_callback: dict[int, callable] = {}
        self._ble_known_scan_slot = None  # slot being scanned for known-addr matching

        # USB hotplug polling state
        self._usb_hotplug_active = False
        self._usb_hotplug_timer_id = None
        self._last_seen_usb_paths: set = set()

        # Auto-scan state
        self._auto_scan_active = False
        self._auto_scan_timer_id = None
        self._auto_scan_pending = False   # True while a scan_connect is in-flight for auto-scan
        self._auto_scan_slot = None       # slot_index used for current auto-scan command
        self._auto_scan_addr_index = 0   # round-robin index for known address targeting
        self._ble_init_in_progress = False

        # Track recent USB hotplug connections for cross-transport migration.
        # Maps slot_index -> (timestamp, usb_device_identity)
        self._recent_usb_hotplug: dict[int, tuple[float, str]] = {}

        self._ble_init_retry_count = 0

        # UI — pass list of cal_mgrs for live octagon drawing
        self.ui = ControllerUI(
            self.root,
            slot_calibrations=self.slot_calibrations,
            slot_cal_mgrs=[s.cal_mgr for s in self.slots],
            on_connect=self.connect_controller,
            on_cal_wizard=self.calibration_wizard_step,
            on_save=self.save_settings,
            on_pair=self.pair_controller if self._ble_available else None,
            on_cal_cancel=self.cancel_calibration,
            on_emulate_all=self.toggle_emulation_all,
            on_test_rumble_all=self.test_rumble_all,
            ble_available=self._ble_available,
            get_known_ble_devices=(self._get_known_ble_devices
                                  if self._ble_available else None),
            on_forget_ble_device=(self._forget_ble_device
                                 if self._ble_available else None),
            on_auto_save=self._auto_save,
            get_device_links=self._get_device_links,
            on_unlink_device=self._unlink_device,
        )

        # Now that UI is built, draw initial trigger markers for all slots
        for i in range(MAX_SLOTS):
            self.ui.draw_trigger_markers(i)

        # Start fixed-rate UI poll timer (reads input data at ~30 fps)
        self._start_ui_poll()

        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # System tray support
        self._tray_icon = None
        self._start_minimized = start_minimized
        if _TRAY_AVAILABLE:
            self._init_tray_icon()
            # Intercept minimize to go to tray when enabled
            self.root.bind('<Unmap>', self._on_window_unmap)
            # Re-apply tray state when setting changes
            self.ui.minimize_to_tray_var.trace_add(
                'write', lambda *_: self._on_tray_setting_changed())

        # macOS: clicking the Dock icon restores the window (pystray menu
        # bar icons don't work reliably from a background thread on macOS).
        if sys.platform == 'darwin':
            try:
                self.root.createcommand(
                    '::tk::mac::ReopenApplication', self._restore_window)
            except Exception:
                pass

        # Auto-connect if enabled (also starts USB hotplug polling)
        if self.slot_calibrations[0]['auto_connect']:
            self.root.after(100, self._auto_connect_then_hotplug)

        # Start/stop USB hotplug polling when the setting is toggled at runtime
        self.ui.auto_connect_var.trace_add(
            'write', lambda *_: self._on_auto_connect_toggled())

        # Auto-init BLE if we have known addresses and auto-scan is enabled
        if self._ble_available and self._get_known_ble_addresses() and self.slot_calibrations[0].get('auto_scan_ble', True):
            self.root.after(500, self._init_ble_async)

    # ── Slot persistence ────────────────────────────────────────────

    def _get_slot_assignments(self) -> dict:
        return self.slot_calibrations[0].get('slot_assignments', {})

    def _get_device_links(self) -> dict:
        return self.slot_calibrations[0].get('device_links', {})

    def _resolve_slot_for_device(self, device_identity: str) -> int | None:
        """Look up the preferred slot for a device identity.

        Checks slot_assignments directly, then follows device_links
        for cross-transport matches (e.g. BLE MAC linked to USB path).
        Returns the slot index or None if unknown.
        """
        assignments = self._get_slot_assignments()

        # Direct lookup
        slot = assignments.get(device_identity)
        if slot is not None:
            return slot

        # Cross-transport lookup via device_links (bidirectional)
        links = self._get_device_links()
        linked = links.get(device_identity)
        if linked:
            slot = assignments.get(linked)
            if slot is not None:
                return slot

        # Reverse lookup: check if any linked identity points to this one
        for link_key, link_val in links.items():
            if link_val == device_identity:
                slot = assignments.get(link_key)
                if slot is not None:
                    return slot

        return None

    def _save_slot_assignment(self, device_identity: str, slot_index: int):
        """Persist the device -> slot mapping and auto-save."""
        assignments = self.slot_calibrations[0].setdefault('slot_assignments', {})
        if assignments.get(device_identity) != slot_index:
            assignments[device_identity] = slot_index
            self._auto_save()

    def _link_devices(self, identity_a: str, identity_b: str):
        """Create a bidirectional link between two device identities (e.g. USB <-> BLE)."""
        links = self.slot_calibrations[0].setdefault('device_links', {})
        if links.get(identity_a) != identity_b:
            links[identity_a] = identity_b
            self._auto_save()
            logger.info("Linked devices: %s <-> %s", identity_a, identity_b)

    def _unlink_device(self, identity: str):
        """Remove a device link (both directions)."""
        links = self.slot_calibrations[0].get('device_links', {})
        removed = False
        if identity in links:
            partner = links.pop(identity)
            removed = True
            if links.get(partner) == identity:
                del links[partner]
        for k, v in list(links.items()):
            if v == identity:
                del links[k]
                removed = True
        if removed:
            self._auto_save()

    def _get_linked_identity(self, device_identity: str) -> str | None:
        """Return the linked partner identity, or None."""
        links = self._get_device_links()
        linked = links.get(device_identity)
        if linked:
            return linked
        for k, v in links.items():
            if v == device_identity:
                return k
        return None

    def _select_slot_tab(self, slot_index: int):
        """Switch the UI tab view to show the given slot."""
        try:
            tab_name = self.ui._tab_names[slot_index]
            self.ui.tabview.set(tab_name)
        except Exception:
            pass

    def _check_dual_connection(self, slot_index: int):
        """Check if the device on this slot has a linked partner on another slot.

        If found, update both slots' UI badges to show dual connection.
        """
        slot = self.slots[slot_index]
        if not slot.device_identity:
            return
        linked = self._get_linked_identity(slot.device_identity)
        if not linked:
            return
        for other_slot in self.slots:
            if other_slot.index == slot_index:
                continue
            if other_slot.is_connected and other_slot.device_identity == linked:
                # Both transports are active — update badges
                self.ui.update_tab_status(
                    slot_index, connected=True, emulating=slot.is_emulating,
                    connection_mode='dual')
                self.ui.update_tab_status(
                    other_slot.index, connected=True,
                    emulating=other_slot.is_emulating,
                    connection_mode='dual')
                self.ui.update_status(
                    slot_index,
                    t("ui.dual_connection_warning"))
                self.ui.update_status(
                    other_slot.index,
                    t("ui.dual_connection_warning"))
                return

    def _find_slot_for_device(self, device_identity: str,
                              exclude_slots: set | None = None) -> int:
        """Determine the best slot for a device.

        Returns the preferred persistent slot if available, otherwise
        the first free slot.  *exclude_slots* is a set of indices that
        are already occupied and must not be reused.
        """
        exclude = exclude_slots or set()

        preferred = self._resolve_slot_for_device(device_identity)
        if preferred is not None and preferred not in exclude:
            slot = self.slots[preferred]
            if not slot.is_connected:
                return preferred

        # Fallback: first free slot
        for i in range(MAX_SLOTS):
            if i not in exclude and not self.slots[i].is_connected:
                return i

        return -1

    def _resolve_ble_target_slot(self, subprocess_slot: int,
                                  device_identity: str) -> int | None:
        """Pick the right slot for an incoming BLE connection.

        Priority:
          1. Persistent slot preference (if free)
          2. The slot the subprocess used (if free)
          3. First free slot
        Returns None if every slot is occupied.
        """
        preferred = self._resolve_slot_for_device(device_identity)
        if preferred is not None and not self.slots[preferred].is_connected:
            return preferred

        if not self.slots[subprocess_slot].is_connected:
            return subprocess_slot

        for i in range(MAX_SLOTS):
            if not self.slots[i].is_connected:
                return i

        return None

    # ── Connection ───────────────────────────────────────────────────

    def connect_controller(self, slot_index: int):
        """Connect to GameCube controller on a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        if slot.is_connected:
            logger.info("Slot %d: disconnecting (toggle)", slot_index)
            self.disconnect_controller(slot_index)
            return

        # Enumerate available HID devices
        all_hid = ConnectionManager.enumerate_devices()
        logger.debug("Slot %d: found %d HID device(s)", slot_index, len(all_hid))

        # Filter out paths already claimed by other slots (USB only)
        claimed_paths = set()
        for i, s in enumerate(self.slots):
            if (i != slot_index and s.is_connected
                    and s.connection_mode == 'usb' and s.conn_mgr.device_path):
                claimed_paths.add(s.conn_mgr.device_path)

        # Auto — pick first unclaimed
        available = [d for d in all_hid if d['path'] not in claimed_paths]
        if not available:
            self.ui.update_status(slot_index, t("ui.no_unclaimed"))
            return
        target_info = available[0]
        target_path = target_info['path']

        # Initialize all USB devices (send init data)
        usb_devices = ConnectionManager.enumerate_usb_devices()
        for usb_dev in usb_devices:
            slot.conn_mgr.initialize_via_usb(usb_device=usb_dev)

        # Open specific HID device by path
        if not slot.conn_mgr.init_hid_device(device_path=target_path):
            return

        slot.device_path = target_path
        slot.connection_mode = 'usb'

        # Build device identity and persist slot assignment
        dev_id = make_usb_device_identity(target_info)
        slot.device_identity = dev_id
        self._save_slot_assignment(dev_id, slot_index)

        # Save the path as the preferred device for this slot (runtime only)
        path_str = target_path.decode('utf-8', errors='replace')
        self.slot_calibrations[slot_index]['preferred_device_path'] = path_str

        slot.input_proc.start()

        sui.connect_btn.configure(text=t("ui.disconnect_usb"))
        if sui.pair_btn:
            sui.pair_btn.configure(state='disabled')
        self.ui.update_tab_status(
            slot_index, connected=True, emulating=False, connection_mode='usb')
        self.toggle_emulation(slot_index)
        self._sync_player_leds()
        self._check_dual_connection(slot_index)

        if self._needs_calibration(slot_index):
            self.ui.update_status(slot_index, t("ui.new_controller_cal"))

    def _reset_rumble(self, slot_index: int):
        """Send rumble OFF if currently ON and reset rumble state."""
        slot = self.slots[slot_index]
        if not slot.rumble_state:
            return
        slot.rumble_state = False
        packet = build_rumble_packet(False, slot.rumble_tid)
        slot.rumble_tid = (slot.rumble_tid + 1) & 0x0F
        if slot.ble_connected:
            self._send_ble_cmd({
                "cmd": "rumble",
                "slot_index": slot_index,
                "data": base64.b64encode(packet).decode('ascii'),
            })
        elif slot.conn_mgr.device:
            slot.conn_mgr.send_rumble(False)

    def disconnect_controller(self, slot_index: int):
        """Disconnect from controller on a specific slot."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        # Stop live trigger display and cancel in-progress calibration
        self._stop_trigger_cal_live(slot_index)
        slot.cal_mgr.trigger_cal_cancel()
        self._show_cal_cancel(slot_index, False)
        sui.cal_wizard_btn.configure(text=t("ui.cal_wizard"))

        # If BLE-connected, use BLE disconnect path
        if slot.ble_connected:
            self._disconnect_ble(slot_index)
            return

        self._reset_rumble(slot_index)
        slot.input_proc.stop()
        slot.emu_mgr.stop()
        slot.conn_mgr.disconnect()
        slot.device_path = None
        slot.device_identity = None

        sui.connect_btn.configure(text=t("ui.connect_usb"))
        if sui.pair_btn:
            sui.pair_btn.configure(state='normal')
        self.ui.update_status(slot_index, t("ui.ready"))
        self.ui.reset_slot_ui(slot_index)
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)

    # ── BLE subprocess helpers ────────────────────────────────────────

    def _start_ble_subprocess(self):
        """Start the BLE subprocess. Uses pkexec on Linux, direct spawn on macOS/Windows."""
        frozen = getattr(sys, 'frozen', False)
        if sys.platform == 'darwin' or sys.platform == 'win32':
            if frozen:
                cmd = [sys.executable, '--bleak-subprocess']
            else:
                script_path = os.path.join(
                    os.path.dirname(__file__), 'ble', 'bleak_subprocess.py')
                python_path = os.pathsep.join(p for p in sys.path if p)
                cmd = [sys.executable, script_path, python_path]
            self._ble_subprocess = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        else:
            if frozen:
                cmd = ['pkexec', sys.executable, '--ble-subprocess']
            else:
                script_path = os.path.join(
                    os.path.dirname(__file__), 'ble', 'ble_subprocess.py')
                python_path = os.pathsep.join(p for p in sys.path if p)
                cmd = ['pkexec', sys.executable, script_path, python_path]
            self._ble_subprocess = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

        self._ble_reader_thread = threading.Thread(
            target=self._ble_event_reader, daemon=True)
        self._ble_reader_thread.start()

    def _send_ble_cmd(self, cmd: dict):
        """Send a JSON-line command to the BLE subprocess."""
        if self._ble_subprocess and self._ble_subprocess.poll() is None:
            try:
                line = json.dumps(cmd, separators=(',', ':')) + '\n'
                self._ble_subprocess.stdin.write(line.encode('utf-8'))
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
        self._ble_slot_remap.clear()

    def _ble_event_reader(self):
        """Read events from the BLE subprocess stdout (runs in a thread).

        Handles two formats on the binary stdout stream:
        - Binary data packets: 0xFF + slot(1) + payload(64) = 66 bytes
        - JSON text lines: UTF-8 encoded, terminated by newline
        """
        try:
            stdout = self._ble_subprocess.stdout
            while True:
                header = stdout.read(1)
                if not header:
                    break
                if header[0] == 0xFF:
                    packet = stdout.read(65)
                    if len(packet) < 65:
                        break
                    si = self._ble_slot_remap.get(packet[0], packet[0])
                    if 0 <= si < len(self.slots):
                        self.slots[si].ble_data_queue.put(packet[1:65])
                    continue

                rest = stdout.readline()
                line = (header + rest).decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get('e')

                if not self._ble_initialized and etype in (
                        'ready', 'bluez_stopped', 'open_ok', 'error'):
                    self._ble_init_result = event
                    self._ble_init_event.set()
                    continue

                self.root.after(
                    0, lambda ev=event: self._handle_ble_event(ev))
        except Exception:
            pass

    def _handle_ble_event(self, event):
        """Handle a BLE runtime event on the main (Tkinter) thread."""
        etype = event.get('e')
        si = event.get('s')

        if etype == 'status' and si is not None:
            # Suppress status updates for background auto-scan
            if self._ble_pair_mode.get(si) != 'autoscan':
                self.ui.update_ble_status(si, event.get('msg', ''))

        elif etype == 'connected' and si is not None:
            mac = event.get('mac')
            mode = self._ble_pair_mode.pop(si, None)
            logger.info("BLE connected: slot=%d  mac=%s  mode=%s",
                        si, mac, mode)
            if mode is None:
                # Stale event from a cancelled auto-scan — disconnect
                logger.info("Ignoring stale BLE connected event on slot %d "
                            "(no active pair mode), disconnecting", si)
                self._send_ble_cmd({
                    "cmd": "disconnect",
                    "slot_index": si,
                    "address": mac,
                })
            elif mode == 'autoscan':
                self._on_auto_scan_connected(si, mac)
            elif mode in ('pair', 'wizard'):
                self._on_pair_complete(si, mac)
            else:
                self._on_reconnect_complete(si, mac)

        elif etype == 'connect_error' and si is not None:
            msg = event.get('msg', 'Connection failed')
            mode = self._ble_pair_mode.pop(si, None)
            logger.info("BLE connect_error: slot=%d  mode=%s  error=%s",
                        si, mode, msg)
            if mode is None:
                logger.debug("Ignoring stale connect_error on slot %d", si)
            elif mode == 'autoscan':
                self._on_auto_scan_failed(si, msg)
            elif mode in ('pair', 'wizard'):
                self._on_pair_complete(si, None, error=msg)
            else:
                self.root.after(
                    3000, lambda _si=si: self._attempt_ble_reconnect(_si))

        elif etype == 'devices_found' and si is not None:
            self._on_devices_found(si, event.get('devices', []))

        elif etype == 'device_detected' and si is not None:
            cb = self._scan_stream_callback.get(si)
            if cb:
                cb(event.get('device', {}))

        elif etype == 'disconnected' and si is not None:
            actual_si = self._ble_slot_remap.get(si, si)
            logger.info("BLE disconnected: subprocess_slot=%d actual_slot=%d",
                        si, actual_si)
            self._on_ble_disconnect(actual_si)

        elif etype == 'error':
            self._messagebox.showerror(
                t("error.ble"), event.get('msg', 'Unknown error'))

    # ── BLE ───────────────────────────────────────────────────────────

    def _init_ble(self) -> bool:
        """Lazy-initialize BLE subsystem on first pair attempt.

        On Linux, spawns a privileged subprocess via pkexec (raw HCI access
        requires elevated privileges). On macOS, spawns a regular subprocess
        using Bleak/CoreBluetooth (no elevated privileges needed).
        Returns True on success.
        """
        if self._ble_initialized:
            return True

        # If async init is running, wait for it instead of starting a second subprocess
        if self._ble_init_in_progress:
            deadline = time.monotonic() + 30
            while self._ble_init_in_progress and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.1)
            return self._ble_initialized

        if sys.platform == 'linux' and not shutil.which('pkexec'):
            self._messagebox.showerror(
                t("error.ble"), t("error.ble_pkexec"))
            return False

        try:
            self._start_ble_subprocess()
        except Exception as e:
            self._messagebox.showerror(
                t("error.ble"), t("error.ble_start_failed", error=e))
            return False

        # Wait for subprocess to start (user authenticates via pkexec on Linux)
        result = self._wait_ble_init(timeout=60)
        if not result or result.get('e') != 'ready':
            self._cleanup_ble()
            self._messagebox.showerror(
                t("error.ble"), t("error.ble_auth_cancelled"))
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
                t("error.ble"), t("error.ble_adapter", msg=msg))
            return False

        self._ble_initialized = True
        return True

    def _init_ble_async(self):
        """Non-blocking BLE init. Runs the full init sequence in a background thread.

        On completion, posts _on_ble_init_complete() to the main thread.
        On Linux this triggers pkexec for elevated privileges.
        """
        if self._ble_initialized or self._ble_init_in_progress:
            if self._ble_initialized:
                self._start_auto_scan()
            return

        self._ble_init_in_progress = True

        def _bg_init():
            try:
                success = self._init_ble_background()
                self.root.after(0, lambda: self._on_ble_init_complete(success))
            except Exception:
                self.root.after(0, lambda: self._on_ble_init_complete(False))

        threading.Thread(target=_bg_init, daemon=True).start()

    def _init_ble_background(self) -> bool:
        """Run the full BLE init sequence (blocking). Called from background thread.

        Same as _init_ble() but without messagebox error dialogs (silent for auto-init).
        """
        if sys.platform == 'linux' and not shutil.which('pkexec'):
            return False

        try:
            self._start_ble_subprocess()
        except Exception:
            return False

        # Wait for subprocess to start
        result = self._wait_ble_init(timeout=60)
        if not result or result.get('e') != 'ready':
            self._cleanup_ble()
            return False

        # Stop BlueZ (Linux only — must release HCI adapter for Bumble)
        self._send_ble_cmd({"cmd": "stop_bluez"})
        result = self._wait_ble_init(timeout=15)
        if not result or result.get('e') != 'bluez_stopped':
            self._cleanup_ble()
            return False

        # Open HCI adapter
        self._send_ble_cmd({"cmd": "open"})
        result = self._wait_ble_init(timeout=15)
        if not result or result.get('e') == 'error':
            self._cleanup_ble()
            return False

        self._ble_initialized = True
        return True

    def _on_ble_init_complete(self, success: bool):
        """Handle completion of async BLE init on the main thread."""
        self._ble_init_in_progress = False

        if success:
            self._ble_init_retry_count = 0
            self._start_auto_scan()
        else:
            self._ble_init_retry_count += 1
            if self._ble_init_retry_count < 3 and self.slot_calibrations[0].get('auto_scan_ble', True):
                # Retry after 30s
                self.root.after(30000, self._init_ble_async)

    def pair_controller(self, slot_index: int):
        """Start BLE pairing to discover a NEW controller.

        Auto-scan handles reconnection to known controllers in the background.
        This button is exclusively for discovering new controllers:
        - macOS/Windows: launch differential scan wizard
        - Linux: scan_connect without target (discover any Nintendo controller)

        Always fills the first available slot regardless of which tab's button
        was clicked. If the clicked slot is BLE-connected, disconnects it instead.
        """
        logger.info("Slot %d: initiating BLE pairing", slot_index)
        slot = self.slots[slot_index]

        # If already BLE-connected on this slot, disconnect
        if slot.ble_connected:
            self._disconnect_ble(slot_index)
            return

        # Cancel any in-flight auto-scan BEFORE searching for a free slot,
        # so that auto-scan's pair-mode entries don't block the preferred slot.
        self._cancel_inflight_auto_scan()

        # Redirect to the first available slot
        target_slot = None
        for i in range(MAX_SLOTS):
            if not self.slots[i].is_connected and i not in self._ble_pair_mode:
                target_slot = i
                break
        if target_slot is None:
            self.ui.update_status(slot_index, t("ui.no_free_slots"))
            return
        slot_index = target_slot
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        # If USB-connected on target slot, disconnect USB first
        if slot.is_connected and slot.connection_mode == 'usb':
            self.disconnect_controller(slot_index)

        # Init BLE subsystem
        if not self._init_ble():
            return

        # Mark this slot as actively pairing BEFORE starting auto-scan,
        # so auto-scan won't interfere with the manual pairing flow.
        self._ble_pair_mode[slot_index] = 'pair'

        # Start auto-scan if not already active (first manual pair initializes it)
        if not self._auto_scan_active:
            self._start_auto_scan()

        # Disable pair button during pairing
        if sui.pair_btn:
            sui.pair_btn.configure(state='disabled')
        self.ui.update_ble_status(slot_index, t("ble.initializing"))

        # Drain any stale data from the queue
        while not slot.ble_data_queue.empty():
            try:
                slot.ble_data_queue.get_nowait()
            except Exception:
                break

        # Build exclude list of already-connected BLE addresses
        exclude = []
        for s in self.slots:
            if s.ble_connected and s.ble_address:
                exclude.append(s.ble_address.upper())

        # macOS/Windows: launch scan dialog to discover a new controller
        if sys.platform != 'linux':
            self._show_controller_scan(slot_index, exclude)
            return

        # Linux: scan_connect without target (auto-identify via handshake)
        self._send_ble_cmd({
            "cmd": "scan_connect",
            "slot_index": slot_index,
            "target_address": None,
            "exclude_addresses": exclude if exclude else None,
        })

    def _on_devices_found(self, slot_index: int, devices: list[dict]):
        """Handle devices_found event.

        Routes to:
        - Diff scan wizard completion callback (if active)
        - Known-address matching logic (if scanning for known addresses)
        - Original picker dialog (fallback)
        """
        logger.debug("Slot %d: devices_found — %d device(s)", slot_index, len(devices))
        for d in devices:
            logger.debug("  %s  name=%r  rssi=%s  mfg=%s  svc=%s",
                         d.get('address'), d.get('name'), d.get('rssi'),
                         d.get('manufacturer_data', {}),
                         d.get('service_uuids', []))

        # Route to wizard completion callback if one is active
        cb = self._diff_scan_callback.pop(slot_index, None)
        if cb is not None:
            cb(devices)
            return

        # Route to known-address matching logic
        if self._ble_known_scan_slot == slot_index:
            self._ble_known_scan_slot = None
            self._on_known_scan_result(slot_index, devices)
            return

        # Original picker fallback
        from .ui_ble_dialog import BLEDevicePickerDialog

        sui = self.ui.slots[slot_index]

        if not devices:
            self.ui.update_ble_status(slot_index, t("ble.no_devices"))
            if sui.pair_btn:
                sui.pair_btn.configure(state='normal')
            return

        picker = BLEDevicePickerDialog(self.root, devices)
        chosen_address = picker.show()

        if not chosen_address:
            # User cancelled
            self.ui.update_ble_status(slot_index, t("ble.pairing_cancelled"))
            if sui.pair_btn:
                sui.pair_btn.configure(state='normal')
            return

        # Send connect_device with the chosen address
        self.ui.update_ble_status(slot_index, t("ble.connecting"))
        self._ble_pair_mode[slot_index] = 'pair'
        self._send_ble_cmd({
            "cmd": "connect_device",
            "slot_index": slot_index,
            "address": chosen_address,
        })

    def _on_pair_complete(self, slot_index: int, mac: str | None,
                          error: str | None = None):
        """Handle completion of BLE pairing attempt."""
        if mac:
            dev_id = make_ble_device_identity(mac)

            # Resolve the best slot: persistent preference > subprocess slot > first free
            target = self._resolve_ble_target_slot(slot_index, dev_id)
            if target is None:
                # No free slot at all — disconnect BLE and report error
                logger.warning("BLE paired %s but no free slot available", mac)
                self._send_ble_cmd({
                    "cmd": "disconnect",
                    "slot_index": slot_index,
                    "address": mac,
                })
                self._add_known_ble_device(mac)
                sui = self.ui.slots[slot_index]
                if sui.pair_btn:
                    sui.pair_btn.configure(state='normal')
                self.ui.update_ble_status(slot_index, t("ble.error", error="No free slot"))
                return

            subprocess_slot = slot_index
            if target != slot_index:
                # Clean up the original slot's pairing state
                self._ble_pair_mode.pop(slot_index, None)
                old_sui = self.ui.slots[slot_index]
                if old_sui.pair_btn:
                    old_sui.pair_btn.configure(state='normal')

            slot_index = target
            slot = self.slots[slot_index]
            sui = self.ui.slots[slot_index]

            # Update the BLE controller's LED and data routing if the slot changed
            if subprocess_slot != slot_index:
                logger.info("Reassigned BLE from subprocess slot %d → slot %d, "
                            "updating LED", subprocess_slot, slot_index)
                self._ble_slot_remap[subprocess_slot] = slot_index
                self._send_ble_cmd({
                    "cmd": "set_led",
                    "slot_index": subprocess_slot,
                    "new_slot_index": slot_index,
                })

            # Stop any USB input thread before touching the device — the
            # read loop caches the device reference at thread start, so
            # closing it from another thread races with `device.read()`.
            # This also lets `input_proc.start(mode='ble')` below take
            # effect (start() no-ops while is_reading is True).
            slot.input_proc.stop()

            # Clear leftover USB state so hotplug doesn't think
            # this slot still claims a USB path.
            if slot.conn_mgr.device:
                try:
                    slot.conn_mgr.device.close()
                except Exception:
                    pass
                slot.conn_mgr.device = None
            slot.conn_mgr.device_path = None
            slot.device_path = None

            slot.ble_connected = True
            slot.ble_address = mac
            slot.connection_mode = 'ble'
            slot.device_identity = dev_id
            self._save_slot_assignment(dev_id, slot_index)

            # Register device and load its calibration into this slot
            self._add_known_ble_device(mac)
            self._load_device_calibration(slot_index, mac)

            # Start input processor in BLE mode
            slot.input_proc.start(mode='ble')

            if sui.pair_btn:
                sui.pair_btn.configure(text=t("btn.disconnect"), state='normal')
            sui.connect_btn.configure(state='disabled')
            self.ui.update_ble_status(slot_index, t("ble.connected", mac=mac))
            if self._needs_calibration(slot_index):
                self.ui.update_status(slot_index, t("ui.new_controller_cal"))
            else:
                self.ui.update_status(slot_index, t("ui.connected_ble"))
            self.ui.update_tab_status(
                slot_index, connected=True, emulating=False, connection_mode='ble')
            self._select_slot_tab(slot_index)
            self.toggle_emulation(slot_index)
            self._check_dual_connection(slot_index)

            # Ensure auto-scan is running after successful pair
            if not self._auto_scan_active and self._ble_initialized:
                self._start_auto_scan()
        else:
            sui = self.ui.slots[slot_index]
            if sui.pair_btn:
                sui.pair_btn.configure(state='normal')
            if error:
                self.ui.update_ble_status(slot_index, t("ble.error", error=error))

    def _get_known_ble_devices(self) -> dict:
        """Return the global known BLE devices registry {mac: calibration_dict}."""
        return self.slot_calibrations[0].get('known_ble_devices', {})

    def _get_known_ble_addresses(self) -> list[str]:
        """Return list of known BLE MAC addresses (derived from device registry)."""
        return list(self._get_known_ble_devices().keys())

    def _add_known_ble_device(self, address: str):
        """Add a BLE device to the known registry (creates entry if new)."""
        devices = self.slot_calibrations[0].setdefault('known_ble_devices', {})
        addr_upper = address.upper()
        if addr_upper not in devices:
            devices[addr_upper] = {}
            self._auto_save()

    def _save_device_calibration(self, slot_index: int, mac: str):
        """Copy per-device calibration keys from a slot into the device registry."""
        from .controller_constants import BLE_DEVICE_CAL_KEYS
        devices = self.slot_calibrations[0].setdefault('known_ble_devices', {})
        addr_upper = mac.upper()
        dev_cal = devices.setdefault(addr_upper, {})
        cal = self.slot_calibrations[slot_index]
        for key in BLE_DEVICE_CAL_KEYS:
            if key in cal:
                dev_cal[key] = cal[key]

    def _load_device_calibration(self, slot_index: int, mac: str):
        """Load per-device calibration from the device registry into a slot."""
        from .controller_constants import BLE_DEVICE_CAL_KEYS
        devices = self._get_known_ble_devices()
        dev_cal = devices.get(mac.upper(), {})
        cal = self.slot_calibrations[slot_index]
        for key in BLE_DEVICE_CAL_KEYS:
            if key in dev_cal:
                cal[key] = dev_cal[key]
        # Refresh the CalibrationManager cache with new values
        self.slots[slot_index].cal_mgr.refresh_cache()
        # Redraw octagon and trigger markers with device's calibration
        self.ui.redraw_octagons(slot_index)
        self.ui.draw_trigger_markers(slot_index)

    def _forget_ble_device(self, mac: str):
        """Remove a single BLE device from the known registry."""
        devices = self.slot_calibrations[0].get('known_ble_devices', {})
        addr_upper = mac.upper()
        if addr_upper in devices:
            del devices[addr_upper]
            # Also clean up slot assignment and device links for this identity
            dev_id = make_ble_device_identity(addr_upper)
            assignments = self.slot_calibrations[0].get('slot_assignments', {})
            assignments.pop(dev_id, None)
            self._unlink_device(dev_id)
            self._auto_save()
            # Disconnect if this device is currently connected on any slot
            for slot in self.slots:
                if slot.ble_address and slot.ble_address.upper() == addr_upper:
                    self.root.after(0, lambda s=slot: self.disconnect_controller(s.index))
            # Stop auto-scan if no known devices remain
            if not devices:
                self._stop_auto_scan()

    def _clear_known_ble_devices(self):
        """Remove all known BLE devices and stop auto-scan."""
        self.slot_calibrations[0]['known_ble_devices'] = {}
        self._auto_save()
        self._stop_auto_scan()

    def _try_known_addresses_scan(self, slot_index: int):
        """Scan once and check if any known address is advertising."""
        self._ble_known_scan_slot = slot_index
        self.ui.update_ble_status(slot_index, t("ble.scanning_known"))
        self._send_ble_cmd({
            "cmd": "scan_devices",
            "slot_index": slot_index,
        })

    def _on_known_scan_result(self, slot_index: int, devices: list[dict]):
        """Handle scan results when checking for known addresses."""
        known = set(a.upper() for a in self._get_known_ble_addresses())
        found_addresses = {d['address'].upper() for d in devices}

        match = known & found_addresses
        if match:
            # Connect to the first matching known address
            addr = next(iter(match))
            self.ui.update_ble_status(slot_index, f"Found known controller: {addr}")
            self._ble_pair_mode[slot_index] = 'pair'
            self._send_ble_cmd({
                "cmd": "connect_device",
                "slot_index": slot_index,
                "address": addr,
            })
        else:
            # No known address found — fall through to wizard
            self._show_controller_scan(slot_index, [])

    def _show_controller_scan(self, slot_index: int,
                              exclude_addresses: list[str] | None = None):
        """Launch the live-scan controller discovery dialog."""
        from .ui_ble_scan_wizard import BLEControllerScanDialog

        self._ble_pair_mode[slot_index] = 'wizard'

        def on_start_scan():
            self._send_ble_cmd({
                "cmd": "scan_start",
                "slot_index": slot_index,
            })

        def on_stop_scan():
            self._scan_stream_callback.pop(slot_index, None)
            self._send_ble_cmd({"cmd": "scan_stop"})

        dialog = BLEControllerScanDialog(
            self.root,
            on_start_scan=on_start_scan,
            on_stop_scan=on_stop_scan,
            exclude_addresses=set(exclude_addresses or ()))

        self._scan_stream_callback[slot_index] = dialog.add_device

        chosen_address = dialog.show()

        self._scan_stream_callback.pop(slot_index, None)

        sui = self.ui.slots[slot_index]

        if not chosen_address:
            self._ble_pair_mode.pop(slot_index, None)
            self.ui.update_ble_status(slot_index, t("ble.pairing_cancelled"))
            if sui.pair_btn:
                sui.pair_btn.configure(state='normal')
            return

        logger.info("Slot %d: user selected %s — connecting...",
                     slot_index, chosen_address)
        self.ui.update_ble_status(slot_index, t("ble.connecting"))
        self._ble_pair_mode[slot_index] = 'pair'
        self._send_ble_cmd({
            "cmd": "connect_device",
            "slot_index": slot_index,
            "address": chosen_address,
        })

    # ── Auto-scan loop ─────────────────────────────────────────────

    def _start_auto_scan(self):
        """Begin the periodic auto-scan loop for known BLE controllers."""
        if self._auto_scan_active:
            return
        self._auto_scan_active = True
        self.ui.set_ble_scanning(True)
        self._auto_scan_tick()

    def _stop_auto_scan(self):
        """Stop the periodic auto-scan loop."""
        self._auto_scan_active = False
        self.ui.set_ble_scanning(False)
        if self._auto_scan_timer_id is not None:
            self.root.after_cancel(self._auto_scan_timer_id)
            self._auto_scan_timer_id = None

    def _cancel_inflight_auto_scan(self):
        """Cancel ALL in-flight BLE scan/connect tasks in the subprocess.

        Sends cancel_all_scans to kill every pending task, then cleans up
        all auto-scan state on the parent side to prevent stale events.
        """
        # Clean up parent-side auto-scan tracking
        scan_slot = self._auto_scan_slot
        self._auto_scan_pending = False
        self._auto_scan_slot = None

        # Remove all autoscan entries from pair mode
        stale_slots = [s for s, m in self._ble_pair_mode.items()
                       if m == 'autoscan']
        for s in stale_slots:
            self._ble_pair_mode.pop(s, None)

        if scan_slot is not None:
            self._ble_pair_mode.pop(scan_slot, None)

        # Tell the subprocess to cancel every pending scan/connect task
        self._send_ble_cmd({"cmd": "cancel_all_scans"})
        logger.debug("Cancelled all in-flight BLE scans")

    def _ensure_auto_scan(self, delay_ms: int = 0):
        """Ensure auto-scan is running. Reschedule the next tick if already active."""
        if not self._ble_initialized or not self._get_known_ble_addresses():
            return
        if self._auto_scan_active:
            # Cancel existing timer and reschedule sooner
            if self._auto_scan_timer_id is not None:
                self.root.after_cancel(self._auto_scan_timer_id)
            self._auto_scan_timer_id = self.root.after(
                delay_ms, self._auto_scan_tick)
        else:
            self._auto_scan_active = True
            self.ui.set_ble_scanning(True)
            self._auto_scan_timer_id = self.root.after(
                delay_ms, self._auto_scan_tick)

    def _auto_scan_tick(self):
        """Periodic callback: scan for any known BLE controller.

        On Windows/Linux, targets a specific known address (round-robin) so
        the Bleak backend can direct-connect to bonded devices invisible to
        scans.  On macOS, uses a blind scan (no target) since CoreBluetooth
        peripheral cache is unreliable — handshake identification works better.
        """
        self._auto_scan_timer_id = None

        if not self._auto_scan_active or not self._ble_initialized:
            logger.debug("Auto-scan tick skipped (active=%s, init=%s)",
                         self._auto_scan_active, self._ble_initialized)
            return

        # Don't scan while another auto-scan is in-flight
        if self._auto_scan_pending:
            logger.debug("Auto-scan tick deferred (pending in-flight)")
            self._auto_scan_timer_id = self.root.after(
                5000, self._auto_scan_tick)
            return

        # Don't scan while a manual pair or reconnect is active
        active_modes = set(self._ble_pair_mode.values())
        if active_modes - {'autoscan'}:
            self._auto_scan_timer_id = self.root.after(
                5000, self._auto_scan_tick)
            return

        # Must have known addresses to auto-scan
        known = self._get_known_ble_addresses()
        if not known:
            self._auto_scan_timer_id = self.root.after(
                10000, self._auto_scan_tick)
            return

        # Build set of already-connected BLE addresses
        connected_addrs = set()
        for s in self.slots:
            if s.ble_connected and s.ble_address:
                connected_addrs.add(s.ble_address.upper())

        # Check if all known controllers are already connected
        unconnected = [a for a in known if a.upper() not in connected_addrs]
        if not unconnected:
            self._auto_scan_timer_id = self.root.after(
                10000, self._auto_scan_tick)
            return

        # Need a free slot
        slot_idx = self._pick_auto_scan_slot()
        if slot_idx is None:
            self._auto_scan_timer_id = self.root.after(
                10000, self._auto_scan_tick)
            return

        # Drain stale data from slot queue
        slot = self.slots[slot_idx]
        while not slot.ble_data_queue.empty():
            try:
                slot.ble_data_queue.get_nowait()
            except Exception:
                break

        # On Windows, bonded devices are invisible to BLE scans — target
        # a specific known address so the Bleak backend will attempt a
        # direct connection when the target is not found in scan results.
        # On macOS, CoreBluetooth UUIDs can become stale after re-pairing
        # or cache invalidation.  A blind scan with Nintendo device
        # filtering is more reliable than targeting a potentially stale UUID
        # (which wastes 20s on a failed direct-connect attempt).
        # On Linux (Bumble), a target address skips scanning and connects
        # directly, which is faster.
        if sys.platform == 'darwin':
            target = None
        else:
            target = unconnected[self._auto_scan_addr_index % len(unconnected)]
            self._auto_scan_addr_index += 1

        self._auto_scan_pending = True
        self._auto_scan_slot = slot_idx
        self._ble_pair_mode[slot_idx] = 'autoscan'
        self._send_ble_cmd({
            "cmd": "scan_connect",
            "slot_index": slot_idx,
            "target_address": target,
            "exclude_addresses": list(connected_addrs),
            "connect_timeout": 8,
        })

    def _pick_auto_scan_slot(self):
        """Pick the first free slot for auto-scan. Returns slot index or None."""
        subprocess_slots_in_use = set(self._ble_slot_remap.keys())
        for i in range(MAX_SLOTS):
            if (not self.slots[i].is_connected
                    and i not in self._ble_pair_mode
                    and i not in subprocess_slots_in_use):
                return i
        return None

    def _on_auto_scan_connected(self, slot_index: int, mac: str):
        """Handle successful auto-scan connection.

        On Linux/Windows, verifies the connected MAC is in the known list.
        On macOS, CoreBluetooth UUIDs are session-dependent and can change
        after the controller sleeps/wakes, so we accept any device that passed
        the scan's Nintendo filter + handshake verification.  The new UUID
        is added to known_ble_devices automatically.
        """
        self._auto_scan_pending = False
        self._auto_scan_slot = None

        # Verify the connected controller is known (skip on macOS where
        # CB UUIDs are unstable — the Nintendo device filter in
        # scan_and_connect already ensures only real controllers connect).
        known_upper = set(a.upper() for a in self._get_known_ble_addresses())
        if mac and mac.upper() not in known_upper:
            if sys.platform == 'darwin':
                logger.info("Auto-scan: new CB UUID %s — accepting "
                            "(macOS UUIDs are session-dependent)", mac)
            else:
                # Unknown controller — disconnect and retry
                self._send_ble_cmd({
                    "cmd": "disconnect",
                    "slot_index": slot_index,
                    "address": mac,
                })
                if self._auto_scan_active:
                    self._auto_scan_timer_id = self.root.after(
                        5000, self._auto_scan_tick)
                return

        # Resolve the best slot for this device (respects persistent
        # slot preferences for reconnection stability).
        dev_id = make_ble_device_identity(mac)
        target = self._resolve_ble_target_slot(slot_index, dev_id)
        if target is None:
            logger.info("Auto-scan: %s connected but no free slot", mac)
            self._send_ble_cmd({
                "cmd": "disconnect",
                "slot_index": slot_index,
                "address": mac,
            })
            if self._auto_scan_active:
                self._auto_scan_timer_id = self.root.after(
                    5000, self._auto_scan_tick)
            return

        subprocess_slot = slot_index
        if target != slot_index:
            self._ble_pair_mode.pop(slot_index, None)
            old_sui = self.ui.slots[slot_index]
            if old_sui.pair_btn:
                old_sui.pair_btn.configure(state='normal')

        slot_index = target
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        if subprocess_slot != slot_index:
            logger.info("Auto-scan: reassigned BLE from subprocess slot %d → "
                        "slot %d, updating LED", subprocess_slot, slot_index)
            self._ble_slot_remap[subprocess_slot] = slot_index
            self._send_ble_cmd({
                "cmd": "set_led",
                "slot_index": subprocess_slot,
                "new_slot_index": slot_index,
            })

        # Stop any USB input thread before touching the device — the
        # read loop caches the device reference at thread start, so
        # closing it from another thread races with `device.read()`.
        # This also lets `input_proc.start(mode='ble')` below take
        # effect (start() no-ops while is_reading is True).
        slot.input_proc.stop()

        # Clear leftover USB state so hotplug doesn't think
        # this slot still claims a USB path.
        if slot.conn_mgr.device:
            try:
                slot.conn_mgr.device.close()
            except Exception:
                pass
            slot.conn_mgr.device = None
        slot.conn_mgr.device_path = None
        slot.device_path = None

        slot.ble_connected = True
        slot.ble_address = mac
        slot.connection_mode = 'ble'
        slot.device_identity = dev_id
        self._save_slot_assignment(dev_id, slot_index)

        # Load device's calibration into this slot
        self._add_known_ble_device(mac)
        self._load_device_calibration(slot_index, mac)

        # Start input processor in BLE mode
        slot.input_proc.start(mode='ble')

        if sui.pair_btn:
            sui.pair_btn.configure(text=t("btn.disconnect"), state='normal')
        sui.connect_btn.configure(state='disabled')
        self.ui.update_status(slot_index, t("ui.auto_connected_ble"))
        self.ui.update_ble_status(slot_index, t("ble.connected", mac=mac))
        self.ui.update_tab_status(
            slot_index, connected=True, emulating=False, connection_mode='ble')
        self._select_slot_tab(slot_index)
        self.toggle_emulation(slot_index)
        self._check_dual_connection(slot_index)

        # Look for more controllers soon
        if self._auto_scan_active:
            self._auto_scan_timer_id = self.root.after(
                3000, self._auto_scan_tick)

    def _on_auto_scan_failed(self, slot_index: int, msg: str):
        """Handle failed auto-scan attempt (silent — controller may be off)."""
        self._auto_scan_pending = False
        self._auto_scan_slot = None

        # Re-enable pair button if it was disabled
        sui = self.ui.slots[slot_index]
        if sui.pair_btn and not self.slots[slot_index].ble_connected:
            sui.pair_btn.configure(state='normal')

        # Schedule next tick
        if self._auto_scan_active:
            self._auto_scan_timer_id = self.root.after(
                8000, self._auto_scan_tick)

    def _disconnect_ble(self, slot_index: int):
        """Disconnect BLE on a specific slot (user-initiated)."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        # Save device calibration before disconnecting
        if slot.ble_address:
            self._save_device_calibration(slot_index, slot.ble_address)

        self._reset_rumble(slot_index)
        slot.input_proc.stop()
        # Ensure stop_event is set even if stop() returned early (input proc
        # already stopped by an earlier unexpected disconnect).  This tells
        # any pending _attempt_ble_reconnect loop to abort.
        slot.input_proc.stop_event.set()
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
        slot.device_identity = None

        # Clean up any auto-scan state that targeted this slot
        if self._auto_scan_slot == slot_index:
            self._auto_scan_pending = False
            self._auto_scan_slot = None
        self._ble_pair_mode.pop(slot_index, None)

        if sui.pair_btn:
            sui.pair_btn.configure(text=t("ui.pair_wireless"), state='normal')
        sui.connect_btn.configure(state='normal')
        self.ui.update_status(slot_index, t("ui.ready"))
        self.ui.reset_slot_ui(slot_index)
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)

        # Reschedule auto-scan so it can reconnect this controller
        self._ensure_auto_scan(delay_ms=3000)

    def _on_ble_disconnect(self, slot_index: int):
        """Handle unexpected BLE disconnect."""
        slot = self.slots[slot_index]
        if not slot.ble_connected:
            return

        slot.reconnect_was_emulating = slot.emu_mgr.is_emulating
        slot.input_proc.stop()
        # Clear stop_event so _attempt_ble_reconnect doesn't mistake this
        # for a user-initiated disconnect (stop() sets it, but here the
        # disconnect is unexpected — we WANT to reconnect).
        slot.input_proc.stop_event.clear()
        if slot.emu_mgr.is_emulating:
            slot.emu_mgr.stop()

        slot.ble_connected = False

        # Clean up any auto-scan state that targeted this slot
        if self._auto_scan_slot == slot_index:
            self._auto_scan_pending = False
            self._auto_scan_slot = None
        self._ble_pair_mode.pop(slot_index, None)

        # Remove any data routing remap that pointed to this slot
        stale = [k for k, v in self._ble_slot_remap.items() if v == slot_index]
        for k in stale:
            del self._ble_slot_remap[k]

        # Check if a USB controller just connected on another slot —
        # if so, it's likely the same physical controller switching
        # from BLE to USB.  Migrate USB to this slot silently.
        self._try_cross_transport_migration(slot_index)
        if slot.is_connected:
            # Migration succeeded — no need to show disconnect/reconnect UI
            return

        sui = self.ui.slots[slot_index]

        self.ui.update_status(slot_index, t("ui.ble_disconnected_reconnecting"))
        self.ui.update_ble_status(slot_index, t("ble.reconnecting"))
        if sui.pair_btn:
            sui.pair_btn.configure(state='disabled')
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)

        # Rapid USB scan: the controller might be switching from BLE to USB.
        # Scan every 300ms for ~5s to catch the USB device ASAP and send
        # init commands before Windows processes raw gamepad inputs.
        self._start_rapid_usb_scan(slot_index)

        self._attempt_ble_reconnect(slot_index)

        # Ensure auto-scan is running (for reconnecting other known controllers)
        self._ensure_auto_scan()

    def _attempt_ble_reconnect(self, slot_index: int):
        """Try to reconnect BLE. Retries every 3 seconds."""
        slot = self.slots[slot_index]

        # Slot already reconnected via another transport (e.g. USB) — abort.
        if slot.is_connected:
            return

        # User clicked disconnect while we were waiting — abort
        if slot.input_proc.stop_event.is_set():
            self.ui.update_status(slot_index, t("ui.ready"))
            self.ui.update_ble_status(slot_index, "")
            self.ui.reset_slot_ui(slot_index)
            if self.ui.slots[slot_index].pair_btn:
                self.ui.slots[slot_index].pair_btn.configure(
                    text=t("ui.pair_wireless"), state='normal')
            self.ui.slots[slot_index].connect_btn.configure(state='normal')
            self.ui.update_tab_status(slot_index, connected=False, emulating=False)

            # Reconnect loop aborted — let auto-scan take over
            self._ensure_auto_scan(delay_ms=3000)
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
        if not mac:
            self.root.after(3000, lambda: self._attempt_ble_reconnect(slot_index))
            return

        # If the slot got claimed by USB while we were reconnecting, find a free one
        subprocess_slot = slot_index
        if self.slots[slot_index].is_connected:
            dev_id = make_ble_device_identity(mac)
            target = self._resolve_ble_target_slot(slot_index, dev_id)
            if target is None:
                logger.info("BLE reconnect: %s but no free slot", mac)
                self._send_ble_cmd({
                    "cmd": "disconnect",
                    "slot_index": slot_index,
                    "address": mac,
                })
                return
            slot_index = target

        if subprocess_slot != slot_index:
            logger.info("BLE reconnect: reassigned from subprocess slot %d → "
                        "slot %d, updating LED", subprocess_slot, slot_index)
            self._ble_slot_remap[subprocess_slot] = slot_index
            self._send_ble_cmd({
                "cmd": "set_led",
                "slot_index": subprocess_slot,
                "new_slot_index": slot_index,
            })

        slot = self.slots[slot_index]

        # Stop any USB input thread before touching the device — the
        # read loop caches the device reference at thread start, so
        # closing it from another thread races with `device.read()`.
        # This also lets `input_proc.start(mode='ble')` below take
        # effect (start() no-ops while is_reading is True).
        slot.input_proc.stop()

        # Clear leftover USB state so hotplug doesn't think
        # this slot still claims a USB path.
        if slot.conn_mgr.device:
            try:
                slot.conn_mgr.device.close()
            except Exception:
                pass
            slot.conn_mgr.device = None
        slot.conn_mgr.device_path = None
        slot.device_path = None

        slot.ble_connected = True
        slot.ble_address = mac
        slot.device_identity = make_ble_device_identity(mac)
        slot.input_proc.start(mode='ble')

        sui = self.ui.slots[slot_index]
        if sui.pair_btn:
            sui.pair_btn.configure(text=t("btn.disconnect"), state='normal')
        sui.connect_btn.configure(state='disabled')
        self.ui.update_status(slot_index, t("ble.reconnected"))
        self.ui.update_ble_status(slot_index, t("ble.connected", mac=mac))
        self.ui.update_tab_status(
            slot_index, connected=True, emulating=False, connection_mode='ble')
        self._select_slot_tab(slot_index)

        if slot.reconnect_was_emulating:
            slot.reconnect_was_emulating = False
            self.toggle_emulation(slot_index)

    def auto_connect_and_emulate(self):
        """Auto-connect all available controllers and start emulation.

        Respects persistent slot_assignments: if a device has a saved slot
        preference, it gets that slot.  Falls back to preferred_device_path
        and then first-come-first-served.
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

        claimed_paths: set = set()
        claimed_slots: set = set()

        def _do_connect(slot_idx, hid_info):
            path = hid_info['path']
            slot = self.slots[slot_idx]
            sui = self.ui.slots[slot_idx]
            if slot.conn_mgr.init_hid_device(device_path=path):
                claimed_paths.add(path)
                claimed_slots.add(slot_idx)
                slot.device_path = path
                slot.connection_mode = 'usb'
                dev_id = make_usb_device_identity(hid_info)
                slot.device_identity = dev_id
                self._save_slot_assignment(dev_id, slot_idx)
                path_str = path.decode('utf-8', errors='replace')
                self.slot_calibrations[slot_idx]['preferred_device_path'] = path_str
                slot.input_proc.start()
                sui.connect_btn.configure(text=t("ui.disconnect_usb"))
                if sui.pair_btn:
                    sui.pair_btn.configure(state='disabled')
                self.ui.update_tab_status(
                    slot_idx, connected=True, emulating=False, connection_mode='usb')
                self.toggle_emulation(slot_idx)
                return True
            return False

        # First pass: assign devices to their persisted slots
        for hid_info in all_hid:
            dev_id = make_usb_device_identity(hid_info)
            preferred = self._resolve_slot_for_device(dev_id)
            if preferred is not None and preferred not in claimed_slots:
                if not self.slots[preferred].is_connected:
                    if hid_info['path'] not in claimed_paths:
                        _do_connect(preferred, hid_info)

        # Second pass (legacy): preferred_device_path for devices without
        # a slot_assignments entry yet
        for i in range(MAX_SLOTS):
            if i in claimed_slots or self.slots[i].is_connected:
                continue
            saved = self.slot_calibrations[i].get('preferred_device_path', '')
            if not saved:
                continue
            pref_bytes = saved.encode('utf-8')
            for hid_info in all_hid:
                if hid_info['path'] == pref_bytes and pref_bytes not in claimed_paths:
                    _do_connect(i, hid_info)
                    break

        # Third pass: fill remaining slots with unclaimed devices (FCFS)
        for hid_info in all_hid:
            if hid_info['path'] in claimed_paths:
                continue
            dev_id = make_usb_device_identity(hid_info)
            slot_idx = self._find_slot_for_device(dev_id, exclude_slots=claimed_slots)
            if slot_idx < 0:
                break
            _do_connect(slot_idx, hid_info)

    def _sync_player_leds(self):
        """Re-send player LED commands to all connected USB controllers.

        Uses IOKit registry on macOS to correctly map each slot's HID device
        to its USB device, ensuring LEDs match GUI slot numbers.
        """
        hid_to_bus = ConnectionManager.build_hid_to_usb_bus_map()
        usb_devices = ConnectionManager.enumerate_usb_devices()
        bus_to_usb = {u.bus: u for u in usb_devices}

        for slot_idx, slot in enumerate(self.slots):
            if not slot.is_connected or not slot.device_path:
                continue

            path_str = slot.device_path
            if isinstance(path_str, bytes):
                path_str = path_str.decode('utf-8', errors='replace')

            try:
                dev_srv_id = int(path_str.split(':')[1])
            except (IndexError, ValueError):
                continue

            bus = hid_to_bus.get(dev_srv_id)
            if bus is not None and bus in bus_to_usb:
                ConnectionManager.set_player_led_usb(
                    bus_to_usb[bus], slot_idx + 1)

    def _auto_connect_then_hotplug(self):
        """Run startup auto-connect, then start hotplug polling."""
        self.auto_connect_and_emulate()
        self._log_all_hid_gamepads("startup")
        self._sync_player_leds()
        self._start_usb_hotplug()
        # Re-select first tab (tab rename during auto-connect can deselect it)
        if self.ui._tab_names:
            try:
                self.ui.tabview.set(self.ui._tab_names[0])
            except Exception:
                pass

    def _on_auto_connect_toggled(self):
        """React to the auto_connect setting being toggled at runtime."""
        if self.ui.auto_connect_var.get():
            self._start_usb_hotplug()
        else:
            self._stop_usb_hotplug()

    # ── USB hotplug polling ────────────────────────────────────────

    def _start_usb_hotplug(self):
        """Begin periodic USB enumeration to detect newly plugged controllers."""
        if self._usb_hotplug_active:
            return
        self._last_seen_usb_paths = {
            d['path'] for d in ConnectionManager.enumerate_devices()
        }
        self._usb_hotplug_active = True
        self._usb_hotplug_timer_id = self.root.after(
            2000, self._usb_hotplug_tick)

    def _stop_usb_hotplug(self):
        """Stop USB hotplug polling."""
        self._usb_hotplug_active = False
        if self._usb_hotplug_timer_id is not None:
            self.root.after_cancel(self._usb_hotplug_timer_id)
            self._usb_hotplug_timer_id = None

    def _usb_hotplug_tick(self):
        """Periodic check for newly connected USB controllers."""
        self._usb_hotplug_timer_id = None
        if not self._usb_hotplug_active:
            return

        try:
            current_paths = {
                d['path'] for d in ConnectionManager.enumerate_devices()
            }
        except Exception:
            current_paths = set()

        new_paths = current_paths - self._last_seen_usb_paths
        self._last_seen_usb_paths = current_paths

        if new_paths:
            self._auto_connect_new_usb(new_paths)

        if self._usb_hotplug_active:
            self._usb_hotplug_timer_id = self.root.after(
                2000, self._usb_hotplug_tick)

    def _auto_connect_new_usb(self, new_paths: set):
        """Auto-connect newly detected USB controllers to free slots."""
        claimed_paths = set()
        for s in self.slots:
            if s.is_connected and s.connection_mode == 'usb' and s.conn_mgr.device_path:
                claimed_paths.add(s.conn_mgr.device_path)

        unclaimed = new_paths - claimed_paths
        if not unclaimed:
            return

        usb_devices = ConnectionManager.enumerate_usb_devices()
        for usb_dev in usb_devices:
            tmp = ConnectionManager(
                on_status=lambda msg: None,
                on_progress=lambda val: None,
            )
            tmp.initialize_via_usb(usb_device=usb_dev)

        # Re-enumerate to get full HID info dicts for identity building
        all_hid = ConnectionManager.enumerate_devices()
        path_to_info = {d['path']: d for d in all_hid}

        for path in unclaimed:
            hid_info = path_to_info.get(path, {'path': path})
            dev_id = make_usb_device_identity(hid_info)
            slot_index = self._find_slot_for_device(dev_id)
            if slot_index < 0:
                break

            slot = self.slots[slot_index]
            sui = self.ui.slots[slot_index]

            if slot.conn_mgr.init_hid_device(device_path=path):
                slot.device_path = path
                slot.connection_mode = 'usb'
                slot.device_identity = dev_id
                self._save_slot_assignment(dev_id, slot_index)
                self.slot_calibrations[slot_index]['preferred_device_path'] = \
                    path.decode('utf-8', errors='replace')
                slot.input_proc.start()
                sui.connect_btn.configure(text=t("ui.disconnect_usb"))
                if sui.pair_btn:
                    sui.pair_btn.configure(state='disabled')
                self.ui.update_tab_status(
                    slot_index, connected=True, emulating=False, connection_mode='usb')
                self.toggle_emulation(slot_index)
                self._sync_player_leds()
                self._recent_usb_hotplug[slot_index] = (time.monotonic(), dev_id)
                logger.info("USB hotplug: slot %d auto-connected (id=%s)",
                            slot_index, dev_id)

    # ── Debug helpers ─────────────────────────────────────────────

    @staticmethod
    def _log_all_hid_gamepads(context: str = ""):
        """Enumerate ALL HID gamepads on the system for debugging."""
        try:
            all_devs = hid.enumerate(0, 0)
            gamepads = [d for d in all_devs
                        if d.get('usage_page') == 0x0001
                        and d.get('usage') in (0x04, 0x05)]
            logger.info("HID gamepads on system (%s): %d found",
                        context, len(gamepads))
            for d in gamepads:
                logger.info("  vid=%04X pid=%04X product=%s path=%s",
                            d.get('vendor_id', 0), d.get('product_id', 0),
                            d.get('product_string', '?'),
                            d.get('path', b'?'))
        except Exception as e:
            logger.debug("Failed to enumerate HID gamepads: %s", e)

    # ── Rapid USB scan after BLE disconnect ───────────────────────

    def _start_rapid_usb_scan(self, ble_slot: int,
                               attempts_left: int = 16):
        """Rapidly enumerate USB after BLE disconnect to minimise the
        window where Windows processes the controller as a native gamepad.

        Runs every 300 ms for ~5 s.  Stops early if the slot reconnects
        (via this scan, normal hotplug, or BLE reconnect).
        """
        slot = self.slots[ble_slot]
        if slot.is_connected or attempts_left <= 0:
            return

        try:
            current_paths = {
                d['path'] for d in ConnectionManager.enumerate_devices()
            }
        except Exception:
            current_paths = set()

        new_paths = current_paths - self._last_seen_usb_paths
        if new_paths:
            self._last_seen_usb_paths = current_paths
            self._auto_connect_new_usb(new_paths)

            self._try_cross_transport_migration(ble_slot)
            if slot.is_connected:
                logger.info("Rapid USB scan: slot %d reconnected via USB "
                            "after BLE disconnect", ble_slot)
                self._log_all_hid_gamepads("after BLE→USB migration")
                sui = self.ui.slots[ble_slot]
                self.ui.update_ble_status(ble_slot, "")
                if sui.pair_btn:
                    sui.pair_btn.configure(state='disabled')
                return

        self.root.after(
            300,
            lambda: self._start_rapid_usb_scan(ble_slot, attempts_left - 1))

    # ── Cross-transport migration ─────────────────────────────────

    def _try_cross_transport_migration(self, ble_slot: int):
        """After BLE disconnects on ble_slot, check if a USB controller just
        connected on another slot.  If so, it's likely the same physical
        controller switching transport — migrate USB to the BLE slot and
        auto-link the two identities.
        """
        now = time.monotonic()
        ble_identity = self.slots[ble_slot].device_identity

        best_usb_slot = None
        best_ts = 0.0
        for usb_slot, (ts, usb_id) in list(self._recent_usb_hotplug.items()):
            if now - ts > 3.0:
                self._recent_usb_hotplug.pop(usb_slot, None)
                continue
            if usb_slot == ble_slot:
                continue
            if not self.slots[usb_slot].is_connected:
                continue
            if self.slots[usb_slot].connection_mode != 'usb':
                continue
            if ts > best_ts:
                best_ts = ts
                best_usb_slot = usb_slot

        if best_usb_slot is None:
            return

        usb_slot = best_usb_slot
        usb_id = self._recent_usb_hotplug[usb_slot][1]
        self._recent_usb_hotplug.pop(usb_slot, None)

        logger.info("Cross-transport migration: USB slot %d → slot %d "
                     "(BLE disconnected, USB just connected)", usb_slot, ble_slot)

        # Disconnect USB from its current slot
        usb_slot_obj = self.slots[usb_slot]
        usb_sui = self.ui.slots[usb_slot]

        was_emulating = usb_slot_obj.emu_mgr.is_emulating
        usb_slot_obj.input_proc.stop()
        if usb_slot_obj.emu_mgr.is_emulating:
            usb_slot_obj.emu_mgr.stop()
        saved_path = usb_slot_obj.device_path
        saved_hid = usb_slot_obj.conn_mgr.device

        # Detach without closing the HID handle
        usb_slot_obj.conn_mgr.device = None
        usb_slot_obj.device_path = None
        usb_slot_obj.device_identity = None
        usb_slot_obj.connection_mode = 'usb'
        usb_sui.connect_btn.configure(text=t("ui.connect_usb"))
        if usb_sui.pair_btn:
            usb_sui.pair_btn.configure(state='normal')
        self.ui.update_status(usb_slot, t("ui.ready"))
        self.ui.reset_slot_ui(usb_slot)
        self.ui.update_tab_status(usb_slot, connected=False, emulating=False)

        # Re-attach on the BLE slot
        target_slot = self.slots[ble_slot]
        target_sui = self.ui.slots[ble_slot]

        target_slot.conn_mgr.device = saved_hid
        target_slot.device_path = saved_path
        target_slot.connection_mode = 'usb'
        target_slot.device_identity = usb_id
        self._save_slot_assignment(usb_id, ble_slot)
        if saved_path:
            self.slot_calibrations[ble_slot]['preferred_device_path'] = \
                saved_path.decode('utf-8', errors='replace')

        target_slot.input_proc.start()
        target_sui.connect_btn.configure(text=t("ui.disconnect_usb"))
        if target_sui.pair_btn:
            target_sui.pair_btn.configure(state='disabled')
        self.ui.update_status(ble_slot, t("ui.reconnected"))
        self.ui.update_tab_status(
            ble_slot, connected=True, emulating=False, connection_mode='usb')
        self._sync_player_leds()

        if was_emulating:
            self.toggle_emulation(ble_slot)

        # Auto-link the USB and BLE identities
        if ble_identity and usb_id:
            self._link_devices(ble_identity, usb_id)
            logger.info("Auto-linked %s ↔ %s", ble_identity, usb_id)

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

        self.ui.update_status(slot_index, t("ui.disconnected_reconnecting"))
        sui.connect_btn.configure(text=t("ui.connect_usb"))
        if sui.pair_btn:
            sui.pair_btn.configure(state='normal')
        self.ui.update_tab_status(slot_index, connected=False, emulating=False)

        self._attempt_reconnect(slot_index)

    def _attempt_reconnect(self, slot_index: int):
        """Try to reconnect controller on a specific slot. Retries every 2 seconds."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]

        # Slot already reconnected via another transport (e.g. BLE) — abort.
        if slot.is_connected:
            return

        # User clicked Disconnect while we were waiting — abort.
        if slot.input_proc.stop_event.is_set():
            self.ui.update_status(slot_index, t("ui.ready"))
            self.ui.reset_slot_ui(slot_index)
            self.ui.update_tab_status(slot_index, connected=False, emulating=False)
            return

        # Build set of paths claimed by other slots (USB only)
        claimed_paths = set()
        for i, s in enumerate(self.slots):
            if (i != slot_index and s.is_connected
                    and s.connection_mode == 'usb' and s.conn_mgr.device_path):
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
                slot.connection_mode = 'usb'
                # Rebuild identity from full HID info if available
                path_to_info = {d['path']: d for d in all_hid}
                hid_info = path_to_info.get(target_path, {'path': target_path})
                slot.device_identity = make_usb_device_identity(hid_info)
                slot.input_proc.start()
                sui.connect_btn.configure(text=t("ui.disconnect_usb"))
                if sui.pair_btn:
                    sui.pair_btn.configure(state='disabled')
                self.ui.update_status(slot_index, t("ui.reconnected"))
                self.ui.update_tab_status(
                    slot_index, connected=True, emulating=False, connection_mode='usb')

                self._sync_player_leds()

                if slot.reconnect_was_emulating:
                    slot.reconnect_was_emulating = False
                    self.toggle_emulation(slot_index)
                return

        # Failed — retry after a delay
        self.ui.update_status(slot_index, t("ui.disconnected_reconnecting"))
        self.root.after(2000, lambda: self._attempt_reconnect(slot_index))

    # ── Emulation ────────────────────────────────────────────────────

    def toggle_emulation_all(self):
        """Start or stop emulation on all connected controllers."""
        any_emulating = any(s.emu_mgr.is_emulating for s in self.slots)
        for i, slot in enumerate(self.slots):
            if any_emulating:
                # Stop all emulating slots
                if slot.emu_mgr.is_emulating or getattr(slot, '_pipe_cancel', None):
                    self.toggle_emulation(i)
            else:
                # Start emulation on all connected slots
                if slot.is_connected and not slot.emu_mgr.is_emulating:
                    self.toggle_emulation(i)

    def test_rumble_all(self):
        """Send a short rumble burst on all emulating controllers."""
        for i in range(MAX_SLOTS):
            self.test_rumble(i)

    def toggle_emulation(self, slot_index: int):
        """Start or stop controller emulation for a specific slot."""
        try:
            self._toggle_emulation_inner(slot_index)
        except Exception as e:
            self._messagebox.showerror(
                t("error.emulation"), t("error.emu_unexpected", error=e))

    def _toggle_emulation_inner(self, slot_index: int):
        """Inner implementation of toggle_emulation."""
        slot = self.slots[slot_index]

        if slot.emu_mgr.is_emulating or getattr(slot, '_pipe_cancel', None):
            # Cancel a pending dolphin pipe wait, or stop active emulation.
            cancel = getattr(slot, '_pipe_cancel', None)
            if cancel is not None:
                cancel.set()
                slot._pipe_cancel = None
            slot.emu_mgr.stop()
            self.ui.update_emu_status(slot_index, "")
            self.ui.update_tab_status(slot_index, connected=slot.is_connected, emulating=False)
        else:
            mode = self.ui.emu_mode_var.get()

            if not is_emulation_available(mode):
                self._messagebox.showerror(
                    t("error.generic"),
                    t("error.emu_unavailable", mode=mode,
                      reason=get_emulation_unavailable_reason(mode)))
                return

            if mode == 'dolphin_pipe':
                self._start_dolphin_pipe_emulation(slot_index)
            elif mode == 'dsu':
                self._start_dsu_emulation(slot_index)
            else:
                self._start_xbox360_emulation(slot_index)

    def _make_rumble_callback(self, slot_index: int):
        """Create a rumble callback closure for a specific slot."""
        def _on_rumble(large_motor: int, small_motor: int):
            slot = self.slots[slot_index]
            new_state = (large_motor > 0 or small_motor > 0)
            if new_state == slot.rumble_state:
                return  # No change, skip
            slot.rumble_state = new_state
            packet = build_rumble_packet(new_state, slot.rumble_tid)
            slot.rumble_tid = (slot.rumble_tid + 1) & 0x0F

            if slot.ble_connected:
                self._send_ble_cmd({
                    "cmd": "rumble",
                    "slot_index": slot_index,
                    "data": base64.b64encode(packet).decode('ascii'),
                })
            elif slot.conn_mgr.device:
                slot.conn_mgr.send_rumble(new_state)
        return _on_rumble

    def test_rumble(self, slot_index: int):
        """Send a short rumble burst (~500ms) to test the motor."""
        slot = self.slots[slot_index]

        if not slot.emu_mgr.is_emulating:
            return
        if not (slot.ble_connected or slot.conn_mgr.device):
            return

        # Send rumble ON (update state so dedup in game callback stays in sync)
        slot.rumble_state = True
        packet_on = build_rumble_packet(True, slot.rumble_tid)
        slot.rumble_tid = (slot.rumble_tid + 1) & 0x0F

        if slot.ble_connected:
            self._send_ble_cmd({
                "cmd": "rumble",
                "slot_index": slot_index,
                "data": base64.b64encode(packet_on).decode('ascii'),
            })
        elif slot.conn_mgr.device:
            slot.conn_mgr.send_rumble(True)

        # Schedule rumble OFF after 500ms
        def _stop_rumble():
            slot.rumble_state = False
            packet_off = build_rumble_packet(False, slot.rumble_tid)
            slot.rumble_tid = (slot.rumble_tid + 1) & 0x0F

            if slot.ble_connected:
                self._send_ble_cmd({
                    "cmd": "rumble",
                    "slot_index": slot_index,
                    "data": base64.b64encode(packet_off).decode('ascii'),
                })
            elif slot.conn_mgr.device:
                slot.conn_mgr.send_rumble(False)

        self.root.after(500, _stop_rumble)

    def _start_xbox360_emulation(self, slot_index: int):
        """Start Xbox 360 emulation synchronously."""
        slot = self.slots[slot_index]
        try:
            slot.emu_mgr.start('xbox360', slot_index=slot_index,
                               rumble_callback=self._make_rumble_callback(slot_index))
            self.ui.update_emu_status(slot_index, t("emu.connected_ready"))
            self.ui.update_tab_status(slot_index, connected=True, emulating=True)
        except Exception as e:
            self._messagebox.showerror(t("error.emulation"),
                                       t("error.emu_failed", error=e))

    def _start_dsu_emulation(self, slot_index: int):
        """Start DSU server emulation synchronously."""
        slot = self.slots[slot_index]
        try:
            slot.emu_mgr.start('dsu', slot_index=slot_index,
                               rumble_callback=self._make_rumble_callback(slot_index))
            port = getattr(slot.emu_mgr.gamepad, 'port', 26760)
            self.ui.update_emu_status(slot_index, t("emu.dsu_ready", port=port))
            self.ui.update_tab_status(slot_index, connected=True, emulating=True)
        except Exception as e:
            self._messagebox.showerror(t("error.emulation"),
                                       t("error.emu_dsu_failed", error=e))

    def _start_dolphin_pipe_emulation(self, slot_index: int):
        """Start Dolphin pipe emulation on a background thread.

        Polls until Dolphin opens the read end of the pipe.
        """
        slot = self.slots[slot_index]
        pipe_name = f'gc_controller_{slot_index + 1}'

        cancel = threading.Event()
        slot._pipe_cancel = cancel
        self.ui.update_emu_status(
            slot_index, t("emu.waiting_dolphin"))

        def _connect():
            try:
                slot.emu_mgr.start('dolphin_pipe', slot_index=slot_index,
                                   cancel_event=cancel)
                self.root.after(0, lambda: self._on_pipe_connected(slot_index))
            except Exception as e:
                self.root.after(0, lambda err=e: self._on_pipe_failed(slot_index, err))

        threading.Thread(target=_connect, daemon=True).start()

    def _on_pipe_connected(self, slot_index: int):
        """Called on the main thread when a dolphin pipe successfully opens."""
        slot = self.slots[slot_index]
        slot._pipe_cancel = None
        self.ui.update_emu_status(
            slot_index, t("emu.connected_ready"))
        self.ui.update_tab_status(slot_index, connected=True, emulating=True)

    def _on_pipe_failed(self, slot_index: int, error: Exception):
        """Called on the main thread when dolphin pipe open fails or is cancelled."""
        slot = self.slots[slot_index]
        slot._pipe_cancel = None
        slot.emu_mgr.stop()
        self.ui.update_emu_status(slot_index, "")
        self.ui.update_tab_status(slot_index, connected=slot.is_connected, emulating=False)
        if getattr(error, 'errno', None) != errno.ECANCELED:
            self._messagebox.showerror(t("error.emulation"),
                                       t("error.emu_pipe_failed", error=error))

    # ── Calibration wizard ──────────────────────────────────────────

    def _needs_calibration(self, slot_index: int) -> bool:
        """Check if a slot has default (uncalibrated) stick calibration."""
        return self.slot_calibrations[slot_index].get('stick_left_octagon') is None

    def calibration_wizard_step(self, slot_index: int):
        """Unified calibration wizard: sticks first, then triggers, one button."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]
        logger.debug("Slot %d: calibration_wizard_step (stick_cal=%s, trigger_step=%d)",
                      slot_index, slot.cal_mgr.stick_calibrating, slot.cal_mgr.trigger_cal_step)

        if slot.cal_mgr.stick_calibrating:
            slot.cal_mgr.finish_stick_calibration()
            self.ui.set_calibration_mode(slot_index, False)
            self.ui.redraw_octagons(slot_index)
            self._auto_save()

            result = slot.cal_mgr.trigger_cal_next_step()
            if result:
                _step, _btn, status_text = result
                sui.cal_wizard_btn.configure(text=t("btn.continue"))
                self.ui.update_status(slot_index, status_text)
                self._show_cal_cancel(slot_index, True)
                self._start_trigger_cal_live(slot_index)

        elif slot.cal_mgr.trigger_cal_step > 0:
            result = slot.cal_mgr.trigger_cal_next_step()
            if result:
                step, btn_text, status_text = result
                self.ui.update_status(slot_index, status_text)
                if step == 0:
                    self._stop_trigger_cal_live(slot_index)
                    self._show_cal_cancel(slot_index, False)
                    sui.cal_wizard_btn.configure(text=t("ui.cal_wizard"))
                    self.ui.draw_trigger_markers(slot_index)
                    self._auto_save()
                else:
                    sui.cal_wizard_btn.configure(text=btn_text)

        else:
            if self._needs_calibration(slot_index):
                self.ui.set_calibration_mode(slot_index, True)
                slot.cal_mgr.start_stick_calibration()
                sui.cal_wizard_btn.configure(text=t("btn.continue"))
                self._show_cal_cancel(slot_index, True)
                self.ui.update_status(slot_index, t("cal.sticks_instruction"))
            else:
                result = slot.cal_mgr.trigger_cal_next_step()
                if result:
                    _step, _btn, status_text = result
                    sui.cal_wizard_btn.configure(text=t("btn.continue"))
                    self.ui.update_status(slot_index, status_text)
                    self._show_cal_cancel(slot_index, True)
                    self._start_trigger_cal_live(slot_index)

    def cancel_calibration(self, slot_index: int):
        """Cancel any in-progress calibration (sticks or triggers)."""
        slot = self.slots[slot_index]
        sui = self.ui.slots[slot_index]
        logger.info("Slot %d: calibration cancelled by user", slot_index)

        if slot.cal_mgr.stick_calibrating:
            slot.cal_mgr.stick_calibrating = False
            self.ui.set_calibration_mode(slot_index, False)
            self.ui.redraw_octagons(slot_index)

        if slot.cal_mgr.trigger_cal_step > 0:
            slot.cal_mgr.trigger_cal_cancel()
            self._stop_trigger_cal_live(slot_index)
            self.ui.draw_trigger_markers(slot_index)

        self._show_cal_cancel(slot_index, False)
        sui.cal_wizard_btn.configure(text=t("ui.cal_wizard"))
        self.ui.update_status(slot_index, t("ui.ready"))

    def _show_cal_cancel(self, slot_index: int, show: bool):
        """Show or hide the calibration cancel button."""
        sui = self.ui.slots[slot_index]
        if sui.cal_cancel_btn is None:
            return
        if show:
            if not sui.cal_cancel_btn.winfo_ismapped():
                sui.cal_cancel_btn.pack(side=self._tk.LEFT, padx=(4, 0))
        else:
            sui.cal_cancel_btn.pack_forget()

    def _start_trigger_cal_live(self, slot_index: int):
        """Start periodic display of live trigger values during calibration."""
        self._stop_trigger_cal_live(slot_index)

        _STEP_KEYS = {
            1: "cal.trigger_release",
            2: "cal.trigger_left_bump",
            3: "cal.trigger_left_max",
            4: "cal.trigger_right_bump",
            5: "cal.trigger_right_max",
        }

        def _tick():
            slot = self.slots[slot_index]
            step = slot.cal_mgr.trigger_cal_step
            if step == 0 or not slot.is_connected:
                self._trigger_cal_live_timers.pop(slot_index, None)
                return
            left = slot.cal_mgr.trigger_cal_last_left
            right = slot.cal_mgr.trigger_cal_last_right
            peak_l = slot.cal_mgr.trigger_cal_peak_left
            peak_r = slot.cal_mgr.trigger_cal_peak_right
            key = _STEP_KEYS.get(step, "")
            instruction = t(key) if key else ""
            self.ui.update_status(
                slot_index,
                f"{instruction}\nL={left} (max={peak_l})  R={right} (max={peak_r})")
            self._trigger_cal_live_timers[slot_index] = self.root.after(
                100, _tick)

        _tick()

    def _stop_trigger_cal_live(self, slot_index: int):
        """Stop the live trigger value display for a slot."""
        timer_id = self._trigger_cal_live_timers.pop(slot_index, None)
        if timer_id is not None:
            self.root.after_cancel(timer_id)

    # ── Settings ─────────────────────────────────────────────────────

    def update_calibration_from_ui(self):
        """Update calibration values from UI variables for all slots."""
        # Global settings stored in slot 0's calibration
        self.slot_calibrations[0]['auto_connect'] = self.ui.auto_connect_var.get()
        self.slot_calibrations[0]['auto_scan_ble'] = self.ui.auto_scan_ble_var.get()
        self.slot_calibrations[0]['emulation_mode'] = self.ui.emu_mode_var.get()
        self.slot_calibrations[0]['trigger_bump_100_percent'] = self.ui.trigger_mode_var.get()
        self.slot_calibrations[0]['minimize_to_tray'] = self.ui.minimize_to_tray_var.get()
        self.slot_calibrations[0]['stick_deadzone'] = self.ui.stick_deadzone_var.get()
        self.slot_calibrations[0]['run_at_startup'] = self.ui.run_at_startup_var.get()

        from . import autostart
        try:
            autostart.set_enabled(self.ui.run_at_startup_var.get())
        except Exception as e:
            logger.warning("Failed to update autostart: %s", e)

        for i in range(MAX_SLOTS):
            cal = self.slot_calibrations[i]
            cal['trigger_bump_100_percent'] = self.ui.trigger_mode_var.get()
            cal['emulation_mode'] = self.ui.emu_mode_var.get()
            cal['stick_deadzone'] = self.ui.stick_deadzone_var.get()
            self.slots[i].cal_mgr.refresh_cache()

            # Save per-device calibration back to the BLE device registry
            slot = self.slots[i]
            if slot.ble_connected and slot.ble_address:
                self._save_device_calibration(i, slot.ble_address)

    def _auto_save(self):
        """Silently save settings (no messagebox). Called after calibration/pairing."""
        self.update_calibration_from_ui()
        try:
            self.settings_mgr.save()
        except Exception as e:
            print(f"Auto-save failed: {e}")

    def save_settings(self):
        """Save calibration settings for all slots to file."""
        self.update_calibration_from_ui()
        try:
            self.settings_mgr.save()
            self._messagebox.showinfo(t("settings.title"), t("settings.saved"))
        except Exception as e:
            self._messagebox.showerror(t("error.generic"), t("settings.save_error", error=e))

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
        """Store latest UI data from the input thread (no Tk calls).

        The main-thread poll timer (_ui_poll) picks this up at ~30 fps.
        """
        self._latest_ui_data[slot_index] = (
            left_x, left_y, right_x, right_y,
            left_trigger, right_trigger, button_states,
            stick_calibrating,
        )

    def _start_ui_poll(self):
        """Start the fixed-rate UI poll timer (~30 fps)."""
        self._ui_poll()

    def _ui_poll(self):
        """Main-thread timer: apply latest input data for each slot."""
        for slot_index in range(MAX_SLOTS):
            data = self._latest_ui_data[slot_index]
            if data is not None:
                self._latest_ui_data[slot_index] = None
                self._apply_ui_update(slot_index, *data)
        self.root.after(33, self._ui_poll)   # ~30 fps

    def _apply_ui_update(self, slot_index: int, left_x, left_y, right_x, right_y,
                         left_trigger, right_trigger, button_states,
                         stick_calibrating):
        """Apply UI updates on the main thread for a specific slot."""
        try:
            self.ui.update_stick_position(slot_index, 'left', left_x, left_y)
            self.ui.update_stick_position(slot_index, 'right', right_x, right_y)
            self.ui.update_trigger_display(slot_index, left_trigger, right_trigger)
            self.ui.update_button_display(slot_index, button_states)

            if stick_calibrating:
                self.ui.draw_octagon_live(slot_index, 'left')
                self.ui.draw_octagon_live(slot_index, 'right')

            # Single PIL composite + paste for all visual changes
            s = self.ui.slots[slot_index]
            s.controller_visual.flush()
        except Exception as e:
            import traceback
            traceback.print_exc()

    # ── System tray ──────────────────────────────────────────────────

    def _init_tray_icon(self):
        """Create the system tray icon (hidden initially)."""
        base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
        png_path = os.path.join(base, "controller.png")

        try:
            image = PILImage.open(png_path)
        except Exception:
            # Fallback: create a simple colored icon
            image = PILImage.new('RGB', (64, 64), color=(83, 84, 134))

        menu = pystray.Menu(
            pystray.MenuItem(t("tray.show"), self._tray_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("tray.quit"), self._tray_quit),
        )

        self._tray_icon = pystray.Icon(
            "nso-gc-controller",
            image,
            "NSO GC Controller",
            menu,
        )
        # Run tray icon in a daemon thread so it doesn't block Tkinter
        tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
        tray_thread.start()
        # Start hidden — only visible when minimize-to-tray is active
        self._tray_icon.visible = False

        # Ensure tray icon is removed on any exit (Ctrl+C, SIGTERM, etc.)
        import atexit
        atexit.register(self._cleanup_tray)
        if sys.platform == 'win32':
            try:
                signal.signal(signal.SIGBREAK, lambda *_: self._cleanup_tray())
            except (OSError, AttributeError):
                pass

    def _cleanup_tray(self):
        """Remove tray icon — called via atexit/signal for clean exit."""
        icon = self._tray_icon
        if icon is not None:
            self._tray_icon = None
            try:
                icon.stop()
            except Exception:
                pass

    def _on_tray_setting_changed(self):
        """Called when the minimize_to_tray setting is toggled."""
        if not self.ui.minimize_to_tray_var.get() and self._tray_icon:
            # Setting was disabled — make sure tray icon is hidden
            self._tray_icon.visible = False

    def _on_window_unmap(self, event):
        """Handle window minimize — go to tray if enabled."""
        if (event.widget == self.root
                and self.ui.minimize_to_tray_var.get()
                and self._tray_icon):
            # Check if the window was actually iconified (minimized)
            self.root.after(50, self._check_iconified)

    def _check_iconified(self):
        """Check if the window is iconified and hide to tray."""
        try:
            if self.root.state() == 'iconic':
                self._hide_to_tray()
        except Exception:
            pass

    def _hide_to_tray(self):
        """Withdraw the window and show the tray icon."""
        self.root.withdraw()
        if self._tray_icon:
            self._tray_icon.visible = True

    def _tray_show(self, icon=None, item=None):
        """Restore the window from the tray."""
        if self._tray_icon:
            self._tray_icon.visible = False
        # Schedule on the Tkinter main thread
        self.root.after(0, self._restore_window)

    def _restore_window(self):
        """Restore and focus the main window."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _tray_quit(self, icon=None, item=None):
        """Quit the application from the tray menu."""
        if self._tray_icon:
            self._tray_icon.visible = False
        # Schedule actual closing on the Tkinter main thread
        self.root.after(0, self._actual_quit)

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_closing(self):
        """Handle application closing — minimize to tray/Dock or quit."""
        if self.ui.minimize_to_tray_var.get():
            # On macOS the Dock icon provides restore even without pystray,
            # on other platforms we need a functioning tray icon.
            if sys.platform == 'darwin' or (_TRAY_AVAILABLE and self._tray_icon):
                self._hide_to_tray()
                return
        self._actual_quit()

    def _actual_quit(self):
        """Perform full application shutdown and destroy the window."""
        # Stop USB hotplug polling
        self._stop_usb_hotplug()

        # Stop auto-scan loop
        self._stop_auto_scan()

        # Stop tray icon
        self._cleanup_tray()

        for i in range(MAX_SLOTS):
            self._reset_rumble(i)
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

    def _set_window_icon(self):
        """Set the window/taskbar icon across platforms."""
        try:
            if sys.platform == "win32":
                # Tell Windows this is its own app, not "python.exe",
                # so the taskbar shows our icon instead of the default.
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "nso.gamecube-controller-pairing-app")

            # Locate the .ico / .png for the window icon
            base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
            ico_path = os.path.join(base, "controller.ico")
            png_path = os.path.join(base, "controller.png")

            if sys.platform == "win32" and os.path.exists(ico_path):
                self.root.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                icon = self._tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, icon)
        except Exception:
            pass

    def run(self):
        """Start the application."""
        if self._start_minimized and _TRAY_AVAILABLE and self._tray_icon:
            self.root.withdraw()
            self._tray_icon.visible = True
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
        """Start the BLE subprocess. Uses pkexec on Linux, direct spawn on macOS/Windows."""
        frozen = getattr(sys, 'frozen', False)
        if sys.platform == 'darwin' or sys.platform == 'win32':
            if frozen:
                cmd = [sys.executable, '--bleak-subprocess']
            else:
                script_path = os.path.join(
                    os.path.dirname(__file__), 'ble', 'bleak_subprocess.py')
                python_path = os.pathsep.join(p for p in sys.path if p)
                cmd = [sys.executable, script_path, python_path]
            self._subprocess = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        else:
            if frozen:
                cmd = ['pkexec', sys.executable, '--ble-subprocess']
            else:
                script_path = os.path.join(
                    os.path.dirname(__file__), 'ble', 'ble_subprocess.py')
                python_path = os.pathsep.join(p for p in sys.path if p)
                cmd = ['pkexec', sys.executable, script_path, python_path]
            self._subprocess = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

    def send_cmd(self, cmd: dict):
        """Send a JSON-line command to the BLE subprocess."""
        if self._subprocess and self._subprocess.poll() is None:
            try:
                line = json.dumps(cmd, separators=(',', ':')) + '\n'
                self._subprocess.stdin.write(line.encode('utf-8'))
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
        On macOS, pkexec is not needed (CoreBluetooth works in userspace).
        Returns True on success, prints errors to stdout.
        """
        if self._initialized:
            return True

        if sys.platform == 'linux' and not shutil.which('pkexec'):
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
        """Read events from the BLE subprocess stdout (runs in a thread).

        Handles two formats on the binary stdout stream:
        - Binary data packets: 0xFF + slot(1) + payload(64) = 66 bytes
        - JSON text lines: UTF-8 encoded, terminated by newline
        """
        try:
            stdout = self._subprocess.stdout
            while True:
                header = stdout.read(1)
                if not header:
                    break
                if header[0] == 0xFF:
                    packet = stdout.read(65)
                    if len(packet) < 65:
                        break
                    si = packet[0]
                    on_data(si, packet[1:65])
                    continue

                rest = stdout.readline()
                line = (header + rest).decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get('e')

                if not self._initialized and etype in (
                        'ready', 'bluez_stopped', 'open_ok', 'error'):
                    self._init_result = event
                    self._init_event.set()
                    continue

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

    settings_mgr = SettingsManager(slot_calibrations, _get_settings_dir())
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

    # Persistent slot assignments (device identity -> slot index)
    slot_assignments = slot_calibrations[0].get('slot_assignments', {})
    device_links = slot_calibrations[0].get('device_links', {})

    def _headless_resolve_slot(dev_id):
        """Resolve persistent slot for a device identity in headless mode."""
        s = slot_assignments.get(dev_id)
        if s is not None:
            return s
        linked = device_links.get(dev_id)
        if linked:
            s = slot_assignments.get(linked)
            if s is not None:
                return s
        for lk, lv in device_links.items():
            if lv == dev_id:
                s = slot_assignments.get(lk)
                if s is not None:
                    return s
        return None

    # Legacy: build slot -> preferred path mapping from settings
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

    # Per-slot rumble state for headless mode
    rumble_tids = [0] * MAX_SLOTS
    rumble_states = [False] * MAX_SLOTS

    def _make_headless_rumble_cb(slot_idx, conn_mgr_ref=None):
        """Create a rumble callback for headless mode (USB or BLE)."""
        def _on_rumble(large_motor, small_motor):
            new_state = (large_motor > 0 or small_motor > 0)
            if new_state == rumble_states[slot_idx]:
                return
            rumble_states[slot_idx] = new_state
            packet = build_rumble_packet(new_state, rumble_tids[slot_idx])
            rumble_tids[slot_idx] = (rumble_tids[slot_idx] + 1) & 0x0F

            # Check if this slot is BLE
            is_ble = False
            for s in active_slots:
                if s['index'] == slot_idx and s['type'] == 'ble':
                    is_ble = True
                    break
            if is_ble and ble_mgr and ble_mgr.is_alive:
                ble_mgr.send_cmd({
                    "cmd": "rumble",
                    "slot_index": slot_idx,
                    "data": base64.b64encode(packet).decode('ascii'),
                })
            elif conn_mgr_ref and conn_mgr_ref.device:
                conn_mgr_ref.send_rumble(new_state)
        return _on_rumble

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

        mode_label = {"dolphin_pipe": "Dolphin pipe", "dsu": "DSU server"}.get(slot_mode, "Xbox 360")
        print(f"[slot {i + 1}] Starting {mode_label} emulation...")
        try:
            rumble_cb = _make_headless_rumble_cb(i, conn_mgr_ref=conn_mgr)
            emu_mgr.start(slot_mode, slot_index=i, rumble_callback=rumble_cb)
            if slot_mode == 'dsu':
                port = getattr(emu_mgr.gamepad, 'port', 26760)
                print(f"[slot {i + 1}] DSU server on port {port}")
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

    claimed_slot_indices = set()

    # First pass: assign devices to their persisted slots
    for hid_info in all_hid:
        dev_id = make_usb_device_identity(hid_info)
        preferred = _headless_resolve_slot(dev_id)
        if preferred is not None and preferred not in claimed_slot_indices:
            path = hid_info['path']
            if path not in claimed_paths:
                _connect_slot(preferred, path)
                claimed_slot_indices.add(preferred)

    # Second pass (legacy): preferred_device_path
    for i in range(MAX_SLOTS):
        if i in claimed_slot_indices or any(s['index'] == i for s in active_slots):
            continue
        pref = slot_preferred.get(i)
        if pref and pref not in claimed_paths:
            _connect_slot(i, pref)
            claimed_slot_indices.add(i)

    # Third pass: fill remaining slots with unclaimed USB devices
    for hid_info in all_hid:
        if hid_info['path'] in claimed_paths:
            continue
        dev_id = make_usb_device_identity(hid_info)
        preferred = _headless_resolve_slot(dev_id)
        slot_idx = preferred if preferred is not None and preferred not in claimed_slot_indices else None
        if slot_idx is None:
            for i in range(MAX_SLOTS):
                if i not in claimed_slot_indices and not any(s['index'] == i for s in active_slots):
                    slot_idx = i
                    break
        if slot_idx is None:
            break
        _connect_slot(slot_idx, hid_info['path'])
        claimed_slot_indices.add(slot_idx)

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

        # Exclude controllers already on other slots so the scan
        # doesn't grab them if they briefly disconnect and re-advertise
        exclude = _get_connected_ble_addresses()

        print(f"[slot {slot_idx + 1}] BLE scanning...")

        ble_mgr.send_cmd({
            "cmd": "scan_connect",
            "slot_index": slot_idx,
            "target_address": None,
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

            # Resolve persistent slot for this BLE device
            dev_id = make_ble_device_identity(mac)
            preferred = _headless_resolve_slot(dev_id)
            if (preferred is not None and preferred != si
                    and preferred not in claimed_slot_indices
                    and not any(s['index'] == preferred for s in active_slots)):
                si = preferred

            print(f"[slot {si + 1}] BLE {'reconnected' if was_reconnect else 'connected'}: {mac}")

            # Persist slot assignment
            slot_assignments[dev_id] = si

            # Register device in known_ble_devices
            devices = slot_calibrations[0].setdefault('known_ble_devices', {})
            if mac.upper() not in devices:
                devices[mac.upper()] = {}

            # Create per-slot data queue, input processor, and emulation
            cal = slot_calibrations[si]
            cal_mgr = CalibrationManager(cal)
            ble_q = _queue.Queue(maxsize=64)
            ble_data_queues[si] = ble_q

            emu_mgr = EmulationManager(cal_mgr)
            slot_mode = mode_override if mode_override else cal.get('emulation_mode', mode)
            mode_label = {"dolphin_pipe": "Dolphin pipe", "dsu": "DSU server"}.get(slot_mode, "Xbox 360")
            print(f"[slot {si + 1}] Starting {mode_label} emulation...")

            try:
                rumble_cb = _make_headless_rumble_cb(si)
                emu_mgr.start(slot_mode, slot_index=si, rumble_callback=rumble_cb)
                if slot_mode == 'dsu':
                    port = getattr(emu_mgr.gamepad, 'port', 26760)
                    print(f"[slot {si + 1}] DSU server on port {port}")
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
                                rumble_cb = _make_headless_rumble_cb(
                                    idx, conn_mgr_ref=conn_mgr)
                                emu_mgr.start(slot_mode, slot_index=idx,
                                              rumble_callback=rumble_cb)
                                mode_label = {"dolphin_pipe": "Dolphin pipe", "dsu": "DSU server"}.get(slot_mode, "Xbox 360")
                                print(f"[slot {idx + 1}] {mode_label} emulation resumed.")
                                if slot_mode == 'dsu':
                                    port = getattr(emu_mgr.gamepad, 'port', 26760)
                                    print(f"[slot {idx + 1}] DSU server on port {port}")
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
        idx = slot_info['index']
        # Send rumble OFF before tearing down
        if rumble_states[idx]:
            rumble_states[idx] = False
            packet = build_rumble_packet(False, rumble_tids[idx])
            rumble_tids[idx] = (rumble_tids[idx] + 1) & 0x0F
            if slot_info['type'] == 'ble' and ble_mgr and ble_mgr.is_alive:
                ble_mgr.send_cmd({
                    "cmd": "rumble",
                    "slot_index": idx,
                    "data": base64.b64encode(packet).decode('ascii'),
                })
            elif slot_info['conn_mgr'] and slot_info['conn_mgr'].device:
                slot_info['conn_mgr'].send_rumble(False)
        slot_info['input_proc'].stop()
        slot_info['emu_mgr'].stop()
        if slot_info['type'] == 'usb' and slot_info['conn_mgr']:
            slot_info['conn_mgr'].disconnect()
    if ble_mgr:
        ble_mgr.shutdown()
    print("Done.")


def run_scan_debug(timeout: float = 10.0):
    """Run a single BLE scan and dump full advertisement data for every device.

    Prints a table of all discovered devices with manufacturer_data,
    service_uuids, and whether each passes the controller detection filter.
    No GUI or subprocess — runs Bleak directly.
    """
    import asyncio

    try:
        from bleak import BleakScanner
    except ImportError:
        print("ERROR: bleak is not installed. Install with: pip install bleak")
        sys.exit(1)

    from .ui_ble_scan_wizard import _is_likely_controller

    async def _scan():
        found = {}
        found_adv = {}

        def _cb(device, adv):
            found[device.address] = device
            found_adv[device.address] = adv

        print(f"Scanning for {timeout}s...\n")
        scanner = BleakScanner(detection_callback=_cb)
        await scanner.start()
        await asyncio.sleep(timeout)
        await scanner.stop()

        devices = []
        for addr, device in found.items():
            adv = found_adv.get(addr)
            mfg = {}
            svc_uuids = []
            if adv:
                mfg = {str(cid): val.hex() for cid, val in
                       getattr(adv, 'manufacturer_data', {}).items()}
                svc_uuids = list(getattr(adv, 'service_uuids', []))
            devices.append({
                'address': addr.upper(),
                'name': device.name or '',
                'rssi': adv.rssi if adv and adv.rssi is not None else -999,
                'manufacturer_data': mfg,
                'service_uuids': svc_uuids,
            })

        devices.sort(key=lambda d: d['rssi'], reverse=True)

        print(f"{'#':>3}  {'Address':17}  {'RSSI':>6}  {'Ctrl?':5}  "
              f"{'Name':25}  {'Manufacturer Data':40}  Service UUIDs")
        print("-" * 150)

        for i, d in enumerate(devices, 1):
            is_ctrl = _is_likely_controller(d)
            mfg_str = ""
            for cid, val in d['manufacturer_data'].items():
                mfg_str += f"0x{int(cid):04X}={val} "
            svc_str = " ".join(d['service_uuids'][:3])
            if len(d['service_uuids']) > 3:
                svc_str += f" (+{len(d['service_uuids']) - 3})"
            name_display = d['name'][:25] if d['name'] else '(no name)'
            marker = " <<" if is_ctrl else ""

            print(f"{i:3}  {d['address']:17}  {d['rssi']:>4} dBm  "
                  f"{'YES' if is_ctrl else '   ':5}  "
                  f"{name_display:25}  {mfg_str:40}  {svc_str}{marker}")

        ctrl_count = sum(1 for d in devices if _is_likely_controller(d))
        print(f"\nTotal: {len(devices)} device(s), "
              f"{ctrl_count} identified as likely controller(s)")

        if ctrl_count > 0:
            print("\nDetected controller details:")
            for d in devices:
                if _is_likely_controller(d):
                    print(f"  {d['address']}  name={d['name']!r}  rssi={d['rssi']}")
                    for cid, val in d['manufacturer_data'].items():
                        print(f"    manufacturer 0x{int(cid):04X}: {val}")
                    for svc in d['service_uuids']:
                        print(f"    service: {svc}")

    asyncio.run(_scan())


# ── Single-instance lock ──────────────────────────────────────────────

def _get_lock_path() -> str:
    """Return a platform-appropriate path for the instance lock file."""
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    elif sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Caches')
    else:
        base = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
    return os.path.join(base, 'nso-gc-controller.lock')


def _acquire_instance_lock():
    """Try to acquire a file-based instance lock.

    Returns a lock handle on success, or None if another instance holds it.
    On Windows uses msvcrt; on POSIX uses fcntl.
    """
    lock_path = _get_lock_path()
    try:
        fd = open(lock_path, 'w')
        if sys.platform == 'win32':
            import msvcrt
            try:
                msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
            except (IOError, OSError):
                fd.close()
                return None
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fd.close()
                return None
        fd.write(str(os.getpid()))
        fd.flush()
        return fd
    except OSError:
        return None


def _release_instance_lock(lock):
    """Release the instance lock and clean up."""
    if lock is None:
        return
    try:
        lock_path = _get_lock_path()
        lock.close()
        try:
            os.unlink(lock_path)
        except OSError:
            pass
    except Exception:
        pass


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="NSO GameCube Controller Pairing App - "
                    "converts GC controllers to Xbox 360 for Steam and other apps"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without the GUI (connect and emulate in the background)",
    )
    parser.add_argument(
        "--mode",
        choices=["xbox360", "dolphin_pipe", "dsu"],
        default=None,
        help="emulation mode for headless operation (default: use saved setting)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable verbose debug logging to stderr and log file",
    )
    parser.add_argument(
        "--scan-debug",
        action="store_true",
        help="run a single BLE scan and dump full advertisement data, then exit",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=10.0,
        help="scan duration in seconds for --scan-debug (default: 10)",
    )
    parser.add_argument(
        "--lang",
        choices=["en", "fr"],
        default=None,
        help="force UI language (default: auto-detect from system)",
    )
    parser.add_argument(
        "--latency",
        action="store_true",
        help="print real-time latency stats to stderr (~1 line/sec per slot)",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="start minimized to the system tray (used by autostart)",
    )
    args = parser.parse_args()

    if args.latency:
        from .input_processor import set_latency_profiling
        set_latency_profiling(True)

    setup_logging(debug=args.debug)

    from .i18n import init as i18n_init
    i18n_init(lang=args.lang)

    if not args.scan_debug:
        lock = _acquire_instance_lock()
        if lock is None:
            logger.warning("Another instance is already running — exiting.")
            print(t("app.already_running"))
            sys.exit(1)

    try:
        if args.scan_debug:
            run_scan_debug(timeout=args.scan_timeout)
        elif args.headless:
            run_headless(mode_override=args.mode)
        else:
            app = GCControllerEnabler(start_minimized=args.minimized)
            app.run()
    finally:
        if not args.scan_debug:
            _release_instance_lock(lock)


if __name__ == "__main__":
    main()
