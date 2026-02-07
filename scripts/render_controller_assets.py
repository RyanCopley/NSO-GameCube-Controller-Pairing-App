#!/usr/bin/env python3
"""Render controller SVG layers as PNG assets for the tkinter canvas.

Uses Inkscape CLI to export each SVG layer as a transparent PNG,
then generates lightened "pressed" versions using PIL.

Usage:
    python scripts/render_controller_assets.py
"""

import os
import subprocess
import sys

from PIL import Image

# ── Paths ───────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_PATH = os.path.join(PROJECT_ROOT, "controller.svg")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "src", "gc_controller", "assets", "controller")

# ── Render config ───────────────────────────────────────────────────
RENDER_WIDTH = 520  # pixels

# SVG layer IDs for individual button/element rendering
LAYER_IDS = [
    "R", "Z", "L", "Zl",
    "Base",
    "char", "home", "capture", "startpause",
    "lefttoggle",
    "dleft", "ddown", "dright", "dup",
    "C",
    "x", "y", "B", "A",
]

# Layers that need pressed (lightened) variants
PRESS_LAYERS = [
    "A", "B", "x", "y",
    "Z", "Zl",
    "L", "R",
    "startpause", "home", "capture", "char",
    "dup", "ddown", "dleft", "dright",
]

LIGHTEN_FACTOR = 0.35  # how much to blend towards white


def render_full(svg_path, output_path, width):
    """Render the complete SVG to a single PNG."""
    cmd = [
        "inkscape", svg_path,
        "--export-type=png",
        f"--export-width={width}",
        f"--export-filename={output_path}",
    ]
    print(f"  Rendering full SVG → {os.path.basename(output_path)}")
    subprocess.run(cmd, check=True, capture_output=True)


def render_layer(svg_path, layer_id, output_path, width):
    """Render a single SVG layer (by id) to a transparent PNG."""
    cmd = [
        "inkscape", svg_path,
        "--export-type=png",
        f"--export-width={width}",
        f"--export-id={layer_id}",
        "--export-id-only",
        "--export-area-page",
        f"--export-filename={output_path}",
    ]
    print(f"  Rendering layer '{layer_id}' → {os.path.basename(output_path)}")
    subprocess.run(cmd, check=True, capture_output=True)


def lighten_image(img, factor):
    """Lighten an RGBA image by blending RGB channels towards white."""
    r, g, b, a = img.split()
    white = Image.new("L", img.size, 255)
    r = Image.blend(r, white, factor)
    g = Image.blend(g, white, factor)
    b = Image.blend(b, white, factor)
    return Image.merge("RGBA", (r, g, b, a))


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.isfile(SVG_PATH):
        print(f"Error: SVG not found at {SVG_PATH}")
        sys.exit(1)

    print(f"Rendering controller assets from {SVG_PATH}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Render width: {RENDER_WIDTH}px\n")

    # 1. Render full SVG as base image
    base_path = os.path.join(OUTPUT_DIR, "base.png")
    render_full(SVG_PATH, base_path, RENDER_WIDTH)

    # 2. Render individual layers
    for layer_id in LAYER_IDS:
        out_path = os.path.join(OUTPUT_DIR, f"{layer_id}.png")
        render_layer(SVG_PATH, layer_id, out_path, RENDER_WIDTH)

    # 3. Generate pressed (lightened) versions
    print(f"\nGenerating pressed variants (lighten factor={LIGHTEN_FACTOR})...")
    for layer_id in PRESS_LAYERS:
        src_path = os.path.join(OUTPUT_DIR, f"{layer_id}.png")
        dst_path = os.path.join(OUTPUT_DIR, f"{layer_id}_pressed.png")
        img = Image.open(src_path).convert("RGBA")
        pressed = lighten_image(img, LIGHTEN_FACTOR)
        pressed.save(dst_path)
        print(f"  {layer_id}.png → {layer_id}_pressed.png")

    print(f"\nDone! {1 + len(LAYER_IDS) + len(PRESS_LAYERS)} images generated.")


if __name__ == "__main__":
    main()
