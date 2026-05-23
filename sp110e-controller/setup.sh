#!/bin/bash
# SP110E Controller — Pi setup script
# Run once on a fresh Raspberry Pi OS install:
#   chmod +x setup.sh && ./setup.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"

echo "================================================"
echo "  SP110E Controller — Pi Setup"
echo "  User: $USER_NAME"
echo "  Dir:  $SCRIPT_DIR"
echo "================================================"
echo ""

# ── System packages ────────────────────────────────────────────────────────
echo "[1/6] Updating system packages..."
sudo apt-get update -y -q
sudo apt-get install -y -q python3 python3-pip python3-venv bluetooth bluez libglib2.0-dev

# ── Python packages ────────────────────────────────────────────────────────
echo "[2/6] Installing Python packages..."
cd "$SCRIPT_DIR"
pip3 install -r requirements.txt --break-system-packages

# ── Bluetooth permissions ──────────────────────────────────────────────────
echo "[3/6] Configuring Bluetooth permissions..."
sudo usermod -a -G bluetooth "$USER_NAME"

# Allow system Python to use BLE without sudo
sudo setcap 'cap_net_raw,cap_net_admin+eip' "$(readlink -f $(which python3))"

# Make sure BlueZ is running
sudo systemctl enable bluetooth
sudo systemctl start bluetooth

# ── Directory structure ────────────────────────────────────────────────────
echo "[4/6] Creating required directories..."
mkdir -p static/images

# ── systemd service ────────────────────────────────────────────────────────
echo "[5/6] Installing systemd service..."
sudo tee /etc/systemd/system/sp110e.service > /dev/null <<EOF
[Unit]
Description=SP110E Cabinet Lighting Controller
After=network.target bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$SCRIPT_DIR
ExecStart=$(which python3) $SCRIPT_DIR/app.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sp110e

# ── Summary ────────────────────────────────────────────────────────────────
echo "[6/6] Done."
echo ""
echo "================================================"
echo "  Next steps:"
echo ""
echo "  1. Edit config.json with your BLE addresses:"
echo "       nano $SCRIPT_DIR/config.json"
echo ""
echo "  2. Scan for SP110E devices:"
echo "       cd $SCRIPT_DIR && source venv/bin/activate"
echo "       python scan.py"
echo ""
echo "  3. Start the server (once):"
echo "       python app.py"
echo ""
echo "  4. Or run as a background service:"
echo "       sudo systemctl start sp110e"
echo "       sudo journalctl -u sp110e -f"
echo ""
echo "  Note: a reboot may be needed for Bluetooth"
echo "  group membership to take effect."
echo "================================================"
