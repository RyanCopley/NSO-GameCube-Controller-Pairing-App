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

    # Standard Switch rumble data (4 bytes per motor)
    _RUMBLE_ON = bytes([0x28, 0x88, 0x60, 0x61])
    _RUMBLE_OFF = bytes([0x00, 0x01, 0x40, 0x40])

    def __init__(self, on_status: Callable[[str], None], on_progress: Callable[[int], None]):
        self._on_status = on_status
        self._on_progress = on_progress
        self.device: Optional[hid.device] = None
        self.device_path: Optional[bytes] = None
        self._rumble_counter = 0

    @staticmethod
    def enumerate_devices() -> List[dict]:
        """Return a list of HID device info dicts for all connected GC controllers."""
        return hid.enumerate(VENDOR_ID, PRODUCT_ID)

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
        """Send a rumble ON/OFF command.

        Tries pyusb first (endpoint 0x02 on interface 1), then falls back
        to HIDAPI write for Windows where pyusb/libusb is unavailable.
        """
        cmd = bytes([0x0a, 0x91, 0x00, 0x02, 0x00, 0x04,
                     0x00, 0x00, 0x01 if state else 0x00,
                     0x00, 0x00, 0x00])

        # Try pyusb (works on Linux/macOS)
        try:
            dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            if dev is not None:
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
                except Exception:
                    pass
                finally:
                    try:
                        usb.util.dispose_resources(dev)
                    except Exception:
                        pass
        except Exception:
            pass

        # Fallback: try alternative HIDAPI methods (Windows — no pyusb)
        if self.device:
            import os, pathlib
            log = pathlib.Path(os.path.expanduser("~/gc_rumble_debug.txt"))
            rumble = self._RUMBLE_ON if state else self._RUMBLE_OFF
            sw2_cmd = bytes([0x0a, 0x91, 0x00, 0x02, 0x00, 0x04,
                             0x00, 0x00, 0x01 if state else 0x00,
                             0x00, 0x00, 0x00])

            results = []
            # Try send_feature_report with SW2 command
            for report_id in [0x00, 0x05, 0x0a]:
                try:
                    pkt = bytes([report_id]) + sw2_cmd
                    ret = self.device.send_feature_report(pkt)
                    results.append(f"feature report_id=0x{report_id:02x}: {ret}")
                    if ret > 0:
                        with open(log, "a") as f:
                            f.write("\n".join(results) + "\n")
                        return True
                except Exception as e:
                    results.append(f"feature report_id=0x{report_id:02x}: {type(e).__name__}: {e}")

            # Try write with various report IDs
            for report_id in [0x05, 0x80]:
                try:
                    pkt = bytearray(64)
                    pkt[0] = report_id
                    pkt[1:1+len(sw2_cmd)] = sw2_cmd
                    ret = self.device.write(bytes(pkt))
                    results.append(f"write report_id=0x{report_id:02x}: {ret}")
                    if ret > 0:
                        with open(log, "a") as f:
                            f.write("\n".join(results) + "\n")
                        return True
                except Exception as e:
                    results.append(f"write report_id=0x{report_id:02x}: {type(e).__name__}: {e}")

            with open(log, "a") as f:
                f.write("\n".join(results) + "\n---\n")
        return False

    def disconnect(self):
        """Close and release the HID device."""
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
            self.device_path = None
