#!/usr/bin/env python3
"""Formatting, width detection, and ANSI-safe truncation for the statusline.

Pure helpers with no dependency on stats/parsing/git. Also defines the
shared ANSI color constants and the cost-conversion constants used across
other modules.
"""

import re
import struct
import sys
import time
import unicodedata

# ANSI color codes
CYAN = '\033[0;36m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
RED = '\033[0;31m'
PURPLE = '\033[0;35m'
DIM = '\033[2m'
NC = '\033[0m'

# Cost conversions
CREDITS_TO_USD = 1 / 100
USD_TO_CNY = 7

# ANSI escape sequence regex:
# - CSI sequences: ESC [ ... letter  (covers SGR, cursor, scroll, etc.)
# - OSC sequences: ESC ] ... BEL/ST  (window title, etc.)
# CSI uses [0-9;?]* to also match private params like ?25l, ?2004h.
# OSC matches up to BEL (\007) or ST (ESC \).
_ANSI_RE = re.compile(r'\033\[[0-9;?]*[A-Za-z]|\033\][^\007]*\007|\033\][^\033]*\033\\')


def format_tokens(n):
    if n is None:
        return "0"
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    else:
        return str(n)


def format_cost(usd):
    """Format cost as $USD(¥CNY) with adaptive precision.

    Uses 2 decimal places normally. Tiny costs that would round to
    $0.00 (e.g. $0.0005) get more digits — up to 8 dp — so the amount
    stays visible instead of showing 0.00.
    """
    if usd is None or usd == 0:
        return ""
    cny = usd * USD_TO_CNY
    places = 2
    while places < 8 and round(usd, places) == 0:
        places += 1
    return f"${usd:.{places}f}(¥{cny:.{places}f})"


def format_duration(ms):
    if ms is None or ms == 0:
        return ""
    s = int(ms) // 1000
    if s < 60:
        return f"{s}s"
    m = s // 60
    s = s % 60
    h = m // 60
    m = m % 60
    if h:
        return f"{h}h{m}m{s}s"
    return f"{m}m{s}s"


def make_progress_bar(pct, width=10):
    """Make a Unicode progress bar with color based on usage."""
    filled = int(pct * width)
    partial_idx = int((pct * width - filled) * 8)

    if filled >= width:
        bar = '█' * width
    elif filled > 0:
        bar = '█' * filled
        partial_chars = ' ▏▎▍▌▋▊▉█'
        if partial_idx > 0:
            bar += partial_chars[min(partial_idx, 7)]
            bar += ' ' * (width - filled - 1)
        else:
            bar += ' ' * (width - filled)
    else:
        bar = ' ' * width

    if pct < 0.5:
        color = GREEN
    elif pct < 0.8:
        color = YELLOW
    else:
        color = RED

    return bar, color


def _char_width(ch):
    """Return the terminal display width of a single character."""
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ('W', 'F') else 1


def _visible_len(s):
    """Return the terminal display width of s, excluding ANSI escapes.

    CJK and other East-Asian wide characters (width category W or F)
    count as 2 columns, matching how most terminals render them.
    """
    return sum(_char_width(ch) for ch in _ANSI_RE.sub('', s))


def truncate_to_width(s, width, ellipsis='…'):
    """Truncate s to at most `width` visible terminal columns, ANSI-safe.

    Preserves ANSI escape sequences intact (never cuts them in half).
    Re-closes any unterminated SGR ("color") sequence before the
    ellipsis so the truncation does not leak color into the next line.

    CJK / wide characters count as 2 columns (matches terminal rendering).

    If width is 0, returns s unchanged (no truncation) — used when
    the terminal width cannot be determined.
    """
    if width == 0:
        return s
    if width < 0:
        return ""
    if _visible_len(s) <= width:
        return s
    ellipsis_w = _visible_len(ellipsis)
    budget = width - ellipsis_w
    if budget <= 0:
        return ellipsis[:width]
    out = []
    visible = 0
    sgr_open = False  # tracked to re-close before the ellipsis
    i = 0
    while i < len(s) and visible < budget:
        m = _ANSI_RE.match(s, i)
        if m:
            seq = m.group(0)
            out.append(seq)
            # SGR codes end with 'm'; a bare reset clears any open style.
            if seq.endswith('m') and seq != '\033[0m':
                sgr_open = True
            elif seq == '\033[0m':
                sgr_open = False
            i = m.end()
        else:
            ch = s[i]
            cw = _char_width(ch)
            # If adding this wide char would exceed the budget, stop
            # before it rather than breaking mid-character.
            if visible + cw > budget:
                break
            out.append(ch)
            i += 1
            visible += cw
    if sgr_open:
        out.append('\033[0m')
    out.append(ellipsis)
    return ''.join(out)


