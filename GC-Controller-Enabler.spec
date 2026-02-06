# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/gc_controller/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[('images/controller.png', '.'), ('images/stick_left.png', '.'), ('images/stick_right.png', '.')],
    hiddenimports=['evdev', 'gc_controller.virtual_gamepad', 'gc_controller.controller_constants', 'gc_controller.settings_manager', 'gc_controller.calibration', 'gc_controller.connection_manager', 'gc_controller.emulation_manager', 'gc_controller.controller_ui', 'gc_controller.input_processor'],
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
    name='GC-Controller-Enabler',
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
    icon=['images/controller.png'],
)
