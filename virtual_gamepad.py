"""
Virtual Gamepad Platform Abstraction Layer

Provides a unified interface for Xbox 360 controller emulation across platforms:
- Windows: vgamepad (ViGEmBus)
- Linux: python-evdev (uinput)
- macOS: Not supported
"""

import os
import sys
from abc import ABC, abstractmethod
from enum import Enum, auto


class GamepadButton(Enum):
    """Platform-independent button constants for Xbox 360 controller."""
    A = auto()
    B = auto()
    X = auto()
    Y = auto()
    LEFT_SHOULDER = auto()
    RIGHT_SHOULDER = auto()
    LEFT_THUMB = auto()
    RIGHT_THUMB = auto()
    START = auto()
    BACK = auto()
    GUIDE = auto()
    DPAD_UP = auto()
    DPAD_DOWN = auto()
    DPAD_LEFT = auto()
    DPAD_RIGHT = auto()


class VirtualGamepad(ABC):
    """Abstract base class for virtual Xbox 360 controller emulation."""

    @abstractmethod
    def left_joystick(self, x_value: int, y_value: int) -> None:
        """Set left joystick position. Values in range [-32767, 32767]."""

    @abstractmethod
    def right_joystick(self, x_value: int, y_value: int) -> None:
        """Set right joystick position. Values in range [-32767, 32767]."""

    @abstractmethod
    def left_trigger(self, value: int) -> None:
        """Set left trigger value. Range [0, 255]."""

    @abstractmethod
    def right_trigger(self, value: int) -> None:
        """Set right trigger value. Range [0, 255]."""

    @abstractmethod
    def press_button(self, button: GamepadButton) -> None:
        """Press a button."""

    @abstractmethod
    def release_button(self, button: GamepadButton) -> None:
        """Release a button."""

    @abstractmethod
    def update(self) -> None:
        """Flush buffered events to the virtual device."""

    @abstractmethod
    def reset(self) -> None:
        """Reset all inputs to neutral."""

    @abstractmethod
    def close(self) -> None:
        """Destroy the virtual device and release resources."""


class WindowsGamepad(VirtualGamepad):
    """Windows implementation using vgamepad (ViGEmBus)."""

    # Map our GamepadButton enum to vgamepad's XUSB_BUTTON constants
    _BUTTON_MAP = None

    def __init__(self):
        import vgamepad as vg
        self._vg = vg
        self._pad = vg.VX360Gamepad()

        if WindowsGamepad._BUTTON_MAP is None:
            WindowsGamepad._BUTTON_MAP = {
                GamepadButton.A: vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                GamepadButton.B: vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                GamepadButton.X: vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                GamepadButton.Y: vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                GamepadButton.LEFT_SHOULDER: vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                GamepadButton.RIGHT_SHOULDER: vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                GamepadButton.LEFT_THUMB: vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
                GamepadButton.RIGHT_THUMB: vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
                GamepadButton.START: vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
                GamepadButton.BACK: vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                GamepadButton.GUIDE: vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
                GamepadButton.DPAD_UP: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
                GamepadButton.DPAD_DOWN: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
                GamepadButton.DPAD_LEFT: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
                GamepadButton.DPAD_RIGHT: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
            }

    def left_joystick(self, x_value: int, y_value: int) -> None:
        self._pad.left_joystick(x_value=x_value, y_value=y_value)

    def right_joystick(self, x_value: int, y_value: int) -> None:
        self._pad.right_joystick(x_value=x_value, y_value=y_value)

    def left_trigger(self, value: int) -> None:
        self._pad.left_trigger(value=value)

    def right_trigger(self, value: int) -> None:
        self._pad.right_trigger(value=value)

    def press_button(self, button: GamepadButton) -> None:
        self._pad.press_button(button=self._BUTTON_MAP[button])

    def release_button(self, button: GamepadButton) -> None:
        self._pad.release_button(button=self._BUTTON_MAP[button])

    def update(self) -> None:
        self._pad.update()

    def reset(self) -> None:
        self._pad.reset()

    def close(self) -> None:
        try:
            self._pad.reset()
            self._pad.update()
        except Exception:
            pass