def _read_tty_columns():
    """Read terminal width from /dev/tty via TIOCGWINSZ; 0 when unavailable.

    TIOCGWINSZ survives pipe redirection (the statusline runs through a
    pipe) because /dev/tty refers to the controlling terminal regardless
    of redirections.
    """
    try:
        import fcntl
        import termios
        with open('/dev/tty', 'rb') as tty:
            # TIOCGWINSZ: arg is a struct winsize (4 unsigned shorts)
            buf = fcntl.ioctl(tty.fileno(), termios.TIOCGWINSZ, b'\x00' * 8)
            return struct.unpack('HHHH', buf)[1]
    except Exception:
        return 0


def _windows_columns():
    """Detect terminal width on Windows (statusline is invoked via pipe).

    Tries in order — only methods that return *live* width that updates
    on terminal resize:

    1. /dev/tty + TIOCGWINSZ: works in Git Bash / MSYS2, survives pipe
       redirection, and reflects the current window size.
    2. GetConsoleScreenBufferInfo via ctypes: reads srWindow from the
       console attached to stdout/stderr — live value, updates on resize.
    3. Returns 0 (unknown) if neither source is available.  The caller
       treats 0 as "skip truncation entirely", which is safer than
       truncating to a stale/guessed width.

    Methods deliberately NOT used:
    - shutil.get_terminal_size(): returns default 80 when stdout is a
      pipe — the root cause of the "truncated too short" bug.
    - COLUMNS env var: set once at shell startup, never updated on
      resize — unreliable for live width.
    """
    # 1. /dev/tty: works in Git Bash / MSYS2 even when statusline is piped
    cols = _read_tty_columns()
    if cols > 0:
        return cols

    # 2. Windows Console API: GetConsoleScreenBufferInfo
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        class COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class SMALL_RECT(ctypes.Structure):
            _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                        ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]

        class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
            _fields_ = [
                ("dwSize", COORD),
                ("dwCursorPosition", COORD),
                ("wAttributes", ctypes.c_ushort),
                ("srWindow", SMALL_RECT),
                ("dwMaximumWindowSize", COORD),
            ]

        kernel32.GetConsoleScreenBufferInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO),
        ]
        kernel32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL

        INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

        # Try stdout first, then stderr (in case one is redirected)
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            h = kernel32.GetStdHandle(handle_id)
            if not h or h == INVALID_HANDLE_VALUE:
                continue
            csbi = CONSOLE_SCREEN_BUFFER_INFO()
            if kernel32.GetConsoleScreenBufferInfo(h, ctypes.byref(csbi)):
                cols = csbi.srWindow.Right - csbi.srWindow.Left + 1
                if cols > 0:
                    return cols
    except Exception:
        pass

    # 3. No reliable live-width source — return 0 (skip truncation)
    return 0


_TTY_COLUMNS_CACHE = (0, 0.0)  # (cols, mtime) — refreshed every 1s


def _tty_columns():
    """Read live terminal width.

    On Unix: uses /dev/tty + TIOCGWINSZ, which survives pipe invocation
    (statusline is invoked through a pipe, so shutil.get_terminal_size()
    cannot see the real TTY — /dev/tty refers to the controlling terminal
    regardless of redirections).

    On Windows: tries /dev/tty (Git Bash/MSYS2) then the Windows Console
    API via ctypes.  Returns 0 when no live width source is available,
    which causes the caller to skip truncation entirely.

    Result is cached for ~1s because this runs every 300ms and the
    underlying call is a syscall we don't need to repeat.

    Returns 0 when no width source is available (no TTY, e.g. CI sandbox).
    """
    global _TTY_COLUMNS_CACHE
    cached, last = _TTY_COLUMNS_CACHE
    # Cache both positive results and zero (no-TTY) results for ~1s so we
    # don't re-read /dev/tty on every 300ms cycle.
    if (time.time() - last) < 1.0:
        return cached

    if sys.platform != 'win32':
        cols = _read_tty_columns()
    else:
        cols = _windows_columns()

    _TTY_COLUMNS_CACHE = (cols, time.time())
    return cols


def get_statusline_width():
    """Return terminal width from /dev/tty via TIOCGWINSZ.

    Returns 0 when /dev/tty is unavailable, signalling the caller to skip
    truncation entirely.
    """
    return _tty_columns()


def get_statusline_width_from_input(input_data):
    """Resolve statusline width from CodeBuddy's input JSON.

    The host *may* report the live terminal width in `terminal_width` (int).
    When the field is missing or non-positive we fall back to TIOCGWINSZ on
    the /dev/tty. Returns 0 when no width source is available, signalling the
    caller to skip truncation entirely.
    """
    tw = None
    if isinstance(input_data, dict):
        tw = input_data.get('terminal_width')
    if isinstance(tw, int) and tw > 0:
        return tw
    return get_statusline_width()
