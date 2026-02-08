"""
UI Controller Canvas - GameCube Controller Visual

Draws a GameCube controller using pre-rendered PNG layers from the SVG source.
Button presses are shown by swapping to lightened overlay images.
Sticks and triggers are drawn as QPainter overlays on top of the images.
"""

import math
import os
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF, QFont
from PyQt6.QtWidgets import QWidget

from . import ui_theme as T
from .controller_constants import normalize

# ── Asset paths ───────────────────────────────────────────────────────
_MODULE_DIR = os.path.dirname(__file__)
if hasattr(sys, '_MEIPASS'):
    _ASSETS_DIR = os.path.join(sys._MEIPASS, "gc_controller", "assets", "controller")
else:
    _ASSETS_DIR = os.path.join(_MODULE_DIR, "assets", "controller")


class GCControllerVisual(QWidget):
    """Draws and manages a GameCube controller visual using pre-rendered PNG layers."""

    CANVAS_W = 520
    CANVAS_H = 396              # 372 image + 24px headroom for trigger bars
    IMG_Y_OFFSET = 24           # shift controller images down to make room

    # ── Stick geometry (SVG coords scaled to canvas: factor ≈ 0.39) ──
    LSTICK_CX, LSTICK_CY = 97, 140 + 24
    CSTICK_CX, CSTICK_CY = 345, 260 + 24

    STICK_GATE_RADIUS = 30      # left stick movement range (SVG r=76 scaled)
    CSTICK_GATE_RADIUS = 23     # c-stick movement range (SVG r=59.7 scaled)
    STICK_DOT_RADIUS = 5
    STICK_IMG_MOVE = 8              # max px offset for left stick image tilt
    CSTICK_IMG_MOVE = 6             # max px offset for C-stick image tilt

    # ── Trigger bar geometry (positioned above controller image) ──────
    TRIGGER_L_X, TRIGGER_L_Y = 45, 2
    TRIGGER_R_X, TRIGGER_R_Y = 345, 2
    TRIGGER_W = 130
    TRIGGER_H = 20

    # ── Button name → SVG layer ID for pressed overlays ───────────────
    _UNDER_BODY_MAP = {
        'R':  'R',
        'Z':  'Z',
        'L':  'L',
        'ZL': 'Zl',
    }
    _UNDER_BODY_ORDER = ['R', 'Z', 'L', 'ZL']

    _ABOVE_BODY_MAP = {
        'A':           'A',
        'B':           'B',
        'X':           'x',
        'Y':           'y',
        'Start/Pause': 'startpause',
        'Home':        'home',
        'Capture':     'capture',
        'Chat':        'char',
        'Dpad Up':     'dup',
        'Dpad Down':   'ddown',
        'Dpad Left':   'dleft',
        'Dpad Right':  'dright',
    }

    _BODY_COMPOSITE_LAYERS = [
        'Base', 'char', 'home', 'capture', 'startpause',
        'dleft', 'ddown', 'dright', 'dup',
        'x', 'y', 'B', 'A',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.CANVAS_W, self.CANVAS_H)

        # State
        self._button_states = {}
        self._lstick_x, self._lstick_y = 0.0, 0.0
        self._cstick_x, self._cstick_y = 0.0, 0.0
        self._trigger_l_fill = 0
        self._trigger_r_fill = 0
        self._calibrating = False

        # Calibration octagon data
        self._lstick_octagon = None   # list of (x_norm, y_norm) or None
        self._cstick_octagon = None
        self._lstick_octagon_live = None
        self._cstick_octagon_live = None

        # Trigger bump marker positions (0-255 raw)
        self._trigger_l_bump = None
        self._trigger_r_bump = None

        # Load images
        self._under_normal_pixmaps = {}
        self._under_pressed_pixmaps = {}
        self._body_pixmap = None
        self._lstick_pixmap = None
        self._cstick_pixmap = None
        self._above_pressed_pixmaps = {}

        self._load_images()

    def _load_images(self):
        """Load all layer images from the assets directory."""
        # Under-body layers: normal and pressed
        for btn_name, layer_id in self._UNDER_BODY_MAP.items():
            normal_path = os.path.join(_ASSETS_DIR, f"{layer_id}.png")
            pressed_path = os.path.join(_ASSETS_DIR, f"{layer_id}_pressed.png")
            self._under_normal_pixmaps[btn_name] = QPixmap(normal_path)
            self._under_pressed_pixmaps[btn_name] = QPixmap(pressed_path)

        # Body composite: alpha-composite all on/above-body layers
        first_layer = QImage(os.path.join(_ASSETS_DIR, "Base.png"))
        body = QImage(first_layer.size(), QImage.Format.Format_ARGB32_Premultiplied)
        body.fill(QColor(0, 0, 0, 0))
        painter = QPainter(body)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for layer_id in self._BODY_COMPOSITE_LAYERS:
            layer_path = os.path.join(_ASSETS_DIR, f"{layer_id}.png")
            layer_img = QImage(layer_path)
            painter.drawImage(0, 0, layer_img)
        painter.end()
        self._body_pixmap = QPixmap.fromImage(body)

        # Stick cap images
        self._lstick_pixmap = QPixmap(os.path.join(_ASSETS_DIR, "lefttoggle.png"))
        self._cstick_pixmap = QPixmap(os.path.join(_ASSETS_DIR, "C.png"))

        # Above-body pressed overlays
        for btn_name, layer_id in self._ABOVE_BODY_MAP.items():
            pressed_path = os.path.join(_ASSETS_DIR, f"{layer_id}_pressed.png")
            self._above_pressed_pixmaps[btn_name] = QPixmap(pressed_path)

    def paintEvent(self, event):
        """Draw the entire controller visual."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Background
        p.fillRect(self.rect(), QColor(T.GC_PURPLE_DARK))

        oy = self.IMG_Y_OFFSET

        # 2. Under-body layers (L, R, Z, ZL)
        for btn_name in self._UNDER_BODY_ORDER:
            is_pressed = self._button_states.get(btn_name, False)
            if is_pressed:
                p.drawPixmap(0, oy, self._under_pressed_pixmaps[btn_name])
            else:
                p.drawPixmap(0, oy, self._under_normal_pixmaps[btn_name])

        # 3. Body composite
        p.drawPixmap(0, oy, self._body_pixmap)

        # 4. Stick cap images (hidden during calibration)
        if not self._calibrating:
            dx = self._lstick_x * self.STICK_IMG_MOVE
            dy = -self._lstick_y * self.STICK_IMG_MOVE
            p.drawPixmap(int(dx), oy + int(dy), self._lstick_pixmap)

            dx = self._cstick_x * self.CSTICK_IMG_MOVE
            dy = -self._cstick_y * self.CSTICK_IMG_MOVE
            p.drawPixmap(int(dx), oy + int(dy), self._cstick_pixmap)

        # 5. Pressed overlays for above-body buttons
        for btn_name, pixmap in self._above_pressed_pixmaps.items():
            if self._button_states.get(btn_name, False):
                p.drawPixmap(0, oy, pixmap)

        # 6. Trigger bars
        self._paint_triggers(p)

        # 7. Calibration elements (only when calibrating)
        if self._calibrating:
            self._paint_calibration(p)

        p.end()

    def _paint_triggers(self, p: QPainter):
        """Draw L/R trigger fill bars."""
        for side, bx, by, fill_val, bump_val in [
            ('L', self.TRIGGER_L_X, self.TRIGGER_L_Y, self._trigger_l_fill, self._trigger_l_bump),
            ('R', self.TRIGGER_R_X, self.TRIGGER_R_Y, self._trigger_r_fill, self._trigger_r_bump),
        ]:
            tw, th = self.TRIGGER_W, self.TRIGGER_H

            # Background rounded rect
            p.setPen(QPen(QColor('#333'), 1))
            p.setBrush(QColor(T.TRIGGER_BG))
            p.drawRoundedRect(QRectF(bx, by, tw, th), 4, 4)

            # Fill bar
            fill_w = (fill_val / 255.0) * (tw - 4)
            if fill_w > 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(T.TRIGGER_FILL))
                p.drawRect(QRectF(bx + 2, by + 2, fill_w, th - 4))

            # Bump marker line
            if bump_val is not None:
                x = bx + 2 + (bump_val / 255.0) * (tw - 4)
                p.setPen(QPen(QColor(T.TRIGGER_BUMP_LINE), 2))
                p.drawLine(QPointF(x, by + 1), QPointF(x, by + th - 1))

            # Label
            p.setPen(QColor(T.TEXT_PRIMARY))
            font = QFont(T.FONT_FAMILY, 12)
            font.setBold(True)
            p.setFont(font)
            p.drawText(QRectF(bx, by, tw, th), Qt.AlignmentFlag.AlignCenter, side)

    def _paint_calibration(self, p: QPainter):
        """Draw calibration octagons and position dots."""
        for tag, cx, cy, gate_r, dot_color, octagon_data, live_data in [
            ('lstick', self.LSTICK_CX, self.LSTICK_CY, self.STICK_GATE_RADIUS,
             T.STICK_DOT, self._lstick_octagon, self._lstick_octagon_live),
            ('cstick', self.CSTICK_CX, self.CSTICK_CY, self.CSTICK_GATE_RADIUS,
             T.CSTICK_YELLOW, self._cstick_octagon, self._cstick_octagon_live),
        ]:
            # Reference 100% octagon (dashed)
            ref_points = []
            for i in range(8):
                angle = math.radians(i * 45)
                ref_points.append(QPointF(
                    cx + math.cos(angle) * gate_r,
                    cy - math.sin(angle) * gate_r))
            pen = QPen(QColor(T.STICK_OCTAGON), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(QPolygonF(ref_points))

            # Calibrated octagon
            if octagon_data:
                oct_points = []
                for x_norm, y_norm in octagon_data:
                    oct_points.append(QPointF(
                        cx + x_norm * gate_r,
                        cy - y_norm * gate_r))
                p.setPen(QPen(QColor(T.STICK_OCTAGON), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(QPolygonF(oct_points))

            # Live octagon (in-progress calibration)
            if live_data:
                live_points = []
                for x_norm, y_norm in live_data:
                    live_points.append(QPointF(
                        cx + x_norm * gate_r,
                        cy - y_norm * gate_r))
                p.setPen(QPen(QColor(T.STICK_OCTAGON_LIVE), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(QPolygonF(live_points))

            # Position dot
            if tag == 'lstick':
                x_norm, y_norm = self._lstick_x, self._lstick_y
            else:
                x_norm, y_norm = self._cstick_x, self._cstick_y
            dr = self.STICK_DOT_RADIUS
            dot_x = cx + x_norm * gate_r
            dot_y = cy - y_norm * gate_r
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(dot_color))
            p.drawEllipse(QPointF(dot_x, dot_y), dr, dr)

    # ── Public API ────────────────────────────────────────────────────

    def update_button_states(self, button_states: dict):
        """Show/hide pressed button overlays."""
        self._button_states = dict(button_states)
        self.update()

    def update_stick_position(self, side: str, x_norm: float, y_norm: float):
        """Move a stick to the given normalized position."""
        x_norm = max(-1.0, min(1.0, x_norm))
        y_norm = max(-1.0, min(1.0, y_norm))
        if side == 'left':
            self._lstick_x = x_norm
            self._lstick_y = y_norm
        else:
            self._cstick_x = x_norm
            self._cstick_y = y_norm
        self.update()

    def update_trigger_fill(self, side: str, value_0_255: int):
        """Fill trigger bar proportionally."""
        if side == 'left':
            self._trigger_l_fill = value_0_255
        else:
            self._trigger_r_fill = value_0_255
        self.update()

    def draw_trigger_bump_line(self, side: str, bump_raw: float):
        """Draw a vertical marker line on the trigger bar at the bump threshold."""
        if side == 'left':
            self._trigger_l_bump = bump_raw
        else:
            self._trigger_r_bump = bump_raw
        self.update()

    def draw_octagon(self, side: str, octagon_data, color: Optional[str] = None):
        """Draw a calibration octagon in the stick area."""
        if side == 'left':
            self._lstick_octagon = octagon_data
        else:
            self._cstick_octagon = octagon_data
        self.update()

    def draw_octagon_live(self, side: str, dists, points, cx_raw, rx, cy_raw, ry):
        """Draw an in-progress calibration octagon from raw data."""
        if side == 'left':
            canvas_cx, canvas_cy = self.LSTICK_CX, self.LSTICK_CY
            r = self.STICK_GATE_RADIUS
        else:
            canvas_cx, canvas_cy = self.CSTICK_CX, self.CSTICK_CY
            r = self.CSTICK_GATE_RADIUS

        live_data = []
        for i in range(8):
            dist = dists[i]
            if dist > 0:
                raw_x, raw_y = points[i]
                x_norm = normalize(raw_x, cx_raw, rx)
                y_norm = normalize(raw_y, cy_raw, ry)
            else:
                x_norm = 0.0
                y_norm = 0.0
            live_data.append((x_norm, y_norm))

        if side == 'left':
            self._lstick_octagon_live = live_data
        else:
            self._cstick_octagon_live = live_data
        self.update()

    def set_calibration_mode(self, enabled: bool):
        """Toggle between calibration view and graphic view."""
        self._calibrating = enabled
        if enabled:
            self._lstick_octagon_live = None
            self._cstick_octagon_live = None
        self.update()

    def reset(self):
        """Reset all elements to default state."""
        self._calibrating = False
        self._button_states = {}
        self._lstick_x = self._lstick_y = 0.0
        self._cstick_x = self._cstick_y = 0.0
        self._trigger_l_fill = 0
        self._trigger_r_fill = 0
        self._lstick_octagon_live = None
        self._cstick_octagon_live = None
        self.update()
