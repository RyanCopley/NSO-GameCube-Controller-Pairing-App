# PyInstaller hook for vgamepad
# This ensures that the ViGEmClient.dll is included in the bundle

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
import os

# Collect all data files from vgamepad
datas = collect_data_files('vgamepad')

# Collect dynamic libraries (DLLs)
binaries = collect_dynamic_libs('vgamepad')

# Ensure we get the ViGEmClient.dll specifically
try:
    import vgamepad
    vgamepad_path = os.path.dirname(vgamepad.__file__)
    
    # Add the vigem DLLs manually
    vigem_client_dll = os.path.join(vgamepad_path, 'win', 'vigem', 'client', 'x64', 'ViGEmClient.dll')
    if os.path.exists(vigem_client_dll):
        binaries.append((vigem_client_dll, 'vgamepad/win/vigem/client/x64/'))
    
    # Add any other DLLs in the vigem directory
    vigem_dir = os.path.join(vgamepad_path, 'win', 'vigem')
    if os.path.exists(vigem_dir):
        for root, dirs, files in os.walk(vigem_dir):
            for file in files:
                if file.endswith('.dll'):
                    dll_path = os.path.join(root, file)
                    rel_path = os.path.relpath(root, vgamepad_path)
                    binaries.append((dll_path, f'vgamepad/{rel_path}/'))

except ImportError:
    pass

# Hidden imports
hiddenimports = [
    'vgamepad.win.vigem_client',
    'vgamepad.win.virtual_gamepad',
    'vgamepad.win.xinput_gamepad',
    'vgamepad.win.ds4_gamepad',
]