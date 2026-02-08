"""
UI BLE Dialog - BLE Device Picker

Modal dialog for choosing a BLE device from scan results,
styled with PyQt6.
"""

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QPushButton,
    QAbstractItemView, QHeaderView,
)

from . import ui_theme as T


class BLEDevicePickerDialog(QDialog):
    """Modal dialog for choosing a BLE device from a scan result list.

    Shows a table with Name, Address, Signal columns.
    Returns the chosen address or None.
    """

    def __init__(self, parent, devices: list[dict]):
        super().__init__(parent)
        self._result: Optional[str] = None

        self.setWindowTitle("Select BLE Controller")
        self.setModal(True)
        self.setFixedSize(460, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        header = QLabel("Select a controller to connect:")
        header.setStyleSheet(f"color: {T.TEXT_PRIMARY}; font-size: 14px;")
        layout.addWidget(header)

        # Sort by RSSI descending (strongest first)
        sorted_devices = sorted(devices, key=lambda d: d.get('rssi', -999),
                                reverse=True)

        # Table
        self._table = QTableWidget(len(sorted_devices), 3)
        self._table.setHorizontalHeaderLabels(["Name", "Address", "Signal"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)

        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        for row, dev in enumerate(sorted_devices):
            rssi = dev.get('rssi', -999)
            signal = f"{rssi} dBm" if rssi > -999 else "?"
            name = dev.get('name', '') or '(unknown)'

            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(dev['address']))

            signal_item = QTableWidgetItem(signal)
            signal_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, signal_item)

        self._table.cellDoubleClicked.connect(self._on_connect)
        layout.addWidget(self._table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        connect_btn = QPushButton("Connect")
        connect_btn.setProperty("cssClass", "connect-btn")
        connect_btn.setFixedWidth(100)
        connect_btn.clicked.connect(self._on_connect)
        btn_layout.addWidget(connect_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("cssClass", "cancel-btn")
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _on_connect(self):
        row = self._table.currentRow()
        if row >= 0:
            self._result = self._table.item(row, 1).text()
            self.accept()

    def show(self) -> Optional[str]:
        """Show the dialog and block until closed. Returns address or None."""
        self.exec()
        return self._result
