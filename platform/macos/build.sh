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
    --icon=images/controller.png \
    --add-data "images/controller.png:." \
    --add-data "images/stick_left.png:." \
    --add-data "images/stick_right.png:." \
    --paths src \
    --hidden-import gc_controller.virtual_gamepad \
    --hidden-import gc_controller.controller_constants \
    --hidden-import gc_controller.settings_manager \
    --hidden-import gc_controller.calibration \
    --hidden-import gc_controller.connection_manager \
    --hidden-import gc_controller.emulation_manager \
    --hidden-import gc_controller.controller_ui \
    --hidden-import gc_controller.input_processor \
    --distpath dist/macos \
    src/gc_controller/__main__.py

echo "Build complete! Executable is in dist/macos/"
echo ""
echo "Note: On macOS, you may need to:"
echo "1. Install libusb: brew install libusb"
echo "2. Grant USB permissions in System Preferences > Security & Privacy"
echo "3. Xbox 360 emulation requires additional drivers"