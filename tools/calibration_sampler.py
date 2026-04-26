#!/usr/bin/env python3
"""
Calibration Sampler for NSO GameCube Controller

Captures raw 12-bit stick values and 8-bit trigger values from a connected
controller, then outputs summary statistics (center, min, max, range) to
help determine better DEFAULT_CALIBRATION values.

Usage:
    python tools/calibration_sampler.py              # USB, guided phases
    python tools/calibration_sampler.py --ble        # BLE, auto-scan
    python tools/calibration_sampler.py --csv data   # save raw data to CSV
    python tools/calibration_sampler.py --quick       # 5s idle + 5s sticks + 3s triggers

Requires: hidapi (pip install hidapi), bleak (pip install bleak) for --ble
"""

import argparse
import collections
import statistics
import sys
import time

VENDOR_ID = 0x057e
PRODUCT_ID = 0x2073
IS_WINDOWS = sys.platform == 'win32'

AXES = ('LX', 'LY', 'RX', 'RY')


def find_controller():
    """Find and open the NSO GameCube controller via HID."""
    import hid
    devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not devices:
        return None, None
    dev = hid.device()
    dev.open_path(devices[0]['path'])
    return dev, devices[0]


def translate_0x05(data):
    """Translate Windows uninitialized report (ID 0x05) to GC USB format."""
    buf = [0] * 64
    b0, b1, b2 = data[5], data[6], data[7]
    b3 = 0
    if b0 & 0x04: b3 |= 0x01
    if b0 & 0x08: b3 |= 0x02
    if b0 & 0x01: b3 |= 0x04
    if b0 & 0x02: b3 |= 0x08
    if b0 & 0x40: b3 |= 0x10
    if b0 & 0x80: b3 |= 0x20
    if b1 & 0x02: b3 |= 0x40
    buf[3] = b3
    b4 = 0
    if b2 & 0x01: b4 |= 0x01
    if b2 & 0x04: b4 |= 0x02
    if b2 & 0x08: b4 |= 0x04
    if b2 & 0x02: b4 |= 0x08
    if b2 & 0x40: b4 |= 0x10
    if b2 & 0x80: b4 |= 0x20
    buf[4] = b4
    for i in range(6):
        buf[6 + i] = data[11 + i]
    if len(data) > 62:
        buf[13] = data[61]
        buf[14] = data[62]
    return buf


def parse_axes(data):
    """Extract raw 12-bit stick values and 8-bit trigger values."""
    lx = data[6] | ((data[7] & 0x0F) << 8)
    ly = (data[7] >> 4) | (data[8] << 4)
    rx = data[9] | ((data[10] & 0x0F) << 8)
    ry = (data[10] >> 4) | (data[11] << 4)
    lt = data[13] if len(data) > 13 else 0
    rt = data[14] if len(data) > 14 else 0
    return lx, ly, rx, ry, lt, rt


