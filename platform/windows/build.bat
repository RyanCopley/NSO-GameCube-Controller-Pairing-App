@echo off
echo Building GameCube Controller Enabler for Windows...

REM Build executable with PyInstaller
echo Building executable...
python -m PyInstaller --onefile --windowed --name "GC-Controller-Enabler" --paths src src\gc_controller\__main__.py

echo Build complete! Executable is in dist/
echo.
echo Note: For Xbox 360 emulation, install ViGEmBus driver:
echo https://github.com/nefarius/ViGEmBus
pause