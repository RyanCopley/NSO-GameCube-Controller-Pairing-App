# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_all

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

# Collect all customtkinter submodules + data files (themes, fonts, icons).
# PyInstaller's auto-discovery of the customtkinter hook is unreliable on
# macOS/Windows, so we explicitly collect everything here.
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")

# Collect pystray and its dependencies
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all("pystray")

# On Linux, collect GObject Introspection typelib files for the AppIndicator
# tray backend. PyInstaller's gi hooks bundle the .typelib data automatically
# when we collect_all the relevant gi subpackages.
gi_datas = []
gi_binaries = []
gi_hiddenimports = []
if sys.platform == "linux":
    try:
        _gi_datas, _gi_binaries, _gi_hiddenimports = collect_all("gi")
        gi_datas = _gi_datas
        gi_binaries = _gi_binaries
        gi_hiddenimports = _gi_hiddenimports
    except Exception:
        pass  # gi not available — will fall back to XOrg backend

# Data files to include
datas = ctk_datas + pystray_datas + gi_datas
binaries = ctk_binaries + pystray_binaries + gi_binaries
if os.path.exists(os.path.join('images', 'controller.png')):
    datas.append((os.path.join('images', 'controller.png'), '.'))
if os.path.exists(os.path.join('images', 'stick_left.png')):
    datas.append((os.path.join('images', 'stick_left.png'), '.'))
if os.path.exists(os.path.join('images', 'stick_right.png')):
    datas.append((os.path.join('images', 'stick_right.png'), '.'))

# Window/taskbar icon (bundled into _MEIPASS root for runtime use)
if os.path.exists('controller.ico'):
    datas.append(('controller.ico', '.'))
if os.path.exists('controller.png'):
    datas.append(('controller.png', '.'))

# Bundled font
_font_path = os.path.join('src', 'gc_controller', 'fonts', 'VarelaRound-Regular.ttf')
if os.path.exists(_font_path):
    datas.append((_font_path, os.path.join('gc_controller', 'fonts')))

# Bundled controller PNG assets
_assets_dir = os.path.join('src', 'gc_controller', 'assets', 'controller')
if os.path.isdir(_assets_dir):
    for f in os.listdir(_assets_dir):
        if f.endswith('.png'):
            datas.append((os.path.join(_assets_dir, f),
                          os.path.join('gc_controller', 'assets', 'controller')))

# Add vgamepad DLLs for Windows as binaries (not datas) so PyInstaller
# resolves their transitive dependencies (MSVC runtime, etc.)
# NOTE: We must NOT 'import vgamepad' here because that triggers CDLL()
# loading of ViGEmClient.dll, which fails on CI (no ViGEmBus driver).
# Instead, locate the package directory without importing it.
if sys.platform == "win32":
    try:
        import importlib.util
        _spec = importlib.util.find_spec('vgamepad')
        if _spec and _spec.submodule_search_locations:
            vgamepad_path = _spec.submodule_search_locations[0]
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
    'PIL._tkinter_finder',
    # pystray — dynamic backend selection requires explicit imports
    'pystray',
    'pystray._base',
    'pystray._util',
    'six',
] + ctk_hiddenimports + pystray_hiddenimports + gi_hiddenimports

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
        # pystray win32 backend
        'pystray._win32',
        'pystray._util.win32',
    ]
elif sys.platform == "darwin":
    hiddenimports += [
        'bleak',
        'gc_controller.ble',
        'gc_controller.ble.bleak_backend',
        'gc_controller.ble.bleak_subprocess',
        'gc_controller.ble.sw2_protocol',
        # pystray macOS backend (requires pyobjc-framework-Cocoa)
        'pystray._darwin',
        'AppKit',
        'Foundation',
        'objc',
        'PyObjCTools',
        'PyObjCTools.MachSignals',
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
        # pystray AppIndicator backend (requires python3-gi + gir1.2-appindicator3-0.1)
        'pystray._appindicator',
        'pystray._util.gtk',
        'pystray._xorg',  # fallback if AppIndicator unavailable
        'gi',
        'gi.repository.Gtk',
        'gi.repository.GLib',
        'gi.repository.GObject',
        'gi.repository.GdkPixbuf',
        'gi.repository.AppIndicator3',
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
    name='NSO-GameCube-Controller-Pairing-App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['ViGEmClient.dll'],
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
        name='NSO-GameCube-Controller-Pairing-App.app',
        icon=icon_file if icon_file and os.path.exists(icon_file) else None,
        bundle_identifier='com.nso.gamecube-controller-pairing-app',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'NSHighResolutionCapable': True,
            'LSUIElement': False,
            'NSRequiresAquaSystemAppearance': False,
        },
    )