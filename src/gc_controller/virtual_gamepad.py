"""
Virtual Gamepad Platform Abstraction Layer

Provides a unified interface for controller emulation across platforms:
- Xbox 360 mode: Windows (vgamepad/ViGEmBus), Linux (python-evdev/uinput)
- Dolphin pipe mode: macOS and Linux (named pipe / FIFO)
"""

import errno
import os
import stat
import sys
import time
import threading
from abc import ABC, abstractmethod
from enum import Enum, auto


_vgamepad_dll_diag = None  # Diagnostic info if DLL pre-load fails


def _setup_vgamepad_dll_path():
    """Pre-load ViGEmClient.dll for vgamepad in frozen PyInstaller builds."""
    global _vgamepad_dll_diag
    if sys.platform != "win32":
        return
    if not getattr(sys, 'frozen', False):
        return

    meipass = getattr(sys, '_MEIPASS', None)
    if not meipass:
        return

    import platform
    import ctypes
    import ctypes.wintypes
    arch = "x64" if platform.architecture()[0] == "64bit" else "x86"
    dll_dir = os.path.join(meipass, 'vgamepad', 'win', 'vigem', 'client', arch)
    dll_path = os.path.join(dll_dir, 'ViGEmClient.dll')

    diag_lines = [f"arch={arch}", f"meipass={meipass}"]
    diag_lines.append(f"dll_path={dll_path}")
    diag_lines.append(f"exists={os.path.isfile(dll_path)}")
    if os.path.isfile(dll_path):
        diag_lines.append(f"size={os.path.getsize(dll_path)}")

    # Add DLL directories to search path
    for d in (meipass, dll_dir):
        try:
            os.add_dll_directory(d)
        except (OSError, AttributeError):
            pass
    os.environ['PATH'] = dll_dir + os.pathsep + meipass + os.pathsep + os.environ.get('PATH', '')

    if not os.path.isfile(dll_path):
        diag_lines.append("DLL file not found")
        _vgamepad_dll_diag = "\n".join(diag_lines)
        return

    # Try loading with different methods
    methods = [
        ("WinDLL+winmode0", lambda: ctypes.WinDLL(dll_path, winmode=0)),
        ("CDLL+winmode0", lambda: ctypes.CDLL(dll_path, winmode=0)),
        ("CDLL_default", lambda: ctypes.CDLL(dll_path)),
        ("LoadLibrary", lambda: ctypes.windll.kernel32.LoadLibraryW(dll_path)),
    ]
    for name, loader in methods:
        try:
            result = loader()
            diag_lines.append(f"{name}=OK (handle={result})")
            _vgamepad_dll_diag = "\n".join(diag_lines)
            return  # Success — DLL is loaded in the process
        except Exception as e:
            diag_lines.append(f"{name}=FAIL: {e}")

    _vgamepad_dll_diag = "\n".join(diag_lines)


_setup_vgamepad_dll_path()


class GamepadButton(Enum):
    """Platform-independent button constants for Xbox 360 controller."""
    A = auto()
    B = auto()
    X = auto()
    Y = auto()
    LEFT_SHOULDER = auto()
    RIGHT_SHOULDER = auto()
    LEFT_THUMB = auto()
    RIGHT_THUMB = auto()
    START = auto()
    BACK = auto()
    GUIDE = auto()
    DPAD_UP = auto()
    DPAD_DOWN = auto()
    DPAD_LEFT = auto()
    DPAD_RIGHT = auto()


class VirtualGamepad(ABC):
    """Abstract base class for virtual Xbox 360 controller emulation."""

    @abstractmethod
    def left_joystick(self, x_value: int, y_value: int) -> None:
        """Set left joystick position. Values in range [-32767, 32767]."""

    @abstractmethod
    def right_joystick(self, x_value: int, y_value: int) -> None:
        """Set right joystick position. Values in range [-32767, 32767]."""

    @abstractmethod
    def left_trigger(self, value: int) -> None:
        """Set left trigger value. Range [0, 255]."""

    @abstractmethod
    def right_trigger(self, value: int) -> None:
        """Set right trigger value. Range [0, 255]."""

    @abstractmethod
    def press_button(self, button: GamepadButton) -> None:
        """Press a button."""

    @abstractmethod
    def release_button(self, button: GamepadButton) -> None:
        """Release a button."""

    @abstractmethod
    def update(self) -> None:
        """Flush buffered events to the virtual device."""

    @abstractmethod
    def reset(self) -> None:
        """Reset all inputs to neutral."""

    @abstractmethod
    def close(self) -> None:
        """Destroy the virtual device and release resources."""

    def set_rumble_callback(self, callback) -> None:
        """Set callback(large_motor: int, small_motor: int) for FF events. Optional."""
        pass

    def stop_rumble_listener(self) -> None:
        """Stop any background rumble listener thread. Called from close()."""
        pass


