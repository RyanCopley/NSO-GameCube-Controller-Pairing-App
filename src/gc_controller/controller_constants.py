"""
Controller Constants

Shared data classes, USB identifiers, button mappings, default calibration values,
and utility functions used across all modules.
"""

from .virtual_gamepad import GamepadButton

# Maximum number of simultaneous controller slots
MAX_SLOTS = 4


class ButtonInfo:
    """Represents a GameCube controller button mapping"""
    def __init__(self, byte_index: int, mask: int, name: str):
        self.byte_index = byte_index
        self.mask = mask
        self.name = name


# GameCube controller USB IDs
VENDOR_ID = 0x057e
PRODUCT_ID = 0x2073

# USB initialization commands
DEFAULT_REPORT_DATA = bytes([0x03, 0x91, 0x00, 0x0d, 0x00, 0x08,
                             0x00, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
SET_LED_DATA = bytes([0x09, 0x91, 0x00, 0x07, 0x00, 0x08,
                      0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

# Xbox 360 button mapping
BUTTON_MAPPING = {
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

# Button definitions for HID data parsing
BUTTONS = [
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

# Default calibration values (per-slot, runtime only)
DEFAULT_CALIBRATION = {
    'trigger_left_base': 32.0,
    'trigger_left_bump': 190.0,
    'trigger_left_max': 230.0,
    'trigger_right_base': 32.0,
    'trigger_right_bump': 190.0,
    'trigger_right_max': 230.0,
    'trigger_bump_100_percent': False,
    'emulation_mode': 'xbox360',
    'stick_left_center_x': 2048, 'stick_left_range_x': 2048,
    'stick_left_center_y': 2048, 'stick_left_range_y': 2048,
    'stick_right_center_x': 2048, 'stick_right_range_x': 2048,
    'stick_right_center_y': 2048, 'stick_right_range_y': 2048,
    'auto_connect': True,
    'auto_scan_ble': True,
    'minimize_to_tray': True,
    'preferred_device_path': '',
    'stick_left_octagon': None,
    'stick_right_octagon': None,
}

# Calibration keys that are per-device (follow the physical controller, not the slot).
# These are stored in known_ble_devices[mac] and loaded into a slot at connect time.
BLE_DEVICE_CAL_KEYS = {
    'stick_left_octagon', 'stick_right_octagon',
    'stick_left_center_x', 'stick_left_range_x',
    'stick_left_center_y', 'stick_left_range_y',
    'stick_right_center_x', 'stick_right_range_x',
    'stick_right_center_y', 'stick_right_range_y',
    'trigger_left_base', 'trigger_left_bump', 'trigger_left_max',
    'trigger_right_base', 'trigger_right_bump', 'trigger_right_max',
}


# BLE rumble
BLE_RUMBLE_HANDLE = 0x0016        # ATT handle for command + rumble channel
BLE_RUMBLE_PACKET_LEN = 21        # Total packet length
BLE_RUMBLE_TID_BASE = 0x50        # Transaction ID base (lower nibble increments)


def normalize(raw, center, range_val):
    """Normalize a raw stick value to [-1.0, 1.0]."""
    return max(-1.0, min(1.0, (raw - center) / max(range_val, 1)))
