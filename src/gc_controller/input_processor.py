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


def _translate_report_0x05(data) -> list:
    """Translate Windows uninitialized report (ID 0x05) to GC USB format.

    On Windows, pyusb/libusb is typically unavailable, so the USB init
    commands that switch the controller to the proprietary GC format are
    never sent.  The controller stays in its default NSO report format
    (report ID 0x05) which has NSO-encoded buttons and different offsets.

    0x05 raw layout (64 bytes, report ID prepended by Windows HIDAPI):
        [0]      0x05 report ID
        [1-3]    timer
        [4]      unknown
        [5]      NSO buttons 0: Y=01 X=02 B=04 A=08 SR=10 SL=20 R=40 ZR=80
        [6]      NSO buttons 1: Plus=02 Home=10 Capture=20
        [7]      NSO buttons 2: DDown=01 DUp=02 DRight=04 DLeft=08 SR=10 SL=20 L=40 ZL=80
        [8-10]   reserved
        [11-16]  sticks (packed 12-bit: LX, LY, RX, RY)
        [17-60]  IMU / unknown
        [61]     left trigger analog (~0x1e rest, ~0xe9 fully pressed)
        [62]     right trigger analog (~0x24 rest, ~0xf0 fully pressed)

    Target GC USB format (what _process_data expects):
        [3]      B=01 A=02 Y=04 X=08 R=10 Z=20 Start=40
        [4]      DDown=01 DRight=02 DLeft=04 DUp=08 L=10 ZL=20
        [5]      Home=01 Capture=02 GR=04 GL=08 Chat=10
        [6-11]   sticks (same packed 12-bit format)
        [13]     left trigger
        [14]     right trigger
    """
    buf = [0] * 64

    # Buttons: remap NSO encoding -> GC encoding
    # (same remapping as translate_ble_native_to_usb for 0x30 format)
    b0_nso = data[5]   # Y=01 X=02 B=04 A=08 R=10 ZR=20
    b1_nso = data[6]   # Plus=02 Home=10 Capture=20
    b2_nso = data[7]   # DDown=01 DUp=02 DRight=04 DLeft=08 L=40 ZL=80

    # Standard Switch USB encoding (differs from BLE BlueRetro encoding):
    #   b0_nso byte: Y=01 X=02 B=04 A=08 SR=10 SL=20 R=40 ZR=80
    #   b2_nso byte: DDown=01 DUp=02 DRight=04 DLeft=08 SR=10 SL=20 L=40 ZL=80
    b3 = 0
    if b0_nso & 0x04: b3 |= 0x01  # B
    if b0_nso & 0x08: b3 |= 0x02  # A
    if b0_nso & 0x01: b3 |= 0x04  # Y
    if b0_nso & 0x02: b3 |= 0x08  # X
    if b0_nso & 0x40: b3 |= 0x10  # R
    if b0_nso & 0x80: b3 |= 0x20  # ZR -> Z
    if b1_nso & 0x02: b3 |= 0x40  # Plus -> Start
    buf[3] = b3

    b4 = 0
    if b2_nso & 0x01: b4 |= 0x01  # DDown
    if b2_nso & 0x04: b4 |= 0x02  # DRight
    if b2_nso & 0x08: b4 |= 0x04  # DLeft
    if b2_nso & 0x02: b4 |= 0x08  # DUp
    if b2_nso & 0x40: b4 |= 0x10  # L
    if b2_nso & 0x80: b4 |= 0x20  # ZL
    buf[4] = b4

    b5 = 0
    if b1_nso & 0x10: b5 |= 0x01  # Home
    if b1_nso & 0x20: b5 |= 0x02  # Capture
    buf[5] = b5

    # Sticks: raw bytes 11-16 -> GC bytes 6-11
    for i in range(6):
        buf[6 + i] = data[11 + i]

    # Analog triggers: bytes 61-62 in the 0x05 report
    if len(data) > 62:
        buf[13] = data[61]  # left trigger analog
        buf[14] = data[62]  # right trigger analog

    return buf


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
                        if IS_WINDOWS:
                            if latest[0] == 0x05:
                                # Uninitialized NSO format (no libusb on
                                # Windows → USB init commands never sent).
                                latest = _translate_report_0x05(latest)
                            else:
                                # Initialized GC format with report ID
                                # prepended by Windows HIDAPI — strip it.
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
