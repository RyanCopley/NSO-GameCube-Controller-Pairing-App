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
if os.path.exists('controller.png'):
    datas.append(('controller.png', '.'))
if os.path.exists('stick_left.png'):
    datas.append(('stick_left.png', '.'))
if os.path.exists('stick_right.png'):
    datas.append(('stick_right.png', '.'))

# Add vgamepad DLLs for Windows
if sys.platform == "win32":
    try:
        import vgamepad
        vgamepad_path = os.path.dirname(vgamepad.__file__)
        vigem_dll_path = os.path.join(vgamepad_path, 'win', 'vigem', 'client', 'x64', 'ViGEmClient.dll')
        if os.path.exists(vigem_dll_path):
            datas.append((vigem_dll_path, 'vgamepad/win/vigem/client/x64/'))
        
        # Also include the entire vigem directory structure
        vigem_dir = os.path.join(vgamepad_path, 'win', 'vigem')
        if os.path.exists(vigem_dir):
            for root, dirs, files in os.walk(vigem_dir):
                for file in files:
                    if file.endswith('.dll'):
                        src_path = os.path.join(root, file)
                        rel_path = os.path.relpath(root, vgamepad_path)
                        datas.append((src_path, f'vgamepad/{rel_path}/'))
    except ImportError:
        pass

# Hidden imports for libraries that might not be detected
hiddenimports = [
    'hid',
    'usb.core',
    'usb.util',
    'virtual_gamepad',
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
    ]
elif sys.platform == "linux":
    hiddenimports += [
        'evdev',
    ]

a = Analysis(
    ['gc_controller_enabler.py'],
    pathex=[],
    binaries=[],
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