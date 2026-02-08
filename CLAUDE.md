# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NSO GameCube Controller Pairing App — a cross-platform Python/PyQt6 application that makes Nintendo Switch Online GameCube controllers work as Xbox 360 controllers or Dolphin emulator input via USB or Bluetooth. Supports up to 4 simultaneous controllers with independent calibration.

## Build & Run Commands

```bash
# Install in development mode
pip install -e .

# Run the application
python -m gc_controller

# Run headless (no GUI)
python -m gc_controller --headless [--mode dolphin_pipe]

# Build platform executables (PyInstaller)
python build_all.py
# Or platform-specific:
platform/linux/build.sh
platform/macos/build.sh
platform/windows/build.bat
```

There is no test suite in this project.

## Architecture

The app follows a **per-slot architecture** — up to 4 independent controller slots, each with its own managers:

```
GUI (PyQt6) → App Orchestrator (app.py)
  → ControllerSlot (controller_slot.py) — per-slot state container
    ├── ConnectionManager  — USB HID init via hidapi/pyusb
    ├── InputProcessor     — dedicated HID read thread per slot
    ├── EmulationManager   — virtual gamepad lifecycle
    └── CalibrationManager — octagon stick + trigger calibration
```

### Key modules in `src/gc_controller/`

- **app.py** — Main orchestrator, multi-slot management, settings persistence, BLE subprocess coordination
- **controller_slot.py** — Encapsulates all managers for one controller slot
- **connection_manager.py** — USB enumeration/init (pyusb), HID open/close (hidapi), path-based device claiming
- **input_processor.py** — Per-slot HID read thread, button/stick remapping, handles USB and BLE input formats
- **emulation_manager.py** — Creates platform-specific virtual gamepads, hot-path input forwarding
- **virtual_gamepad.py** — Abstract base + platform implementations (Windows: vgamepad/ViGEmBus, Linux: evdev/uinput, Dolphin: named FIFO pipes)
- **calibration.py** — 8-sector octagon stick calibration, 3-point trigger calibration, thread-safe with locks
- **settings_manager.py** — JSON persistence with v1→v2 migration, per-slot calibration storage
- **controller_constants.py** — Shared button/stick constants and mappings

### BLE subsystem (`src/gc_controller/ble/`)

- **sw2_protocol.py** — Switch 2 BLE protocol (pairing, initialization)
- **bumble_backend.py** — Linux: direct HCI transport via Bumble (requires elevated privileges via pkexec)
- **bleak_backend.py** — macOS/Windows: userspace BLE via Bleak
- **ble_subprocess.py / bleak_subprocess.py** — Privileged subprocess runners
- BLE requires MTU ≥185 bytes; input reports are 63 bytes on GATT characteristic 0x000E

### UI modules

- **controller_ui.py** — Per-slot controller cards with calibration/connection UI
- **ui_controller_canvas.py** — Stick/trigger visualization canvas
- **ui_ble_dialog.py** — BLE device picker dialog
- **ui_settings_dialog.py** — Settings dialog
- **ui_theme.py** — PyQt6 QSS theme configuration

## Platform-Specific Notes

| Platform | Xbox 360 Emulation | Dolphin Pipe | BLE Backend | Notes |
|----------|-------------------|--------------|-------------|-------|
| Windows  | vgamepad (ViGEmBus) | N/A | Bleak | USB rumble needs WinUSB driver (Zadig) |
| Linux    | evdev/uinput | Named FIFO | Bumble (HCI) | BLE needs elevated privileges; BlueZ stopped while Bumble active |
| macOS    | Not supported | Named FIFO | Bleak | Use Dolphin pipe mode |

## Important Patterns

- **Thread safety**: Calibration modifications use locks; UI updates go through `pyqtSignal.emit()` to stay on the Qt main thread
- **Device claiming**: Path-based to prevent two slots from connecting to the same physical controller
- **Report formats**: Standard GC USB binary format vs Windows NSO (report ID 0x05, different button encoding handled via `_translate_report_0x05()`) vs BLE (63-byte native Switch format)
- **Platform detection**: Uses `sys.platform` throughout (`win32`, `linux`, `darwin`)
- **BLE state**: Lazy initialization on first pair; subprocess messaging via events/queues
- **PyInstaller builds**: vgamepad DLL paths need special handling in frozen builds via `sys._MEIPASS`
- **Entry points**: `--ble-subprocess` and `--bleak-subprocess` flags in `__main__.py` dispatch to BLE subprocess runners instead of the main app
- **System tray**: Uses `QSystemTrayIcon` (built into PyQt6). Optional — gracefully disabled if unavailable.

## Frozen Build Checklist

**When adding new features or dependencies, always verify they work in PyInstaller frozen builds on all three platforms.** Specifically:

1. **New imports**: If a library uses dynamic/conditional imports, PyInstaller can't trace them automatically. Add explicit hidden imports to the platform-specific sections in `gc_controller_enabler.spec`.
2. **New data/asset files**: Any runtime-loaded files (images, fonts, configs) must be added to the `datas` list in the spec file AND loaded via `getattr(sys, '_MEIPASS', os.path.dirname(__file__))` in code.
3. **New pip dependencies**: Add to `pyproject.toml` with platform markers where appropriate (e.g., `; sys_platform == 'win32'`).
4. **System-only packages** (not pip-installable, e.g., `gi`/PyGObject on Linux): Use `collect_all()` wrapped in try/except in the spec file, and ensure the feature degrades gracefully at runtime if the package is missing.
5. **New C extensions or DLLs**: Add as `binaries` (not `datas`) in the spec file so PyInstaller resolves transitive dependencies.
6. **Optional features**: Always wrap imports in try/except with a `_FEATURE_AVAILABLE` flag so the app runs even if bundling is incomplete.

## Dependencies

Core: `hidapi`, `pyusb`, `PyQt6`
Platform: `vgamepad` (Windows), `evdev` + `bumble` (Linux), `bleak` (macOS/Windows), `pyobjc-framework-Cocoa` (macOS)
Build: `pyinstaller`

## License

GPLv3
