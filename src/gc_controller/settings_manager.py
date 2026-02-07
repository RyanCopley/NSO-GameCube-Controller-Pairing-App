"""
Settings Manager

Handles loading and saving calibration settings to a JSON file,
including migration from v1 (single-controller) to v2 (multi-slot) format.
"""

import json
import os
from typing import List

from .controller_constants import DEFAULT_CALIBRATION, MAX_SLOTS


# Keys that belong in per-slot settings (everything except global keys)
_GLOBAL_KEYS = {'auto_connect', 'emulation_mode', 'trigger_bump_100_percent'}


class SettingsManager:
    """Manages persistent calibration settings for up to 4 controller slots."""

    def __init__(self, slot_calibrations: List[dict], settings_dir: str):
        self._slot_calibrations = slot_calibrations
        self._settings_file = os.path.join(settings_dir, 'gc_controller_settings.json')

    def load(self):
        """Load settings from file. Handles v1 (flat) and v2 (multi-slot) formats."""
        try:
            if not os.path.exists(self._settings_file):
                return
            with open(self._settings_file, 'r') as f:
                saved = json.load(f)

            if saved.get('version', 1) >= 2:
                self._load_v2(saved)
            else:
                self._load_v1(saved)
        except Exception as e:
            print(f"Failed to load settings: {e}")

    def _load_v1(self, saved: dict):
        """Migrate v1 flat settings into slot 0, defaults for others."""
        # Run key migration for old trigger key names
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

        # Apply all v1 data to slot 0
        self._slot_calibrations[0].update(saved)

        # Copy global keys (auto_connect) to all slots so the orchestrator can read from slot 0
        # (auto_connect is now a global setting but was stored flat in v1)

    def _load_v2(self, saved: dict):
        """Load v2 multi-slot format."""
        global_settings = saved.get('global', {})
        slots_data = saved.get('slots', {})

        for i in range(MAX_SLOTS):
            slot_data = slots_data.get(str(i), {})
            # Merge global keys into slot 0 for backward compat reading
            if i == 0:
                for key in _GLOBAL_KEYS:
                    if key in global_settings:
                        slot_data.setdefault(key, global_settings[key])
            self._slot_calibrations[i].update(slot_data)

        # Ensure global keys are accessible from slot 0
        for key in _GLOBAL_KEYS:
            if key in global_settings:
                self._slot_calibrations[0][key] = global_settings[key]

    def save(self):
        """Write all slot calibrations in v2 format. Raises on failure."""
        global_settings = {}
        slots_data = {}

        for i in range(MAX_SLOTS):
            cal = self._slot_calibrations[i]
            slot_dict = {}
            for key, value in cal.items():
                if key in _GLOBAL_KEYS:
                    # Only read global keys from slot 0
                    if i == 0:
                        global_settings[key] = value
                else:
                    slot_dict[key] = value
            slots_data[str(i)] = slot_dict

        output = {
            'version': 2,
            'global': global_settings,
            'slots': slots_data,
        }

        with open(self._settings_file, 'w') as f:
            json.dump(output, f, indent=2)
