"""
Autostart Manager

Register or unregister the app to start automatically at login.
- Windows: per-user Startup folder launcher.
- Linux: systemd user service or XDG autostart .desktop file.
- macOS: LaunchAgent plist.
"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

_TASK_NAME = "NSO GC Controller"
_LAUNCHAGENT_LABEL = "com.nso.gc-controller"
_WINDOWS_STARTUP_SCRIPT = "NSO GC Controller.vbs"


def _get_exe_path() -> str:
    """Return the path to the current executable or script entry point."""
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


# ── Windows ──────────────────────────────────────────────────────────

def _win_is_enabled() -> bool:
    return os.path.isfile(_win_startup_script_path())


def _win_startup_script_path() -> str:
    startup_dir = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )
    return os.path.join(startup_dir, _WINDOWS_STARTUP_SCRIPT)


def _win_enable_startup_script():
    exe = _get_exe_path()
    path = _win_startup_script_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exe_vbs = exe.replace('"', '""')
    contents = (
        'Set shell = CreateObject("WScript.Shell")\n'
        f'shell.Run """" & "{exe_vbs}" & """ --minimized", 0, False\n'
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(contents)
    logger.info("Windows startup script created: %s", path)


def _win_enable():
    _win_enable_startup_script()


def _win_disable():
    path = _win_startup_script_path()
    if os.path.isfile(path):
        os.remove(path)
        logger.info("Windows startup script removed: %s", path)
    else:
        logger.info("Windows startup script already absent: %s", path)


# ── Linux ────────────────────────────────────────────────────────────

def _linux_autostart_path() -> str:
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg_config, "autostart", "nso-gc-controller.desktop")


def _linux_is_enabled() -> bool:
    return os.path.isfile(_linux_autostart_path())


def _linux_enable():
    exe = _get_exe_path()
    desktop_entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={_TASK_NAME}\n"
        f"Exec={exe} --minimized\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Hidden=false\n"
    )
    path = _linux_autostart_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(desktop_entry)
    logger.info("Linux autostart desktop entry created: %s", path)


def _linux_disable():
    path = _linux_autostart_path()
    if os.path.isfile(path):
        os.remove(path)
        logger.info("Linux autostart desktop entry removed: %s", path)


# ── macOS ────────────────────────────────────────────────────────────

def _mac_plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{_LAUNCHAGENT_LABEL}.plist")


def _mac_is_enabled() -> bool:
    return os.path.isfile(_mac_plist_path())


def _mac_enable():
    exe = _get_exe_path()
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'    <key>Label</key>\n    <string>{_LAUNCHAGENT_LABEL}</string>\n'
        f'    <key>ProgramArguments</key>\n'
        f'    <array>\n        <string>{exe}</string>\n'
        f'        <string>--minimized</string>\n    </array>\n'
        '    <key>RunAtLoad</key>\n    <true/>\n'
        '    <key>KeepAlive</key>\n    <false/>\n'
        '</dict>\n</plist>\n'
    )
    path = _mac_plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(plist)
    logger.info("macOS LaunchAgent created: %s", path)


def _mac_disable():
    path = _mac_plist_path()
    if os.path.isfile(path):
        os.remove(path)
        logger.info("macOS LaunchAgent removed: %s", path)


# ── Public API ───────────────────────────────────────────────────────

def is_enabled() -> bool:
    """Return True if the app is registered to start at login."""
    try:
        if sys.platform == "win32":
            return _win_is_enabled()
        elif sys.platform == "darwin":
            return _mac_is_enabled()
        elif sys.platform == "linux":
            return _linux_is_enabled()
    except Exception as e:
        logger.warning("Failed to check autostart status: %s", e)
    return False


def enable():
    """Register the app to start at login."""
    if sys.platform == "win32":
        _win_enable()
    elif sys.platform == "darwin":
        _mac_enable()
    elif sys.platform == "linux":
        _linux_enable()


def disable():
    """Unregister the app from starting at login."""
    if sys.platform == "win32":
        _win_disable()
    elif sys.platform == "darwin":
        _mac_disable()
    elif sys.platform == "linux":
        _linux_disable()


def set_enabled(enabled: bool):
    """Enable or disable autostart."""
    if enabled:
        enable()
    else:
        disable()
