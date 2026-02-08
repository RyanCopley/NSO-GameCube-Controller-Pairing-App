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
import re
import sys
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .sw2_protocol import (
    LED_MAP, build_led_cmd, translate_ble_native_to_usb,
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


def _normalize_address(addr: str | None) -> str | None:
    """Strip /P or /R suffix from a BLE address (Linux Bumble format)."""
    if not addr:
        return addr
    return re.sub(r'/[PR]$', '', addr)


# MAC address pattern: XX:XX:XX:XX:XX:XX
_MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')


def _is_mac_address(addr: str) -> bool:
    """Return True if addr looks like a MAC address (not a CoreBluetooth UUID)."""
    return bool(_MAC_RE.match(addr))


class BleakBackend:
    """Manages BLE connections via Bleak (macOS/Windows).

    Follows the nso-gc-bridge approach: scan all devices, try connecting
    to each, verify with a handshake write, then subscribe to notifications.
    """

    def __init__(self):
        self._clients: dict[str, BleakClient] = {}  # identifier -> BleakClient
        self._write_chars: dict[str, object] = {}   # identifier -> handshake char (command writes)
        self._cmd_chars: dict[str, object] = {}     # identifier -> command channel char (for vibration)
        self._last_scan: dict[str, BLEDevice] = {}  # address -> BLEDevice from last scan_only()

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
        scan_timeout: float = 5.0,
        connect_timeout: float = 15.0,
    ) -> Optional[str]:
        """Scan for an NSO GC controller, connect, and init.

        Uses a scan-first approach with early stop: if target_address is set,
        the scan stops as soon as that device is seen (fast reconnect).
        Otherwise scans for the full timeout, then tries each device.

        Returns device identifier string on success, None on failure.
        """
        target_address = _normalize_address(target_address)
        exclude = set(_normalize_address(a) or a for a in (exclude_addresses or []))

        # On macOS, CoreBluetooth uses UUIDs, not MAC addresses.  A saved
        # MAC from Linux will never match — discard it so we don't waste
        # time waiting for a match that can never happen.
        if target_address and sys.platform == 'darwin' and _is_mac_address(target_address):
            _log(f"Discarding Linux MAC {target_address} (useless on macOS)")
            target_address = None

        on_status("Scanning for controller...")
        _log(f"Scanning for {scan_timeout}s (target={target_address})...")

        # Collect devices via detection callback.  For early-stop we poll
        # found_devices instead of signalling an asyncio.Event — Bleak's
        # callback threading varies across platforms and the Event approach
        # is unreliable on macOS.
        found_devices: dict[str, BLEDevice] = {}
        found_adv: dict[str, AdvertisementData] = {}

        def _on_detected(device: BLEDevice, adv: AdvertisementData):
            found_devices[device.address] = device
            found_adv[device.address] = adv

        scanner = BleakScanner(detection_callback=_on_detected)
        await scanner.start()
        try:
            if target_address:
                # Poll every 0.3s for the target instead of sleeping the full timeout
                target_upper = target_address.upper()
                deadline = asyncio.get_event_loop().time() + scan_timeout
                while asyncio.get_event_loop().time() < deadline:
                    if any(a.upper() == target_upper for a in found_devices):
                        _log(f"Target {target_address} found during scan")
                        break
                    await asyncio.sleep(0.3)
                else:
                    _log(f"Target {target_address} not found in {scan_timeout}s")
            else:
                await asyncio.sleep(scan_timeout)
        finally:
            await scanner.stop()

        if not found_devices:
            on_status("No devices found")
            return None

        _log(f"Found {len(found_devices)} device(s), trying each...")

        # Build ordered list: target first (if found), then sorted by priority
        def _sort_key(addr):
            d = found_devices[addr]
            name = (d.name or "").lower()
            adv = found_adv.get(addr)
            rssi = adv.rssi if adv and adv.rssi is not None else -999
            is_nintendo = False
            if adv:
                md = getattr(adv, 'manufacturer_data', {})
                if _NINTENDO_COMPANY_ID in md:
                    is_nintendo = True
            name_match = name == "devicename" or any(
                p.lower() in name for p in _NINTENDO_NAME_PATTERNS)
            return (
                0 if is_nintendo else 1,
                0 if name_match else 1,
                -rssi,
                addr,
            )

        ordered_addrs = sorted(found_devices.keys(), key=_sort_key)

        # Move target to front if found
        if target_address:
            for addr in ordered_addrs:
                if addr.upper() == target_address.upper():
                    ordered_addrs.remove(addr)
                    ordered_addrs.insert(0, addr)
                    break

        for addr in ordered_addrs:
            if addr in exclude:
                continue
            if addr in self._clients:
                continue

            d = found_devices[addr]
            name = d.name or "(no name)"
            _log(f"  Trying {name} ({addr})...")
            on_status(f"Trying {name}...")

            result = await self._connect_and_init(
                addr, d, slot_index, data_queue,
                on_status, on_disconnect, connect_timeout)
            if result:
                return result

        on_status("No controller found")
        return None

    async def scan_only(self, scan_timeout: float = 4.0) -> list[dict]:
        """Run a full BLE scan and return discovered devices.

        Returns a list of dicts with keys: address, name, rssi.
        Caches BLEDevice objects in self._last_scan for connect_device().
        """
        _log(f"scan_only: scanning for {scan_timeout}s...")
        found_devices: dict[str, BLEDevice] = {}
        found_adv: dict[str, AdvertisementData] = {}

        def _on_detected(device: BLEDevice, adv: AdvertisementData):
            found_devices[device.address] = device
            found_adv[device.address] = adv

        scanner = BleakScanner(detection_callback=_on_detected)
        await scanner.start()
        await asyncio.sleep(scan_timeout)
        await scanner.stop()

        self._last_scan = dict(found_devices)

        result = []
        for addr, device in found_devices.items():
            adv = found_adv.get(addr)
            rssi = adv.rssi if adv and adv.rssi is not None else -999
            result.append({
                'address': addr,
                'name': device.name or '',
                'rssi': rssi,
            })

        _log(f"scan_only: found {len(result)} device(s)")
        return result

    async def connect_device(
        self,
        address: str,
        slot_index: int,
        data_queue: queue.Queue,
        on_status: Callable[[str], None],
        on_disconnect: Callable[[], None],
        connect_timeout: float = 15.0,
    ) -> Optional[str]:
        """Connect to a specific address using cached BLEDevice from last scan.

        Returns the device address on success, None on failure.
        """
        address = _normalize_address(address) or address
        ble_device = self._last_scan.get(address)
        if not ble_device:
            _log(f"connect_device: {address} not in scan cache")
            on_status(f"Device {address} not found in scan results")
            return None

        name = ble_device.name or "(no name)"
        _log(f"connect_device: connecting to {name} ({address})...")
        on_status(f"Connecting to {name}...")

        return await self._connect_and_init(
            address, ble_device, slot_index, data_queue,
            on_status, on_disconnect, connect_timeout)

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
            self._cmd_chars.pop(address, None)
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

        # Identify the command channel for vibration commands.
        # The Nintendo SW2 service has 3 WriteNoResp characteristics:
        #   1st (lowest handle): Vibration/rumble output (0x0012)
        #   2nd: Command channel (0x0014) — accepts SW2 commands like 0x0A
        #   3rd (highest handle): Command + rumble prefix (0x0016)
        # Find the service with ≥3 WriteNoResp chars, take the 2nd by handle.
        for svc in client.services:
            wnr = sorted(
                [c for c in svc.characteristics
                 if "write-without-response" in (getattr(c, "properties", []) or [])],
                key=lambda c: c.handle)
            if len(wnr) >= 3:
                self._cmd_chars[address] = wnr[1]
                _log(f"  Command channel: 0x{wnr[1].handle:04X} {wnr[1].uuid}")
                break

        if disconnected.is_set():
            self._clients.pop(address, None)
            self._write_chars.pop(address, None)
            self._cmd_chars.pop(address, None)
            return None

        # Subscribe to all notify characteristics
        on_status("Subscribing to input...")

        _report_count = [0]

        def _on_input(char: BleakGATTCharacteristic, value: bytearray):
            # Ignore non-input notifications (e.g. command responses triggered
            # by rumble writes).  BLE input reports are 63 bytes; command
            # responses are shorter and would be misinterpreted as joystick
            # data, corrupting both sticks while rumble is active.
            if len(value) < 30:
                return
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

        # Send init commands (from nso-gc-bridge approach).
        # SW2 protocol commands (like LED set) must go to the command channel
        # characteristic (2nd WriteNoResp by handle = 0x0014 equivalent), not
        # the handshake char.  Using the wrong characteristic causes the
        # controller to silently ignore the command — this is why player LEDs
        # didn't light up on macOS/Windows while working on Linux (Bumble
        # writes directly to handle 0x0014).
        cmd_char = self._cmd_chars.get(address, handshake_char)
        for data in (_DEFAULT_REPORT_DATA, bytearray(build_led_cmd(
                LED_MAP[min(slot_index, len(LED_MAP) - 1)]))):
            try:
                await client.write_gatt_char(cmd_char, data, response=False)
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
            self._cmd_chars.pop(address, None)
            return None

        on_status("Connected via BLE")
        return address

    async def send_rumble(self, identifier: str, packet: bytes) -> bool:
        """Send vibration command via the SW2 command channel.

        The Bumble backend (Linux) writes the 0x50-prefix rumble packet
        directly to ATT handle 0x0016 after a full SW2 init.  The Bleak
        backend skips the proprietary pairing, so that handle rejects
        rumble.  Instead, send the standard SW2 vibration command (0x0A,
        same format as USB) to the command channel — this works without
        the full init.  The char object is used directly to avoid
        UUID/handle ambiguity.
        """
        client = self._clients.get(identifier)
        cmd_char = self._cmd_chars.get(identifier)
        if not client or not client.is_connected or not cmd_char:
            return False
        # Extract on/off state from the rumble packet (byte 2)
        state = packet[2] if len(packet) > 2 else 0
        # SW2 vibration command: cmd 0x0A, interface 0x01 (BLE)
        vibration_cmd = bytearray([
            0x0A, 0x91, 0x01, 0x02, 0x00, 0x04,
            0x00, 0x00, 0x01 if state else 0x00,
            0x00, 0x00, 0x00,
        ])
        try:
            await client.write_gatt_char(cmd_char, vibration_cmd, response=False)
            return True
        except Exception as e:
            _log(f"  Rumble write failed: {type(e).__name__}: {e}")
            return False

    async def disconnect(self, identifier: str):
        """Disconnect a specific controller."""
        self._write_chars.pop(identifier, None)
        self._cmd_chars.pop(identifier, None)
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
