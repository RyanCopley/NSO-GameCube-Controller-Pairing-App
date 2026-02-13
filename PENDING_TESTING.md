# Pending BLE Testing

Changes made to align the Bluetooth implementation with ndeadly's
[switch2_controller_research](https://github.com/ndeadly/switch2_controller_research/blob/master/bluetooth_interface.md).

Three fixes were applied. Each section below lists what changed, which
platforms are affected, and what to verify.

---

## Fix 5 — Removed SMP Pairing

**Platforms affected: Linux only** (Bumble backend)

macOS/Windows use the Bleak backend, which delegates SMP to the OS BLE
stack and was not changed.

### What changed
- Removed the explicit `connection.pair()` call that ran Legacy "Just Works"
  SMP before the proprietary Nintendo pairing handshake.
- Removed the `security_request` event handler that auto-responded to
  controller-initiated SMP requests.
- Removed `PairingConfig`/`PairingDelegate` setup entirely.

### Why
The guide states "Attempting standard SMP pairing causes controller
disconnection." The previous code used specific SMP key distribution flags
that happened to work, but this was undocumented behavior.

### Test plan

| # | Scenario | Steps | Pass criteria |
|---|----------|-------|---------------|
| 1 | Fresh pair (Linux) | Remove any saved BLE address for the controller in settings. Pair a GC controller via the BLE dialog. | Controller connects, LED lights up, input works. |
| 2 | Reconnect known device (Linux) | After test 1, disconnect and reconnect using the saved address. | Reconnects without re-scanning. Input works. |
| 3 | Multi-slot (Linux) | Pair 2+ controllers to different slots simultaneously. | Both connect and stream input independently. |
| 4 | Cold boot reconnect (Linux) | Close the app after pairing. Relaunch with auto-scan enabled. | Controller auto-reconnects on startup. |

---

## Fix 6 — Dynamic Pairing Crypto

**Platforms affected: Linux only** (Bumble backend; `sw2_init()` is not
called by the Bleak backend)

### What changed
- Replaced hardcoded 16-byte public key (A1) and challenge (A2) with
  `os.urandom(16)` — a fresh random key pair is generated per connection.
- LTK is now computed as `A1 XOR B1` (B1 is the controller's fixed public
  key) instead of being read from SPI flash.
- Added AES-128-ECB verification of the controller's challenge response
  (B2) using the `cryptography` library (gracefully skipped if unavailable).
- SPI flash read at `0x1FA000` is retained as a fallback LTK source in the
  encryption attempt list.

### Why
The guide describes a dynamic crypto exchange. The previous implementation
used static values, meaning every pairing produced the same LTK.

### Test plan

| # | Scenario | Steps | Pass criteria |
|---|----------|-------|---------------|
| 1 | Fresh pair (Linux) | Clear saved BLE data. Pair via BLE dialog. | Connects, encrypts link, LED lights, input streams. |
| 2 | Verify unique LTK | Pair twice (clear saved address between attempts). Check console output for "challenge verification failed" warnings. | No verification failure warnings in either pairing. |
| 3 | Encryption fallback | If test 1 fails on a specific controller, check whether the SPI fallback LTK succeeds (look for multiple encryption attempts in output). | Connection eventually encrypts and works. |
| 4 | Rumble (Linux) | Trigger rumble while connected via BLE. | Rumble activates and deactivates cleanly. |
| 5 | Without `cryptography` | Uninstall `cryptography` pip package, run the app. Pair a controller. | Pairing succeeds (AES verification is skipped gracefully). |

---

## Fix 10 — Manufacturer Data Filtering

**Platforms affected: Linux, macOS, Windows**

### What changed
- **Bumble backend (Linux)**: `_scan()` now checks BLE advertisement
  manufacturer data for company IDs `0x0553` and `0x057E` (per the guide),
  in addition to the existing Nintendo OUI MAC prefix fallback.
- **Bleak backend (macOS/Windows)**: Device prioritization now checks for
  company IDs `0x0553`, `0x057E`, and `0x037E` (was only `0x037E`).

### Why
The guide specifies manufacturer data ID `0x0553` for Switch 2 controllers.
The previous code used `0x037E` (Bleak) or only OUI MAC matching (Bumble),
which could miss controllers or mis-prioritize them.

### Test plan

| # | Scenario | Steps | Pass criteria |
|---|----------|-------|---------------|
| 1 | Auto-scan (Linux) | Use the auto-scan / BLE pair flow. | GC controller is discovered and connectable. |
| 2 | Auto-scan (macOS) | Use the auto-scan / BLE pair flow. | GC controller is discovered and connectable. |
| 3 | Auto-scan (Windows) | Use the auto-scan / BLE pair flow. | GC controller is discovered and connectable. |
| 4 | Device picker (Linux) | Open the BLE device picker dialog (scan_only). | GC controller appears in the list. |
| 5 | Device picker (macOS) | Open the BLE device picker dialog. | GC controller appears in the list. |
| 6 | Device picker (Windows) | Open the BLE device picker dialog. | GC controller appears in the list. |
| 7 | Non-GC BLE devices nearby | Have other BLE devices advertising nearby. | GC controller is still discovered; other devices don't cause errors. |
| 8 | Bonded device (Windows) | Pair once, restart app. Reconnect to the bonded device. | Direct connect by address succeeds even if device doesn't appear in scan. |

---

## Test matrix summary

| Test area | Linux | macOS | Windows |
|-----------|:-----:|:-----:|:-------:|
| Fix 5 — No SMP | REQUIRED | n/a | n/a |
| Fix 6 — Dynamic crypto | REQUIRED | n/a | n/a |
| Fix 10 — Scan filtering | REQUIRED | REQUIRED | REQUIRED |

Linux is the highest-risk platform since all three fixes apply there.
macOS and Windows only need scan/discovery regression testing.
