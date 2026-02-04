![](https://github.com/Accolith/GC-controller-enabler/blob/main/Screenshot%202025-07-14%20204357.png)
# GameCube Controller Enabler - Python Version

A Python/Tkinter implementation of the GameCube Controller Enabler tool that allows connecting GameCube controllers via USB to make them usable on Steam and other platforms.

## Features

- **USB Initialization**: Sends required initialization commands to GameCube controllers
- **HID Communication**: Reads controller input via HID interface
- **Xbox 360 Emulation**: Maps GameCube inputs to Xbox 360 controller (Windows via vgamepad, Linux via evdev/uinput)
- **Analog Trigger Calibration**: Configurable trigger ranges for different controller variations
- **Visual Controller Display**: Real-time visualization of button presses, analog sticks, and triggers
- **Settings Persistence**: Save and load calibration settings

## Requirements

- Python 3.7 or higher
- **Windows**: ViGEmBus driver for Xbox 360 emulation
- **Linux**: python-evdev and uinput access for Xbox 360 emulation
- **macOS**: Controller reading works, but Xbox 360 emulation is not supported

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Platform-specific setup:

### Windows
- Install ViGEmBus driver: https://github.com/nefarius/ViGEmBus

### Linux
- Install udev rules for controller and uinput access:
```bash
sudo cp 99-gc-controller.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```
- Install libusb: `sudo apt-get install libusb-1.0-0-dev` (Ubuntu/Debian) or `sudo dnf install libusb1-devel` (Fedora)
- You may need to log out and back in for the uinput group permissions to take effect

### macOS
- Xbox 360 controller emulation is not available on macOS (OS limitation)

## Usage

### Running from Source

1. Run the application:
```bash
python gc_controller_enabler.py
```

### Running Pre-built Executables

Download the appropriate executable for your platform from the releases page, or build your own using the provided build scripts:

- **Windows**: Run `build_windows.bat` → executable in `dist/windows/`
- **macOS**: Run `./build_macos.sh` → executable in `dist/macos/`  
- **Linux**: Run `./build_linux.sh` → executable in `dist/linux/`

See [BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md) for detailed build information.

### Controller Setup

1. Connect your GameCube controller via USB
2. Click "Connect" to initialize the controller
3. Optionally click "Emulate Xbox 360" to start virtual controller emulation

## Calibration

Each GameCube controller may have different analog trigger ranges. The calibration section allows you to configure:

- **Base Value**: Resting trigger position (typically ~32)
- **Bump Value**: Position where trigger "clicks" (typically ~190)
- **Max Value**: Fully pressed position (typically ~230)

### Trigger Modes

- **100% at bump**: Full trigger response at click point
- **100% at press**: Full trigger response at maximum press

To calibrate:
1. Connect your controller
2. Press and release triggers while observing the raw values
3. Enter the observed base, bump, and max values
4. Click "Save Settings" to persist the configuration

## Dependencies

- **hid**: HID device communication
- **pyusb**: USB device initialization
- **vgamepad**: Xbox 360 controller emulation (Windows only, optional)
- **evdev**: Xbox 360 controller emulation (Linux only, optional)

## Troubleshooting

### Controller Not Detected
- Ensure GameCube controller adapter is properly connected
- On Windows, check Device Manager; on Linux, check `lsusb`
- Verify Vendor ID (0x057e) and Product ID (0x2073)

### Emulation Not Working
- **Windows**: Install ViGEmBus driver from Nefarius and `pip install vgamepad`
- **Linux**: Install evdev (`pip install evdev`) and ensure `/dev/uinput` is accessible via udev rules
- **macOS**: Xbox 360 emulation is not supported

### Permission Errors
- On Windows, HID access may require administrator privileges
- On Linux, install the udev rules file and reload: `sudo cp 99-gc-controller.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules`

## Differences from C# Version

- Uses Python's hid library instead of HidLibrary
- Uses pyusb instead of LibUsbDotNet
- Uses vgamepad instead of Nefarius.ViGEm.Client
- Tkinter GUI instead of Windows Forms
- JSON settings file instead of .NET settings

## License

This Python version maintains the same open-source spirit as the original C# implementation. See the original LICENSE files for details.

HidLibrary: MIT License

LibUsbDotNet: GNU Lesser General Public License v3.0

Nefarius.ViGEm.Client: MIT License
