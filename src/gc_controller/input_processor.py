"""
Input Processor

Manages the HID read thread and processes raw controller data, feeding
calibration tracking, emulation updates, and UI update scheduling.
"""

import collections
import logging
import queue
import sys
import threading
import time
from typing import Callable, Optional

from .controller_constants import BUTTONS, normalize, apply_deadzone
from .calibration import CalibrationManager
from .emulation_manager import EmulationManager

IS_WINDOWS = sys.platform == 'win32'
logger = logging.getLogger(__name__)

_latency_profiling = False


def set_latency_profiling(enabled: bool):
    """Enable or disable real-time latency profiling output."""
    global _latency_profiling
    _latency_profiling = enabled


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
    if b1_nso & 0x40: b5 |= 0x10  # Chat
    buf[5] = b5

    # Sticks: raw bytes 11-16 -> GC bytes 6-11
    for i in range(6):
        buf[6 + i] = data[11 + i]

    # Analog triggers: bytes 61-62 in the 0x05 report
    if len(data) > 62:
        buf[13] = data[61]  # left trigger analog
        buf[14] = data[62]  # right trigger analog
    else:
        logger.warning("Short 0x05 report (%d bytes) — trigger data missing", len(data))

    return buf


def _translate_report_0x0A(data) -> list:
    """Translate Windows report ID 0x0A (Switch 0x30-like) to GC USB format.

    Some NSO GC controllers (possibly after BLE pairing or firmware update)
    send report ID 0x0A instead of the usual 0x05.  The layout matches the
    standard Switch 0x30 input report but with a different report ID.

    0x0A raw layout (64 bytes, report ID prepended by Windows HIDAPI):
        [0]      0x0A report ID
        [1]      timer
        [2]      battery / status (0x20 typical)
        [3]      NSO buttons 0: Y=01 X=02 B=04 A=08 R=10 ZR=20
        [4]      NSO buttons 1: Minus=01 Plus=02 RStick=04 LStick=08 Home=10 Capture=20
        [5]      NSO buttons 2: DDown=01 DUp=02 DRight=04 DLeft=08 SR=10 SL=20 L=40 ZL=80
        [6-11]   sticks (packed 12-bit: LX, LY, RX, RY)
        [12]     vibrator
        [13]     left trigger analog
        [14]     right trigger analog

    Note: button byte 0 encoding differs from 0x05 — R/ZR are at 0x10/0x20
    here (standard Switch) vs 0x40/0x80 in the 0x05 format (which has
    SR/SL occupying 0x10/0x20).
    """
    buf = [0] * 64

    b0_nso = data[3]
    b1_nso = data[4]
    b2_nso = data[5]

    b3 = 0
    if b0_nso & 0x04: b3 |= 0x01  # B
    if b0_nso & 0x08: b3 |= 0x02  # A
    if b0_nso & 0x01: b3 |= 0x04  # Y
    if b0_nso & 0x02: b3 |= 0x08  # X
    if b0_nso & 0x10: b3 |= 0x10  # R
    if b0_nso & 0x20: b3 |= 0x20  # ZR -> Z
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

    for i in range(6):
        buf[6 + i] = data[6 + i]

    if len(data) > 14:
        buf[13] = data[13]
        buf[14] = data[14]

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
        self._debug_log_counter = 0
        # Connection warmup gate: discard initial reports with non-zero buttons
        # to filter out transient firmware artifacts (especially during
        # BLE -> USB transitions where the controller briefly sets status bits
        # in the buttons bytes before stabilizing).
        self._warmup_passed = False
        self._warmup_start_t = 0.0
        self._warmup_timeout_s = 0.5

        # Latency profiling state
        self._prof_last_read_t = 0.0
        self._prof_intervals = collections.deque(maxlen=250)
        self._prof_process_times = collections.deque(maxlen=250)
        self._prof_emu_times = collections.deque(maxlen=250)
        self._prof_total_times = collections.deque(maxlen=250)
        self._prof_drain_counts = collections.deque(maxlen=250)
        self._prof_last_print = 0.0
        self._prof_report_count = 0

        # Raw calibration sampling (printed alongside latency stats when profiling)
        self._raw_mins = None
        self._raw_maxs = None
        self._raw_sums = None
        self._raw_count = 0

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
        self._raw_mins = None
        self._raw_maxs = None
        self._raw_sums = None
        self._raw_count = 0
        self._warmup_passed = False
        self._warmup_start_t = time.perf_counter()
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
        """Main HID reading loop using blocking read for minimal latency."""
        try:
            device = self._device_getter()
            if not device:
                return
            first_report = True
            while self.is_reading and not self._stop_event.is_set():
                if not device:
                    break
                try:
                    data = device.read(64, timeout_ms=8)
                    t_read = time.perf_counter()
                    if not data:
                        continue
                    latest = data
                    drain_count = 0
                    device.set_nonblocking(1)
                    try:
                        for _ in range(63):
                            more = device.read(64)
                            if more:
                                latest = more
                                drain_count += 1
                            else:
                                break
                    finally:
                        device.set_nonblocking(0)
                    if first_report:
                        first_report = False
                        logger.info("First USB report: id=0x%02X len=%d "
                                    "first16=%s",
                                    latest[0] if latest else 0,
                                    len(latest),
                                    ' '.join(f'{b:02X}' for b in latest[:16]))
                    if IS_WINDOWS:
                        if latest[0] == 0x05:
                            latest = _translate_report_0x05(latest)
                        elif latest[0] == 0x0A:
                            latest = _translate_report_0x0A(latest)
                        else:
                            latest = latest[1:]
                    self._process_data(latest, t_read=t_read,
                                       drain_count=drain_count)
                except Exception as e:
                    if self.is_reading:
                        print(f"Read error: {e}")
                    break
        except Exception as e:
            self._on_error(f"Read loop error: {e}")
        finally:
            self.is_reading = False
            if not self._stop_event.is_set() and self._on_disconnect:
                self._on_disconnect()

    def _read_loop_ble(self):
        """BLE reading loop — blocks on queue for immediate wakeup on data."""
        try:
            while self.is_reading and not self._stop_event.is_set():
                try:
                    latest = self._ble_queue.get(timeout=0.008)
                except queue.Empty:
                    continue
                t_read = time.perf_counter()
                drain_count = 0
                try:
                    while True:
                        latest = self._ble_queue.get_nowait()
                        drain_count += 1
                except queue.Empty:
                    pass
                self._process_data(latest, t_read=t_read,
                                   drain_count=drain_count)
        except Exception as e:
            self._on_error(f"BLE read loop error: {e}")
        finally:
            self.is_reading = False
            if not self._stop_event.is_set() and self._on_disconnect:
                self._on_disconnect()

    def _process_data(self, data: list, t_read: float = 0.0,
                       drain_count: int = 0):
        """Process raw controller data and route to subsystems."""
        if len(data) < 15:
            return

        # Connection warmup gate: during BLE -> USB transitions (and other
        # connection events) the NSO GC controller briefly emits non-zero
        # status bits in the button bytes before settling.  Discard those
        # initial reports so we never forward phantom button presses to the
        # virtual gamepad.  The gate opens on the first all-zero buttons
        # report (controller has settled) or after a short failsafe timeout
        # so a user holding a button at connect time still gets registered.
        if not self._warmup_passed:
            buttons_clean = (data[3] == 0 and data[4] == 0 and data[5] == 0)
            elapsed = time.perf_counter() - self._warmup_start_t
            if buttons_clean or elapsed >= self._warmup_timeout_s:
                self._warmup_passed = True
            else:
                return

        left_stick_x = data[6] | ((data[7] & 0x0F) << 8)
        left_stick_y = ((data[7] >> 4) | (data[8] << 4))
        right_stick_x = data[9] | ((data[10] & 0x0F) << 8)
        right_stick_y = ((data[10] >> 4) | (data[11] << 4))

        if self._cal_mgr.stick_calibrating:
            self._cal_mgr.track_stick_data(left_stick_x, left_stick_y,
                                           right_stick_x, right_stick_y)

        cal = self._calibration
        left_x_norm = normalize(left_stick_x, cal['stick_left_center_x'], cal['stick_left_range_x'])
        left_y_norm = normalize(left_stick_y, cal['stick_left_center_y'], cal['stick_left_range_y'])
        right_x_norm = normalize(right_stick_x, cal['stick_right_center_x'], cal['stick_right_range_x'])
        right_y_norm = normalize(right_stick_y, cal['stick_right_center_y'], cal['stick_right_range_y'])

        if not self._cal_mgr.stick_calibrating:
            dz = cal.get('stick_deadzone', 0.05)
            left_x_norm = apply_deadzone(left_x_norm, dz)
            left_y_norm = apply_deadzone(left_y_norm, dz)
            right_x_norm = apply_deadzone(right_x_norm, dz)
            right_y_norm = apply_deadzone(right_y_norm, dz)

        button_states = {}
        for button in BUTTONS:
            if len(data) > button.byte_index:
                pressed = (data[button.byte_index] & button.mask) != 0
                button_states[button.name] = pressed

        left_trigger = data[13] if len(data) > 13 else 0
        right_trigger = data[14] if len(data) > 14 else 0

        self._cal_mgr.update_trigger_raw(left_trigger, right_trigger)

        t_emu_start = time.perf_counter()
        if self._emu_mgr.is_emulating and self._emu_mgr.gamepad:
            self._emu_mgr.update(left_x_norm, left_y_norm, right_x_norm, right_y_norm,
                                 left_trigger, right_trigger, button_states)
        t_done = time.perf_counter()

        # Latency profiling (zero overhead when disabled)
        if _latency_profiling and t_read > 0:
            self._prof_report_count += 1
            if self._prof_last_read_t > 0:
                interval_us = int((t_read - self._prof_last_read_t) * 1_000_000)
                self._prof_intervals.append(interval_us)
            self._prof_last_read_t = t_read

            process_us = int((t_emu_start - t_read) * 1_000_000)
            emu_us = int((t_done - t_emu_start) * 1_000_000)
            total_us = int((t_done - t_read) * 1_000_000)
            self._prof_process_times.append(process_us)
            self._prof_emu_times.append(emu_us)
            self._prof_total_times.append(total_us)
            self._prof_drain_counts.append(drain_count)

            raw = (left_stick_x, left_stick_y, right_stick_x, right_stick_y,
                   left_trigger, right_trigger)
            if self._raw_mins is None:
                self._raw_mins = list(raw)
                self._raw_maxs = list(raw)
                self._raw_sums = [0] * 6
                self._raw_count = 0
            for j in range(6):
                if raw[j] < self._raw_mins[j]:
                    self._raw_mins[j] = raw[j]
                if raw[j] > self._raw_maxs[j]:
                    self._raw_maxs[j] = raw[j]
                self._raw_sums[j] += raw[j]
            self._raw_count += 1

            now = t_done
            if now - self._prof_last_print >= 1.0:
                self._prof_last_print = now
                self._print_latency_stats()

        self._debug_log_counter += 1
        if self._debug_log_counter % 250 == 0:
            pressed = [b for b, v in button_states.items() if v]
            logger.debug("Input: LT=%d RT=%d LS=(%.2f,%.2f) RS=(%.2f,%.2f) btn=%s",
                         left_trigger, right_trigger,
                         left_x_norm, left_y_norm, right_x_norm, right_y_norm,
                         pressed or "none")

        self._ui_update_counter += 1
        if self._ui_update_counter % 3 == 0:
            self._on_ui_update(left_x_norm, left_y_norm, right_x_norm, right_y_norm,
                               left_trigger, right_trigger, button_states,
                               self._cal_mgr.stick_calibrating)

    def _print_latency_stats(self):
        """Print a single line of latency stats to stderr."""
        def _fmt(deq):
            if not deq:
                return "---", "---", "---"
            s = sorted(deq)
            avg = sum(s) // len(s)
            p99_idx = min(int(len(s) * 0.99), len(s) - 1)
            return f"{avg/1000:.2f}", f"{s[p99_idx]/1000:.2f}", f"{s[-1]/1000:.2f}"

        int_avg, int_p99, int_max = _fmt(self._prof_intervals)
        proc_avg, proc_p99, _ = _fmt(self._prof_process_times)
        emu_avg, emu_p99, _ = _fmt(self._prof_emu_times)
        total_avg, total_p99, total_max = _fmt(self._prof_total_times)

        hz = "---"
        if self._prof_intervals:
            avg_us = sum(self._prof_intervals) / len(self._prof_intervals)
            if avg_us > 0:
                hz = f"{1_000_000 / avg_us:.0f}"

        drains = sum(self._prof_drain_counts)

        print(
            f"[LATENCY] {hz:>4}Hz | "
            f"interval: {int_avg}/{int_p99}/{int_max}ms | "
            f"parse: {proc_avg}/{proc_p99}ms | "
            f"emu: {emu_avg}/{emu_p99}ms | "
            f"total: {total_avg}/{total_p99}/{total_max}ms | "
            f"drops: {drains}",
            file=sys.stderr, flush=True
        )

        if self._raw_mins is not None and self._raw_count > 0:
            labels = ('LX', 'LY', 'RX', 'RY', 'LT', 'RT')
            avgs = [self._raw_sums[j] / self._raw_count for j in range(6)]
            parts = []
            for j, lbl in enumerate(labels):
                parts.append(f"{lbl}={self._raw_mins[j]}/{avgs[j]:.0f}/{self._raw_maxs[j]}")
            print(
                f"[RAW CAL] {' | '.join(parts)}  (min/avg/max, n={self._raw_count})",
                file=sys.stderr, flush=True
            )
