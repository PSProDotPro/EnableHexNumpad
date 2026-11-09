#!/usr/bin/env python3
"""
alt-input-daemon  —  Wayland Alt+Numpad input daemon
======================================================
Replicates Windows AltCode and EnableHexNumpad behavior on KDE Plasma / Fedora.

Version 7

WHAT CHANGED IN v7
------------------
v6 hardcoded WAYLAND_DISPLAY=wayland-0 and DISPLAY=:0 for the wl-copy and
xdotool subprocesses. On any machine whose compositor socket has a different
name (e.g. wayland-1), wl-copy could not reach the compositor, the clipboard
never changed, and Ctrl+V pasted whatever was on the clipboard beforehand.
The daemon still logged "Emitted ... OK", because that only reported that
xdotool had pressed Ctrl+V.

v7 fixes both problems:
  - The Wayland socket and X display are discovered at emission time instead
    of assumed (see emit_env()).
  - wl-copy failures are detected and logged instead of being swallowed.

ARCHITECTURE
------------
keyd (root, kernel level)
  → intercepts Right Alt+numpad key events before Wayland sees them
  → calls keyd-send <CMD> for each relevant keypress

keyd-send (bash script, runs as root via keyd command() macro)
  → uses 'sudo -u "#<uid>"' to connect to daemon socket as the logged-in user
  → sends the command string and exits

alt-input-daemon (this file, runs as user systemd service)
  → receives commands via Unix socket at /run/user/<uid>/alt-input.sock
  → maintains state machine to accumulate digit sequences
  → on numpad Enter (ALT_UP), looks up the character and emits it

IMPORTANT: Only RIGHT Alt is intercepted. Left Alt passes through normally
for application menu access (Alt+F, Alt+E, Alt+Tab, etc.)

EMISSION STRATEGY
-----------------
wl-copy runs as a persistent background process, keeping a warm connection
to the Wayland clipboard manager at all times. On each emission:

  1. Start a new wl-copy <char> (replaces the clipboard selection)
  2. Short delay (0.3s) for the clipboard to register
  3. xdotool key --clearmodifiers ctrl+v  →  paste into focused window
  4. xdotool keyup alt ISO_Level3_Shift   →  release Alt modifiers

At daemon startup, wl-copy is pre-warmed with a space character so the
clipboard connection is established before the first character is requested.

COMMIT KEY
----------
Numpad Enter sends ALT_UP which commits and emits the sequence.

THREE INPUT MODES
-----------------
  CP437 / OEM    (first numpad key is 1-9):  RAlt + 149   + Enter  →  ò
  CP1252 / ANSI  (first numpad key is 0):    RAlt + 0149  + Enter  →  •
  Unicode hex    (first numpad key is +):    RAlt + +2122 + Enter  →  ™
                                             RAlt + +025BC + Enter →  ▼

REQUIREMENTS
------------
  wl-clipboard  (wl-copy)   sudo dnf install wl-clipboard
  xdotool                   sudo dnf install xdotool
  XWayland                  running by default on KDE Plasma
"""

import glob
import os
import socket
import stat
import subprocess
import sys
import logging
import tempfile
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [alt-input] %(levelname)s: %(message)s',
    stream=sys.stdout,
)
log = logging.getLogger('alt-input')

UID = os.getuid()

# Persistent wl-copy process — kept alive between emissions
_wl_copy_proc = None

# ---------------------------------------------------------------------------
# Display discovery
#
# The Wayland socket name (wayland-0, wayland-1, ...) and the XWayland display
# number (:0, :1, ...) are NOT constant across machines or sessions, so they
# are looked up each time rather than hardcoded.
# ---------------------------------------------------------------------------
def _find_wayland_display(runtime_dir):
    """Return the name of a live Wayland socket in runtime_dir, or None."""
    cur = os.environ.get('WAYLAND_DISPLAY')
    if cur:
        path = cur if os.path.isabs(cur) else os.path.join(runtime_dir, cur)
        if os.path.exists(path):
            return cur
    for path in sorted(glob.glob(os.path.join(runtime_dir, 'wayland-*'))):
        if path.endswith('.lock'):
            continue
        try:
            if stat.S_ISSOCK(os.stat(path).st_mode):
                return os.path.basename(path)
        except OSError:
            continue
    return cur  # may be None; wl-copy will report a clear error

def _find_x_display():
    """Return the XWayland DISPLAY value (e.g. ':0')."""
    cur = os.environ.get('DISPLAY')
    if cur:
        return cur
    socks = sorted(glob.glob('/tmp/.X11-unix/X*'))
    if socks:
        return ':' + os.path.basename(socks[0])[1:]
    return ':0'

