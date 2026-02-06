"""
Bleak BLE Backend

macOS/Windows BLE backend using the Bleak library.
Approach modeled after nso-gc-bridge: scan all devices, try connecting to each,
send handshake to identify the controller, then subscribe to notifications.

The OS BLE stack handles SMP pairing, MTU negotiation, and encryption automatically.
No elevated privileges needed.
"""

import asyncio
import queue
import sys
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

from .sw2_protocol import (
    H_OUT_CMD, LED_MAP, build_led_cmd, translate_ble_native_to_usb,
)

# Nintendo BLE manufacturer company ID (from protocol doc)
_NINTENDO_COMPANY_ID = 0x037E

# Known Nintendo controller name substrings
_NINTENDO_NAME_PATTERNS = (
    'Pro Controller', 'Nintendo', 'Joy-Con', 'HORI', 'NSO', 'DeviceName',
)

# SPI read command used as handshake (same as nso-gc-bridge BLE_HANDSHAKE_READ_SPI)
_HANDSHAKE_CMD = bytearray([
    0x02, 0x91, 0x01, 0x04,
    0x00, 0x08, 0x00, 0x00, 0x40, 0x7e, 0x00, 0x00, 0x00, 0x30, 0x01, 0x00
])

# Init commands sent after handshake (from nso-gc-bridge)
_DEFAULT_REPORT_DATA = bytearray([
    0x03, 0x91, 0x00, 0x0d, 0x00, 0x08,
    0x00, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF
])

_SET_INPUT_MODE = bytearray([
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x30
])


def _log(msg: str):
    """Debug log to stderr (visible in terminal, not in IPC pipe)."""
    print(f"[bleak] {msg}", file=sys.stderr, flush=True)


