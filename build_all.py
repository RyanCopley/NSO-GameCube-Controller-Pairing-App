#!/usr/bin/env python3
"""
Cross-platform build script for GameCube Controller Enabler
Automatically detects the platform and builds the appropriate executable
"""

import os
import sys
import subprocess
import platform
import shutil

def run_command(cmd, shell=True):
    """Run a command and return success status"""
    try:
        result = subprocess.run(cmd, shell=shell, check=True, capture_output=True, text=True)
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        print(f"Output: {e.stdout}")
        print(f"Error: {e.stderr}")
        return False

def build_executable():
    """Build executable for current platform"""
    print(f"Building for {platform.system()} ({platform.machine()})")
    
    # Determine platform-specific settings
    system = platform.system().lower()
    
    if system == "windows":
        output_dir = "dist/windows"
        script_name = "build_windows.bat"
    elif system == "darwin":
        output_dir = "dist/macos"
        script_name = "./build_macos.sh"
    elif system == "linux":
        output_dir = "dist/linux"
        script_name = "./build_linux.sh"
    else:
        print(f"Unsupported platform: {system}")
        return False
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Check if build script exists
    if os.path.exists(script_name):
        print(f"Running platform-specific build script: {script_name}")
        if system == "windows":
            return run_command(script_name)
        else:
            # Make sure script is executable
            os.chmod(script_name, 0o755)
            return run_command(script_name)
    else:
        # Fallback to direct PyInstaller build
        print("Platform-specific script not found, using direct PyInstaller build...")
        return build_with_pyinstaller(output_dir)

def build_with_pyinstaller(output_dir):
    """Build using PyInstaller directly"""
    
    print("Building with PyInstaller...")
    # Use python -m PyInstaller for better compatibility
    cmd = [
        "python", "-m", "PyInstaller",
        "--onefile",
        "--windowed" if platform.system() != "Linux" else "",
        "--name", "GC-Controller-Enabler",
        "--distpath", output_dir,
        "gc_controller_enabler.py"
    ]
    # Remove empty strings
    cmd = [c for c in cmd if c]
    cmd = " ".join(cmd)
    
    return run_command(cmd)

def check_dependencies():
    """Check if required dependencies are installed"""
    print("Checking dependencies...")
    
    # Check Python version
    if sys.version_info < (3, 7):
        print("Error: Python 3.7 or higher is required")
        return False
    
    # Check if PyInstaller is available
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("Installing PyInstaller...")
        if not run_command("pip install pyinstaller"):
            print("Failed to install PyInstaller")
            return False
    
    # Check main dependencies
    required_packages = ["tkinter", "threading", "json"]
    if platform.system().lower() == "windows":
        optional_packages = ["hid", "usb", "vgamepad"]
    elif platform.system().lower() == "linux":
        optional_packages = ["hid", "usb", "evdev"]
    else:
        optional_packages = ["hid", "usb"]
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"✗ {package} - Required dependency missing")
            return False
    
    for package in optional_packages:
        try:
            __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"⚠ {package} - Optional dependency missing (some features may not work)")
    
    return True

def main():
    """Main build function"""
    print("GameCube Controller Enabler - Build Script")
    print("=" * 50)
    
    # Change to script directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Check dependencies
    if not check_dependencies():
        print("Dependency check failed. Please install required packages.")
        return 1
    
    # Build executable
    if build_executable():
        print("\n" + "=" * 50)
        print("Build completed successfully!")
        
        # Show output location
        system = platform.system().lower()
        if system == "windows":
            output_dir = "dist/windows"
        elif system == "darwin":
            output_dir = "dist/macos"
        else:
            output_dir = "dist/linux"
        
        if os.path.exists(output_dir):
            print(f"Executable location: {os.path.abspath(output_dir)}")
            files = os.listdir(output_dir)
            print(f"Files created: {files}")
        
        print("\nNext steps:")
        print("1. Test the executable on a clean system")
        print("2. Check that all features work correctly")
        if system == "windows":
            print("3. Ensure ViGEmBus driver is installed for Xbox 360 emulation")
        elif system == "darwin":
            print("3. Grant USB permissions if needed")
        elif system == "linux":
            print("3. Set up udev rules for USB access")
        
        return 0
    else:
        print("\nBuild failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())