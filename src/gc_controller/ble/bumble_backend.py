"""
Bumble BLE Backend

Linux-only BLE backend using Google Bumble with raw HCI sockets.
Bypasses BlueZ entirely for full control over SMP key distribution.
"""

import asyncio
import queue
from typing import Callable, Optional

from bumble.device import Device, Peer, ConnectionParametersPreferences
from bumble.hci import Address, HCI_LE_1M_PHY
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.transport import open_transport
from bumble import smp  # noqa: F401

from .sw2_protocol import sw2_init, translate_ble_to_usb

# Known Nintendo BLE MAC OUI prefixes (first 3 octets)
_NINTENDO_OUIS = (
    '3C:A9:AB', '98:B6:E9', '7C:BB:8A', '58:2F:40',
    'D8:6B:F7', '04:03:D6', 'A4:C0:E1', '40:F4:07',
)


class BumbleBackend:
    """Manages HCI transport and Bumble Device for BLE connections."""

    def __init__(self):
        self._transport = None
        self._device: Optional[Device] = None
        self._connections: dict[str, object] = {}  # mac -> connection
        self._hci_index: Optional[int] = None

    @property
    def is_open(self) -> bool:
        return self._device is not None

    async def open(self, hci_index: int):
        """Open the HCI transport and power on the Bumble device."""
        self._hci_index = hci_index
        transport_name = f"hci-socket:{hci_index}"

        self._transport = await open_transport(transport_name)
        hci_source, hci_sink = self._transport

        self._device = Device.with_hci(
            "Bumble-GC",
            Address("F0:F1:F2:F3:F4:F5"),
            hci_source,
            hci_sink,
        )

        # Configure SMP for Legacy "Just Works" with exact BlueRetro key distribution
        self._device.pairing_config_factory = lambda connection: PairingConfig(
            sc=False,
            mitm=False,
            bonding=True,
            delegate=PairingDelegate(
                io_capability=PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT,
                local_initiator_key_distribution=(
                    PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY
                ),
                local_responder_key_distribution=(
                    PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
                ),
            ),
        )

        await self._device.power_on()

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
        """Scan for an NSO GC controller, connect, pair, and init SW2 protocol.

        Args:
            slot_index: Controller slot (0-3)
            data_queue: Queue for input data (64-byte packets with 0x00 prefix)
            on_status: Status message callback
            on_disconnect: Callback for unexpected disconnect
            target_address: If set, connect directly to this MAC (skip scan)
            exclude_addresses: MACs to skip during scanning (other slots' controllers)
            scan_timeout: Seconds to scan before giving up
            connect_timeout: Seconds to wait for connection

        Returns:
            MAC address string on success, None on failure.
        """
        if not self._device:
            on_status("BLE not initialized")
            return None

        # Determine target MAC
        mac = target_address
        if not mac:
            on_status("Scanning for controller...")
            mac = await self._scan(scan_timeout, exclude_addresses)
            if not mac:
                on_status("No controller found")
                return None

        # Prevent double-connecting
        if mac in self._connections:
            on_status("Already connected to this controller")
            return mac

        # Connect
        on_status("Connecting...")
        try:
            connection = await self._device.connect(
                Address(mac, Address.PUBLIC_DEVICE_ADDRESS),
                connection_parameters_preferences={
                    HCI_LE_1M_PHY: ConnectionParametersPreferences(
                        connection_interval_min=15.0,
                        connection_interval_max=30.0,
                        max_latency=0,
                        supervision_timeout=5000,
                    )
                },
                timeout=connect_timeout,
            )
        except Exception as e:
            on_status(f"Connection failed: {e}")
            return None

        self._connections[mac] = connection

        # Track disconnection with an event, like the PoC
        disconnected = asyncio.Event()

        def _on_disconnection(reason):
            disconnected.set()
            self._connections.pop(mac, None)
            on_disconnect()

        connection.on("disconnection", _on_disconnection)

        # Handle security requests from controller
        async def _on_security_request(auth_req):
            try:
                await connection.pair()
            except Exception:
                pass

        connection.on("security_request",
                      lambda auth_req: asyncio.ensure_future(
                          _on_security_request(auth_req)))

        # SMP Legacy pairing
        on_status("SMP pairing...")
        try:
            await connection.pair()
        except Exception:
            # Continue without SMP — proprietary pairing may still work
            if disconnected.is_set():
                self._connections.pop(mac, None)
                on_status("Disconnected during pairing")
                return None

        if disconnected.is_set():
            self._connections.pop(mac, None)
            on_status("Disconnected during pairing")
            return None

        # MTU exchange (SW2 input reports are 63 bytes)
        on_status("MTU exchange...")
        peer = Peer(connection)
        try:
            await peer.request_mtu(512)
        except Exception:
            pass

        if disconnected.is_set():
            self._connections.pop(mac, None)
            return None

        # GATT discovery
        on_status("Discovering services...")
        await peer.discover_services()
        for service in peer.services:
            await service.discover_characteristics()
            for char in service.characteristics:
                await char.discover_descriptors()

        if disconnected.is_set():
            self._connections.pop(mac, None)
            return None

        # Input notification callback: translate BLE format to USB-compatible 64 bytes
        def _on_input(value: bytes):
            try:
                data_queue.put_nowait(translate_ble_to_usb(value))
            except queue.Full:
                pass

        # Run SW2 init sequence
        on_status("Initializing controller...")
        success = await sw2_init(
            peer=peer,
            connection=connection,
            device=self._device,
            slot_index=slot_index,
            on_input=_on_input,
            on_status=on_status,
            disconnected=disconnected,
        )

        if not success or disconnected.is_set():
            self._connections.pop(mac, None)
            if not disconnected.is_set():
                try:
                    await connection.disconnect()
                except Exception:
                    pass
            on_status("Controller init failed")
            return None

        return mac

    async def _scan(self, timeout: float,
                    exclude_addresses: Optional[list[str]] = None,
                    ) -> Optional[str]:
        """Scan for NSO GC controllers, return first found MAC.

        Matches by Nintendo OUI prefix in the MAC address, mirroring
        the PoC's approach of matching by known MAC.
        """
        exclude = set(exclude_addresses or [])
        found_event = asyncio.Event()
        found_mac = [None]

        def on_advertisement(advertisement):
            try:
                if found_event.is_set():
                    return
                addr_str = str(advertisement.address).upper()
                # Skip controllers that are already connected
                if addr_str in self._connections:
                    return
                # Skip controllers assigned to other slots
                if addr_str in exclude:
                    return
                # Match by Nintendo OUI prefix (same approach as PoC's MAC check)
                for oui in _NINTENDO_OUIS:
                    if oui in addr_str:
                        found_mac[0] = addr_str
                        found_event.set()
                        return
            except Exception:
                pass

        self._device.on("advertisement", on_advertisement)
        await self._device.start_scanning(filter_duplicates=False)

        try:
            await asyncio.wait_for(found_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            await self._device.stop_scanning()

        return found_mac[0]

    async def disconnect(self, mac_address: str):
        """Disconnect a specific controller."""
        connection = self._connections.pop(mac_address, None)
        if connection:
            try:
                await connection.disconnect()
            except Exception:
                pass

    async def close(self):
        """Disconnect all controllers and close the HCI transport."""
        for mac in list(self._connections.keys()):
            await self.disconnect(mac)

        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._device = None