class WindowsGamepad(VirtualGamepad):
    """Windows implementation using vgamepad (ViGEmBus)."""

    # Map our GamepadButton enum to vgamepad's XUSB_BUTTON constants
    _BUTTON_MAP = None

    def __init__(self):
        import vgamepad as vg
        self._vg = vg
        self._pad = vg.VX360Gamepad()

        if WindowsGamepad._BUTTON_MAP is None:
            WindowsGamepad._BUTTON_MAP = {
                GamepadButton.A: vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                GamepadButton.B: vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                GamepadButton.X: vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                GamepadButton.Y: vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                GamepadButton.LEFT_SHOULDER: vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                GamepadButton.RIGHT_SHOULDER: vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                GamepadButton.LEFT_THUMB: vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
                GamepadButton.RIGHT_THUMB: vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
                GamepadButton.START: vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
                GamepadButton.BACK: vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                GamepadButton.GUIDE: vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
                GamepadButton.DPAD_UP: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
                GamepadButton.DPAD_DOWN: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
                GamepadButton.DPAD_LEFT: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
                GamepadButton.DPAD_RIGHT: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
            }

    def left_joystick(self, x_value: int, y_value: int) -> None:
        self._pad.left_joystick(x_value=x_value, y_value=y_value)

    def right_joystick(self, x_value: int, y_value: int) -> None:
        self._pad.right_joystick(x_value=x_value, y_value=y_value)

    def left_trigger(self, value: int) -> None:
        self._pad.left_trigger(value=value)

    def right_trigger(self, value: int) -> None:
        self._pad.right_trigger(value=value)

    def press_button(self, button: GamepadButton) -> None:
        self._pad.press_button(button=self._BUTTON_MAP[button])

    def release_button(self, button: GamepadButton) -> None:
        self._pad.release_button(button=self._BUTTON_MAP[button])

    def update(self) -> None:
        self._pad.update()

    def reset(self) -> None:
        self._pad.reset()

    def set_rumble_callback(self, callback) -> None:
        def _vg_callback(client, target, large_motor, small_motor, led_number, user_data):
            callback(large_motor, small_motor)
        try:
            self._pad.register_notification(callback_function=_vg_callback)
        except Exception:
            pass  # Rumble not available but emulation still works

    def close(self) -> None:
        try:
            self._pad.reset()
            self._pad.update()
        except Exception:
            pass


