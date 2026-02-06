"""
Controller Slot

Bundles per-controller state for multi-controller support.
Each slot has its own managers, calibration, and device connection.
"""

import queue
from typing import Optional

from .calibration import CalibrationManager
from .connection_manager import ConnectionManager
from .emulation_manager import EmulationManager
from .input_processor import InputProcessor


class ControllerSlot:
    """Per-controller state container.

    Each slot is fully independent — its own HID read thread,
    calibration lock, virtual gamepad, and connection.
    """

    def __init__(self, index: int, calibration: dict,
                 on_status, on_progress, on_ui_update, on_error, on_disconnect):
        self.index = index
        self.calibration = calibration
        self.device_path: Optional[bytes] = None
        self.reconnect_was_emulating = False

        # BLE state
        self.connection_mode: str = calibration.get('connection_mode', 'usb')
        self.ble_address: Optional[str] = calibration.get('preferred_ble_address', '') or None
        self.ble_data_queue: queue.Queue = queue.Queue(maxsize=64)
        self.ble_connected: bool = False

        # Rumble state
        self.rumble_tid: int = 0
        self.rumble_state: bool = False

        self.cal_mgr = CalibrationManager(calibration)
        self.conn_mgr = ConnectionManager(on_status=on_status, on_progress=on_progress)
        self.emu_mgr = EmulationManager(self.cal_mgr)
        self.input_proc = InputProcessor(
            device_getter=lambda: self.conn_mgr.device,
            calibration=calibration,
            cal_mgr=self.cal_mgr,
            emu_mgr=self.emu_mgr,
            on_ui_update=on_ui_update,
            on_error=on_error,
            on_disconnect=on_disconnect,
            ble_queue=self.ble_data_queue,
        )

    @property
    def is_connected(self) -> bool:
        return self.input_proc.is_reading

    @property
    def is_emulating(self) -> bool:
        return self.emu_mgr.is_emulating
