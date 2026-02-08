"""
UI Controller Canvas - GameCube Controller Visual

Draws a GameCube controller using pre-rendered PNG layers from the SVG source.
Button presses are shown by swapping to lightened overlay images.
Sticks and triggers are drawn as canvas overlays on top of the images.
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
    # Layers rendered BELOW the body in the SVG (body occludes parts of them).
    # These need separate normal + pressed images swapped underneath the body.
    _UNDER_BODY_MAP = {
        'R':  'R',
        'Z':  'Z',
        'L':  'L',
        'ZL': 'Zl',
    }
    # SVG order for under-body compositing
    _UNDER_BODY_ORDER = ['R', 'Z', 'L', 'ZL']

    # Layers ON or ABOVE the body in the SVG.
    # Pressed overlays sit above the body image.
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

        # Keep references to PhotoImage objects to prevent GC
        self._photos = {}
        self._pressed_photos = {}
        # Canvas item IDs for pressed overlays (above-body buttons)
        self._pressed_items = {}
        # Canvas item IDs for under-body layers: normal + pressed
        self._under_normal_items = {}
        self._under_pressed_items = {}

        self._calibrating = False

        # Dirty-tracking: cache previous state to skip redundant canvas ops
        self._prev_buttons = {}      # button_name → bool
        self._prev_lstick = (None, None)
        self._prev_cstick = (None, None)
        self._prev_ltrigger = None
        self._prev_rtrigger = None

        self._load_images()
        self._create_canvas_items()

    # ── Image loading ────────────────────────────────────────────────

    def _load_images(self):
        """Load all layer images from the assets directory."""
        # Under-body layers: load both normal and pressed
        for btn_name, layer_id in self._UNDER_BODY_MAP.items():
            normal_path = os.path.join(_ASSETS_DIR, f"{layer_id}.png")
            pressed_path = os.path.join(_ASSETS_DIR, f"{layer_id}_pressed.png")
            self._photos[f'{btn_name}_normal'] = ImageTk.PhotoImage(
                Image.open(normal_path))
            self._pressed_photos[btn_name] = ImageTk.PhotoImage(
                Image.open(pressed_path))

        # Body composite: alpha-composite all on/above-body layers
        # Use the actual PNG dimensions (not canvas, which includes headroom)
        first_layer = Image.open(os.path.join(_ASSETS_DIR, "Base.png"))
        body = Image.new('RGBA', first_layer.size, (0, 0, 0, 0))
        for layer_id in self._BODY_COMPOSITE_LAYERS:
            layer_path = os.path.join(_ASSETS_DIR, f"{layer_id}.png")
            layer_img = Image.open(layer_path).convert('RGBA')
            body = Image.alpha_composite(body, layer_img)
        self._photos['body'] = ImageTk.PhotoImage(body)

        # Stick cap images (separate movable layers)
        for layer_id in ('lefttoggle', 'C'):
            path = os.path.join(_ASSETS_DIR, f"{layer_id}.png")
            self._photos[f'stick_{layer_id}'] = ImageTk.PhotoImage(
                Image.open(path).convert('RGBA'))

        # Above-body layers: load pressed versions only
        for btn_name, layer_id in self._ABOVE_BODY_MAP.items():
            pressed_path = os.path.join(_ASSETS_DIR, f"{layer_id}_pressed.png")
            self._pressed_photos[btn_name] = ImageTk.PhotoImage(
                Image.open(pressed_path))

    # ── Canvas item creation ────────────────────────────────────────
    # Z-order: under-body (normal+pressed) → body → above-body overlays
    #          → triggers → sticks

    def _create_canvas_items(self):
        """Create all canvas items in the correct layer order."""
        # 1. Under-body layers (L, R, Z, ZL) — normal shown, pressed hidden
        #    The body image will occlude the parts that should be hidden.
        oy = self.IMG_Y_OFFSET
        for btn_name in self._UNDER_BODY_ORDER:
            normal_item = self.canvas.create_image(
                0, oy, anchor='nw',
                image=self._photos[f'{btn_name}_normal'],
                tags=f'under_{btn_name}_normal',
            )
            pressed_item = self.canvas.create_image(
                0, oy, anchor='nw',
                image=self._pressed_photos[btn_name],
                state='hidden',
                tags=f'under_{btn_name}_pressed',
            )
            self._under_normal_items[btn_name] = normal_item
            self._under_pressed_items[btn_name] = pressed_item

        # 2. Body composite (Base + all on-body elements, occludes shoulders)
        self.canvas.create_image(
            0, oy, anchor='nw',
            image=self._photos['body'],
            tags='body_img',
        )

        # 3. Movable stick cap images (shown in normal mode, hidden in calibration)
        self.canvas.create_image(
            0, oy, anchor='nw',
            image=self._photos['stick_lefttoggle'],
            tags=('lstick_img', 'normal_item'),
        )
        self.canvas.create_image(
            0, oy, anchor='nw',
            image=self._photos['stick_C'],
            tags=('cstick_img', 'normal_item'),
        )

        # 4. Pressed overlays for above-body buttons (hidden initially)
        for btn_name in self._ABOVE_BODY_MAP:
            item = self.canvas.create_image(
                0, oy, anchor='nw',
                image=self._pressed_photos[btn_name],
                state='hidden',
                tags=f'pressed_{btn_name}',
            )
            self._pressed_items[btn_name] = item

        # 5. Trigger fill bars (above everything so always visible)
        self._draw_triggers()

        # 6. Stick octagons and dots (topmost layer, hidden in normal mode)
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

    # ── Public API ────────────────────────────────────────────────────

    def update_button_states(self, button_states: dict):
        """Show/hide pressed button overlays (only updates changed buttons).

        Args:
            button_states: dict mapping button name → bool (pressed).
        """
        prev = self._prev_buttons

        for name, is_pressed in button_states.items():
            # Skip if unchanged from last frame
            if prev.get(name) == is_pressed:
                continue

            if name in self._under_normal_items:
                if is_pressed:
                    self.canvas.itemconfigure(
                        self._under_normal_items[name], state='hidden')
                    self.canvas.itemconfigure(
                        self._under_pressed_items[name], state='normal')
                else:
                    self.canvas.itemconfigure(
                        self._under_normal_items[name], state='normal')
                    self.canvas.itemconfigure(
                        self._under_pressed_items[name], state='hidden')
            elif name in self._pressed_items:
                self.canvas.itemconfigure(
                    self._pressed_items[name],
                    state='normal' if is_pressed else 'hidden')

        self._prev_buttons = button_states

    # Minimum change in normalized stick value to trigger a canvas update.
    # 2/4096 ≈ 0.0005 — filters sub-pixel jitter without adding visible lag.
    _STICK_EPSILON = 0.005

    def update_stick_position(self, side: str, x_norm: float, y_norm: float):
        """Move a stick dot and stick image to the given normalized position.

        Args:
            side: 'left' or 'right' (C-stick).
            x_norm: normalized X in [-1, 1].
            y_norm: normalized Y in [-1, 1].
        """
        x_norm = max(-1.0, min(1.0, x_norm))
        y_norm = max(-1.0, min(1.0, y_norm))

        # Skip update if stick hasn't moved enough
        if side == 'left':
            prev = self._prev_lstick
        else:
            prev = self._prev_cstick
        if (prev[0] is not None
                and abs(x_norm - prev[0]) < self._STICK_EPSILON
                and abs(y_norm - prev[1]) < self._STICK_EPSILON):
            return
        if side == 'left':
            self._prev_lstick = (x_norm, y_norm)
            cx, cy = self.LSTICK_CX, self.LSTICK_CY
            r = self.STICK_GATE_RADIUS
            dot_tag = 'lstick_dot'
            img_tag = 'lstick_img'
            img_move = self.STICK_IMG_MOVE
        else:
            self._prev_cstick = (x_norm, y_norm)
            cx, cy = self.CSTICK_CX, self.CSTICK_CY
            r = self.CSTICK_GATE_RADIUS
            dot_tag = 'cstick_dot'
            img_tag = 'cstick_img'
            img_move = self.CSTICK_IMG_MOVE

        # Move calibration dot
        dr = self.STICK_DOT_RADIUS
        x_pos = cx + x_norm * r
        y_pos = cy - y_norm * r

        self.canvas.coords(dot_tag,
                           x_pos - dr, y_pos - dr,
                           x_pos + dr, y_pos + dr)

        # Move stick cap image (slight tilt effect)
        self.canvas.coords(img_tag,
                           x_norm * img_move,
                           self.IMG_Y_OFFSET - y_norm * img_move)

    def update_trigger_fill(self, side: str, value_0_255: int):
        """Fill trigger bar proportionally.

        Args:
            side: 'left' or 'right'.
            value_0_255: raw trigger value 0–255.
        """
        # Skip if unchanged
        if side == 'left':
            if self._prev_ltrigger == value_0_255:
                return
            self._prev_ltrigger = value_0_255
            tag = 'trigger_L_fill'
            bx, by = self.TRIGGER_L_X, self.TRIGGER_L_Y
        else:
            if self._prev_rtrigger == value_0_255:
                return
            self._prev_rtrigger = value_0_255
            tag = 'trigger_R_fill'
            bx, by = self.TRIGGER_R_X, self.TRIGGER_R_Y

        tw = self.TRIGGER_W
        th = self.TRIGGER_H
        fill_w = (value_0_255 / 255.0) * (tw - 4)
        self.canvas.coords(tag,
                           bx + 2, by + 2,
                           bx + 2 + fill_w, by + th - 2)

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
            self.canvas.itemconfigure('normal_item', state='hidden')
        else:
            self.canvas.itemconfigure('cal_item', state='hidden')
            self.canvas.itemconfigure('normal_item', state='normal')

    def reset(self):
        """Reset all elements to default (unpressed, centered sticks, empty triggers)."""
        # Restore normal (non-calibration) view
        self._calibrating = False
        self.canvas.itemconfigure('cal_item', state='hidden')
        self.canvas.itemconfigure('normal_item', state='normal')

        # Reset under-body layers to normal
        for btn_name in self._under_normal_items:
            self.canvas.itemconfigure(
                self._under_normal_items[btn_name], state='normal')
            self.canvas.itemconfigure(
                self._under_pressed_items[btn_name], state='hidden')

        # Hide above-body pressed overlays
        for btn_name, item_id in self._pressed_items.items():
            self.canvas.itemconfigure(item_id, state='hidden')

        # Clear dirty-tracking caches so next update applies fully
        self._prev_buttons = {}
        self._prev_lstick = (None, None)
        self._prev_cstick = (None, None)
        self._prev_ltrigger = None
        self._prev_rtrigger = None

        # Center sticks (moves both dots and stick images)
        for side in ('left', 'right'):
            self.update_stick_position(side, 0.0, 0.0)

        # Empty triggers
        self.update_trigger_fill('left', 0)
        self.update_trigger_fill('right', 0)

    def grid(self, **kwargs):
        """Proxy grid() to the underlying canvas."""
        self.canvas.grid(**kwargs)

    def pack(self, **kwargs):
        """Proxy pack() to the underlying canvas."""
        self.canvas.pack(**kwargs)

    def place(self, **kwargs):
        """Proxy place() to the underlying canvas."""
        self.canvas.place(**kwargs)
