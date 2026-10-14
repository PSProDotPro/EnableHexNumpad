# EnableHexNumpad for Linux — KDE Plasma Wayland

> *Windows-style AltCode and Unicode character entry for KDE Plasma Wayland on Fedora 44.*

---

## Background

I started in the 1980s using Extended ASCII characters under DOS for ASCII box-art and foreign language character entry. Ever since those Cretaceous times they have been an integral part of my daily workflow — I still work almost exclusively in text files, using character art and special symbols for visual formatting without introducing the overhead of a word processor.

When I retired Windows in favor of Fedora KDE, discovering the absence of EnableHexNumpad-equivalent functionality in Linux almost made me reverse course. After several days of collaboration with Claude, we built something that acts just like Windows' EnableHexNumpad. It works like a →CHAMP←.

---

## What It Does

Replicates all three Windows Alt+Numpad input modes:

| Input | Result | Mode |
|-------|--------|------|
| RAlt + `0149` + numpad Enter | • | CP1252 / ANSI (leading zero = Windows ANSI codepage) |
| RAlt + `149` + numpad Enter | ò | CP437 / OEM (no leading zero = DOS/OEM codepage) |
| RAlt + `+2122` + numpad Enter | ™ | Unicode hex (+ prefix = full Unicode range) |
| RAlt + `+025BC` + numpad Enter | ▼ | Unicode hex (leading zeros are fine) |

Works in all window types — native Wayland and XWayland alike.

---

## Usage

- Press and **hold Right Alt**
- Enter the numeric code using **number pad keys only** (not the top-row number keys)
- For Unicode hex mode, press **numpad `+` first**, then the hex digits
- Alphabetic hex digits (A–F) are entered on the **main keyboard** while Right Alt is held
- Press **numpad Enter** to commit, then release Right Alt

**Left Alt is completely unaffected** — Alt+F, Alt+E, Alt+Tab and all other Left Alt shortcuts work normally.

---

## Known Quirks

- **Permissions dialog**: In a given focused window, the first time a character is pasted you may see a KDE "Remote Control" permissions dialog. Click Approve. It should not reappear for that window.
- **Clipboard**: This technique uses the Wayland clipboard. Anything previously on the clipboard is replaced on each character emission. If your clipboard manager tracks history, entries are preserved there.

---

## Requirements

- Fedora 44 (may work on other Fedora versions — untested)
- KDE Plasma on Wayland
- `keyd` (from COPR: `alternateved/keyd`)
- `wl-clipboard` (`wl-copy`)
- `xdotool`

The install script handles all dependencies.

---

## Install

```bash
git clone https://github.com/PSProDotPro/EnableHexNumpad.git
cd EnableHexNumpad
chmod +x install.sh keyd-send
./install.sh
```

---

## Uninstall

```bash
chmod +x uninstall.sh
./uninstall.sh
```

---

## Emergency Recovery

If the keyboard ever locks up (and it hasn't on me since about v2 under a totally different mechanical schema when I was still experimenting):

| Method | Command |
|--------|---------|
| Physical (no other device needed) | Press `Backspace` + `Escape` + `Enter` simultaneously — keyd's built-in panic sequence |
| SSH from another device | `sudo systemctl stop keyd` (no password required after install) |

---

## How It Works

```
Keypress (Right Alt + numpad)
  → keyd           kernel-level interception before Wayland sees it
  → keyd-send      bash IPC bridge; uses sudo -u to reach user socket
  → alt-input-daemon   Python state machine accumulates digit sequence
  → wl-copy        places character on Wayland clipboard (persistent process)
  → xdotool        injects Ctrl+V into focused window via XWayland
```

### Why It's This Complex

KDE Plasma's Wayland compositor (KWin) does not implement the
`zwp_virtual_keyboard_v1` protocol, which means every "just inject a character"
tool fails:

| Tool | Why it fails |
|------|-------------|
| `wtype` | KWin missing `zwp_virtual_keyboard_v1` |
| `ydotool` | Raw kernel keycodes only — no Unicode support |
| `xdotool key U<codepoint>` | Doesn't work via XWayland on KDE |
| `wl-copy` + `xdotool ctrl+v` | ✓ Works for all window types |

### When This Gets Simpler

If KWin ever implements `zwp_virtual_keyboard_v1`, the entire emission
strategy reduces to a single `wtype <char>` call, and the `wl-copy`/`xdotool`
dependency disappears entirely.

---

## Three Input Modes — Detail

### CP437 / OEM (no leading zero)
The original IBM DOS codepage. First numpad digit is 1–9.
- `RAlt + 149 + Enter` → `ò`
- `RAlt + 3 + Enter` → `♥`
- `RAlt + 14 + Enter` → `♫`

### CP1252 / ANSI (leading zero)
Windows Western codepage. First numpad digit is `0`.
- `RAlt + 0149 + Enter` → `•`
- `RAlt + 0169 + Enter` → `©`
- `RAlt + 0153 + Enter` → `™`

### Unicode Hex (+ prefix)
Full Unicode range U+0001–U+10FFFF. First key after Right Alt is numpad `+`.
A–F entered on main keyboard while Right Alt held.
- `RAlt + +2022 + Enter` → `•`
- `RAlt + +2122 + Enter` → `™`
- `RAlt + +25BC + Enter` → `▼`
- `RAlt + +1F600 + Enter` → `😀`

---

## Files

| File | Purpose |
|------|---------|
| `alt-input-daemon.py` | Python daemon — state machine, socket listener, emission |
| `keyd-send` | Bash IPC bridge from keyd (root) to daemon (user) |
| `keyd-default.conf` | keyd config — Right Alt layer only |
| `alt-input-daemon.service` | systemd user service unit |
| `install.sh` | One-shot installer |
| `uninstall.sh` | Complete backout |

---

## License

GPLv3 — you are free to use, modify, and distribute this software, but any
derivative work must also be released under GPLv3. Improvements belong to
the community.
