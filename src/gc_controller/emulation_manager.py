"""
Emulation Manager

Handles virtual controller creation, teardown, and the hot-path
update that maps GC input to the virtual gamepad.

Supports Xbox 360 mode and Dolphin named pipe mode.
"""

import errno
import threading
from typing import Optional, Dict

from .virtual_gamepad import VirtualGamepad, create_gamepad
from .controller_constants import BUTTON_MAPPING
from .calibration import CalibrationManager


class EmulationManager:
    """Manages controller emulation lifecycle and input forwarding."""

    def __init__(self, cal_mgr: CalibrationManager):
        self._cal_mgr = cal_mgr
        self.gamepad: Optional[VirtualGamepad] = None
        self.is_emulating = False
        self.mode: str = 'xbox360'

    def start(self, mode: str = 'xbox360', slot_index: int = 0,
              cancel_event: threading.Event | None = None,
              rumble_callback=None) -> None:
        """Create the virtual gamepad and begin emulation. Raises on failure."""
        self.mode = mode
        self.gamepad = create_gamepad(mode, slot_index=slot_index,
                                     cancel_event=cancel_event)
        if rumble_callback and mode == 'xbox360':
            self.gamepad.set_rumble_callback(rumble_callback)
        self.is_emulating = True

    def stop(self) -> None:
        """Stop emulation and destroy the virtual gamepad."""
        self.is_emulating = False
        if self.gamepad:
            try:
                self.gamepad.stop_rumble_listener()
            except Exception:
                pass
            try:
                self.gamepad.close()
            except Exception:
                pass
            self.gamepad = None

    def update(self, left_x, left_y, right_x, right_y,
               left_trigger, right_trigger, button_states: Dict[str, bool]):
        """Update virtual Xbox 360 controller state (hot path)."""
        if not self.gamepad:
            return

        try:
            stick_scale = 32767
            left_x_scaled = int(max(-32767, min(32767, left_x * stick_scale)))
            left_y_scaled = int(max(-32767, min(32767, left_y * stick_scale)))
            right_x_scaled = int(max(-32767, min(32767, right_x * stick_scale)))
            right_y_scaled = int(max(-32767, min(32767, right_y * stick_scale)))

            self.gamepad.left_joystick(x_value=left_x_scaled, y_value=left_y_scaled)
            self.gamepad.right_joystick(x_value=right_x_scaled, y_value=right_y_scaled)

            # Process analog triggers with calibration
            left_trigger_calibrated = self._cal_mgr.calibrate_trigger_fast(left_trigger, 'left')
            right_trigger_calibrated = self._cal_mgr.calibrate_trigger_fast(right_trigger, 'right')

            # Update button states
            for button_name, xbox_button in BUTTON_MAPPING.items():
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

            self.gamepad.update()

        except Exception as e:
            print(f"Virtual controller update error: {e}")
