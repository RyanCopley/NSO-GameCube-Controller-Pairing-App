# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_all

if sys.platform == "win32":
    icon_file = 'controller.ico'
elif sys.platform == "darwin":
    icon_file = 'controller.icns'
else:
    icon_file = None

# Collect all PyQt6 submodules + data files (plugins, translations, etc.)
pyqt6_datas, pyqt6_binaries, pyqt6_hiddenimports = collect_all("PyQt6")

a = Analysis(
    ['src/gc_controller/__main__.py'],
    pathex=['src'],
    binaries=pyqt6_binaries,
    datas=pyqt6_datas,
    hiddenimports=[
        'PyQt6.QtWidgets', 'PyQt6.QtGui', 'PyQt6.QtCore', 'PyQt6.sip',
        'gc_controller.virtual_gamepad',
        'gc_controller.controller_constants',
        'gc_controller.settings_manager',
        'gc_controller.calibration',
        'gc_controller.connection_manager',
        'gc_controller.emulation_manager',
        'gc_controller.controller_ui',
        'gc_controller.input_processor',
        'gc_controller.ui_theme',
        'gc_controller.ui_controller_canvas',
        'gc_controller.ui_ble_dialog',
        'gc_controller.ui_settings_dialog',
    ] + pyqt6_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NSO-GameCube-Controller-Pairing-App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if icon_file and os.path.exists(icon_file) else None,
)
