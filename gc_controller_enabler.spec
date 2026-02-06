# -*- mode: python ; coding: utf-8 -*-

import sys
import os

# Determine if we're building for Windows, macOS, or Linux
if sys.platform == "win32":
    icon_file = 'controller.ico'
    console = False
elif sys.platform == "darwin":
    icon_file = 'controller.icns'
    console = False
else:  # Linux and other Unix-like systems
    icon_file = None
    console = False

block_cipher = None

# Data files to include
datas = []
binaries = []
if os.path.exists(os.path.join('images', 'controller.png')):
    datas.append((os.path.join('images', 'controller.png'), '.'))
if os.path.exists(os.path.join('images', 'stick_left.png')):
    datas.append((os.path.join('images', 'stick_left.png'), '.'))
if os.path.exists(os.path.join('images', 'stick_right.png')):
    datas.append((os.path.join('images', 'stick_right.png'), '.'))

# Add vgamepad DLLs for Windows as binaries (not datas) so PyInstaller
# resolves their transitive dependencies (MSVC runtime, etc.)
if sys.platform == "win32":
    try:
        import vgamepad
        vgamepad_path = os.path.dirname(vgamepad.__file__)
        vigem_dir = os.path.join(vgamepad_path, 'win', 'vigem')
        if os.path.exists(vigem_dir):
            for root, dirs, files in os.walk(vigem_dir):
                for file in files:
                    if file.endswith('.dll'):
                        src_path = os.path.join(root, file)
                        rel_path = os.path.relpath(root, vgamepad_path)
                        binaries.append((src_path, f'vgamepad/{rel_path}/'))
    except Exception:
        pass

# Hidden imports for libraries that might not be detected
hiddenimports = [
    'hid',
    'usb.core',
    'usb.util',
    'gc_controller.virtual_gamepad',
    'gc_controller.controller_constants',
    'gc_controller.settings_manager',
    'gc_controller.calibration',
    'gc_controller.connection_manager',
    'gc_controller.emulation_manager',
    'gc_controller.controller_ui',
    'gc_controller.input_processor',
    'tkinter',
    'tkinter.ttk',
    '_tkinter',
]

# Platform-conditional hidden imports
if sys.platform == "win32":
    hiddenimports += [
        'vgamepad',
        'vgamepad.win',
        'vgamepad.win.vigem_client',
        'vgamepad.win.virtual_gamepad',
        'bleak',
        'gc_controller.ble',
        'gc_controller.ble.bleak_backend',
        'gc_controller.ble.bleak_subprocess',
        'gc_controller.ble.sw2_protocol',
    ]
elif sys.platform == "darwin":
    hiddenimports += [
        'bleak',
        'gc_controller.ble',
        'gc_controller.ble.bleak_backend',
        'gc_controller.ble.bleak_subprocess',
        'gc_controller.ble.sw2_protocol',
    ]
elif sys.platform == "linux":
    hiddenimports += [
        'evdev',
        'bumble',
        'bumble.device',
        'bumble.hci',
        'bumble.pairing',
        'bumble.transport',
        'bumble.smp',
        'bumble.gatt',
        'gc_controller.ble',
        'gc_controller.ble.bumble_backend',
        'gc_controller.ble.ble_subprocess',
        'gc_controller.ble.sw2_protocol',
    ]

a = Analysis(
    ['src/gc_controller/__main__.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GC-Controller-Enabler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if icon_file and os.path.exists(icon_file) else None,
)

# For macOS, create an app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name='GC-Controller-Enabler.app',
        icon=icon_file if icon_file and os.path.exists(icon_file) else None,
        bundle_identifier='com.gccontroller.enabler',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'NSHighResolutionCapable': True,
            'LSUIElement': False,
            'NSRequiresAquaSystemAppearance': False,
        },
    )