def emit_env():
    """Environment for the wl-copy / xdotool subprocesses."""
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{UID}'
    env = {
        **os.environ,
        'XDG_RUNTIME_DIR': runtime_dir,
        'DISPLAY': _find_x_display(),
    }
    wayland = _find_wayland_display(runtime_dir)
    if wayland:
        env['WAYLAND_DISPLAY'] = wayland
    return env

# ---------------------------------------------------------------------------
# CP437 table (OEM codepage, no leading zero)
# ---------------------------------------------------------------------------
_CP437 = {
    1:'☺', 2:'☻', 3:'♥', 4:'♦', 5:'♣', 6:'♠', 7:'•', 8:'◘',
    9:'○', 10:'◙', 11:'♂', 12:'♀', 13:'♪', 14:'♫', 15:'☼', 16:'►',
    17:'◄', 18:'↕', 19:'‼', 20:'¶', 21:'§', 22:'▬', 23:'↨', 24:'↑',
    25:'↓', 26:'→', 27:'←', 28:'∟', 29:'↔', 30:'▲', 31:'▼', 127:'⌂',
}

def cp437_to_char(code):
    if code <= 0 or code > 255:
        return None
    if code in _CP437:
        return _CP437[code]
    try:
        return bytes([code]).decode('cp437')
    except Exception:
        return None

# ---------------------------------------------------------------------------
# CP1252 table (Windows ANSI codepage, leading zero)
# ---------------------------------------------------------------------------
_CP1252 = {
    0x80:'\u20AC', 0x82:'\u201A', 0x83:'\u0192', 0x84:'\u201E',
    0x85:'\u2026', 0x86:'\u2020', 0x87:'\u2021', 0x88:'\u02C6',
    0x89:'\u2030', 0x8A:'\u0160', 0x8B:'\u2039', 0x8C:'\u0152',
    0x8E:'\u017D', 0x91:'\u2018', 0x92:'\u2019', 0x93:'\u201C',
    0x94:'\u201D', 0x95:'\u2022', 0x96:'\u2013', 0x97:'\u2014',
    0x98:'\u02DC', 0x99:'\u2122', 0x9A:'\u0161', 0x9B:'\u203A',
    0x9C:'\u0153', 0x9E:'\u017E', 0x9F:'\u0178',
}

def cp1252_to_char(code):
    if code <= 0 or code > 255:
        return None
    if code in _CP1252:
        return _CP1252[code]
    if 0x80 <= code <= 0x9F:
        return None
    return chr(code)

# ---------------------------------------------------------------------------
# wl-copy management
# ---------------------------------------------------------------------------
def wlcopy_start(char, env):
    """Start wl-copy with the given character. Returns True on success.

    wl-copy normally forks into the background and its parent exits 0 almost
    immediately. If it cannot reach the compositor, the parent exits non-zero
    and prints the reason to stderr; that is captured and logged here so a
    failed clipboard update is never silent.
    """
    global _wl_copy_proc

    # Stop the previous instance if it is still running
    if _wl_copy_proc is not None:
        try:
            _wl_copy_proc.terminate()
            _wl_copy_proc.wait(timeout=1)
        except Exception:
            try:
                _wl_copy_proc.kill()
            except Exception:
                pass
        _wl_copy_proc = None

    try:
        with tempfile.TemporaryFile() as errf:
            proc = subprocess.Popen(
                ['wl-copy', char],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=errf,
            )
            try:
                rc = proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                rc = None  # still running: serving the selection
            if rc not in (None, 0):
                errf.seek(0)
                err = errf.read().decode('utf-8', errors='replace').strip()
                log.error('wl-copy failed (exit %d): %s', rc, err or '(no message)')
                return False
        _wl_copy_proc = proc
        log.debug('wl-copy started (pid=%d) for %r', proc.pid, char)
        return True
    except Exception as e:
        log.error('wl-copy failed to start: %s', e)
        return False

def wlcopy_warmup():
    """Pre-warm wl-copy at daemon startup with a space character."""
    log.info('Warming up wl-copy...')
    if wlcopy_start(' ', emit_env()):
        time.sleep(0.3)
        log.info('wl-copy warmed up and ready')
    else:
        log.warning('wl-copy warmup failed — see the error above')

