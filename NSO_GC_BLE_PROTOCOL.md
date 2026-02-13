# NSO GameCube Controller — BLE Protocol Guide

A library-agnostic guide for connecting the Nintendo Switch Online GameCube Controller (VID `0x057E`, PID `0x2073`) via Bluetooth Low Energy on any platform.

This controller uses a **proprietary Switch 2 (SW2) BLE protocol** that differs significantly from the original Switch Pro Controller protocol. Simply enabling GATT notifications is not enough — the controller requires SMP pairing with specific parameters, an MTU exchange, and a multi-step proprietary initialization sequence before it will send input data.

**Sources**: [BlueRetro](https://github.com/darthcloud/BlueRetro) (darthcloud), [switch2_controller_research](https://github.com/ndeadly/switch2_controller_research) (ndeadly), and original research.

---

## Table of Contents

1. [Controller Identification](#1-controller-identification)
2. [Entering BLE Advertising Mode](#2-entering-ble-advertising-mode)
3. [Connection Sequence Overview](#3-connection-sequence-overview)
4. [Step 1: BLE Connection](#step-1-ble-connection)
5. [Step 2: SMP Pairing (Critical)](#step-2-smp-pairing-critical)
6. [Step 3: MTU Exchange (Critical)](#step-3-mtu-exchange-critical)
7. [Step 4: GATT Discovery](#step-4-gatt-discovery)
8. [Step 5: SW2 Protocol Initialization](#step-5-sw2-protocol-initialization)
9. [Step 6: Enable Input Notifications](#step-6-enable-input-notifications)
10. [GATT Service & Handle Map](#gatt-service--handle-map)
11. [SW2 Command Format](#sw2-command-format)
12. [Input Report Format (63 bytes)](#input-report-format-63-bytes)
13. [Common Pitfalls](#common-pitfalls)
14. [Platform Notes](#platform-notes)
15. [References](#references)

---

## 1. Controller Identification

| Field | Value |
|-------|-------|
| Vendor ID | `0x057E` (Nintendo) |
| Product ID | `0x2073` |
| BLE Device Name | `DeviceName` (Generic Attribute `0x002D`) |
| Manufacturer Data | Company ID `0x037E` (Nintendo), includes PID `0x2073` |

During BLE advertising, the controller broadcasts manufacturer-specific data containing the Nintendo company ID and the product ID. Use these to identify the device during scanning.

---

## 2. Entering BLE Advertising Mode

The controller **does not** enter BLE advertising automatically and **cannot** be triggered into advertising via USB commands. You must:

1. Disconnect the controller from USB (if connected)
2. Press the **SYNC** button on the controller (small button, usually on the back/top)
3. The controller will advertise for approximately 60 seconds

There is no USB command to trigger BLE advertising — the full USB command space (0x00–0xFF) has been probed without finding one.

---

## 3. Connection Sequence Overview

```
┌─────────────────────────────────┐
│  1. BLE Connect                 │
│     (public address, LE 1M PHY) │
├─────────────────────────────────┤
│  2. SMP Legacy "Just Works"     │  ← CRITICAL: specific key
│     (sc=false, mitm=false)      │    distribution flags required
├─────────────────────────────────┤
│  3. MTU Exchange                │  ← CRITICAL: reports are 63B,
│     (request ≥185)              │    default MTU 23 drops them
├─────────────────────────────────┤
│  4. GATT Discovery              │
├─────────────────────────────────┤
│  5. SW2 Protocol Init (23 steps)│
│    a. Enable service (0x0005)   │
│    b. Enable cmd CCCD (0x001B)  │
│    c. Init cmds + SPI reads     │
│    d. Proprietary pairing       │
│    e. LE encryption              │
│    f. Vibration, LED, features  │
│    g. Calibration SPI reads     │
│    h. Report rate (0x0010)      │
├─────────────────────────────────┤
│  6. Enable Input Notifications  │
│    - Write 0x0100 to 0x000F     │
│    - Write 0x0000 to 0x001B     │
├─────────────────────────────────┤
│  ✓ Input data flows on 0x000E  │
│    (63-byte reports)            │
└─────────────────────────────────┘
```

---

## Step 1: BLE Connection

Connect to the controller's **public** BLE address using LE 1M PHY.

**Connection parameters** (known-working):
- Connection interval: 15–30 ms
- Slave latency: 0
- Supervision timeout: 5000 ms

The controller connects quickly (typically <1 second).

---

## Step 2: SMP Pairing (Critical)

Immediately after connecting, initiate **SMP Legacy "Just Works" pairing**. This step establishes an encrypted link, which the controller requires before it will send input data.

### Required Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Secure Connections (SC) | **false** | Must be Legacy pairing; controller rejects SC |
| MITM | **false** | "Just Works" association model |
| Bonding | **true** | |
| IO Capability | NoInputNoOutput | |
| Initiator Key Distribution | **0x02** (Identity Key only) | **NOT the default 0x03** |
| Responder Key Distribution | **0x01** (Encryption Key only) | **NOT the default 0x03** |

### Why This Is Critical

Most BLE stacks default to `initiator_key_distribution=0x03` and `responder_key_distribution=0x03`. The controller **rejects** these defaults with `SMP_PAIRING_NOT_SUPPORTED_ERROR (0x05)`. You must explicitly set the key distribution to match BlueRetro's values:

- Initiator distributes: **Identity Key only** (0x02)
- Responder distributes: **Encryption Key only** (0x01)

This is the single most important detail in this guide. Without the correct key distribution flags, pairing fails and the entire protocol is blocked.

### Expected Result

After successful pairing, the BLE link should be encrypted. Verify by checking the connection's encryption status. If encryption is not established, the controller will not send input data.

---

## Step 3: MTU Exchange (Critical)

Before GATT discovery, request a larger ATT MTU. The controller's input reports are **63 bytes**, but the default BLE MTU of 23 only allows a 20-byte ATT payload. If the MTU is too small, the controller **silently drops all notifications** — there is no error.

**Request**: MTU of 512 (or any value ≥ 185)
**Controller responds**: MTU of 185 (typical)

This must happen **before** GATT discovery and notification subscription.

---

## Step 4: GATT Discovery

Perform standard GATT service and characteristic discovery. The controller exposes 4 services. See the [GATT Handle Map](#gatt-service--handle-map) below for the full layout.

---

## Step 5: SW2 Protocol Initialization (26 Steps)

All SW2 commands are written to handle `0x0014` (WriteWithoutResponse) and responses arrive as notifications on handle `0x001A`.

> **Note**: There are two valid command channel pairs. Handle `0x0014`/`0x001A` is the primary pair — commands are sent directly. Handle `0x0016`/`0x001E` is the secondary pair — commands require a 33-byte zero prefix, and responses have a 14-byte header before the actual data. ndeadly's switch2_input_viewer defaults to the primary pair.

The full sequence below is derived from ndeadly's switch2_input_viewer.

| Step | Action | Handle | Details |
|------|--------|--------|---------|
| 1 | Enable service | 0x0005 | Write `01 00` (with response) |
| 2 | Enable cmd response CCCD | 0x001B | Write `01 00`, subscribe to 0x001A |
| 3 | SPI read device info | 0x0014 | Address 0x13000, 0x40 bytes |
| 4-7 | Proprietary pairing (Bumble only) | 0x0014 | cmd 0x15, subcmds 0x01-0x04 |
| 8 | SPI read pairing data (Bumble only) | 0x0014 | Address 0x1FA000, 0x40 bytes |
| 9 | LE encryption (Bumble only) | HCI | Use computed or SPI LTK |
| 10 | Vibration sample | 0x0014 | cmd 0x0A, subcmd 0x02, index 0x03 |
| 11 | Set LED | 0x0014 | cmd 0x09, subcmd 0x07 |
| 12 | Configure features 0xFF | 0x0014 | cmd 0x0C, subcmd 0x02, flags 0xFF |
| 13 | SPI read left stick cal | 0x0014 | Address 0x13080, 0x40 bytes |
| 14 | SPI read right stick cal | 0x0014 | Address 0x130C0, 0x40 bytes |
| 15 | SPI read user cal | 0x0014 | Address 0x1FC040, 0x40 bytes |
| 16 | SPI read gyro cal | 0x0014 | Address 0x13040, 0x10 bytes |
| 17 | SPI read accel/mag cal | 0x0014 | Address 0x13100, 0x18 bytes |
| 18 | SPI read trigger cal (GC) | 0x0014 | Address 0x13140, 0x02 bytes |
| 19 | SPI read GC cal 2 (GC) | 0x0014 | Address 0x13160, 0x20 bytes |
| 20 | Enable features 0x03 | 0x0014 | cmd 0x0C, subcmd 0x04, flags 0x03 |
| 21 | Get firmware version | 0x0014 | cmd 0x10, subcmd 0x01 |
| 22 | Set report rate | 0x0010 | Write `85 00` (descriptor, with response) |
| 23 | Enable GC input, disable cmd CCCD | 0x000F/0x001B | `01 00` / `00 00` |

Steps 4-9 are only performed on Linux (Bumble backend) which handles proprietary pairing and LE encryption at the HCI level. On macOS/Windows (Bleak backend), the OS BLE stack handles SMP pairing automatically.

### Proprietary Pairing (Steps 4-7, Bumble only)

A 4-step cryptographic handshake using command ID `0x15`. All commands are written to handle `0x0014`. Wait for a response on `0x001A` after each step.

**Step 4** — Send local BLE address:
```
15 91 01 01 00 0E 00 00 00 02
[6 bytes: local BLE address]
[6 bytes: local BLE address with last byte decremented by 1]
```

The local BLE address is the adapter's BLE MAC address in byte order as reported by the HCI controller (typically little-endian, i.e., least significant byte first).

**Step 5** — Send random public key A1 (subcommand 0x04):
```
15 91 01 04 00 11 00 00 00
[16 bytes: random A1 key]
```

The response contains the controller's public key B1 (fixed: `5C F6 EE 79 2C DF 05 E1 BA 2B 63 25 C4 1A 5F 10`).

Compute the LTK: `LTK = A1 XOR B1`

**Step 6** — Send random challenge A2 (subcommand 0x02):
```
15 91 01 02 00 11 00 00 00
[16 bytes: random A2 challenge]
```

The response contains B2. Verify: `B2 == AES-128-ECB(reverse(LTK), reverse(A2))`.

**Important**: The LTK must be byte-reversed before use as the AES key.

**Step 7** — Finalize pairing:
```
15 91 01 03 00 01 00 00 00
```

### LED Command (Step 11)

Send an LED command to indicate which player slot the controller is assigned to:

```
09 91 01 07 00 08 00 00 [LED_MASK] 00 00 00 00 00 00 00
```

LED mask values for player positions:

| Player | LED Mask |
|--------|----------|
| 1 | `0x01` |
| 2 | `0x03` |
| 3 | `0x05` |
| 4 | `0x06` |

---

## Step 6: Enable Input Notifications

This is the final step (step 23 in the full sequence). Write **two** values:

1. **Enable GC input CCCD**: Write `0x01 0x00` to handle `0x000F` (with response)
2. **Disable command response CCCD**: Write `0x00 0x00` to handle `0x001B` (with response)

Both writes are required. The command response CCCD must be disabled at the same time as enabling GC input — omitting the second write may prevent notifications from flowing.

After this step, **63-byte input reports** will arrive as notifications on handle **`0x000E`**. Data arrives at approximately 125 Hz (8 ms interval) after the report rate is set to `0x85 0x00` on handle `0x0010`.

---

## GATT Service & Handle Map

### Service 1: `00c5af5d-1964-4e30-8f51-1956f96bd280` (Service Control)

| Handle | UUID Suffix | Properties | Purpose |
|--------|-------------|------------|---------|
| 0x0005 | `bd282` | Write | **Service enable** — write `0x01 0x00` to activate |

### Service 2: `ab7de9be-89fe-49ad-828f-118f09df7fd0` (Nintendo SW2)

| Handle | Type | Properties | Purpose |
|--------|------|------------|---------|
| 0x000A | Characteristic | Read, Notify | Input report (format 0, legacy) |
| 0x000B | CCCD | — | CCCD for 0x000A (legacy) |
| 0x000E | Characteristic | Read, Notify | **GC input report (format 3)** — 63-byte reports arrive here |
| 0x000F | CCCD | — | **GC input CCCD** (write `0x01 0x00` to enable) |
| 0x0010 | Descriptor | Write | **Report rate** — write `0x85 0x00` for ~125 Hz (UUID: `679d5510-...`) |
| 0x0012 | Characteristic | WriteNoResp | Vibration/rumble output |
| 0x0014 | Characteristic | WriteNoResp | **Command channel** (SW2 protocol commands, ndeadly default) |
| 0x0016 | Characteristic | WriteNoResp | Alt command channel (requires 33-byte zero prefix) |
| 0x001A | Characteristic | Notify | **Command response** (for 0x0014 writes) |
| 0x001B | CCCD | — | **Command response CCCD** (write `0x01 0x00` to enable) |
| 0x001E | Characteristic | Notify | Alt command response (for 0x0016 writes, 14-byte header) |
| 0x001F | CCCD | — | CCCD for 0x001E |

### Service 3: `00001800` (GAP)

| Handle | UUID | Properties | Purpose |
|--------|------|------------|---------|
| 0x002D | `00002A00` | Read | Device Name ("DeviceName") |
| 0x002F | `00002A01` | Read | Appearance |

### Service 4: `00001801` (GATT)

Empty service (handle 0x0030).

---

## SW2 Command Format

All commands are written to handle `0x0014` (WriteWithoutResponse). Responses arrive on `0x001A`.

```
Byte 0:    Command ID
Byte 1:    0x91 (request type)
Byte 2:    0x01 (BLE interface)
Byte 3:    Sub-command
Byte 4:    0x00
Byte 5:    Data length (varies)
Byte 6-7:  0x00 0x00
Byte 8+:   Command-specific data
```

### Command IDs

| ID | Name | Sub-commands |
|----|------|--------------|
| `0x02` | SPI Flash Read | `0x04` = read |
| `0x09` | Set LED | `0x07` = set player LED |
| `0x0A` | Vibration | `0x02` = play sample |
| `0x0C` | Feature Flags | `0x02` = configure, `0x04` = enable, `0x05` = disable |
| `0x10` | Version Info | `0x01` = get firmware version |
| `0x15` | Proprietary Pairing | `0x01`–`0x04` = pairing steps 1–4 |

### SPI Read Command

```
02 91 01 04 00 08 00 00
[1 byte: read size]
7E 00 00
[4 bytes: SPI address, little-endian]
```

**Response format** (on handle `0x001A`):
```
Bytes 0-15:   Response header (cmd echo, status, flags, size, address)
Bytes 16+:    SPI flash data
```

### Known SPI Addresses

| Address | Size | Contents |
|---------|------|----------|
| `0x00013000` | 0x40 | Device info (serial, VID, PID, colours) |
| `0x00013040` | 0x10 | Gyro calibration (temperature + bias) |
| `0x00013080` | 0x40 | Primary stick factory calibration |
| `0x000130C0` | 0x40 | Secondary stick factory calibration |
| `0x00013100` | 0x18 | Accelerometer / magnetometer calibration |
| `0x00013140` | 0x02 | Analog trigger calibration (GC-specific) |
| `0x00013160` | 0x20 | GC calibration 2 (GC-specific) |
| `0x001FA000` | 0x40 | Pairing data (host addresses, LTK at offset 0x1A) |
| `0x001FC040` | 0x40 | User stick calibrations |

---

## Input Report Format (63 bytes)

Notifications arrive on handle **`0x000E`** (format 3). Each report is exactly 63 bytes.

### Byte Layout

| Offset | Size | Field |
|--------|------|-------|
| `0x00` | 1 | Packet counter (increments each report) |
| `0x01` | 1 | Flags (`0x20` at idle) |
| `0x02` | 1 | Buttons byte 1 |
| `0x03` | 1 | Buttons byte 2 |
| `0x04` | 1 | Buttons byte 3 |
| `0x05`–`0x07` | 3 | Left stick (12-bit X + 12-bit Y, packed) |
| `0x08`–`0x0A` | 3 | Right stick / C-stick (12-bit X + 12-bit Y, packed) |
| `0x0B` | 1 | Unknown (`0x30` at idle) |
| `0x0C` | 1 | Left trigger (analog, 0x00–0xFF) |
| `0x0D` | 1 | Right trigger (analog, 0x00–0xFF) |
| `0x0E` | 1 | Unknown |
| `0x0F`–`0x36` | 40 | IMU / motion data (accelerometer + gyroscope) |
| `0x37`–`0x3E` | 8 | Unknown / padding |

### Button Bits

The button encoding is **identical to the USB HID report** (USB bytes 3–5 = BLE bytes 0x02–0x04).

**Byte 0x02:**

| Bit | Mask | Button |
|-----|------|--------|
| 0 | `0x01` | B |
| 1 | `0x02` | A |
| 2 | `0x04` | Y |
| 3 | `0x08` | X |
| 4 | `0x10` | R (digital click) |
| 5 | `0x20` | Z |
| 6 | `0x40` | Start |
| 7 | `0x80` | (unused) |

**Byte 0x03:**

| Bit | Mask | Button |
|-----|------|--------|
| 0 | `0x01` | D-pad Down |
| 1 | `0x02` | D-pad Right |
| 2 | `0x04` | D-pad Left |
| 3 | `0x08` | D-pad Up |
| 4 | `0x10` | L (digital click) |
| 5 | `0x20` | ZL |
| 6 | `0x40` | (unused) |
| 7 | `0x80` | (unused) |

**Byte 0x04:**

| Bit | Mask | Button |
|-----|------|--------|
| 0 | `0x01` | Home |
| 1 | `0x02` | Capture |
| 2 | `0x04` | GR |
| 3 | `0x08` | GL |
| 4 | `0x10` | Chat |
| 5–7 | — | (unused) |

### Stick Decoding

Both sticks use 12-bit resolution (0–4095) packed into 3 bytes:

```
byte[0] | ((byte[1] & 0x0F) << 8)  →  X axis (12-bit)
(byte[1] >> 4) | (byte[2] << 4)    →  Y axis (12-bit)
```

**Left stick** (bytes `0x05`–`0x07`):
```
LX = data[0x05] | ((data[0x06] & 0x0F) << 8)    // center ≈ 2048
LY = (data[0x06] >> 4) | (data[0x07] << 4)       // center ≈ 2048
```

**Right / C-stick** (bytes `0x08`–`0x0A`):
```
RX = data[0x08] | ((data[0x09] & 0x0F) << 8)     // center ≈ 2048
RY = (data[0x09] >> 4) | (data[0x0A] << 4)        // center ≈ 2048
```

Center position is approximately `0x800` (2048). Full range is `0x000`–`0xFFF` (0–4095).

### Trigger Decoding

| Byte | Trigger | Rest Value | Full Press |
|------|---------|------------|------------|
| `0x0C` | Left trigger | ~0x22 (34) | ~0xEA (234) |
| `0x0D` | Right trigger | ~0x22 (34) | ~0xF0 (240) |

The triggers have both analog values (bytes `0x0C`–`0x0D`) and digital click bits (byte 0x02 bit 4 for R, byte 0x03 bit 4 for L). The digital bits activate when the trigger is fully depressed.

### Controller Notes

- **No clickable sticks**: The GC controller does not have L3/R3 (stick press) buttons. There are no digital bits for stick clicks.
- **Trigger dual-mode**: Each trigger has an analog value AND a digital bit. The digital bit activates at the end of the trigger's physical travel.

---

## Common Pitfalls

### 1. SMP key distribution flags (most common failure)

**Symptom**: `SMP_PAIRING_NOT_SUPPORTED_ERROR (0x05)` immediately after sending SMP Pairing Request.

**Cause**: Your BLE stack is sending the default key distribution flags (`init=0x03, resp=0x03`). The controller requires `init=0x02 (ID_KEY only), resp=0x01 (ENC_KEY only)`.

**Fix**: Override your BLE stack's SMP pairing delegate/config to set explicit key distribution values.

### 2. Missing MTU exchange (silent failure)

**Symptom**: All initialization succeeds, no errors, but zero notifications arrive.

**Cause**: The default BLE MTU of 23 allows only a 20-byte ATT payload. The controller's 63-byte input reports exceed this, so the controller silently drops them.

**Fix**: Request MTU ≥ 185 before GATT discovery.

### 3. Feature flags (cmd 0x0C) ARE required

**Note**: Earlier versions of this document stated that cmd `0x0C` should not be sent. This was incorrect — ndeadly's switch2_input_viewer includes feature flags as a required part of the init sequence.

**Correct usage**: Send `0x0C` with subcmd `0x02` (configure, flags `0xFF`) before calibration reads, then `0x0C` with subcmd `0x04` (enable, flags `0x03`) after calibration reads.

### 4. Not disabling command response CCCD when enabling input

**Symptom**: Input CCCD written successfully but no notifications.

**Cause**: The command response CCCD (`0x00 0x00` to `0x001B`) must be disabled at the same time as enabling the GC input CCCD. Omitting this may prevent input data from flowing.

**Fix**: Write both: `0x01 0x00` to `0x000F` (GC input CCCD) AND `0x00 0x00` to `0x001B` (cmd response CCCD).

### 5. Report rate descriptor IS required

**Note**: Earlier versions of this document stated that the report rate descriptor should not be written. This was incorrect — the ndeadly guide includes it as step 25.

**Correct usage**: Write `0x85 0x00` to handle `0x0010` (with response) after the extended vibration config and before enabling GC input notifications. This sets the report rate to ~125 Hz (8 ms interval). The characteristic UUID is `679d5510-5a24-4dee-9557-95df80486ecb`.

### 6. Using handle 0x002A (legacy output)

**Symptom**: Commands written to `0x002A` work for basic LED control but nothing else.

**Cause**: `0x002A` is the legacy Switch Pro Controller output handle. The SW2 protocol uses `0x0014` for commands with responses on `0x001A`.

**Fix**: All SW2 commands go to `0x0014`.

### 7. AES verification uses reversed LTK

**Symptom**: `challenge verification failed` during proprietary pairing step 8.

**Cause**: The LTK must be byte-reversed before use as the AES-128-ECB key. The verification formula is: `B2 == AES-128-ECB(reverse(LTK), reverse(A2))`.

**Fix**: Reverse the LTK bytes before passing to AES: `algorithms.AES(bytes(reversed(ltk)))`.

### 7. BlueZ D-Bus `ServicesResolved` stays false

**Symptom**: `bluetoothctl` connects but GATT services never appear. `bleak` times out.

**Cause**: BlueZ's D-Bus GATT service export has issues with this controller. `ServicesResolved` stays `false` even when the HCI connection is active. This is a BlueZ/D-Bus layer issue, not a controller issue.

**Fix**: Use a BLE stack that operates at the HCI level (e.g., Bumble with `HCI_CHANNEL_USER`, or a raw HCI implementation). See [Platform Notes](#platform-notes).

---

## Platform Notes

### Linux

**BlueZ D-Bus (bleak, bluepy, etc.)**: Does not work reliably. `ServicesResolved` stays `false`, GATT objects never appear in D-Bus. Disabling `-P input,hog` plugins fixes `bluetoothctl` connectivity but not `bleak`.

**Recommended approach**: Use [Google Bumble](https://github.com/nicklasb/bumble) via raw HCI sockets (`HCI_CHANNEL_USER`). This bypasses BlueZ entirely and provides full control over SMP parameters.

Requirements:
- BlueZ service must be stopped: `sudo systemctl stop bluetooth.service`
- HCI adapter must be brought down: `sudo hciconfig hci0 down`
- Root access required for raw HCI sockets

### Windows

**WinRT (bleak on Windows, C# UWP)**: Works transparently. WinRT handles SMP pairing automatically with correct parameters. Simply connect and enable notifications — the OS handles the rest. This is why existing Windows tools like NS2-Connect.py appear to skip the pairing state machine.

### macOS

**CoreBluetooth**: Untested. CoreBluetooth manages its own SMP pairing. If it uses correct key distribution flags by default (or allows overriding them), it should work.

---

## References

- [BlueRetro](https://github.com/darthcloud/BlueRetro) — ESP32 BLE-to-wired adapter with complete SW2 protocol implementation. Key files: `main/src/wired/sw2.c`, `sw2.h`
- [switch2_controller_research](https://github.com/ndeadly/switch2_controller_research) — Comprehensive Switch 2 controller research by ndeadly. Defines the full 26-step init sequence, handle map, and crypto details.
- [Switch2-Controllers](https://github.com/Nohzockt/Switch2-Controllers) — Windows BLE gamepad mapper. Uses legacy protocol (0x002A) with WinRT handling pairing transparently.
- [Google Bumble](https://github.com/nicklasb/bumble) — Python BLE stack with raw HCI support. Used for the reference Linux implementation.
