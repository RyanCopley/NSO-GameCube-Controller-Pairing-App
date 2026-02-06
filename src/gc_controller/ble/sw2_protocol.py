"""
SW2 BLE Protocol

Platform-independent Switch 2 BLE initialization sequence for NSO GameCube controllers.
Faithfully ported from the working PoC (tools/ble_bumble_connect.py), which was derived
from BlueRetro (darthcloud) and ndeadly's switch2_input_viewer.py.
"""

import asyncio
import struct
from typing import Callable, Optional

# --- SW2 BLE button bits (uint32 LE at BLE offset 4) ---
# From BlueRetro sw2.h sw2_btns_mask enum
_SW2_Y       = 0x00000001
_SW2_X       = 0x00000002
_SW2_B       = 0x00000004
_SW2_A       = 0x00000008
_SW2_R       = 0x00000040
_SW2_ZR      = 0x00000080
_SW2_PLUS    = 0x00000200
_SW2_HOME    = 0x00001000
_SW2_CAPTURE = 0x00002000
_SW2_CHAT    = 0x00004000
_SW2_DOWN    = 0x00010000
_SW2_UP      = 0x00020000
_SW2_RIGHT   = 0x00040000
_SW2_LEFT    = 0x00080000
_SW2_L       = 0x00400000
_SW2_ZL      = 0x00800000
_SW2_GR      = 0x01000000
_SW2_GL      = 0x02000000


def translate_ble_to_usb(ble_data: bytes) -> bytes:
    """Translate 63-byte BLE input report to 64-byte USB HID format.

    BLE format (from BlueRetro sw2_map):
        [0-3]   reserved
        [4-7]   buttons (uint32 LE)
        [8-9]   reserved
        [10-15] stick axes (packed 12-bit: LX, LY, RX, RY)
        [16-59] reserved (IMU etc.)
        [60]    left trigger
        [61]    right trigger
        [62]    reserved

    USB format (from controller_constants.py):
        [0]     report ID (0x00)
        [3]     buttons byte 0: B=0x01 A=0x02 Y=0x04 X=0x08 R=0x10 Z=0x20 Start=0x40
        [4]     buttons byte 1: DDown=0x01 DRight=0x02 DLeft=0x04 DUp=0x08 L=0x10 ZL=0x20
        [5]     buttons byte 2: Home=0x01 Capture=0x02 GR=0x04 GL=0x08 Chat=0x10
        [6-11]  stick axes (same packed 12-bit format)
        [13]    left trigger
        [14]    right trigger
    """
    if len(ble_data) < 16:
        return b'\x00' * 64

    buf = bytearray(64)

    # Buttons: BLE uint32 LE at offset 4 -> USB bytes at [3], [4], [5]
    buttons = int.from_bytes(ble_data[4:8], 'little')

    b3 = 0
    if buttons & _SW2_B:    b3 |= 0x01
    if buttons & _SW2_A:    b3 |= 0x02
    if buttons & _SW2_Y:    b3 |= 0x04
    if buttons & _SW2_X:    b3 |= 0x08
    if buttons & _SW2_R:    b3 |= 0x10
    if buttons & _SW2_ZR:   b3 |= 0x20
    if buttons & _SW2_PLUS: b3 |= 0x40
    buf[3] = b3

    b4 = 0
    if buttons & _SW2_DOWN:  b4 |= 0x01
    if buttons & _SW2_RIGHT: b4 |= 0x02
    if buttons & _SW2_LEFT:  b4 |= 0x04
    if buttons & _SW2_UP:    b4 |= 0x08
    if buttons & _SW2_L:     b4 |= 0x10
    if buttons & _SW2_ZL:    b4 |= 0x20
    buf[4] = b4

    b5 = 0
    if buttons & _SW2_HOME:    b5 |= 0x01
    if buttons & _SW2_CAPTURE: b5 |= 0x02
    if buttons & _SW2_GR:      b5 |= 0x04
    if buttons & _SW2_GL:      b5 |= 0x08
    if buttons & _SW2_CHAT:    b5 |= 0x10
    buf[5] = b5

    # Sticks: BLE offset 10-15 -> USB offset 6-11 (same packed 12-bit format)
    buf[6:12] = ble_data[10:16]

    # Triggers: BLE offset 60-61 -> USB offset 13-14
    if len(ble_data) > 61:
        buf[13] = ble_data[60]
        buf[14] = ble_data[61]

    return bytes(buf)

from bumble.device import Peer, Device
from bumble.gatt import Characteristic
from bumble.hci import HCI_LE_Enable_Encryption_Command

# --- Fixed ATT Handles ---
H_SVC1_ENABLE = 0x0005
H_INPUT_REPORT = 0x000A
H_INPUT_CCCD = 0x000B
H_CMD_WRITE = 0x0014
H_CMD_RESPONSE = 0x001A
H_CMD_RESP_CCCD = 0x001B

