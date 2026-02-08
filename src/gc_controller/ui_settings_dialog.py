"""
UI Settings Dialog - Global Settings

Modal dialog for global settings: emulation mode, trigger mode,
auto-connect, start/stop emulation, and test rumble.
"""

import sys
import webbrowser
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QCheckBox, QButtonGroup,
    QFrame,
)

from . import ui_theme as T

IS_MACOS = sys.platform == "darwin"


class SettingsDialog(QDialog):
    """Modal settings dialog accessible via the gear icon."""

    def __init__(self, parent,
                 emu_mode: str,
                 trigger_bump_100: bool,
                 auto_connect: bool,
                 minimize_to_tray: bool,
                 on_emulate_all: Callable,
                 on_test_rumble_all: Callable,
                 is_any_emulating: Callable[[], bool],
                 is_any_connected: Callable[[], bool] = lambda: False,
                 on_save: Optional[Callable] = None):
        super().__init__(parent)
        self._on_emulate_all = on_emulate_all
        self._on_test_rumble_all = on_test_rumble_all
        self._is_any_emulating = is_any_emulating
        self._is_any_connected = is_any_connected
        self._on_save = on_save

        # Result values (updated when save is clicked)
        self.result_emu_mode = emu_mode
        self.result_trigger_bump_100 = trigger_bump_100
        self.result_auto_connect = auto_connect
        self.result_minimize_to_tray = minimize_to_tray

        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setFixedSize(520, 380)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        # ═══ LEFT COLUMN — Settings ═══
        left = QVBoxLayout()
        left.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Emulation Mode
        lbl = QLabel("Emulation Mode")
        lbl.setStyleSheet(f"font-family: '{T.FONT_FAMILY}'; font-size: 16px; font-weight: bold;")
        left.addWidget(lbl)

        self._emu_group = QButtonGroup(self)
        self._xbox_radio = QRadioButton("Xbox 360")
        self._dolphin_radio = QRadioButton("Dolphin Pipe")
        self._emu_group.addButton(self._xbox_radio)
        self._emu_group.addButton(self._dolphin_radio)

        if IS_MACOS:
            self._xbox_radio.setEnabled(False)
        if emu_mode == 'xbox360':
            self._xbox_radio.setChecked(True)
        else:
            self._dolphin_radio.setChecked(True)

        left.addWidget(self._xbox_radio)
        left.addWidget(self._dolphin_radio)

        # Trigger Mode
        left.addSpacing(8)
        lbl2 = QLabel("Trigger Mode")
        lbl2.setStyleSheet(f"font-family: '{T.FONT_FAMILY}'; font-size: 16px; font-weight: bold;")
        left.addWidget(lbl2)

        self._trigger_group = QButtonGroup(self)
        self._trigger_bump_radio = QRadioButton("100% at bump")
        self._trigger_press_radio = QRadioButton("100% at press")
        self._trigger_group.addButton(self._trigger_bump_radio)
        self._trigger_group.addButton(self._trigger_press_radio)

        if trigger_bump_100:
            self._trigger_bump_radio.setChecked(True)
        else:
            self._trigger_press_radio.setChecked(True)

        left.addWidget(self._trigger_bump_radio)
        left.addWidget(self._trigger_press_radio)

        # Auto-connect
        left.addSpacing(8)
        self._auto_connect_cb = QCheckBox("Auto-connect USB at startup")
        self._auto_connect_cb.setChecked(auto_connect)
        left.addWidget(self._auto_connect_cb)

        # Minimize to tray
        self._minimize_tray_cb = QCheckBox("Minimize to system tray")
        self._minimize_tray_cb.setChecked(minimize_to_tray)
        left.addWidget(self._minimize_tray_cb)

        # Save button
        left.addSpacing(8)
        save_btn = QPushButton("Save")
        save_btn.setProperty("cssClass", "settings-btn")
        save_btn.setFixedSize(220, 36)
        save_btn.clicked.connect(self._on_save_click)
        left.addWidget(save_btn)

        outer.addLayout(left)

        # Vertical separator
        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setProperty("cssClass", "vsep")
        outer.addWidget(vsep)

        # ═══ RIGHT COLUMN — Actions & About ═══
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignTop)

        any_connected = self._is_any_connected()
        emu_text = "Stop Emulation" if self._is_any_emulating() else "Start Emulation"

        self._emulate_btn = QPushButton(emu_text)
        self._emulate_btn.setProperty("cssClass", "settings-action")
        self._emulate_btn.setFixedSize(220, 36)
        self._emulate_btn.setEnabled(any_connected)
        self._emulate_btn.clicked.connect(self._on_emulate_click)
        right.addWidget(self._emulate_btn)

        self._rumble_btn = QPushButton("Test Rumble")
        self._rumble_btn.setProperty("cssClass", "settings-action")
        self._rumble_btn.setFixedSize(220, 36)
        self._rumble_btn.setEnabled(any_connected)
        self._rumble_btn.clicked.connect(self._on_test_rumble_all)
        right.addWidget(self._rumble_btn)

        # Separator
        right.addSpacing(8)
        hsep = QFrame()
        hsep.setFrameShape(QFrame.Shape.HLine)
        hsep.setProperty("cssClass", "hsep")
        right.addWidget(hsep)
        right.addSpacing(4)

        # About
        about_lbl = QLabel("About")
        about_lbl.setStyleSheet(f"font-family: '{T.FONT_FAMILY}'; font-size: 16px; font-weight: bold;")
        right.addWidget(about_lbl)

        src_link = QLabel(
            '<a href="https://github.com/RyanCopley/NSO-GameCube-Controller-Pairing-App"'
            f' style="color: {T.TEXT_SECONDARY};">Source Code on GitHub</a>')
        src_link.setOpenExternalLinks(True)
        right.addWidget(src_link)

        credits_lbl = QLabel("Credits & Special Thanks")
        credits_lbl.setStyleSheet(
            f"font-family: '{T.FONT_FAMILY}'; font-size: 14px; font-weight: bold;")
        right.addWidget(credits_lbl)

        credits = [
            ("GVNPWRS/NSO-GC-Controller-PC", "https://github.com/GVNPWRS/NSO-GC-Controller-PC"),
            ("Nohzockt/Switch2-Controllers", "https://github.com/Nohzockt/Switch2-Controllers"),
            ("isaacs-12/nso-gc-bridge", "https://github.com/isaacs-12/nso-gc-bridge"),
            ("darthcloud/BlueRetro", "https://github.com/darthcloud/BlueRetro"),
        ]
        for label_text, url in credits:
            lbl = QLabel(
                f'<a href="{url}" style="color: {T.TEXT_SECONDARY};">{label_text}</a>')
            lbl.setOpenExternalLinks(True)
            lbl.setContentsMargins(12, 0, 0, 0)
            right.addWidget(lbl)

        right.addStretch()
        outer.addLayout(right)

    def _on_save_click(self):
        self.result_emu_mode = 'xbox360' if self._xbox_radio.isChecked() else 'dolphin_pipe'
        self.result_trigger_bump_100 = self._trigger_bump_radio.isChecked()
        self.result_auto_connect = self._auto_connect_cb.isChecked()
        self.result_minimize_to_tray = self._minimize_tray_cb.isChecked()
        if self._on_save:
            self._on_save()
        self.accept()

    def _on_emulate_click(self):
        self._on_emulate_all()
        emu_text = "Stop Emulation" if self._is_any_emulating() else "Start Emulation"
        self._emulate_btn.setText(emu_text)
