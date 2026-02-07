"""
Input Processor

Manages the HID read thread and processes raw controller data, feeding
calibration tracking, emulation updates, and UI update scheduling.
"""

import queue
import sys
import time
import threading
from typing import Callable, Optional

from .controller_constants import BUTTONS, normalize
from .calibration import CalibrationManager
from .emulation_manager import EmulationManager

IS_WINDOWS = sys.platform == 'win32'


class InputProcessor:
    """Reads HID data in a background thread and routes it to subsystems."""

    def __init__(self, device_getter: Callable, calibration: dict,
                 cal_mgr: CalibrationManager, emu_mgr: EmulationManager,
                 on_ui_update: Callable, on_error: Callable[[str], None],
                 on_disconnect: Optional[Callable] = None,
                 ble_queue: Optional[queue.Queue] = None):
        self._device_getter = device_getter
        self._calibration = calibration
        self._cal_mgr = cal_mgr
        self._emu_mgr = emu_mgr
        self._on_ui_update = on_ui_update
        self._on_error = on_error
        self._on_disconnect = on_disconnect
        self._ble_queue = ble_queue

        self.is_reading = False
        self._stop_event = threading.Event()
        self._read_thread: Optional[threading.Thread] = None
        self._ui_update_counter = 0

    @property
    def stop_event(self) -> threading.Event:
        """Expose the stop event for reconnect logic to check."""
        return self._stop_event

    def start(self, mode: str = 'usb'):
        """Start the reading thread.

        Args:
            mode: 'usb' for HID device polling, 'ble' for queue-based reading.
        """
        if self.is_reading:
            return
        self.is_reading = True
        self._stop_event.clear()
        target = self._read_loop_ble if mode == 'ble' else self._read_loop
        self._read_thread = threading.Thread(target=target, daemon=True)
        self._read_thread.start()

    def stop(self):
        """Stop the HID reading thread."""
        if not self.is_reading:
            return
        self.is_reading = False
        self._stop_event.set()
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)

    def _read_loop(self):
        """Main HID reading loop with nonblocking drain."""
        try:
            device = self._device_getter()
            if not device:
                return
            device.set_nonblocking(1)

            while self.is_reading and not self._stop_event.is_set():
                if not device:
                    break
                try:
                    # Drain all buffered reports, only keep the latest
                    latest = None
                    for _ in range(64):
                        data = device.read(64)
                        if data:
                            latest = data
                        else:
                            break
                    if latest:
                        # On Windows, HIDAPI prepends the report ID byte
                        # to hid_read() data; strip it so byte offsets
                        # match the Linux/macOS layout the parser expects.
                        if IS_WINDOWS:
                            latest = latest[1:]
                        self._process_data(latest)
                    else:
                        time.sleep(0.004)
                except Exception as e:
                    if self.is_reading:
                        print(f"Read error: {e}")
                    break
        except Exception as e:
            self._on_error(f"Read loop error: {e}")
        finally:
            self.is_reading = False
            # If we weren't asked to stop, this was an unexpected disconnect
            if not self._stop_event.is_set() and self._on_disconnect:
                self._on_disconnect()

    def _read_loop_ble(self):
        """BLE reading loop — drains the queue, keeps only the latest packet."""
        try:
            while self.is_reading and not self._stop_event.is_set():
                # Drain queue, keep latest
                latest = None
                try:
                    while True:
                        latest = self._ble_queue.get_nowait()
                except queue.Empty:
                    pass

                if latest:
                    self._process_data(latest)
                else:
                    time.sleep(0.004)
        except Exception as e:
            self._on_error(f"BLE read loop error: {e}")
        finally:
            self.is_reading = False
            if not self._stop_event.is_set() and self._on_disconnect:
                self._on_disconnect()

    def _process_data(self, data: list):
        """Process raw controller data and route to subsystems."""
        if len(data) < 15:
            return

        # Extract analog stick values
        left_stick_x = data[6] | ((data[7] & 0x0F) << 8)
        left_stick_y = ((data[7] >> 4) | (data[8] << 4))
        right_stick_x = data[9] | ((data[10] & 0x0F) << 8)
        right_stick_y = ((data[10] >> 4) | (data[11] << 4))

        # Track during stick calibration
        if self._cal_mgr.stick_calibrating:
            self._cal_mgr.track_stick_data(left_stick_x, left_stick_y,
                                           right_stick_x, right_stick_y)

        # Normalize stick values
        cal = self._calibration
        left_x_norm = normalize(left_stick_x, cal['stick_left_center_x'], cal['stick_left_range_x'])
        left_y_norm = normalize(left_stick_y, cal['stick_left_center_y'], cal['stick_left_range_y'])
        right_x_norm = normalize(right_stick_x, cal['stick_right_center_x'], cal['stick_right_range_x'])
        right_y_norm = normalize(right_stick_y, cal['stick_right_center_y'], cal['stick_right_range_y'])

        # Process buttons
        button_states = {}
        for button in BUTTONS:
            if len(data) > button.byte_index:
                pressed = (data[button.byte_index] & button.mask) != 0
                button_states[button.name] = pressed

        # Extract trigger values
        left_trigger = data[13] if len(data) > 13 else 0
        right_trigger = data[14] if len(data) > 14 else 0

        # Store raw values for trigger calibration wizard
        self._cal_mgr.update_trigger_raw(left_trigger, right_trigger)

        # Forward to emulation (hot path)
        if self._emu_mgr.is_emulating and self._emu_mgr.gamepad:
            self._emu_mgr.update(left_x_norm, left_y_norm, right_x_norm, right_y_norm,
                                 left_trigger, right_trigger, button_states)

        # UI updates (throttled)
        self._ui_update_counter += 1
        if self._ui_update_counter % 3 == 0:
            self._on_ui_update(left_x_norm, left_y_norm, right_x_norm, right_y_norm,
                               left_trigger, right_trigger, button_states,
                               self._cal_mgr.stick_calibrating)
