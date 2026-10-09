#!/usr/bin/env bash
# uninstall.sh  —  Full backout for Alt+Numpad input setup
# =========================================================
# Stops and removes everything installed by install.sh.
# Safe to run even if install was only partially completed.

set -uo pipefail

echo "==> Stopping user service..."
systemctl --user stop alt-input-daemon 2>/dev/null || true
systemctl --user disable alt-input-daemon 2>/dev/null || true
rm -f ~/.config/systemd/user/alt-input-daemon.service
systemctl --user daemon-reload

echo "==> Stopping and disabling keyd..."
sudo systemctl stop keyd 2>/dev/null || true
sudo systemctl disable keyd 2>/dev/null || true

echo "==> Restoring keyd config..."
if [[ -f /etc/keyd/default.conf.bak ]]; then
    sudo cp /etc/keyd/default.conf.bak /etc/keyd/default.conf
    echo "    Restored from backup."
else
    sudo rm -f /etc/keyd/default.conf
    echo "    No backup found — removed config."
fi

echo "==> Removing installed files..."
sudo rm -f /usr/local/bin/alt-input-daemon
sudo rm -f /usr/local/bin/keyd-send
sudo rm -f /etc/sudoers.d/stop-keyd

echo "==> Removing packages..."
sudo dnf remove -y keyd wl-clipboard xdotool 2>/dev/null || true

echo "==> Removing COPR repo..."
sudo dnf copr remove -y alternateved/keyd 2>/dev/null || true

echo ""
echo "==> Backout complete."
echo "    Keyboard should be back to normal immediately."
echo "    keyd panic sequence: Backspace+Escape+Enter"
echo "    Or from another terminal: sudo systemctl stop keyd"