# --- Command IDs ---
CMD_SPI_READ = 0x02
CMD_SET_LED = 0x09
CMD_PAIRING = 0x15

# --- Command format constants ---
REQ_TYPE = 0x91
IFACE_BLE = 0x01

# --- SPI addresses ---
SPI_DEVICE_INFO = (0x00, 0x30, 0x01, 0x00)   # 0x00013000
SPI_PAIRING_DATA = (0x00, 0xA0, 0x1F, 0x00)  # 0x001FA000

# --- LED map (player indicators) ---
LED_MAP = [0x01, 0x03, 0x05, 0x06, 0x07, 0x09, 0x0A, 0x0B]

# --- Pairing crypto constants from BlueRetro ---
PAIR_STEP2 = bytes([
    CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x04,
    0x00, 0x11, 0x00, 0x00, 0x00,
    0xEA, 0xBD, 0x47, 0x13, 0x89, 0x35, 0x42,
    0xC6, 0x79, 0xEE, 0x07, 0xF2, 0x53, 0x2C, 0x6C, 0x31,
])

PAIR_STEP3 = bytes([
    CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x02,
    0x00, 0x11, 0x00, 0x00, 0x00,
    0x40, 0xB0, 0x8A, 0x5F, 0xCD, 0x1F, 0x9B,
    0x41, 0x12, 0x5C, 0xAC, 0xC6, 0x3F, 0x38, 0xA0, 0x73,
])

PAIR_STEP4 = bytes([
    CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x03,
    0x00, 0x01, 0x00, 0x00, 0x00,
])


def build_spi_read(addr_bytes: tuple, size: int) -> bytes:
    """Build SPI flash read command."""
    return bytes([
        CMD_SPI_READ, REQ_TYPE, IFACE_BLE, 0x04,
        0x00, 0x08, 0x00, 0x00,
        size, 0x7E, 0x00, 0x00,
        addr_bytes[0], addr_bytes[1], addr_bytes[2], addr_bytes[3],
    ])


def build_led_cmd(led_mask: int) -> bytes:
    """Build LED command."""
    return bytes([
        CMD_SET_LED, REQ_TYPE, IFACE_BLE, 0x07,
        0x00, 0x08, 0x00, 0x00,
        led_mask, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ])


def build_pair_step1(local_addr_bytes: bytes) -> bytes:
    """Build pairing step 1: send local BLE address to controller."""
    addr = bytes(local_addr_bytes)
    addr_m1 = bytearray(addr)
    addr_m1[5] = (addr_m1[5] - 1) & 0xFF
    return bytes([
        CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x01,
        0x00, 0x0E, 0x00, 0x00, 0x00, 0x02,
    ]) + addr + bytes(addr_m1)


async def _write_handle(peer: Peer, handle: int, data: bytes,
                        with_response: bool = False) -> bool:
    """Write to a specific ATT handle."""
    try:
        await peer.gatt_client.write_value(
            attribute=handle,
            value=data,
            with_response=with_response,
        )
        return True
    except Exception as e:
        print(f"  BLE write to 0x{handle:04X} failed: {e}")
        return False


