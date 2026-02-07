@echo off
echo Building GameCube Controller Enabler for Windows...

REM Build executable with PyInstaller using the project spec file
echo Building executable...
python -m PyInstaller --distpath dist\windows gc_controller_enabler.spec

echo Build complete! Executable is in dist/
echo.
echo Note: For Xbox 360 emulation, install ViGEmBus driver:
echo https://github.com/nefarius/ViGEmBus
pause