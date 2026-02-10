"""
Settings Manager

Handles loading and saving calibration settings to a JSON file,
including migration from v1/v2 (slot-based) to v3 (global-only) format.

v3 format: only global settings + known_ble_devices (per-device calibration).
No per-slot data is persisted — slots are assigned at runtime.
"""

import json
import os
from typing import List

from .controller_constants import DEFAULT_CALIBRATION, MAX_SLOTS, BLE_DEVICE_CAL_KEYS


# Keys stored in the global section of the config file.
_GLOBAL_KEYS = {
    'auto_connect', 'auto_scan_ble', 'emulation_mode', 'trigger_bump_100_percent',
    'minimize_to_tray', 'known_ble_devices',
}


class SettingsManager:
    """Manages persistent calibration settings."""

    def __init__(self, slot_calibrations: List[dict], settings_dir: str):
        self._slot_calibrations = slot_calibrations
        self._settings_file = os.path.join(settings_dir, 'gc_controller_settings.json')

    def load(self):
        """Load settings from file. Handles v1, v2, and v3 formats."""
        try:
            if not os.path.exists(self._settings_file):
                return
            with open(self._settings_file, 'r') as f:
                saved = json.load(f)

            version = saved.get('version', 1)
            if version >= 3:
                self._load_v3(saved)
            elif version >= 2:
                self._load_v2(saved)
            else:
                self._load_v1(saved)
        except Exception as e:
            print(f"Failed to load settings: {e}")

    def _load_v1(self, saved: dict):
        """Migrate v1 flat settings — extract global keys only."""
        key_migration = {
            'left_base': 'trigger_left_base',
            'left_bump': 'trigger_left_bump',
            'left_max': 'trigger_left_max',
            'right_base': 'trigger_right_base',
            'right_bump': 'trigger_right_bump',
            'right_max': 'trigger_right_max',
            'bump_100_percent': 'trigger_bump_100_percent',
        }
        for old_key, new_key in key_migration.items():
            if old_key in saved and new_key not in saved:
                saved[new_key] = saved.pop(old_key)
            elif old_key in saved:
                del saved[old_key]

        # Apply only global keys
        for key in _GLOBAL_KEYS:
            if key in saved:
                self._slot_calibrations[0][key] = saved[key]

    def _load_v2(self, saved: dict):
        """Migrate v2 multi-slot format — extract global keys + build device registry."""
        global_settings = saved.get('global', {})
        slots_data = saved.get('slots', {})

        # Migrate known_ble_addresses → known_ble_devices
        old_known = global_settings.pop('known_ble_addresses', [])
        known_devices = global_settings.get('known_ble_devices', {})

        # Build device entries from per-slot preferred_ble_address + calibration
        for i in range(MAX_SLOTS):
            slot_data = slots_data.get(str(i), {})
            addr = (slot_data.get('preferred_ble_address', '') or '').upper()

            if addr and addr not in known_devices:
                dev_cal = {}
                for key in BLE_DEVICE_CAL_KEYS:
                    if key in slot_data:
                        dev_cal[key] = slot_data[key]
                known_devices[addr] = dev_cal

        # Add any addresses from old known_ble_addresses list
        for addr in old_known:
            addr_upper = addr.upper()
            if addr_upper not in known_devices:
                known_devices[addr_upper] = {}

        global_settings['known_ble_devices'] = known_devices

        # Apply only global keys to slot 0
        for key in _GLOBAL_KEYS:
            if key in global_settings:
                self._slot_calibrations[0][key] = global_settings[key]

    def _load_v3(self, saved: dict):
        """Load v3 format — global settings only."""
        global_settings = saved.get('global', {})
        for key in _GLOBAL_KEYS:
            if key in global_settings:
                self._slot_calibrations[0][key] = global_settings[key]

    def save(self):
        """Write settings in v3 format (global only). Raises on failure."""
        cal = self._slot_calibrations[0]
        global_settings = {key: cal[key] for key in _GLOBAL_KEYS if key in cal}

        output = {
            'version': 3,
            'global': global_settings,
        }

        with open(self._settings_file, 'w') as f:
            json.dump(output, f, indent=2)