# ---------------------------------------------------------------------------
# Character emission
# ---------------------------------------------------------------------------
def emit_char(char):
    log.info('Emitting U+%04X %r', ord(char), char)
    env = emit_env()

    # Step 1: put the character on the Wayland clipboard
    if not wlcopy_start(char, env):
        log.error('Clipboard not updated; skipping paste of U+%04X', ord(char))
        return

    # Step 2: short delay for the clipboard to register
    time.sleep(0.3)

    # Step 3: inject Ctrl+V into the focused window via XWayland
    try:
        subprocess.run(
            ['xdotool', 'key', '--clearmodifiers', 'ctrl+v'],
            check=True, timeout=5, capture_output=True,
            env=env,
        )
        log.info('Emitted U+%04X %r OK', ord(char), char)
    except Exception as e:
        log.error('xdotool key failed: %s', e)
        return

    # Step 4: explicitly release Alt to prevent it getting stuck
    try:
        subprocess.run(
            ['xdotool', 'keyup', 'alt', 'ISO_Level3_Shift'],
            capture_output=True, timeout=5, env=env,
        )
        log.debug('Alt released OK')
    except Exception as e:
        log.error('Alt release failed: %s', e)

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class AltInputFSM:
    IDLE    = 'IDLE'
    CP437   = 'CP437'
    CP1252  = 'CP1252'
    UNICODE = 'UNICODE'

    def __init__(self):
        self.state = self.IDLE
        self.buf   = ''

    def _reset(self):
        self.state = self.IDLE
        self.buf   = ''

    def handle(self, cmd):
        cmd = cmd.strip()
        log.debug('CMD %-12s state=%-10s buf=%r', cmd, self.state, self.buf)

        if cmd == 'ALT_DOWN':
            self._reset()

        elif cmd == 'ALT_UP':
            self._commit()
            self._reset()

        elif cmd == 'CANCEL':
            self._reset()

        elif cmd == 'PLUS':
            if self.state == self.IDLE:
                self.state = self.UNICODE
                self.buf   = ''

        elif cmd == 'ZERO':
            if self.state == self.IDLE:
                self.state = self.CP1252
                self.buf   = '0'
            elif self.state in (self.CP1252, self.UNICODE):
                self.buf += '0'
            elif self.state == self.CP437:
                self.buf += '0'
                if len(self.buf) > 3:
                    self.buf = self.buf[-3:]

        elif cmd in '123456789':
            if self.state == self.IDLE:
                self.state = self.CP437
                self.buf   = cmd
            elif self.state == self.CP437:
                self.buf += cmd
                if len(self.buf) > 3:
                    self.buf = self.buf[-3:]
            elif self.state in (self.CP1252, self.UNICODE):
                self.buf += cmd

        elif cmd in 'abcdef':
            if self.state == self.UNICODE:
                self.buf += cmd

        else:
            log.debug('Unknown command ignored: %r', cmd)

    def _commit(self):
        if self.state == self.IDLE or not self.buf:
            return

        if self.state == self.CP437:
            try:
                char = cp437_to_char(int(self.buf))
                if char:
                    emit_char(char)
                else:
                    log.warning('CP437[%d] has no mapping', int(self.buf))
            except ValueError:
                log.warning('Bad CP437 buffer: %r', self.buf)

        elif self.state == self.CP1252:
            try:
                char = cp1252_to_char(int(self.buf))
                if char:
                    emit_char(char)
                else:
                    log.warning('CP1252[%d] is undefined', int(self.buf))
            except ValueError:
                log.warning('Bad CP1252 buffer: %r', self.buf)

        elif self.state == self.UNICODE:
            try:
                cp = int(self.buf, 16)
                if 1 <= cp <= 0x10FFFF and not (0xD800 <= cp <= 0xDFFF):
                    emit_char(chr(cp))
                else:
                    log.warning('U+%s out of range or surrogate', self.buf.upper())
            except ValueError:
                log.warning('Bad Unicode hex buffer: %r', self.buf)

# ---------------------------------------------------------------------------
# Unix socket server
# ---------------------------------------------------------------------------
def run():
    uid       = os.getuid()
    sock_path = f'/run/user/{uid}/alt-input.sock'

    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    os.chmod(sock_path, 0o600)
    server.listen(32)

    log.info('Listening on %s (uid=%d)', sock_path, uid)

    env = emit_env()
    log.info('Detected: WAYLAND_DISPLAY=%s DISPLAY=%s XDG_RUNTIME_DIR=%s',
             env.get('WAYLAND_DISPLAY'), env.get('DISPLAY'),
             env.get('XDG_RUNTIME_DIR'))

    for tool in ['wl-copy', 'xdotool']:
        r = subprocess.run(['which', tool], capture_output=True, text=True)
        log.info('%s: %s', tool,
                 r.stdout.strip() if r.returncode == 0 else 'NOT FOUND')

    # Pre-warm wl-copy so the first emission has no cold-start delay
    wlcopy_warmup()

    fsm = AltInputFSM()

    while True:
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(0.5)
                try:
                    data = conn.recv(64).decode('utf-8', errors='replace').strip()
                except socket.timeout:
                    continue
            if data:
                fsm.handle(data)
        except KeyboardInterrupt:
            log.info('Shutting down.')
            break
        except Exception as e:
            log.error('Server loop error: %s', e)

    # Clean up wl-copy on exit
    global _wl_copy_proc
    if _wl_copy_proc is not None:
        try:
            _wl_copy_proc.terminate()
        except Exception:
            pass

    try:
        os.unlink(sock_path)
    except Exception:
        pass

if __name__ == '__main__':
    run()