class LinuxGamepad(VirtualGamepad):
    """Linux implementation using python-evdev and uinput.

    Creates a virtual Xbox 360 controller (vendor=0x045e, product=0x028e)
    that is recognized by applications as a standard Xbox gamepad.
    """

    def __init__(self):
        import evdev
        from evdev import UInput, AbsInfo, ecodes

        self._ecodes = ecodes

        # Capability setup for Xbox 360 controller
        cap = {
            ecodes.EV_ABS: [
                # Left stick
                (ecodes.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                # Right stick
                (ecodes.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (ecodes.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                # Triggers
                (ecodes.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                # D-Pad (hat switch)
                (ecodes.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            ],
            ecodes.EV_KEY: [
                ecodes.BTN_A,
                ecodes.BTN_B,
                ecodes.BTN_X,
                ecodes.BTN_Y,
                ecodes.BTN_TL,      # Left shoulder
                ecodes.BTN_TR,      # Right shoulder
                ecodes.BTN_THUMBL,  # Left thumb
                ecodes.BTN_THUMBR,  # Right thumb
                ecodes.BTN_START,
                ecodes.BTN_SELECT,  # Back
                ecodes.BTN_MODE,    # Guide
            ],
        }

        self._device = UInput(
            events=cap,
            name="Microsoft X-Box 360 pad",
            vendor=0x045E,
            product=0x028E,
            version=0x0110,
            bustype=ecodes.BUS_USB,
        )

        # Button mapping: GamepadButton -> evdev key code
        self._button_map = {
            GamepadButton.A: ecodes.BTN_A,
            GamepadButton.B: ecodes.BTN_B,
            GamepadButton.X: ecodes.BTN_X,
            GamepadButton.Y: ecodes.BTN_Y,
            GamepadButton.LEFT_SHOULDER: ecodes.BTN_TL,
            GamepadButton.RIGHT_SHOULDER: ecodes.BTN_TR,
            GamepadButton.LEFT_THUMB: ecodes.BTN_THUMBL,
            GamepadButton.RIGHT_THUMB: ecodes.BTN_THUMBR,
            GamepadButton.START: ecodes.BTN_START,
            GamepadButton.BACK: ecodes.BTN_SELECT,
            GamepadButton.GUIDE: ecodes.BTN_MODE,
        }

        # D-Pad buttons map to hat axes, not key events.
        # Track D-Pad state to handle diagonals correctly.
        self._dpad_x = 0  # -1=left, 0=center, 1=right
        self._dpad_y = 0  # -1=up, 0=center, 1=down

    def left_joystick(self, x_value: int, y_value: int) -> None:
        ec = self._ecodes
        self._device.write(ec.EV_ABS, ec.ABS_X, x_value)
        # Invert Y: callers use positive-up, evdev uses positive-down
        self._device.write(ec.EV_ABS, ec.ABS_Y, -y_value)

    def right_joystick(self, x_value: int, y_value: int) -> None:
        ec = self._ecodes
        self._device.write(ec.EV_ABS, ec.ABS_RX, x_value)
        self._device.write(ec.EV_ABS, ec.ABS_RY, -y_value)

    def left_trigger(self, value: int) -> None:
        self._device.write(self._ecodes.EV_ABS, self._ecodes.ABS_Z, value)

    def right_trigger(self, value: int) -> None:
        self._device.write(self._ecodes.EV_ABS, self._ecodes.ABS_RZ, value)

    def press_button(self, button: GamepadButton) -> None:
        if button in (GamepadButton.DPAD_UP, GamepadButton.DPAD_DOWN,
                      GamepadButton.DPAD_LEFT, GamepadButton.DPAD_RIGHT):
            self._set_dpad(button, pressed=True)
        else:
            code = self._button_map[button]
            self._device.write(self._ecodes.EV_KEY, code, 1)

    def release_button(self, button: GamepadButton) -> None:
        if button in (GamepadButton.DPAD_UP, GamepadButton.DPAD_DOWN,
                      GamepadButton.DPAD_LEFT, GamepadButton.DPAD_RIGHT):
            self._set_dpad(button, pressed=False)
        else:
            code = self._button_map[button]
            self._device.write(self._ecodes.EV_KEY, code, 0)

    def _set_dpad(self, button: GamepadButton, pressed: bool) -> None:
        """Translate D-Pad button press/release to HAT axis values."""
        ec = self._ecodes
        if button == GamepadButton.DPAD_LEFT:
            self._dpad_x = -1 if pressed else (1 if self._dpad_x == 1 else 0)
        elif button == GamepadButton.DPAD_RIGHT:
            self._dpad_x = 1 if pressed else (-1 if self._dpad_x == -1 else 0)
        elif button == GamepadButton.DPAD_UP:
            self._dpad_y = -1 if pressed else (1 if self._dpad_y == 1 else 0)
        elif button == GamepadButton.DPAD_DOWN:
            self._dpad_y = 1 if pressed else (-1 if self._dpad_y == -1 else 0)

        self._device.write(ec.EV_ABS, ec.ABS_HAT0X, self._dpad_x)
        self._device.write(ec.EV_ABS, ec.ABS_HAT0Y, self._dpad_y)

    def update(self) -> None:
        self._device.syn()

    def reset(self) -> None:
        ec = self._ecodes
        # Center sticks
        self._device.write(ec.EV_ABS, ec.ABS_X, 0)
        self._device.write(ec.EV_ABS, ec.ABS_Y, 0)
        self._device.write(ec.EV_ABS, ec.ABS_RX, 0)
        self._device.write(ec.EV_ABS, ec.ABS_RY, 0)
        # Release triggers
        self._device.write(ec.EV_ABS, ec.ABS_Z, 0)
        self._device.write(ec.EV_ABS, ec.ABS_RZ, 0)
        # Release D-Pad
        self._dpad_x = 0
        self._dpad_y = 0
        self._device.write(ec.EV_ABS, ec.ABS_HAT0X, 0)
        self._device.write(ec.EV_ABS, ec.ABS_HAT0Y, 0)
        # Release all buttons
        for code in self._button_map.values():
            self._device.write(ec.EV_KEY, code, 0)
        self._device.syn()

    def close(self) -> None:
        try:
            self.reset()
        except Exception:
            pass
        try:
            self._device.close()
        except Exception:
            pass


def is_emulation_available() -> bool:
    """Check whether virtual gamepad emulation is available on this platform."""
    if sys.platform == "win32":
        try:
            import vgamepad
            return True
        except ImportError:
            return False
    elif sys.platform == "linux":
        try:
            import evdev
            return os.access('/dev/uinput', os.W_OK)
        except ImportError:
            return False
    else:
        return False


def get_emulation_unavailable_reason() -> str:
    """Return a human-readable explanation of why emulation is unavailable."""
    if sys.platform == "win32":
        return (
            "Xbox 360 emulation requires vgamepad and ViGEmBus driver.\n"
            "Install vgamepad: pip install vgamepad\n"
            "Install ViGEmBus: https://github.com/nefarius/ViGEmBus"
        )
    elif sys.platform == "linux":
        return (
            "Xbox 360 emulation requires python-evdev and uinput access.\n"
            "Install evdev: pip install evdev\n"
            "Ensure /dev/uinput is accessible (add udev rule or run as root)."
        )
    elif sys.platform == "darwin":
        return (
            "Xbox 360 controller emulation is not supported on macOS.\n"
            "macOS does not allow user-space creation of virtual HID game controllers."
        )
    else:
        return f"Xbox 360 emulation is not supported on {sys.platform}."


def create_gamepad() -> VirtualGamepad:
    """Factory: create the appropriate VirtualGamepad for the current platform."""
    if sys.platform == "win32":
        return WindowsGamepad()
    elif sys.platform == "linux":
        return LinuxGamepad()
    elif sys.platform == "darwin":
        raise RuntimeError(
            "Xbox 360 controller emulation is not supported on macOS.\n"
            "macOS does not allow user-space creation of virtual HID game controllers.\n"
            "Consider using a hardware adapter or alternative input remapping tool."
        )
    else:
        raise RuntimeError(f"Virtual gamepad emulation is not supported on {sys.platform}.")
