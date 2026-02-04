#!/bin/bash
echo "Building GameCube Controller Enabler for Linux..."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create build directory
mkdir -p dist

# Build executable with PyInstaller
echo "Building executable..."
pyinstaller --onefile \
    --name "GC-Controller-Enabler" \
    --icon=controller.png \
    --add-data "controller.png:." \
    --add-data "stick_left.png:." \
    --add-data "stick_right.png:." \
    --hidden-import evdev \
    --hidden-import virtual_gamepad \
    --distpath dist/linux \
    gc_controller_enabler.py

echo "Build complete! Executable is in dist/linux/"
echo ""
echo "Note: On Linux, you need to:"
echo "1. Install libusb: sudo apt-get install libusb-1.0-0-dev (Ubuntu/Debian)"
echo "   or: sudo dnf install libusb1-devel (Fedora)"
echo "2. Copy udev rules: sudo cp 99-gc-controller.rules /etc/udev/rules.d/"
echo "3. Reload udev rules: sudo udevadm control --reload-rules && sudo udevadm trigger"
echo "4. Ensure /dev/uinput is accessible for Xbox 360 emulation (handled by udev rule above)"