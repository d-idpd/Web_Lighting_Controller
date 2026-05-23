#!/bin/bash
# Install system and Python dependencies for the SP110E web lighting controller.
# Run once on a fresh Pi OS install, or after a Python upgrade.
# Usage: chmod +x install_python_requirements.sh && ./install_python_requirements.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================"
echo "  SP110E — Python Requirements Installer"
echo "================================================"
echo ""

# ── System packages ────────────────────────────────────────────────────────────
echo "[1/3] Installing system packages..."
sudo apt-get update -y -q
sudo apt-get install -y -q \
    python3 \
    python3-pip \
    bluetooth \
    bluez \
    libglib2.0-dev

echo ""

# ── Python packages ────────────────────────────────────────────────────────────
echo "[2/3] Installing Python packages..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" --break-system-packages

echo ""

# ── BLE capabilities ───────────────────────────────────────────────────────────
echo "[3/3] Granting BLE capabilities to python3..."
# Required so the app can open raw BT sockets without running as root.
# Must be re-run after any Python upgrade that changes the binary path.
PYTHON_BIN="$(readlink -f "$(which python3)")"
sudo setcap 'cap_net_raw,cap_net_admin+eip' "$PYTHON_BIN"
echo "  caps set on $PYTHON_BIN"

echo ""
echo "================================================"
echo "  Done."
echo "  If this is a first-time setup, also run:"
echo "    sudo usermod -a -G bluetooth \$(whoami)"
echo "  then reboot for group membership to take effect."
echo "================================================"