async def sw2_init(peer: Peer, connection, device: Device, slot_index: int,
                   on_input: Callable[[bytes], None],
                   on_status: Callable[[str], None],
                   disconnected: Optional[asyncio.Event] = None) -> bool:
    """Run the full SW2 BLE initialization sequence.

    Args:
        peer: Bumble Peer wrapping the connection
        connection: Bumble connection object
        device: Bumble Device object (for HCI commands)
        slot_index: Controller slot (0-3), used for LED assignment
        on_input: Callback for input report notifications (63-byte value)
        on_status: Callback for status messages
        disconnected: Event set when the connection drops

    Returns:
        True if initialization succeeded and input streaming is active.
    """
    cmd_responses: asyncio.Queue = asyncio.Queue()

    def _on_cmd_response(value: bytes):
        cmd_responses.put_nowait(value)

    async def _wait_cmd_response(timeout: float = 3.0) -> Optional[bytes]:
        try:
            return await asyncio.wait_for(cmd_responses.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    # Step 1: Enable proprietary service
    on_status("Enabling service...")
    if not await _write_handle(peer, H_SVC1_ENABLE, bytes([0x01, 0x00]),
                               with_response=True):
        return False
    await asyncio.sleep(0.2)

    # Step 2: Enable command response notifications
    on_status("Setting up command channel...")
    await _write_handle(peer, H_CMD_RESP_CCCD, bytes([0x01, 0x00]),
                        with_response=True)

    # Subscribe to command response characteristic
    for service in peer.services:
        for char in service.characteristics:
            if char.handle == H_CMD_RESPONSE:
                try:
                    await char.subscribe(subscriber=_on_cmd_response)
                except Exception:
                    pass
    await asyncio.sleep(0.2)

    # Step 3: Read device info (SPI 0x00013000)
    on_status("Reading device info...")
    cmd = build_spi_read(SPI_DEVICE_INFO, 0x40)
    await _write_handle(peer, H_CMD_WRITE, cmd)
    await _wait_cmd_response(timeout=3.0)

    if disconnected and disconnected.is_set():
        return False

    # Step 4: Proprietary pairing handshake (cmd 0x15)
    on_status("Pairing (proprietary)...")
    local_addr = device.public_address
    if local_addr:
        addr_bytes = bytes(local_addr)
    else:
        addr_bytes = bytes([0xF5, 0xF4, 0xF3, 0xF2, 0xF1, 0xF0])

    # 4a: Send local address
    pair1 = build_pair_step1(addr_bytes)
    await _write_handle(peer, H_CMD_WRITE, pair1)
    await _wait_cmd_response(timeout=3.0)
    if disconnected and disconnected.is_set():
        return False

    # 4b: Send crypto challenge
    await _write_handle(peer, H_CMD_WRITE, PAIR_STEP2)
    await _wait_cmd_response(timeout=3.0)
    if disconnected and disconnected.is_set():
        return False

    # 4c: Send second crypto value
    await _write_handle(peer, H_CMD_WRITE, PAIR_STEP3)
    await _wait_cmd_response(timeout=3.0)
    if disconnected and disconnected.is_set():
        return False

    # 4d: Finalize pairing
    await _write_handle(peer, H_CMD_WRITE, PAIR_STEP4)
    await _wait_cmd_response(timeout=3.0)
    if disconnected and disconnected.is_set():
        return False

    # Step 5: Read pairing data (SPI 0x1FA000) — extract LTK for encryption
    on_status("Reading pairing data...")
    cmd = build_spi_read(SPI_PAIRING_DATA, 0x40)
    await _write_handle(peer, H_CMD_WRITE, cmd)
    resp = await _wait_cmd_response(timeout=3.0)

    ltk_bytes = None
    ediv_value = 0
    rand_bytes = bytes(8)

    if resp and len(resp) >= 16 + 0x30:
        spi = resp[16:]
        unknown1 = spi[0x0E:0x1A]
        ltk_bytes = bytes(spi[0x1A:0x2A])
        ediv_value = struct.unpack_from("<H", unknown1, 0)[0]
        rand_bytes = bytes(unknown1[2:10])
    elif resp and len(resp) >= 16:
        ltk_bytes = bytes(resp[-16:])

    if disconnected and disconnected.is_set():
        return False

    # Step 6: LE encryption with LTK (if SMP didn't already encrypt)
    if not connection.is_encrypted and ltk_bytes:
        on_status("Encrypting link...")
        attempts = [
            (ediv_value, rand_bytes, ltk_bytes),
            (0, bytes(8), ltk_bytes),
            (0, bytes(8), bytes(reversed(ltk_bytes))),
        ]
        if ediv_value == 0 and rand_bytes == bytes(8):
            attempts = attempts[1:]

        for ediv, rand, ltk in attempts:
            if connection.is_encrypted or disconnected and disconnected.is_set():
                break
            encryption_done = asyncio.Event()

            def _on_enc_change():
                encryption_done.set()

            def _on_enc_failure(e):
                encryption_done.set()

            connection.on("connection_encryption_change", _on_enc_change)
            connection.on("connection_encryption_failure", _on_enc_failure)

            try:
                await device.send_command(
                    HCI_LE_Enable_Encryption_Command(
                        connection_handle=connection.handle,
                        random_number=rand,
                        encrypted_diversifier=ediv,
                        long_term_key=ltk,
                    )
                )
                try:
                    await asyncio.wait_for(encryption_done.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
            except Exception:
                pass

            if connection.is_encrypted:
                break
            await asyncio.sleep(0.3)

    if disconnected and disconnected.is_set():
        return False

    # Step 7: Set player LED
    on_status("Setting LED...")
    led_idx = min(slot_index, len(LED_MAP) - 1)
    cmd = build_led_cmd(LED_MAP[led_idx])
    await _write_handle(peer, H_CMD_WRITE, cmd)
    await _wait_cmd_response(timeout=2.0)
    await asyncio.sleep(0.2)

    if disconnected and disconnected.is_set():
        return False

    # Step 8: Enable input notifications + disable cmd response
    on_status("Enabling input...")
    for service in peer.services:
        for char in service.characteristics:
            if char.handle == H_INPUT_REPORT:
                try:
                    await char.subscribe(subscriber=on_input)
                except Exception:
                    pass

    await _write_handle(peer, H_INPUT_CCCD, bytes([0x01, 0x00]),
                        with_response=True)
    await _write_handle(peer, H_CMD_RESP_CCCD, bytes([0x00, 0x00]),
                        with_response=True)

    on_status("Connected via BLE")
    return True