class LinuxGamepad(VirtualGamepad):
    """Linux implementation using python-evdev and uinput.

    Creates a virtual Xbox 360 controller (vendor=0x045e, product=0x028e)
    that is recognized by applications as a standard Xbox gamepad.
    """

    def __init__(self):
        import evdev
        from evdev import UInput, AbsInfo, ecodes

        self._ecodes = ecodes
        self._rumble_callback = None
        self._rumble_thread = None
        self._rumble_stop = threading.Event()

        # Capability setup for Xbox 360 controller
        cap = {
            ecodes.EV_ABS: [
                # Left stick
                (ecodes.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                # Right stick
                (ecodes.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (ecodes.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                # Triggers
                (ecodes.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                # D-Pad (hat switch)
                (ecodes.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            ],
            ecodes.EV_KEY: [
                ecodes.BTN_A,
                ecodes.BTN_B,
                ecodes.BTN_X,
                ecodes.BTN_Y,
                ecodes.BTN_TL,      # Left shoulder
                ecodes.BTN_TR,      # Right shoulder
                ecodes.BTN_THUMBL,  # Left thumb
                ecodes.BTN_THUMBR,  # Right thumb
                ecodes.BTN_START,
                ecodes.BTN_SELECT,  # Back
                ecodes.BTN_MODE,    # Guide
            ],
            ecodes.EV_FF: [
                ecodes.FF_RUMBLE,
            ],
        }

        self._device = UInput(
            events=cap,
            name="Microsoft X-Box 360 pad",
            vendor=0x045E,
            product=0x028E,
            version=0x0110,
            bustype=ecodes.BUS_USB,
            max_effects=16,
        )

        # Button mapping: GamepadButton -> evdev key code
        self._button_map = {
            GamepadButton.A: ecodes.BTN_A,
            GamepadButton.B: ecodes.BTN_B,
            GamepadButton.X: ecodes.BTN_X,
            GamepadButton.Y: ecodes.BTN_Y,
            GamepadButton.LEFT_SHOULDER: ecodes.BTN_TL,
            GamepadButton.RIGHT_SHOULDER: ecodes.BTN_TR,
            GamepadButton.LEFT_THUMB: ecodes.BTN_THUMBL,
            GamepadButton.RIGHT_THUMB: ecodes.BTN_THUMBR,
            GamepadButton.START: ecodes.BTN_START,
            GamepadButton.BACK: ecodes.BTN_SELECT,
            GamepadButton.GUIDE: ecodes.BTN_MODE,
        }

        # D-Pad buttons map to hat axes, not key events.
        # Track D-Pad state to handle diagonals correctly.
        self._dpad_x = 0  # -1=left, 0=center, 1=right
        self._dpad_y = 0  # -1=up, 0=center, 1=down

    def left_joystick(self, x_value: int, y_value: int) -> None:
        ec = self._ecodes
        self._device.write(ec.EV_ABS, ec.ABS_X, x_value)
        # Invert Y: callers use positive-up, evdev uses positive-down
        self._device.write(ec.EV_ABS, ec.ABS_Y, -y_value)

    def right_joystick(self, x_value: int, y_value: int) -> None:
        ec = self._ecodes
        self._device.write(ec.EV_ABS, ec.ABS_RX, x_value)
        self._device.write(ec.EV_ABS, ec.ABS_RY, -y_value)

    def left_trigger(self, value: int) -> None:
        self._device.write(self._ecodes.EV_ABS, self._ecodes.ABS_Z, value)

    def right_trigger(self, value: int) -> None:
        self._device.write(self._ecodes.EV_ABS, self._ecodes.ABS_RZ, value)

    def press_button(self, button: GamepadButton) -> None:
        if button in (GamepadButton.DPAD_UP, GamepadButton.DPAD_DOWN,
                      GamepadButton.DPAD_LEFT, GamepadButton.DPAD_RIGHT):
            self._set_dpad(button, pressed=True)
        else:
            code = self._button_map[button]
            self._device.write(self._ecodes.EV_KEY, code, 1)

    def release_button(self, button: GamepadButton) -> None:
        if button in (GamepadButton.DPAD_UP, GamepadButton.DPAD_DOWN,
                      GamepadButton.DPAD_LEFT, GamepadButton.DPAD_RIGHT):
            self._set_dpad(button, pressed=False)
        else:
            code = self._button_map[button]
            self._device.write(self._ecodes.EV_KEY, code, 0)

    def _set_dpad(self, button: GamepadButton, pressed: bool) -> None:
        """Translate D-Pad button press/release to HAT axis values."""
        ec = self._ecodes
        if button == GamepadButton.DPAD_LEFT:
            self._dpad_x = -1 if pressed else (1 if self._dpad_x == 1 else 0)
        elif button == GamepadButton.DPAD_RIGHT:
            self._dpad_x = 1 if pressed else (-1 if self._dpad_x == -1 else 0)
        elif button == GamepadButton.DPAD_UP:
            self._dpad_y = -1 if pressed else (1 if self._dpad_y == 1 else 0)
        elif button == GamepadButton.DPAD_DOWN:
            self._dpad_y = 1 if pressed else (-1 if self._dpad_y == -1 else 0)

        self._device.write(ec.EV_ABS, ec.ABS_HAT0X, self._dpad_x)
        self._device.write(ec.EV_ABS, ec.ABS_HAT0Y, self._dpad_y)

    def update(self) -> None:
        self._device.syn()

    def reset(self) -> None:
        ec = self._ecodes
        # Center sticks
        self._device.write(ec.EV_ABS, ec.ABS_X, 0)
        self._device.write(ec.EV_ABS, ec.ABS_Y, 0)
        self._device.write(ec.EV_ABS, ec.ABS_RX, 0)
        self._device.write(ec.EV_ABS, ec.ABS_RY, 0)
        # Release triggers
        self._device.write(ec.EV_ABS, ec.ABS_Z, 0)
        self._device.write(ec.EV_ABS, ec.ABS_RZ, 0)
        # Release D-Pad
        self._dpad_x = 0
        self._dpad_y = 0
        self._device.write(ec.EV_ABS, ec.ABS_HAT0X, 0)
        self._device.write(ec.EV_ABS, ec.ABS_HAT0Y, 0)
        # Release all buttons
        for code in self._button_map.values():
            self._device.write(ec.EV_KEY, code, 0)
        self._device.syn()

    def set_rumble_callback(self, callback) -> None:
        self._rumble_callback = callback
        self._rumble_stop.clear()
        self._rumble_thread = threading.Thread(
            target=self._rumble_reader, daemon=True)
        self._rumble_thread.start()

    def stop_rumble_listener(self) -> None:
        self._rumble_stop.set()
        self._rumble_thread = None

    def _rumble_reader(self):
        """Background thread: read FF events from the UInput fd.

        The UInput fd receives EV_UINPUT events (upload/erase handshakes)
        and EV_FF events (play/stop) from applications using the virtual
        gamepad.  UInput inherits EventIO.read() which reads from self.fd.
        """
        import select
        from evdev import ecodes

        while not self._rumble_stop.is_set():
            try:
                r, _, _ = select.select([self._device.fd], [], [], 0.1)
                if not r:
                    continue

                for event in self._device.read():
                    if event.type == ecodes.EV_UINPUT:
                        if event.code == ecodes.UI_FF_UPLOAD:
                            upload = self._device.begin_upload(event.value)
                            upload.retval = 0
                            self._device.end_upload(upload)
                        elif event.code == ecodes.UI_FF_ERASE:
                            erase = self._device.begin_erase(event.value)
                            erase.retval = 0
                            self._device.end_erase(erase)
                    elif event.type == ecodes.EV_FF:
                        if self._rumble_callback:
                            if event.value > 0:
                                self._rumble_callback(255, 255)
                            else:
                                self._rumble_callback(0, 0)
            except OSError:
                break
            except Exception:
                if self._rumble_stop.is_set():
                    break

    def close(self) -> None:
        self.stop_rumble_listener()
        try:
            self.reset()
        except Exception:
            pass
        try:
            self._device.close()
        except Exception:
            pass


def _get_real_home() -> str:
    """Get the real user's home directory, even when running under sudo."""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        import pwd
        try:
            return pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            pass
    return os.path.expanduser('~')


_REAL_HOME = _get_real_home()

_FLATPAK_DOLPHIN_DATA = os.path.join(
    _REAL_HOME, '.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu')


def _get_all_dolphin_user_dirs() -> list[str]:
    """Return all detected Dolphin user directories that exist on disk.

    Checks every known location so that pipes are created in all of them,
    regardless of how Dolphin was installed (Flatpak, native package, etc.).
    Uses the real user's home when running under sudo.
    """
    if sys.platform == 'darwin':
        d = os.path.join(_REAL_HOME, 'Library/Application Support/Dolphin')
        return [d] if os.path.isdir(d) else []

    # Linux — collect every directory that exists, deduplicating by realpath.
    candidates: list[str] = []

    env_path = os.environ.get('DOLPHIN_EMU_USERPATH')
    if env_path:
        candidates.append(env_path)

    candidates.append(_FLATPAK_DOLPHIN_DATA)
    candidates.append(os.path.join(_REAL_HOME, '.dolphin-emu'))

    xdg_data = os.environ.get('XDG_DATA_HOME',
                               os.path.join(_REAL_HOME, '.local/share'))
    candidates.append(os.path.join(xdg_data, 'dolphin-emu'))

    seen: set[str] = set()
    result: list[str] = []
    for path in candidates:
        real = os.path.realpath(path)
        if real not in seen and os.path.isdir(path):
            seen.add(real)
            result.append(path)
    return result


def ensure_dolphin_pipe(pipe_name: str = 'gc_controller') -> list[str]:
    """Create the Dolphin named-pipe FIFO in every detected Dolphin user dir.

    Call this early (e.g. at app startup) so the pipe file is visible in
    Dolphin's controller device list before emulation is started.

    Returns a list of all pipe paths that were created / verified.
    """
    user_dirs = _get_all_dolphin_user_dirs()
    if not user_dirs:
        # No existing Dolphin dirs — fall back to XDG default.
        xdg_data = os.environ.get('XDG_DATA_HOME',
                                  os.path.expanduser('~/.local/share'))
        user_dirs = [os.path.join(xdg_data, 'dolphin-emu')]

    pipe_paths: list[str] = []
    for user_dir in user_dirs:
        pipe_dir = os.path.join(user_dir, 'Pipes')
        try:
            os.makedirs(pipe_dir, exist_ok=True)
            pipe_path = os.path.join(pipe_dir, pipe_name)

            if not os.path.exists(pipe_path):
                os.mkfifo(pipe_path)
            elif not stat.S_ISFIFO(os.stat(pipe_path).st_mode):
                continue  # skip non-FIFO files without failing

            pipe_paths.append(pipe_path)
        except OSError:
            continue  # skip dirs we can't write to

    if not pipe_paths:
        raise RuntimeError(
            f"Could not create Dolphin pipe '{pipe_name}' in any "
            "detected Dolphin directory.")

    return pipe_paths


class DolphinPipeGamepad(VirtualGamepad):
    """Dolphin named pipe implementation for macOS and Linux.

    Sends controller input to Dolphin Emulator via a Unix FIFO using
    the Dolphin pipe input protocol.  No virtual HID device or special
    drivers are required.
    """

    _BUTTON_MAP = {
        GamepadButton.A: 'A',
        GamepadButton.B: 'B',
        GamepadButton.X: 'X',
        GamepadButton.Y: 'Y',
        GamepadButton.START: 'START',
        GamepadButton.RIGHT_SHOULDER: 'Z',
        GamepadButton.LEFT_SHOULDER: 'L',
        GamepadButton.DPAD_UP: 'D_UP',
        GamepadButton.DPAD_DOWN: 'D_DOWN',
        GamepadButton.DPAD_LEFT: 'D_LEFT',
        GamepadButton.DPAD_RIGHT: 'D_RIGHT',
    }

    def __init__(self, pipe_name: str = 'gc_controller',
                 cancel_event: threading.Event | None = None):
        pipe_paths = ensure_dolphin_pipe(pipe_name)

        # Poll until Dolphin opens the read end of one of the pipes.
        # With cancel_event, this can be stopped from another thread.
        while True:
            for path in pipe_paths:
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
                    self._pipe_path = path
                    self._pipe = os.fdopen(fd, 'w')
                    self._pressed: set[str] = set()
                    return
                except OSError as e:
                    if e.errno != errno.ENXIO:
                        raise

            if cancel_event is not None and cancel_event.is_set():
                path_list = '\n  '.join(pipe_paths)
                raise OSError(
                    errno.ECANCELED,
                    f"Pipe emulation cancelled.\nPipes:\n  {path_list}")

            time.sleep(0.5)

    def left_joystick(self, x_value: int, y_value: int) -> None:
        x = (x_value / 32767 + 1) / 2
        y = (y_value / 32767 + 1) / 2
        self._pipe.write(f'SET MAIN {x:.4f} {y:.4f}\n')

    def right_joystick(self, x_value: int, y_value: int) -> None:
        x = (x_value / 32767 + 1) / 2
        y = (y_value / 32767 + 1) / 2
        self._pipe.write(f'SET C {x:.4f} {y:.4f}\n')

    def left_trigger(self, value: int) -> None:
        self._pipe.write(f'SET L {value / 255:.4f}\n')

    def right_trigger(self, value: int) -> None:
        self._pipe.write(f'SET R {value / 255:.4f}\n')

    def press_button(self, button: GamepadButton) -> None:
        name = self._BUTTON_MAP.get(button)
        if name is None:
            return
        self._pipe.write(f'PRESS {name}\n')
        self._pressed.add(name)

    def release_button(self, button: GamepadButton) -> None:
        name = self._BUTTON_MAP.get(button)
        if name is None:
            return
        self._pipe.write(f'RELEASE {name}\n')
        self._pressed.discard(name)

    def update(self) -> None:
        self._pipe.flush()

    def reset(self) -> None:
        self._pipe.write('SET MAIN 0.5000 0.5000\n')
        self._pipe.write('SET C 0.5000 0.5000\n')
        self._pipe.write('SET L 0.0000\n')
        self._pipe.write('SET R 0.0000\n')
        for name in list(self._pressed):
            self._pipe.write(f'RELEASE {name}\n')
        self._pressed.clear()
        self._pipe.flush()

    def close(self) -> None:
        try:
            self.reset()
        except Exception:
            pass
        try:
            self._pipe.close()
        except Exception:
            pass


def is_emulation_available(mode: str = 'xbox360') -> bool:
    """Check whether virtual gamepad emulation is available on this platform."""
    if mode == 'dolphin_pipe':
        return sys.platform in ('darwin', 'linux')

    # Xbox 360 mode
    if sys.platform == "win32":
        try:
            import vgamepad
            vgamepad.VX360Gamepad  # verify class is accessible
            return True
        except Exception:
            return False
    elif sys.platform == "linux":
        try:
            import evdev
            return os.access('/dev/uinput', os.W_OK)
        except Exception:
            return False
    else:
        return False


def get_emulation_unavailable_reason(mode: str = 'xbox360') -> str:
    """Return a human-readable explanation of why emulation is unavailable."""
    if mode == 'dolphin_pipe':
        return "Dolphin pipe emulation is only supported on macOS and Linux."

    # Xbox 360 mode
    if sys.platform == "win32":
        # Diagnose which component is missing
        try:
            import vgamepad
            vgamepad.VX360Gamepad
        except ImportError as e:
            return (
                "Xbox 360 emulation requires the vgamepad Python package.\n\n"
                f"Error: {e}\n\n"
                "Install with: pip install vgamepad"
            )
        except OSError as e:
            diag = _vgamepad_dll_diag or "no diagnostics"
            return (
                f"vgamepad failed to load ViGEmClient DLL.\n\n"
                f"Error: {e}\n\n"
                f"Diagnostics:\n{diag}\n\n"
                "Try installing the VC++ Redistributable:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                "And ViGEmBus driver:\n"
                "https://github.com/nefarius/ViGEmBus/releases"
            )
        except Exception as e:
            diag = _vgamepad_dll_diag or "no diagnostics"
            return (
                f"vgamepad failed to initialize.\n\n"
                f"Error: {e}\n\n"
                f"Diagnostics:\n{diag}\n\n"
                "Make sure ViGEmBus driver is installed:\n"
                "https://github.com/nefarius/ViGEmBus/releases"
            )

        # vgamepad imported OK — the problem is likely ViGEmBus driver
        return (
            "Xbox 360 emulation requires the ViGEmBus driver.\n\n"
            "Download and install it from:\n"
            "https://github.com/nefarius/ViGEmBus/releases\n\n"
            "After installing, restart your computer."
        )
    elif sys.platform == "linux":
        return (
            "Xbox 360 emulation requires python-evdev and uinput access.\n"
            "Install evdev: pip install evdev\n"
            "Ensure /dev/uinput is accessible (add udev rule or run as root)."
        )
    elif sys.platform == "darwin":
        return (
            "Xbox 360 controller emulation is not supported on macOS.\n"
            "macOS does not allow user-space creation of virtual HID game controllers."
        )
    else:
        return f"Xbox 360 emulation is not supported on {sys.platform}."


def create_gamepad(mode: str = 'xbox360', slot_index: int = 0,
                   cancel_event: threading.Event | None = None) -> VirtualGamepad:
    """Factory: create the appropriate VirtualGamepad for the current platform/mode."""
    if mode == 'dolphin_pipe':
        pipe_name = f'gc_controller_{slot_index + 1}'
        return DolphinPipeGamepad(pipe_name=pipe_name, cancel_event=cancel_event)

    # Xbox 360 mode
    if sys.platform == "win32":
        return WindowsGamepad()
    elif sys.platform == "linux":
        return LinuxGamepad()
    elif sys.platform == "darwin":
        raise RuntimeError(
            "Xbox 360 controller emulation is not supported on macOS.\n"
            "macOS does not allow user-space creation of virtual HID game controllers.\n"
            "Consider using a hardware adapter or alternative input remapping tool."
        )
    else:
        raise RuntimeError(f"Virtual gamepad emulation is not supported on {sys.platform}.")
