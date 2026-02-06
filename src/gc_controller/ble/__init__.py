"""
BLE Subpackage

Provides Bluetooth Low Energy connectivity for NSO GameCube controllers
using Google Bumble on Linux.
"""

import os
import subprocess
import sys


def is_ble_available() -> bool:
    """Check if BLE support is available (Linux + bumble importable)."""
    if sys.platform != 'linux':
        return False
    try:
        import bumble  # noqa: F401
        return True
    except ImportError:
        return False


def get_ble_unavailable_reason() -> str:
    """Return a human-readable reason why BLE is not available."""
    if sys.platform != 'linux':
        return "BLE support is only available on Linux."
    try:
        import bumble  # noqa: F401
    except ImportError:
        return "The 'bumble' package is not installed. Install with: pip install bumble"
    return ""


def stop_bluez() -> bool:
    """Stop BlueZ bluetooth.service and bring down the HCI adapter.

    Bumble uses raw HCI sockets which require exclusive access.
    Returns True if BlueZ was stopped (or was already stopped).
    """
    try:
        subprocess.run(
            ['systemctl', 'stop', 'bluetooth.service'],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass

    # Find and bring down all HCI adapters
    bt_dir = '/sys/class/bluetooth'
    if os.path.isdir(bt_dir):
        for entry in sorted(os.listdir(bt_dir)):
            if entry.startswith('hci'):
                try:
                    subprocess.run(
                        ['hciconfig', entry, 'down'],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass

    return True


def find_hci_adapter() -> int | None:
    """Find the first available HCI adapter index by checking /sys/class/bluetooth/."""
    bt_dir = '/sys/class/bluetooth'
    if not os.path.isdir(bt_dir):
        return None
    for entry in sorted(os.listdir(bt_dir)):
        if entry.startswith('hci'):
            try:
                return int(entry[3:])
            except ValueError:
                continue
    return None
