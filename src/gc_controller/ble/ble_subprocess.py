#!/usr/bin/env python3
"""BLE subprocess — runs with elevated privileges via pkexec.

Handles all Bluetooth Low Energy operations requiring raw HCI access.
Communicates with the main app via JSON lines on stdin/stdout.

Protocol (JSON lines):
  Parent -> Child commands:
    {"cmd": "stop_bluez"}
    {"cmd": "open", "hci_index": 0}
    {"cmd": "scan_connect", "slot_index": 0, "target_address": "XX:XX:XX:XX:XX:XX"}
    {"cmd": "disconnect", "slot_index": 0, "address": "XX:XX:XX:XX:XX:XX"}
    {"cmd": "shutdown"}

  Child -> Parent events:
    {"e": "ready"}
    {"e": "bluez_stopped"}
    {"e": "open_ok"}
    {"e": "error", "ctx": "...", "msg": "..."}
    {"e": "status", "s": <slot>, "msg": "..."}
    {"e": "connected", "s": <slot>, "mac": "..."}
    {"e": "connect_error", "s": <slot>, "msg": "..."}
    {"e": "data", "s": <slot>, "d": "<base64>"}
    {"e": "disconnected", "s": <slot>}
"""

import asyncio
import base64
import json
import os
import queue
import sys
import threading


def send(event: dict):
    """Send a JSON-line event to the parent process."""
    try:
        sys.stdout.write(json.dumps(event, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except Exception:
        pass


class PipeQueue:
    """queue.Queue adapter that forwards data to the parent via stdout."""

    def __init__(self, slot_index: int):
        self._slot = slot_index

    def put_nowait(self, data):
        try:
            send({"e": "data", "s": self._slot,
                  "d": base64.b64encode(data).decode('ascii')})
        except Exception:
            pass

    def put(self, data):
        self.put_nowait(data)

    def empty(self):
        return True

    def get_nowait(self):
        raise queue.Empty()


async def do_scan_connect(backend, slot_index, target_address,
                          exclude_addresses=None, slot_macs=None):
    """Run scan_and_connect as a background asyncio task."""
    pq = PipeQueue(slot_index)

    def on_status(msg, _si=slot_index):
        send({"e": "status", "s": _si, "msg": msg})

    def on_disconnect(_si=slot_index):
        if slot_macs is not None:
            slot_macs.pop(_si, None)
        send({"e": "disconnected", "s": _si})

    try:
        mac = await backend.scan_and_connect(
            slot_index=slot_index,
            data_queue=pq,
            on_status=on_status,
            on_disconnect=on_disconnect,
            target_address=target_address,
            exclude_addresses=exclude_addresses,
        )
        if mac:
            if slot_macs is not None:
                slot_macs[slot_index] = mac
            send({"e": "connected", "s": slot_index, "mac": mac})
        else:
            send({"e": "connect_error", "s": slot_index,
                  "msg": "Connection failed"})
    except asyncio.CancelledError:
        pass
    except Exception as ex:
        send({"e": "connect_error", "s": slot_index, "msg": str(ex)})


def main():
    # Restore Python path from first argument so imports work
    if len(sys.argv) > 1:
        for p in sys.argv[1].split(os.pathsep):
            if p and p not in sys.path:
                sys.path.insert(0, p)

    try:
        from gc_controller.ble import stop_bluez, find_hci_adapter
        from gc_controller.ble.bumble_backend import BumbleBackend
    except ImportError as e:
        send({"e": "error", "ctx": "import", "msg": str(e)})
        sys.exit(1)

    backend = BumbleBackend()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Read commands from stdin in a background thread
    cmd_queue = queue.Queue()

    def stdin_reader():
        try:
            for line in sys.stdin:
                line = line.strip()
                if line:
                    cmd_queue.put(json.loads(line))
        except Exception:
            pass
        cmd_queue.put(None)

    threading.Thread(target=stdin_reader, daemon=True).start()

    send({"e": "ready"})

    async def process():
        connect_tasks = {}  # slot_index -> asyncio.Task
        slot_macs = {}      # slot_index -> mac address (for rumble routing)

        while True:
            cmd = await loop.run_in_executor(None, cmd_queue.get)
            if cmd is None:
                break

            action = cmd.get("cmd")

            if action == "stop_bluez":
                stop_bluez()
                send({"e": "bluez_stopped"})

            elif action == "open":
                hci_idx = cmd.get("hci_index")
                if hci_idx is None:
                    hci_idx = find_hci_adapter()
                if hci_idx is None:
                    send({"e": "error", "ctx": "open",
                          "msg": "No HCI Bluetooth adapter found."})
                    continue
                try:
                    await backend.open(hci_idx)
                    send({"e": "open_ok"})
                except Exception as ex:
                    send({"e": "error", "ctx": "open", "msg": str(ex)})

            elif action == "scan_connect":
                si = cmd["slot_index"]
                if si in connect_tasks and not connect_tasks[si].done():
                    connect_tasks[si].cancel()
                connect_tasks[si] = asyncio.create_task(
                    do_scan_connect(backend, si, cmd.get("target_address"),
                                    cmd.get("exclude_addresses"),
                                    slot_macs=slot_macs))

            elif action == "rumble":
                si = cmd.get("slot_index")
                data = base64.b64decode(cmd["data"])
                mac = slot_macs.get(si)
                if mac:
                    asyncio.create_task(backend.send_rumble(mac, data))

            elif action == "disconnect":
                addr = cmd.get("address")
                si = cmd.get("slot_index")
                if si is not None and si in connect_tasks:
                    if not connect_tasks[si].done():
                        connect_tasks[si].cancel()
                if addr:
                    try:
                        await backend.disconnect(addr)
                    except Exception:
                        pass

            elif action in ("close", "shutdown"):
                for task in connect_tasks.values():
                    if not task.done():
                        task.cancel()
                try:
                    await backend.close()
                except Exception:
                    pass
                break

    try:
        loop.run_until_complete(process())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == '__main__':
    main()
