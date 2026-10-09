#!/usr/bin/env bash
# install.sh  —  Alt+Numpad AltCode / Unicode input for KDE Plasma Wayland / Fedora 44
# =====================================================================================
# Run as yourself (uses sudo internally where needed). Safe to re-run.
#
# IMPORTANT: Only RIGHT Alt is used for character entry.
# Left Alt passes through normally for application shortcuts.
#
# Usage after install:
#   RAlt + 0149  + numpad Enter  →  •   (CP1252/ANSI)
#   RAlt + 149   + numpad Enter  →  ò   (CP437/OEM)
#   RAlt + +2122 + numpad Enter  →  ™   (Unicode hex)
#
# Emergency recovery if keyboard locks up:
#   Physical:  Backspace+Escape+Enter simultaneously (keyd panic sequence)
#   SSH:       sudo systemctl stop keyd  (no password needed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing dependencies..."
sudo dnf copr enable -y alternateved/keyd
sudo dnf install -y keyd wl-clipboard xdotool

echo "==> Creating /etc/keyd/ (COPR package omits this)..."
sudo mkdir -p /etc/keyd

echo "==> Installing daemon and IPC bridge..."
sudo install -m 0755 "$SCRIPT_DIR/alt-input-daemon.py" /usr/local/bin/alt-input-daemon
sudo install -m 0755 "$SCRIPT_DIR/keyd-send"           /usr/local/bin/keyd-send

echo "==> Installing keyd config..."
if [[ -f /etc/keyd/default.conf ]]; then
    sudo cp /etc/keyd/default.conf /etc/keyd/default.conf.bak
    echo "    (backed up to /etc/keyd/default.conf.bak)"
fi
sudo install -m 0644 "$SCRIPT_DIR/keyd-default.conf" /etc/keyd/default.conf

echo "==> Enabling and starting keyd (system service)..."
sudo systemctl enable --now keyd

echo "==> Installing user service..."
mkdir -p ~/.config/systemd/user
install -m 0644 "$SCRIPT_DIR/alt-input-daemon.service" \
    ~/.config/systemd/user/alt-input-daemon.service

echo "==> Enabling and starting alt-input-daemon (user service)..."
systemctl --user daemon-reload
systemctl --user enable --now alt-input-daemon

echo "==> Setting up passwordless 'sudo systemctl stop keyd' for recovery..."
echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop keyd" | \
    sudo tee /etc/sudoers.d/stop-keyd > /dev/null

echo ""
echo "==> Done."
echo ""
echo "    Check daemon:  systemctl --user status alt-input-daemon"
echo "    Check keyd:    sudo systemctl status keyd"
echo "    Watch log:     journalctl --user -fu alt-input-daemon"
echo ""
echo "    Test (use RIGHT Alt):"
echo "      RAlt + 0149  + numpad Enter  →  •"
echo "      RAlt + 149   + numpad Enter  →  ò"
echo "      RAlt + +2122 + numpad Enter  →  ™"
echo ""
echo "    Left Alt works normally for application menus and shortcuts."
echo ""
echo "    Emergency recovery:"
echo "      Backspace+Escape+Enter  (keyd panic — kills keyd instantly)"
echo "      ssh then: sudo systemctl stop keyd  (no password needed)"
