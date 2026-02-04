#!/bin/bash
echo "Building GameCube Controller Enabler for macOS..."

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
    --windowed \
    --name "GC-Controller-Enabler" \
    --icon=controller.png \
    --add-data "controller.png:." \
    --add-data "stick_left.png:." \
    --add-data "stick_right.png:." \
    --distpath dist/macos \
    gc_controller_enabler.py

echo "Build complete! Executable is in dist/macos/"
echo ""
echo "Note: On macOS, you may need to:"
echo "1. Install libusb: brew install libusb"
echo "2. Grant USB permissions in System Preferences > Security & Privacy"
echo "3. Xbox 360 emulation requires additional drivers"