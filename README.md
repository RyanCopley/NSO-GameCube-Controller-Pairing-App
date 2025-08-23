![](https://github.com/Accolith/GC-controller-enabler/blob/main/Screenshot%202025-07-14%20204357.png)
# GameCube Controller Enabler - Python Version

A Python/Tkinter implementation of the GameCube Controller Enabler tool that allows connecting GameCube controllers via USB to make them usable on Steam and other platforms.

## Features

- **USB Initialization**: Sends required initialization commands to GameCube controllers
- **HID Communication**: Reads controller input via HID interface
- **Xbox 360 Emulation**: Maps GameCube inputs to Xbox 360 controller using vgamepad
- **Analog Trigger Calibration**: Configurable trigger ranges for different controller variations
- **Visual Controller Display**: Real-time visualization of button presses, analog sticks, and triggers
- **Settings Persistence**: Save and load calibration settings

## Requirements

- Python 3.7 or higher
- Windows (for Xbox 360 emulation via ViGEmBus)

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. For Xbox 360 emulation, install ViGEmBus driver:
   - Download from: https://github.com/nefarius/ViGEmBus
   - Install the driver according to their instructions

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
- **vgamepad**: Xbox 360 controller emulation (optional)

## Troubleshooting

### Controller Not Detected
- Ensure GameCube controller adapter is properly connected
- Check that the controller is recognized by Windows Device Manager
- Verify Vendor ID (0x057e) and Product ID (0x2073)

### Emulation Not Working
- Install ViGEmBus driver from Nefarius
- Ensure vgamepad is installed: `pip install vgamepad`
- Run as administrator if needed

### Permission Errors
- On Windows, HID access may require administrator privileges
- Try running the application as administrator

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