def countdown(label, seconds):
    """Display a countdown with a label."""
    print()
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(f"\r  {label} — starting in {remaining}s...  ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write(f"\r  {label} — GO!                              \n")
    sys.stdout.flush()


def print_summary(idle_data, range_data, trigger_data):
    """Print the calibration summary from collected data."""
    print()
    print("=" * 72)
    print("  CALIBRATION SUMMARY")
    print("=" * 72)

    # Stick centers (from idle data)
    if idle_data:
        print()
        print("  STICK CENTERS (median of idle samples)")
        print("  " + "-" * 40)
        for i, axis in enumerate(AXES):
            values = [s[i] for s in idle_data]
            med = statistics.median(values)
            mn, mx = min(values), max(values)
            std = statistics.stdev(values) if len(values) > 1 else 0
            print(f"    {axis:>2}: center={med:7.1f}  idle_range=[{mn}, {mx}]  stdev={std:.1f}")

    # Stick ranges (from range data = idle + range phases)
    all_stick = idle_data + range_data
    if all_stick:
        print()
        print("  STICK RANGES (min/max across all samples)")
        print("  " + "-" * 40)
        for i, axis in enumerate(AXES):
            values = [s[i] for s in all_stick]
            mn, mx = min(values), max(values)
            idle_med = statistics.median([s[i] for s in idle_data]) if idle_data else 2048
            half_neg = idle_med - mn
            half_pos = mx - idle_med
            half_range = max(half_neg, half_pos)
            print(f"    {axis:>2}: min={mn:5d}  max={mx:5d}  "
                  f"half_range={half_range:7.1f}  "
                  f"(neg={half_neg:.0f}, pos={half_pos:.0f})")

    # Trigger data
    if trigger_data:
        lt_vals = [s[4] for s in idle_data + trigger_data]
        rt_vals = [s[5] for s in idle_data + trigger_data]
        lt_idle = [s[4] for s in idle_data] if idle_data else lt_vals[:10]
        rt_idle = [s[5] for s in idle_data] if idle_data else rt_vals[:10]

        print()
        print("  TRIGGER VALUES")
        print("  " + "-" * 40)
        lt_base = statistics.median(lt_idle) if lt_idle else 0
        rt_base = statistics.median(rt_idle) if rt_idle else 0
        print(f"    LT: base(idle)={lt_base:5.1f}  min={min(lt_vals):3d}  max={max(lt_vals):3d}")
        print(f"    RT: base(idle)={rt_base:5.1f}  min={min(rt_vals):3d}  max={max(rt_vals):3d}")

    # Proposed defaults
    if idle_data and all_stick:
        print()
        print("  PROPOSED DEFAULT_CALIBRATION VALUES")
        print("  " + "-" * 40)
        for i, axis in enumerate(AXES):
            idle_vals = [s[i] for s in idle_data]
            all_vals = [s[i] for s in all_stick]
            center = round(statistics.median(idle_vals))
            mn, mx = min(all_vals), max(all_vals)
            half_range = round(max(center - mn, mx - center))
            side = axis[0].lower()
            xy = axis[1].lower()
            print(f"    'stick_{side}{'eft' if side == 'l' else 'ight'}_center_{xy}': {center},  "
                  f"'stick_{side}{'eft' if side == 'l' else 'ight'}_range_{xy}': {half_range},")

        if trigger_data:
            lt_idle_vals = [s[4] for s in idle_data]
            rt_idle_vals = [s[5] for s in idle_data]
            lt_base = round(statistics.median(lt_idle_vals))
            rt_base = round(statistics.median(rt_idle_vals))
            lt_max = max(s[4] for s in trigger_data)
            rt_max = max(s[5] for s in trigger_data)
            lt_bump = round(lt_base + (lt_max - lt_base) * 0.8)
            rt_bump = round(rt_base + (rt_max - rt_base) * 0.8)
            print(f"    'trigger_left_base': {lt_base}.0,  "
                  f"'trigger_left_bump': {lt_bump}.0,  "
                  f"'trigger_left_max': {lt_max}.0,")
            print(f"    'trigger_right_base': {rt_base}.0,  "
                  f"'trigger_right_bump': {rt_bump}.0,  "
                  f"'trigger_right_max': {rt_max}.0,")

    print()
    print("=" * 72)


# ---------------------------------------------------------------------------
# USB sampling
# ---------------------------------------------------------------------------

def run_usb_sampler(idle_secs, range_secs, trigger_secs, csv_prefix):
    print("=" * 72)
    print("  NSO GameCube Controller — Calibration Sampler (USB)")
    print("=" * 72)
    print()
    print("Searching for controller (VID=057e PID=2073)...")

    device, info = find_controller()
    if not device:
        print("ERROR: No NSO GameCube controller found.")
        print("  - Make sure it's connected via USB")
        print("  - On Linux: check udev rules / run as root")
        sys.exit(1)

    product = info.get('product_string', 'Unknown')
    print(f"Found: {product}")
    print()

    # Warm up
    for _ in range(20):
        device.read(64, timeout_ms=100)

    csv_file = None
    if csv_prefix:
        csv_path = f"{csv_prefix}_usb.csv"
        csv_file = open(csv_path, 'w')
        csv_file.write("phase,timestamp_ms,LX,LY,RX,RY,LT,RT\n")
        print(f"CSV output: {csv_path}")

    def read_one():
        """Read one report, handling Windows translation."""
        data = device.read(64, timeout_ms=16)
        if not data:
            return None
        device.set_nonblocking(1)
        try:
            for _ in range(63):
                more = device.read(64)
                if more:
                    data = more
                else:
                    break
        finally:
            device.set_nonblocking(0)
        if IS_WINDOWS:
            if data[0] == 0x05:
                data = translate_0x05(data)
            else:
                data = data[1:]
        return data

    idle_data = []
    range_data = []
    trigger_data = []

    try:
        # Phase 1: idle
        countdown("PHASE 1: Leave both sticks centered, don't touch anything", 3)
        print(f"  Recording idle for {idle_secs}s...")
        t_end = time.perf_counter() + idle_secs
        t_start = time.perf_counter()
        while time.perf_counter() < t_end:
            data = read_one()
            if data and len(data) >= 15:
                sample = parse_axes(data)
                idle_data.append(sample)
                if csv_file:
                    t = int((time.perf_counter() - t_start) * 1000)
                    csv_file.write(f"idle,{t},{','.join(str(v) for v in sample)}\n")
        print(f"  Collected {len(idle_data)} idle samples")

        # Phase 2: full stick rotation
        countdown("PHASE 2: Rotate BOTH sticks slowly around the full gate", 3)
        print(f"  Recording stick range for {range_secs}s...")
        t_end = time.perf_counter() + range_secs
        while time.perf_counter() < t_end:
            data = read_one()
            if data and len(data) >= 15:
                sample = parse_axes(data)
                range_data.append(sample)
                if csv_file:
                    t = int((time.perf_counter() - t_start) * 1000)
                    csv_file.write(f"range,{t},{','.join(str(v) for v in sample)}\n")
            elapsed = time.perf_counter() - (t_end - range_secs)
            pct = min(100, int(elapsed / range_secs * 100))
            sys.stdout.write(f"\r  Progress: {pct}%  samples: {len(range_data)}  ")
            sys.stdout.flush()
        print()
        print(f"  Collected {len(range_data)} range samples")

        # Phase 3: triggers
        countdown("PHASE 3: Slowly press BOTH triggers fully, then release. Repeat.", 3)
        print(f"  Recording triggers for {trigger_secs}s...")
        t_end = time.perf_counter() + trigger_secs
        while time.perf_counter() < t_end:
            data = read_one()
            if data and len(data) >= 15:
                sample = parse_axes(data)
                trigger_data.append(sample)
                if csv_file:
                    t = int((time.perf_counter() - t_start) * 1000)
                    csv_file.write(f"trigger,{t},{','.join(str(v) for v in sample)}\n")
        print(f"  Collected {len(trigger_data)} trigger samples")

    except KeyboardInterrupt:
        print("\n  Interrupted — showing partial results")
    finally:
        device.close()
        if csv_file:
            csv_file.close()

    print_summary(idle_data, range_data, trigger_data)


# ---------------------------------------------------------------------------
# BLE sampling
# ---------------------------------------------------------------------------

def run_ble_sampler(idle_secs, range_secs, trigger_secs, csv_prefix, address):
    import asyncio

    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        print("ERROR: bleak not installed.  pip install bleak")
        sys.exit(1)

    print("=" * 72)
    print("  NSO GameCube Controller — Calibration Sampler (BLE)")
    print("=" * 72)
    print()

    _HANDSHAKE_CMD = bytearray([
        0x02, 0x91, 0x01, 0x04,
        0x00, 0x08, 0x00, 0x00, 0x40, 0x7e, 0x00, 0x00, 0x00, 0x30, 0x01, 0x00
    ])
    _DEFAULT_REPORT_DATA = bytearray([
        0x03, 0x91, 0x00, 0x0d, 0x00, 0x08,
        0x00, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF
    ])
    _SET_INPUT_MODE = bytearray([
        0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x30
    ])

    NINTENDO_COMPANY_IDS = {0x037E, 0x0553}
    NINTENDO_NAMES = ('Pro Controller', 'Nintendo', 'Joy-Con', 'NSO', 'DeviceName')

    samples = collections.deque()

    def on_notification(char, value: bytearray):
        if len(value) < 15:
            return
        data = list(value)
        samples.append(parse_axes(data))

    async def _run():
        target = None

        if address:
            print(f"Connecting to {address}...")
            target = address
        else:
            print("Scanning for NSO GameCube controller (10s)...")
            devices = await BleakScanner.discover(timeout=10.0)
            for d in devices:
                name = d.name or ''
                md = getattr(d, 'metadata', {}) or {}
                mfr = md.get('manufacturer_data', {})
                is_nintendo = any(cid in mfr for cid in NINTENDO_COMPANY_IDS)
                is_named = any(n in name for n in NINTENDO_NAMES)
                if is_nintendo or is_named:
                    target = d.address
                    print(f"Found: {name or 'Unknown'} [{d.address}] RSSI={d.rssi}")
                    break

            if not target:
                print("ERROR: No Nintendo controller found via BLE.")
                return

        client = BleakClient(target, timeout=15.0)
        try:
            await client.connect()
        except Exception as e:
            print(f"Connection failed: {e}")
            return

        if not client.is_connected:
            print("Connection failed")
            return

        print(f"Connected to {target}")

        write_chars = []
        notify_chars = []
        for svc in client.services:
            for char in svc.characteristics:
                props = getattr(char, "properties", []) or []
                if "notify" in props or "indicate" in props:
                    notify_chars.append(char)
                if "write" in props or "write-without-response" in props:
                    write_chars.append(char)

        handshake_char = None
        for char in write_chars:
            try:
                await client.write_gatt_char(char.uuid, _HANDSHAKE_CMD)
                handshake_char = char
                break
            except Exception:
                try:
                    await client.write_gatt_char(char.uuid, bytearray([0x01, 0x01]))
                    handshake_char = char
                    break
                except Exception:
                    pass

        if not handshake_char:
            print("  Handshake failed")
            await client.disconnect()
            return

        for char in notify_chars:
            try:
                await client.start_notify(char.uuid, on_notification)
            except Exception:
                pass

        cmd_char = handshake_char
        for svc in client.services:
            wnr = sorted(
                [c for c in svc.characteristics
                 if "write-without-response" in (getattr(c, "properties", []) or [])],
                key=lambda c: c.handle)
            if len(wnr) >= 3:
                cmd_char = wnr[1]
                break

        for data in (_DEFAULT_REPORT_DATA,):
            try:
                await client.write_gatt_char(cmd_char, data, response=False)
            except Exception:
                pass

        try:
            await client.write_gatt_char(handshake_char.uuid, _SET_INPUT_MODE)
        except Exception:
            pass

        print("  Init complete — receiving notifications")
        await asyncio.sleep(0.5)
        samples.clear()

        idle_data = []
        range_data = []
        trigger_data = []

        csv_file = None
        if csv_prefix:
            csv_path = f"{csv_prefix}_ble.csv"
            csv_file = open(csv_path, 'w')
            csv_file.write("phase,timestamp_ms,LX,LY,RX,RY,LT,RT\n")
            print(f"  CSV output: {csv_path}")

        t_start = time.perf_counter()

        try:
            # Phase 1: idle
            print()
            print(f"  PHASE 1: Leave both sticks centered ({idle_secs}s)")
            for r in range(3, 0, -1):
                print(f"    Starting in {r}s...")
                await asyncio.sleep(1)
            print("    GO!")
            samples.clear()
            await asyncio.sleep(idle_secs)
            idle_data.extend(samples)
            samples.clear()
            print(f"    Collected {len(idle_data)} idle samples")

            # Phase 2: stick range
            print()
            print(f"  PHASE 2: Rotate BOTH sticks around the gate ({range_secs}s)")
            for r in range(3, 0, -1):
                print(f"    Starting in {r}s...")
                await asyncio.sleep(1)
            print("    GO!")
            samples.clear()
            await asyncio.sleep(range_secs)
            range_data.extend(samples)
            samples.clear()
            print(f"    Collected {len(range_data)} range samples")

            # Phase 3: triggers
            print()
            print(f"  PHASE 3: Press BOTH triggers fully, then release ({trigger_secs}s)")
            for r in range(3, 0, -1):
                print(f"    Starting in {r}s...")
                await asyncio.sleep(1)
            print("    GO!")
            samples.clear()
            await asyncio.sleep(trigger_secs)
            trigger_data.extend(samples)
            samples.clear()
            print(f"    Collected {len(trigger_data)} trigger samples")

        except asyncio.CancelledError:
            pass
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            if csv_file:
                for phase, data_list in [('idle', idle_data), ('range', range_data),
                                          ('trigger', trigger_data)]:
                    for s in data_list:
                        csv_file.write(f"{phase},0,{','.join(str(v) for v in s)}\n")
                csv_file.close()

        return idle_data, range_data, trigger_data

    result = None
    try:
        result = asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n  Interrupted")

    if result:
        idle_data, range_data, trigger_data = result
        print_summary(idle_data, range_data, trigger_data)
    else:
        print("\n  No data collected")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="NSO GameCube Controller — Calibration Sampler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Collects raw stick/trigger values in three guided phases:
  1. Idle (sticks centered) — determines stick center
  2. Full rotation (move sticks to all edges) — determines stick range
  3. Trigger press/release — determines trigger base/max

Run once per controller, then compare results to pick better defaults.

Examples:
  python tools/calibration_sampler.py                # USB
  python tools/calibration_sampler.py --ble          # BLE, auto-scan
  python tools/calibration_sampler.py --csv ctrl1    # save to ctrl1_usb.csv
  python tools/calibration_sampler.py --quick        # shorter phases
        """)
    parser.add_argument('--ble', action='store_true',
                        help='use BLE instead of USB (requires bleak)')
    parser.add_argument('--address', type=str, default=None,
                        help='BLE device address (skip scan)')
    parser.add_argument('--csv', type=str, default=None, metavar='PREFIX',
                        help='save raw data to PREFIX_usb.csv or PREFIX_ble.csv')
    parser.add_argument('--quick', action='store_true',
                        help='shorter phase durations (5/5/3 instead of 10/10/5)')
    args = parser.parse_args()

    idle_secs = 5 if args.quick else 10
    range_secs = 5 if args.quick else 10
    trigger_secs = 3 if args.quick else 5

    if args.ble:
        run_ble_sampler(idle_secs, range_secs, trigger_secs,
                        csv_prefix=args.csv, address=args.address)
    else:
        run_usb_sampler(idle_secs, range_secs, trigger_secs,
                        csv_prefix=args.csv)


if __name__ == '__main__':
    main()
