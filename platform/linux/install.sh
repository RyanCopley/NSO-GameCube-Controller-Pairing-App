#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

BIN_DIR="$HOME/.local/bin"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
APP_DIR="$HOME/.local/share/applications"

echo "Installing NSO GameCube Controller Pairing App..."

# Find the binary — either next to this script or one directory up (inside zip layout)
BINARY=""
for candidate in \
    "$SCRIPT_DIR/NSO-GameCube-Controller-Pairing-App" \
    "$SCRIPT_DIR/../NSO-GameCube-Controller-Pairing-App"; do
    if [ -f "$candidate" ]; then
        BINARY="$(realpath "$candidate")"
        break
    fi
done

if [ -z "$BINARY" ]; then
    echo "Error: Could not find NSO-GameCube-Controller-Pairing-App binary."
    exit 1
fi

mkdir -p "$BIN_DIR" "$ICON_DIR" "$APP_DIR"

# Install binary
cp "$BINARY" "$BIN_DIR/NSO-GameCube-Controller-Pairing-App"
chmod 755 "$BIN_DIR/NSO-GameCube-Controller-Pairing-App"

# Install icon
cp "$SCRIPT_DIR/controller-256.png" "$ICON_DIR/nso-gc-controller.png"

# Install .desktop file with absolute Exec path
sed "s|Exec=NSO-GameCube-Controller-Pairing-App|Exec=$BIN_DIR/NSO-GameCube-Controller-Pairing-App|" \
    "$SCRIPT_DIR/nso-gc-controller.desktop" > "$APP_DIR/nso-gc-controller.desktop"

# Refresh icon cache if available
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "Installed successfully."
echo "  Binary:  $BIN_DIR/NSO-GameCube-Controller-Pairing-App"
echo "  Icon:    $ICON_DIR/nso-gc-controller.png"
echo "  Desktop: $APP_DIR/nso-gc-controller.desktop"
echo ""
echo "Make sure ~/.local/bin is in your PATH, then launch from your app menu or run:"
echo "  NSO-GameCube-Controller-Pairing-App"
