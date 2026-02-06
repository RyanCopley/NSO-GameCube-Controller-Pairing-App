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
    --paths src \
    --hidden-import evdev \
    --hidden-import gc_controller.virtual_gamepad \
    --hidden-import gc_controller.controller_constants \
    --hidden-import gc_controller.settings_manager \
    --hidden-import gc_controller.calibration \
    --hidden-import gc_controller.connection_manager \
    --hidden-import gc_controller.emulation_manager \
    --hidden-import gc_controller.controller_ui \
    --hidden-import gc_controller.input_processor \
    --distpath dist/linux \
    src/gc_controller/__main__.py

echo "Build complete! Executable is in dist/linux/"
echo ""
echo "Note: On Linux, you need to:"
echo "1. Install libusb: sudo apt-get install libusb-1.0-0-dev (Ubuntu/Debian)"
echo "   or: sudo dnf install libusb1-devel (Fedora)"
echo "2. Copy udev rules: sudo cp platform/linux/99-gc-controller.rules /etc/udev/rules.d/"
echo "3. Reload udev rules: sudo udevadm control --reload-rules && sudo udevadm trigger"
echo "4. Ensure your user is in the 'input' group: sudo usermod -aG input \$USER"
echo "5. Log out and back in for group changes to take effect"
