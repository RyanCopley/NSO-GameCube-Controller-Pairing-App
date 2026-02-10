"""
UI Controller Canvas - GameCube Controller Visual

All PNG layers are composited in PIL (fast C code) into a single image.
Only ONE PhotoImage sits on the canvas, plus lightweight geometric items
for triggers and calibration overlays.  This avoids the ~20 stacked
transparent-PNG canvas items that caused severe lag on Windows GDI.
"""

import math
import os
import sys
import tkinter as tk
from typing import Optional

from PIL import Image, ImageTk

from . import ui_theme as T
from .controller_constants import normalize

# ── Asset paths ───────────────────────────────────────────────────────
_MODULE_DIR = os.path.dirname(__file__)
if hasattr(sys, '_MEIPASS'):
    _ASSETS_DIR = os.path.join(sys._MEIPASS, "gc_controller", "assets", "controller")
else:
    _ASSETS_DIR = os.path.join(_MODULE_DIR, "assets", "controller")


class GCControllerVisual:
    """Draws and manages a GameCube controller visual using PIL compositing."""

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
    CSTICK_IMG_MOVE = 16            # max px offset for C-stick image tilt

    # ── Trigger bar geometry (positioned above controller image) ──────
    TRIGGER_L_X, TRIGGER_L_Y = 45, 2
    TRIGGER_R_X, TRIGGER_R_Y = 345, 2
    TRIGGER_W = 130
    TRIGGER_H = 20

    # ── Player LED geometry (between L/R trigger bars) ────────────────
    LED_SIZE = 6
    LED_GAP = 4
    LED_COUNT = 4
    _LED_TOTAL_W = LED_COUNT * LED_SIZE + (LED_COUNT - 1) * LED_GAP  # 36
    LED_START_X = (CANVAS_W - _LED_TOTAL_W) // 2   # centered
    LED_Y = TRIGGER_L_Y + (TRIGGER_H - LED_SIZE) // 2  # vertically centered with triggers
    LED_COLOR_OFF = '#1a1a1a'
    LED_COLOR_ON = '#00e050'

    # ── Button name → SVG layer ID for pressed overlays ───────────────
    # Layers rendered BELOW the body in the SVG (body occludes parts of them).
    _UNDER_BODY_MAP = {
        'R':  'R',
        'Z':  'Z',
        'L':  'L',
        'ZL': 'Zl',
    }
    # SVG order for under-body compositing
    _UNDER_BODY_ORDER = ['R', 'Z', 'L', 'ZL']

    # Layers ON or ABOVE the body in the SVG.
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

    # All above-body SVG layer IDs in SVG order (for body composite)
    _BODY_COMPOSITE_LAYERS = [
        'Base', 'char', 'home', 'capture', 'startpause',
        'dleft', 'ddown', 'dright', 'dup',
        'x', 'y', 'B', 'A',
    ]

    def __init__(self, parent, **kwargs):
        self.canvas = tk.Canvas(
            parent,
            width=self.CANVAS_W,
            height=self.CANVAS_H,
            bg=T.GC_PURPLE_DARK,
            highlightthickness=0,
            **kwargs,
        )

        self._calibrating = False

        # Current visual state
        self._btn_states = {}           # button_name → bool
        self._lstick_pos = (0.0, 0.0)   # normalized (x, y)
        self._cstick_pos = (0.0, 0.0)
        self._dirty = False             # True when composite needs rebuild

        self._load_pil_images()
        self._create_canvas_items()

    # ── Image loading ────────────────────────────────────────────────

    def _load_pil_images(self):
        """Load all layer images as PIL Image objects for compositing."""
        # Under-body layers: normal and pressed (PIL images)
        self._pil_under_normal = {}
        self._pil_under_pressed = {}
        for btn_name, layer_id in self._UNDER_BODY_MAP.items():
            self._pil_under_normal[btn_name] = Image.open(
                os.path.join(_ASSETS_DIR, f"{layer_id}.png")).convert('RGBA')
            self._pil_under_pressed[btn_name] = Image.open(
                os.path.join(_ASSETS_DIR, f"{layer_id}_pressed.png")).convert('RGBA')

        # Body composite: alpha-composite all on/above-body layers once
        first_layer = Image.open(os.path.join(_ASSETS_DIR, "Base.png"))
        self._img_size = first_layer.size
        body = Image.new('RGBA', self._img_size, (0, 0, 0, 0))
        for layer_id in self._BODY_COMPOSITE_LAYERS:
            layer_img = Image.open(
                os.path.join(_ASSETS_DIR, f"{layer_id}.png")).convert('RGBA')
            body = Image.alpha_composite(body, layer_img)
        self._body_pil = body

        # Stick cap images
        self._pil_sticks = {}
        for layer_id in ('lefttoggle', 'C'):
            self._pil_sticks[layer_id] = Image.open(
                os.path.join(_ASSETS_DIR, f"{layer_id}.png")).convert('RGBA')

        # Above-body pressed overlays
        self._pil_above_pressed = {}
        for btn_name, layer_id in self._ABOVE_BODY_MAP.items():
            self._pil_above_pressed[btn_name] = Image.open(
                os.path.join(_ASSETS_DIR, f"{layer_id}_pressed.png")).convert('RGBA')

        # Pre-composite the idle frame (no buttons pressed, sticks centered)
        self._idle_frame = self._composite_frame({}, (0, 0), (0, 0))

    def _composite_frame(self, btn_states, lstick_px, cstick_px):
        """Build a complete controller image from current state via PIL.

        Args:
            btn_states: dict of button_name → bool (pressed).
            lstick_px: (dx, dy) pixel offset for left stick cap.
            cstick_px: (dx, dy) pixel offset for c-stick cap.
        """
        img = Image.new('RGBA', self._img_size, (0, 0, 0, 0))

        # 1. Under-body layers (normal or pressed)
        for btn_name in self._UNDER_BODY_ORDER:
            if btn_states.get(btn_name):
                img = Image.alpha_composite(img, self._pil_under_pressed[btn_name])
            else:
                img = Image.alpha_composite(img, self._pil_under_normal[btn_name])

        # 2. Body composite
        img = Image.alpha_composite(img, self._body_pil)

        # 3. Stick caps (shifted if stick is tilted)
        for stick_id, offset in [('lefttoggle', lstick_px), ('C', cstick_px)]:
            stick = self._pil_sticks[stick_id]
            if not self._calibrating:
                dx, dy = offset
                if dx == 0 and dy == 0:
                    img = Image.alpha_composite(img, stick)
                else:
                    shifted = Image.new('RGBA', self._img_size, (0, 0, 0, 0))
                    shifted.paste(stick, (dx, dy), stick)
                    img = Image.alpha_composite(img, shifted)

        # 4. Above-body pressed overlays
        for btn_name in self._ABOVE_BODY_MAP:
            if btn_states.get(btn_name):
                img = Image.alpha_composite(img, self._pil_above_pressed[btn_name])

        return img

    # ── Canvas item creation ────────────────────────────────────────
    # Only ONE image item + lightweight geometric overlays.

    def _create_canvas_items(self):
        """Create canvas items: single composited image + geometric overlays."""
        # 1. Single composited controller image
        self._display_photo = ImageTk.PhotoImage(self._idle_frame)
        self._display_item = self.canvas.create_image(
            0, self.IMG_Y_OFFSET, anchor='nw',
            image=self._display_photo,
            tags='controller_img',
        )

        # 2. Trigger fill bars (lightweight canvas rectangles)
        self._draw_triggers()

        # 3. Player LED indicators (between trigger bars)
        self._draw_leds()

        # 4. Calibration octagons and dots (hidden in normal mode)
        self._draw_sticks()

    def _draw_triggers(self):
        """Draw L/R trigger fill bars above the shoulder bumpers."""
        for side, bx, by in [('L', self.TRIGGER_L_X, self.TRIGGER_L_Y),
                              ('R', self.TRIGGER_R_X, self.TRIGGER_R_Y)]:
            tw, th = self.TRIGGER_W, self.TRIGGER_H

            # Background bar
            self._rounded_rect(bx, by, bx + tw, by + th, 4,
                               fill=T.TRIGGER_BG, outline='#333',
                               width=1, tags=f'trigger_{side}_bg')
            # Fill bar (zero width initially)
            self.canvas.create_rectangle(
                bx + 2, by + 2, bx + 2, by + th - 2,
                fill=T.TRIGGER_FILL, outline='',
                tags=f'trigger_{side}_fill',
            )
            # Label
            self.canvas.create_text(
                bx + tw / 2, by + th / 2,
                text=side, fill=T.TEXT_PRIMARY,
                font=("", 12, "bold"),
                tags=f'trigger_{side}_text',
            )

    def _draw_leds(self):
        """Draw 4 player LED indicator squares between the trigger bars."""
        self._led_items = []
        for i in range(self.LED_COUNT):
            x = self.LED_START_X + i * (self.LED_SIZE + self.LED_GAP)
            y = self.LED_Y
            item = self.canvas.create_rectangle(
                x, y, x + self.LED_SIZE, y + self.LED_SIZE,
                fill=self.LED_COLOR_OFF, outline='#333', width=1,
                tags=f'led_{i}',
            )
            self._led_items.append(item)

    def _draw_sticks(self):
        """Draw stick octagon outlines and movable position dots."""
        dr = self.STICK_DOT_RADIUS

        for tag, cx, cy, gate_r, dot_color in [
            ('lstick', self.LSTICK_CX, self.LSTICK_CY,
             self.STICK_GATE_RADIUS, T.STICK_DOT),
            ('cstick', self.CSTICK_CX, self.CSTICK_CY,
             self.CSTICK_GATE_RADIUS, T.CSTICK_YELLOW),
        ]:
            # Reference 100% octagon (dashed, shows max range in calibration)
            ref_coords = []
            for i in range(8):
                angle = math.radians(i * 45)
                ref_coords.append(cx + math.cos(angle) * gate_r)
                ref_coords.append(cy - math.sin(angle) * gate_r)
            ref_item = self.canvas.create_polygon(
                ref_coords, outline=T.STICK_OCTAGON, fill='',
                width=1, dash=(4, 4),
                tags=(f'{tag}_ref', 'cal_item'),
            )
            if not self._calibrating:
                self.canvas.itemconfigure(ref_item, state='hidden')

            # Calibrated octagon outline (hidden in normal mode via cal_item tag)
            self._draw_octagon_shape(tag, cx, cy, gate_r, None)

            # Stick position dot (hidden in normal mode via cal_item tag)
            item = self.canvas.create_oval(
                cx - dr, cy - dr, cx + dr, cy + dr,
                fill=dot_color, outline='',
                tags=(f'{tag}_dot', 'cal_item'),
            )
            if not self._calibrating:
                self.canvas.itemconfigure(item, state='hidden')

    # ── Drawing primitives ────────────────────────────────────────────

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        """Draw a rounded rectangle on the canvas."""
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **kw)

    def _draw_octagon_shape(self, stick_tag, cx, cy, radius, octagon_data,
                            color=None, line_tag=None):
        """Draw an octagon polygon inside a stick gate."""
        tag = line_tag or f'{stick_tag}_octagon'
        self.canvas.delete(tag)

        if color is None:
            color = T.STICK_OCTAGON

        if octagon_data:
            coords = []
            for x_norm, y_norm in octagon_data:
                coords.append(cx + x_norm * radius)
                coords.append(cy - y_norm * radius)
        else:
            coords = []
            for i in range(8):
                angle = math.radians(i * 45)
                coords.append(cx + math.cos(angle) * radius)
                coords.append(cy - math.sin(angle) * radius)

        item = self.canvas.create_polygon(
            coords, outline=color, fill='', width=2, tags=(tag, 'cal_item'),
        )
        if not self._calibrating:
            self.canvas.itemconfigure(item, state='hidden')

    # ── Internal rendering ───────────────────────────────────────────

    def _refresh_display(self):
        """Re-composite all layers and update the single canvas image."""
        lstick_px = (round(self._lstick_pos[0] * self.STICK_IMG_MOVE),
                     round(-self._lstick_pos[1] * self.STICK_IMG_MOVE))
        cstick_px = (round(self._cstick_pos[0] * self.CSTICK_IMG_MOVE),
                     round(-self._cstick_pos[1] * self.CSTICK_IMG_MOVE))
        frame = self._composite_frame(self._btn_states, lstick_px, cstick_px)
        self._display_photo.paste(frame)

    # ── Public API ────────────────────────────────────────────────────

    def update_button_states(self, button_states: dict):
        """Update pressed button state. Call flush() after all updates.

        Args:
            button_states: dict mapping button name → bool (pressed).
        """
        if button_states != self._btn_states:
            self._btn_states = button_states
            self._dirty = True

    def update_stick_position(self, side: str, x_norm: float, y_norm: float):
        """Update stick position state. Call flush() after all updates.

        Args:
            side: 'left' or 'right' (C-stick).
            x_norm: normalized X in [-1, 1].
            y_norm: normalized Y in [-1, 1].
        """
        x_norm = max(-1.0, min(1.0, x_norm))
        y_norm = max(-1.0, min(1.0, y_norm))

        if side == 'left':
            if self._lstick_pos != (x_norm, y_norm):
                self._lstick_pos = (x_norm, y_norm)
                self._dirty = True
        else:
            if self._cstick_pos != (x_norm, y_norm):
                self._cstick_pos = (x_norm, y_norm)
                self._dirty = True

        # Update calibration dot position (lightweight canvas oval)
        if side == 'left':
            cx, cy = self.LSTICK_CX, self.LSTICK_CY
            r = self.STICK_GATE_RADIUS
            dot_tag = 'lstick_dot'
        else:
            cx, cy = self.CSTICK_CX, self.CSTICK_CY
            r = self.CSTICK_GATE_RADIUS
            dot_tag = 'cstick_dot'

        dr = self.STICK_DOT_RADIUS
        x_pos = cx + x_norm * r
        y_pos = cy - y_norm * r
        self.canvas.coords(dot_tag,
                           x_pos - dr, y_pos - dr,
                           x_pos + dr, y_pos + dr)

    def update_player_leds(self, player_num: int):
        """Update player LED indicators.

        Args:
            player_num: 0 = all off, 1–4 = that LED lit.
        """
        for i in range(self.LED_COUNT):
            color = self.LED_COLOR_ON if (i + 1) <= player_num else self.LED_COLOR_OFF
            self.canvas.itemconfigure(self._led_items[i], fill=color)

    def update_trigger_fill(self, side: str, value_0_255: int):
        """Fill trigger bar proportionally.

        Args:
            side: 'left' or 'right'.
            value_0_255: raw trigger value 0–255.
        """
        tw = self.TRIGGER_W

        if side == 'left':
            tag = 'trigger_L_fill'
            bx, by = self.TRIGGER_L_X, self.TRIGGER_L_Y
        else:
            tag = 'trigger_R_fill'
            bx, by = self.TRIGGER_R_X, self.TRIGGER_R_Y

        th = self.TRIGGER_H
        fill_w = (value_0_255 / 255.0) * (tw - 4)
        self.canvas.coords(tag,
                           bx + 2, by + 2,
                           bx + 2 + fill_w, by + th - 2)

    def flush(self):
        """Re-composite and display if anything changed since last flush."""
        if self._dirty:
            self._dirty = False
            self._refresh_display()

    def draw_trigger_bump_line(self, side: str, bump_raw: float):
        """Draw a vertical marker line on the trigger bar at the bump threshold.

        Args:
            side: 'left' or 'right'.
            bump_raw: raw bump value (0–255).
        """
        tw = self.TRIGGER_W
        if side == 'left':
            tag = 'trigger_L_bump'
            bx, by = self.TRIGGER_L_X, self.TRIGGER_L_Y
        else:
            tag = 'trigger_R_bump'
            bx, by = self.TRIGGER_R_X, self.TRIGGER_R_Y

        self.canvas.delete(tag)
        th = self.TRIGGER_H
        x = bx + 2 + (bump_raw / 255.0) * (tw - 4)
        self.canvas.create_line(
            x, by + 1, x, by + th - 1,
            fill=T.TRIGGER_BUMP_LINE, width=2, tags=tag,
        )

    def draw_octagon(self, side: str, octagon_data, color: Optional[str] = None):
        """Draw a calibration octagon in the stick area.

        Args:
            side: 'left' or 'right'.
            octagon_data: list of (x_norm, y_norm) pairs, or None for default.
            color: override color, or None for default.
        """
        if side == 'left':
            tag = 'lstick'
            cx, cy = self.LSTICK_CX, self.LSTICK_CY
            r = self.STICK_GATE_RADIUS
        else:
            tag = 'cstick'
            cx, cy = self.CSTICK_CX, self.CSTICK_CY
            r = self.CSTICK_GATE_RADIUS

        self._draw_octagon_shape(tag, cx, cy, r, octagon_data, color=color)
        self.canvas.tag_raise(f'{tag}_dot')

    def draw_octagon_live(self, side: str, dists, points, cx_raw, rx, cy_raw, ry):
        """Draw an in-progress calibration octagon from raw data.

        Args:
            side: 'left' or 'right'.
            dists: list of 8 distances.
            points: list of 8 (raw_x, raw_y) tuples.
            cx_raw, rx, cy_raw, ry: calibration center/range values.
        """
        if not self._calibrating:
            return

        if side == 'left':
            tag = 'lstick'
            canvas_cx, canvas_cy = self.LSTICK_CX, self.LSTICK_CY
            r = self.STICK_GATE_RADIUS
        else:
            tag = 'cstick'
            canvas_cx, canvas_cy = self.CSTICK_CX, self.CSTICK_CY
            r = self.CSTICK_GATE_RADIUS

        live_tag = f'{tag}_octagon'
        self.canvas.delete(live_tag)

        coords = []
        for i in range(8):
            dist = dists[i]
            if dist > 0:
                raw_x, raw_y = points[i]
                x_norm = normalize(raw_x, cx_raw, rx)
                y_norm = normalize(raw_y, cy_raw, ry)
            else:
                x_norm = 0.0
                y_norm = 0.0
            coords.append(canvas_cx + x_norm * r)
            coords.append(canvas_cy - y_norm * r)

        self.canvas.create_polygon(
            coords, outline=T.STICK_OCTAGON_LIVE, fill='', width=2,
            tags=(live_tag, 'cal_item'),
        )
        self.canvas.tag_raise(f'{tag}_dot')

    def set_calibration_mode(self, enabled: bool):
        """Toggle between calibration view (octagons/dots) and graphic view (stick images)."""
        self._calibrating = enabled
        if enabled:
            # Remove stale calibration octagons so only reference + dot show
            self.canvas.delete('lstick_octagon')
            self.canvas.delete('cstick_octagon')
            self.canvas.itemconfigure('cal_item', state='normal')
        else:
            self.canvas.itemconfigure('cal_item', state='hidden')
        # Re-render (sticks hidden/shown in calibration mode)
        self._refresh_display()

    def reset(self):
        """Reset all elements to default (unpressed, centered sticks, empty triggers)."""
        self._calibrating = False
        self.canvas.itemconfigure('cal_item', state='hidden')

        # Reset visual state
        self._btn_states = {}
        self._lstick_pos = (0.0, 0.0)
        self._cstick_pos = (0.0, 0.0)

        # Re-render with idle frame
        self._display_photo.paste(self._idle_frame)

        # Center calibration dots
        for side in ('left', 'right'):
            self.update_stick_position(side, 0.0, 0.0)

        # Empty triggers
        self.update_trigger_fill('left', 0)
        self.update_trigger_fill('right', 0)

        # Turn off all player LEDs
        self.update_player_leds(0)

    def grid(self, **kwargs):
        """Proxy grid() to the underlying canvas."""
        self.canvas.grid(**kwargs)

    def pack(self, **kwargs):
        """Proxy pack() to the underlying canvas."""
        self.canvas.pack(**kwargs)

    def place(self, **kwargs):
        """Proxy place() to the underlying canvas."""
        self.canvas.place(**kwargs)
