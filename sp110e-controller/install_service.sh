#!/bin/bash
# Install the web_lighting_controller systemd service.
# Creates:
#   /etc/web_lighting_controller/config.json   (app config)
#   /usr/bin/web_lighting_controller           (symlink → app.py)
#   /etc/systemd/system/web_lighting_controller.service
#
# Usage: chmod +x install_service.sh && ./install_service.sh

set -e

APP_PATH="/home/admin/sp110e-controller/app.py"
SYMLINK="/usr/bin/web_lighting_controller"
CONFIG_DIR="/etc/web_lighting_controller"
SERVICE="web_lighting_controller"
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
RUN_USER="admin"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================"
echo "  SP110E — Service Installer"
echo "  Service: $SERVICE"
echo "  App:     $APP_PATH"
echo "  Config:  $CONFIG_DIR"
echo "================================================"
echo ""

# ── Config directory ───────────────────────────────────────────────────────────
echo "[1/4] Setting up config directory..."
sudo mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.json" ]; then
    sudo cp "$SCRIPT_DIR/config.json" "$CONFIG_DIR/config.json"
    sudo chown "$RUN_USER:$RUN_USER" "$CONFIG_DIR/config.json"
    echo "  Copied config.json → $CONFIG_DIR/config.json"
else
    echo "  Config already exists at $CONFIG_DIR/config.json — not overwriting."
    echo "  Edit it manually: sudo nano $CONFIG_DIR/config.json"
fi

echo ""

# ── Symlink ────────────────────────────────────────────────────────────────────
echo "[2/4] Creating symlink..."
sudo ln -sf "$APP_PATH" "$SYMLINK"
echo "  $SYMLINK → $APP_PATH"

echo ""

# ── systemd service file ───────────────────────────────────────────────────────
echo "[3/4] Writing service file..."
PYTHON_BIN="$(readlink -f "$(which python3)")"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=SP110E Web Lighting Controller
After=network.target bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=/home/${RUN_USER}/sp110e-controller
ExecStart=${PYTHON_BIN} ${SYMLINK}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "  Written: $SERVICE_FILE"

echo ""

# ── Enable service ─────────────────────────────────────────────────────────────
echo "[4/4] Enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"

echo ""
echo "================================================"
echo "  Service installed and enabled."
echo ""
echo "  Start now:     sudo systemctl start $SERVICE"
echo "  Stop:          sudo systemctl stop $SERVICE"
echo "  Status:        sudo systemctl status $SERVICE"
echo "  Logs (live):   sudo journalctl -u $SERVICE -f"
echo ""
echo "  Config:        sudo nano $CONFIG_DIR/config.json"
echo "================================================"
