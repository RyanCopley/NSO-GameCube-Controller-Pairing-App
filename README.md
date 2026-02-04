![Screenshot](Screenshot%202025-07-14%20204357.png)

# GameCube Controller Enabler

A cross-platform Python/Tkinter tool that connects Nintendo GameCube controllers via USB and makes them usable on Steam and other platforms through Xbox 360 controller emulation.

## Features

- USB initialization and HID communication with GameCube controllers
- Xbox 360 controller emulation (Windows via vgamepad, Linux via evdev/uinput)
- Analog trigger calibration for different controller variations
- Real-time visualization of inputs (buttons, sticks, triggers)
- Persistent calibration settings

## Requirements

- Python 3.7+
- Platform-specific dependencies (see below)

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Platform-specific setup:

### Windows
- Install the [ViGEmBus driver](https://github.com/nefarius/ViGEmBus) for Xbox 360 emulation

### Linux
- Install libusb: `sudo apt install libusb-1.0-0-dev` (Ubuntu/Debian) or `sudo dnf install libusb1-devel` (Fedora)
- Install udev rules for controller and uinput access:
```bash
sudo cp platform/linux/99-gc-controller.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```
- You may need to log out and back in for uinput group permissions to take effect

### macOS
- Install libusb: `brew install libusb`
- Xbox 360 controller emulation is not available on macOS

## Usage

Run the application:
```bash
python gc_controller_enabler.py
```

1. Connect your GameCube controller via USB
2. Click **Connect** to initialize the controller
3. Click **Emulate Xbox 360** to start virtual controller emulation

## Building Executables

Platform-specific build scripts are in the `platform/` directory:

- **Windows**: `platform/windows/build.bat`
- **macOS**: `platform/macos/build.sh`
- **Linux**: `platform/linux/build.sh`

Or use the unified build script:
```bash
python build_all.py
```

## Calibration

Each GameCube controller may have different analog trigger ranges. Configure via the calibration section:

- **Base Value**: Resting trigger position (typically ~32)
- **Bump Value**: Position where trigger "clicks" (typically ~190)
- **Max Value**: Fully pressed position (typically ~230)

Trigger modes:
- **100% at bump**: Full trigger response at the click point
- **100% at press**: Full trigger response at maximum press

## Project Structure

```
gc_controller_enabler.py    Main application
virtual_gamepad.py          Cross-platform gamepad abstraction
gc_controller_enabler.spec  PyInstaller spec file
build_all.py                Unified build script
platform/
  linux/
    build.sh                Linux build script
    99-gc-controller.rules  udev rules for USB/uinput access
  macos/
    build.sh                macOS build script
  windows/
    build.bat               Windows build script
    hook-vgamepad.py        PyInstaller hook for vgamepad
```

## Troubleshooting

### Controller Not Detected
- Ensure the GameCube controller adapter is connected
- Verify Vendor ID `0x057e` and Product ID `0x2073` (check `lsusb` on Linux or Device Manager on Windows)

### Emulation Not Working
- **Windows**: Install [ViGEmBus](https://github.com/nefarius/ViGEmBus) and `pip install vgamepad`
- **Linux**: Install evdev (`pip install evdev`) and ensure `/dev/uinput` is accessible via udev rules
- **macOS**: Not supported

### Permission Errors
- **Windows**: HID access may require administrator privileges
- **Linux**: Install the udev rules and reload:
  ```bash
  sudo cp platform/linux/99-gc-controller.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules
  ```

## License

See the original LICENSE files for details.
