"""
Connection Manager

Handles USB initialization and HID device connection for the GameCube controller.
Supports multi-device enumeration and path-targeted open for multi-controller setups.
"""

import sys
from typing import Optional, Callable, List

import hid
import usb.core
import usb.util

from .controller_constants import VENDOR_ID, PRODUCT_ID, DEFAULT_REPORT_DATA, SET_LED_DATA

IS_MACOS = sys.platform == "darwin"


class ConnectionManager:
    """Manages USB initialization and HID connection."""

    def __init__(self, on_status: Callable[[str], None], on_progress: Callable[[int], None]):
        self._on_status = on_status
        self._on_progress = on_progress
        self.device: Optional[hid.device] = None
        self.device_path: Optional[bytes] = None

    @staticmethod
    def enumerate_devices() -> List[dict]:
        """Return a list of HID device info dicts for all connected GC controllers."""
        devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
        if sys.platform == 'win32':
            import os, pathlib
            log = pathlib.Path(os.path.expanduser("~/gc_debug.txt"))
            with open(log, "a") as f:
                f.write(f"--- enumerate: {len(devices)} device(s) ---\n")
                for i, d in enumerate(devices):
                    f.write(f"  dev {i}: interface={d.get('interface_number', '?')} "
                            f"usage_page=0x{d.get('usage_page', 0):04x} "
                            f"usage=0x{d.get('usage', 0):04x} "
                            f"path={d['path']}\n")
        return devices

    @staticmethod
    def enumerate_usb_devices() -> list:
        """Return a list of all USB device objects matching the GC controller VID/PID."""
        try:
            devices = usb.core.find(find_all=True, idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            return list(devices) if devices else []
        except Exception:
            # pyusb backend not available (e.g. missing libusb on Windows)
            return []

    def initialize_via_usb(self, usb_device=None) -> bool:
        """Initialize controller via USB.

        If usb_device is provided, use it directly instead of scanning.
        """
        try:
            self._on_status("Looking for device...")
            self._on_progress(10)

            dev = usb_device if usb_device is not None else usb.core.find(
                idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            if dev is None:
                self._on_status("Device not found")
                return False

            self._on_status("Device found")
            self._on_progress(30)

            if IS_MACOS:
                try:
                    if dev.is_kernel_driver_active(1):
                        dev.detach_kernel_driver(1)
                except (usb.core.USBError, NotImplementedError):
                    pass

            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass  # May already be configured

            try:
                usb.util.claim_interface(dev, 1)
            except usb.core.USBError:
                pass  # May already be claimed

            self._on_progress(50)

            self._on_status("Sending initialization data...")
            dev.write(0x02, DEFAULT_REPORT_DATA, 2000)

            self._on_progress(70)

            self._on_status("Sending LED data...")
            dev.write(0x02, SET_LED_DATA, 2000)

            self._on_progress(90)

            try:
                usb.util.release_interface(dev, 1)
            except usb.core.USBError:
                pass

            # Release pyusb resources so the handle is fully closed before
            # HIDAPI opens the device — prevents conflicts on Windows where
            # WinUSB and HID class driver can't share the device.
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass

            self._on_status("USB initialization complete")
            return True

        except Exception as e:
            self._on_status(f"USB initialization failed: {e}")
            return False

    def init_hid_device(self, device_path: Optional[bytes] = None) -> bool:
        """Initialize HID connection.

        If device_path is provided, open that specific device by path.
        Otherwise, open the first matching VID/PID device.
        """
        try:
            self._on_status("Connecting via HID...")

            self.device = hid.device()
            if device_path:
                self.device.open_path(device_path)
            else:
                self.device.open(VENDOR_ID, PRODUCT_ID)

            if self.device:
                self.device_path = device_path
                self._on_status("Connected via HID")
                self._on_progress(100)
                return True
            else:
                self._on_status("Failed to connect via HID")
                return False

        except Exception as e:
            self._on_status(f"HID connection failed: {e}")
            return False

    def connect(self, usb_device=None, device_path: Optional[bytes] = None) -> bool:
        """Full connection sequence: USB init then HID.

        Optionally target a specific USB device and/or HID device path.
        """
        if not self.initialize_via_usb(usb_device=usb_device):
            return False
        return self.init_hid_device(device_path=device_path)

    def send_rumble(self, state: bool) -> bool:
        """Send a rumble ON/OFF command via USB endpoint 0x02 on interface 1.

        Uses the SW2 vibration pattern command (0x0A) in the standard
        command format — the same transport used for init and LED commands.

        Acquires a fresh pyusb device each time and releases it after use
        to avoid holding WinUSB handles that conflict with HIDAPI on Windows.
        """
        try:
            dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            if dev is None:
                return False
        except Exception:
            return False
        # CMD 0x0A = set vibration pattern, interface 0x00 = USB
        cmd = bytes([0x0a, 0x91, 0x00, 0x02, 0x00, 0x04,
                     0x00, 0x00, 0x01 if state else 0x00,
                     0x00, 0x00, 0x00])
        try:
            try:
                usb.util.claim_interface(dev, 1)
            except usb.core.USBError:
                pass
            dev.write(0x02, cmd, 1000)
            try:
                usb.util.release_interface(dev, 1)
            except usb.core.USBError:
                pass
            return True
        except Exception as e:
            print(f"USB rumble write error: {e}")
            return False
        finally:
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass

    def disconnect(self):
        """Close and release the HID device."""
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
            self.device_path = None