class BleakBackend:
    """Manages BLE connections via Bleak (macOS/Windows).

    Follows the nso-gc-bridge approach: scan all devices, try connecting
    to each, verify with a handshake write, then subscribe to notifications.
    """

    def __init__(self):
        self._clients: dict[str, BleakClient] = {}  # identifier -> BleakClient
        self._write_chars: dict[str, object] = {}   # identifier -> handshake char (command writes)
        self._rumble_chars: dict[str, object] = {}  # identifier -> rumble char (handle 0x0016)

    @property
    def is_open(self) -> bool:
        return True

    async def open(self):
        """No-op — the OS BLE stack is always available in userspace."""
        pass

    async def scan_and_connect(
        self,
        slot_index: int,
        data_queue: queue.Queue,
        on_status: Callable[[str], None],
        on_disconnect: Callable[[], None],
        target_address: Optional[str] = None,
        exclude_addresses: Optional[list[str]] = None,
        scan_timeout: float = 15.0,
        connect_timeout: float = 15.0,
    ) -> Optional[str]:
        """Scan for an NSO GC controller, connect, and init.

        If target_address is set, connects directly to that address.
        Otherwise, scans all devices and tries each one (strongest signal first),
        identifying the controller by attempting a handshake write.

        Returns device identifier string on success, None on failure.
        """
        exclude = set(exclude_addresses or [])

        if target_address:
            # Direct connect to known address
            on_status("Connecting...")
            result = await self._connect_and_init(
                target_address, None, slot_index, data_queue,
                on_status, on_disconnect, connect_timeout)
            if result:
                return result
            # If direct connect fails, fall through to scan
            _log("Direct connect failed, falling back to scan...")

        # Scan all devices
        on_status("Scanning for controller...")
        _log(f"Scanning for {scan_timeout}s...")

        try:
            discovered = await BleakScanner.discover(
                timeout=scan_timeout, return_adv=True)
        except TypeError:
            # Older Bleak without return_adv
            raw = await BleakScanner.discover(timeout=scan_timeout)
            discovered = {d.address: (d, None) for d in raw}

        devices = [d for d, _ in discovered.values()]
        if not devices:
            on_status("No devices found")
            return None

        _log(f"Found {len(devices)} device(s), trying each...")

        # Sort: strongest RSSI first, then prefer Nintendo-like names
        def _sort_key(d):
            name = (d.name or "").lower()
            rssi = -999
            if d.address in discovered:
                _, adv = discovered[d.address]
                if adv is not None and hasattr(adv, 'rssi') and adv.rssi is not None:
                    rssi = adv.rssi
            # Check manufacturer data for Nintendo
            is_nintendo = False
            if d.address in discovered:
                _, adv = discovered[d.address]
                if adv is not None:
                    md = getattr(adv, 'manufacturer_data', {})
                    if _NINTENDO_COMPANY_ID in md:
                        is_nintendo = True
            name_match = name == "devicename" or any(
                p.lower() in name for p in _NINTENDO_NAME_PATTERNS)
            return (
                0 if is_nintendo else 1,
                0 if name_match else 1,
                -rssi,
                d.address,
            )

        ordered = sorted(devices, key=_sort_key)

        for d in ordered:
            if d.address in exclude:
                continue
            if d.address in self._clients:
                continue

            name = d.name or "(no name)"
            _log(f"  Trying {name} ({d.address})...")
            on_status(f"Trying {name}...")

            result = await self._connect_and_init(
                d.address, d, slot_index, data_queue,
                on_status, on_disconnect, connect_timeout)
            if result:
                return result

        on_status("No controller found")
        return None

    async def _connect_and_init(
        self,
        address: str,
        ble_device: Optional[object],
        slot_index: int,
        data_queue: queue.Queue,
        on_status: Callable[[str], None],
        on_disconnect: Callable[[], None],
        connect_timeout: float,
    ) -> Optional[str]:
        """Try to connect to a device, handshake, and init.

        Returns the address on success, None on failure.
        """
        disconnected = asyncio.Event()

        def _on_disconnected(client: BleakClient):
            _log(f"Disconnected from {address}")
            disconnected.set()
            self._clients.pop(address, None)
            self._write_chars.pop(address, None)
            self._rumble_chars.pop(address, None)
            on_disconnect()

        # Connect — use BLEDevice object if available, else address string
        try:
            target = ble_device if ble_device is not None else address
            client = BleakClient(target, timeout=connect_timeout,
                                 disconnected_callback=_on_disconnected)
            await client.connect()
        except Exception as e:
            _log(f"  Connect failed: {type(e).__name__}: {e}")
            return None

        if not client.is_connected:
            _log(f"  Not connected after connect()")
            return None

        _log(f"  Connected to {address}")

        # Log MTU
        try:
            _log(f"  MTU = {client.mtu_size}")
        except Exception:
            pass

        # Discover services and find write/notify characteristics
        write_chars = []
        notify_chars = []
        for svc in client.services:
            _log(f"  Service: {svc.uuid}")
            for char in svc.characteristics:
                props = getattr(char, "properties", []) or []
                _log(f"    0x{char.handle:04X} {char.uuid} props={props}")
                if "notify" in props or "indicate" in props:
                    notify_chars.append(char)
                if "write" in props or "write-without-response" in props:
                    write_chars.append(char)

        if not write_chars:
            _log(f"  No write characteristics — not a controller")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None

        # Try handshake: write SPI read command to each write characteristic
        handshake_char = None
        for char in write_chars:
            try:
                await client.write_gatt_char(char.uuid, _HANDSHAKE_CMD)
                handshake_char = char
                _log(f"  Handshake accepted on {char.uuid}")
                break
            except Exception:
                try:
                    # Fallback handshake
                    await client.write_gatt_char(char.uuid, bytearray([0x01, 0x01]))
                    handshake_char = char
                    _log(f"  Fallback handshake accepted on {char.uuid}")
                    break
                except Exception:
                    pass

        if handshake_char is None:
            _log(f"  Handshake failed on all chars — not the controller")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None

        self._clients[address] = client
        self._write_chars[address] = handshake_char

        # Find rumble characteristic: match by ATT handle (0x0016) first,
        # then fall back to the write char with the highest handle that
        # isn't the handshake char.  On Windows/WinRT the ATT handles are
        # preserved, so matching H_OUT_CMD directly works.
        rumble_char = None
        for char in write_chars:
            if char.handle == H_OUT_CMD:
                rumble_char = char
                break
        if rumble_char is None:
            # Fallback: pick the write char with the highest handle
            # (0x0016 > 0x0014 > 0x0012 in the protocol)
            candidates = sorted(
                [c for c in write_chars if c.handle != handshake_char.handle],
                key=lambda c: c.handle, reverse=True)
            if candidates:
                rumble_char = candidates[0]
        if rumble_char:
            self._rumble_chars[address] = rumble_char
            _log(f"  Rumble char: 0x{rumble_char.handle:04X} {rumble_char.uuid}")
        else:
            _log(f"  No separate rumble char found, will use handshake char")

        if disconnected.is_set():
            self._clients.pop(address, None)
            self._write_chars.pop(address, None)
            self._rumble_chars.pop(address, None)
            return None

        # Subscribe to all notify characteristics
        on_status("Subscribing to input...")

        _report_count = [0]

        def _on_input(char: BleakGATTCharacteristic, value: bytearray):
            if _report_count[0] < 3:
                _report_count[0] += 1
                _log(f"  Report #{_report_count[0]}: len={len(value)} first16={list(value[:16])}")
            try:
                data_queue.put_nowait(translate_ble_native_to_usb(bytes(value)))
            except queue.Full:
                pass

        for char in notify_chars:
            try:
                await client.start_notify(char.uuid, _on_input)
                _log(f"  Subscribed to {char.uuid}")
            except Exception as e:
                _log(f"  Failed to subscribe to {char.uuid}: {e}")

        # Send init commands (from nso-gc-bridge approach)
        for data in (_DEFAULT_REPORT_DATA, bytearray(build_led_cmd(
                LED_MAP[min(slot_index, len(LED_MAP) - 1)]))):
            try:
                await client.write_gatt_char(handshake_char.uuid, data)
            except Exception:
                pass

        try:
            await client.write_gatt_char(handshake_char.uuid, _SET_INPUT_MODE)
        except Exception:
            pass

        _log(f"  Init complete for slot {slot_index}")

        if disconnected.is_set():
            self._clients.pop(address, None)
            self._write_chars.pop(address, None)
            self._rumble_chars.pop(address, None)
            return None

        on_status("Connected via BLE")
        return address

    async def send_rumble(self, identifier: str, packet: bytes) -> bool:
        """Send rumble packet via GATT write-without-response."""
        client = self._clients.get(identifier)
        char = self._rumble_chars.get(identifier) or self._write_chars.get(identifier)
        if not client or not client.is_connected or not char:
            return False
        try:
            await client.write_gatt_char(char.uuid, bytearray(packet), response=False)
            return True
        except Exception:
            return False

    async def disconnect(self, identifier: str):
        """Disconnect a specific controller."""
        self._write_chars.pop(identifier, None)
        self._rumble_chars.pop(identifier, None)
        client = self._clients.pop(identifier, None)
        if client and client.is_connected:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def close(self):
        """Disconnect all controllers."""
        for identifier in list(self._clients.keys()):
            await self.disconnect(identifier)
