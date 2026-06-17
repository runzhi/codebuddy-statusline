#!/usr/bin/env python3
"""
CodeBuddy Code Cost Monitor - Statusline Script (Incremental)
Displays real-time cost, token usage, context progress, tools usage, and request stats.

Uses incremental parsing for all metrics from main + sub-agent transcripts.
In/Out/Cache/Credits include sub-agent data for a complete picture.

Requires Python 3.6+.
"""

import json
import sys
import os
import re
import struct
import subprocess
import time
import unicodedata

# Fix Windows GBK encoding: stdout defaults to GBK on Chinese Windows,
# which cannot encode Unicode chars like ✓, █, ▕, × used in the output.
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_PLUGIN_DATA = os.environ.get('CODEBUDDY_PLUGIN_DATA', '') or os.path.expanduser("~/.codebuddy/plugins/data/statusline")
CACHE_DIR = os.path.join(_PLUGIN_DATA, "cache")
CACHE_MAX_AGE_DAYS = 7
CACHE_VERSION = 8

# Plugin mode: CODEBUDDY_PLUGIN_ROOT is set when installed via marketplace
# Git-clone mode: fallback to script's own directory
PLUGIN_DIR = os.environ.get('CODEBUDDY_PLUGIN_ROOT', '') or os.path.dirname(os.path.abspath(__file__))
IS_PLUGIN_MODE = bool(os.environ.get('CODEBUDDY_PLUGIN_ROOT', ''))

# Auto-update (git-clone mode only): throttled via marker file
UPDATE_MARKER = os.path.join(CACHE_DIR, ".last-update-check")
UPDATE_INTERVAL_SECONDS = 86400  # once per day

# ANSI color codes
CYAN = '\033[0;36m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
RED = '\033[0;31m'
PURPLE = '\033[0;35m'
DIM = '\033[2m'
NC = '\033[0m'

# Tool display order and short names
TOOL_ORDER = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Agent", "WebFetch", "WebSearch"]
TOOL_SHORT = {
    "Bash": "Bash", "Read": "Read", "Edit": "Edit", "Write": "Write",
    "Glob": "Glob", "Grep": "Grep", "Agent": "Agent",
    "WebFetch": "Fetch", "WebSearch": "Search",
}

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

CREDITS_TO_USD = 1 / 100
USD_TO_CNY = 7

def format_cost(usd):
    """Format cost as $USD(¥CNY), both with 2 decimal places."""
    if usd is None or usd == 0:
        return ""
    cny = usd * USD_TO_CNY
    return f"${usd:.2f}(¥{cny:.2f})"

def format_duration(ms):
    if ms is None or ms == 0:
        return ""
    s = int(ms) // 1000
    if s < 60:
        return f"{s}s"
    m = s // 60
    s = s % 60
    return f"{m}m{s}s"

# Parses the first line of `git status --porcelain=v1 --branch` output.
# Examples:
#   ## master
#   ## master...origin/master
#   ## master...origin/master [ahead 2]
#   ## master...origin/master [ahead 2, behind 1]
#   ## HEAD (no branch)
_GIT_BRANCH_LINE_RE = re.compile(
    r'^## (?:'
    r'(?P<detached>HEAD \(no branch\))'
    r'|'
    r'(?P<branch>[^.\s]+)(?:\.\.\.[^\s]+)?'
    r'(?: \[(?:ahead (?P<ahead>\d+))?(?:, )?(?:behind (?P<behind>\d+))?\])?'
    r')$'
)

# Git info is fetched synchronously on each call (no cache).
# CodeBuddy's statusline invocation cycle is irregular (seconds to minutes),
# so caching would risk stale data (branch switches, commits, pulls) without
# meaningfully reducing fork overhead. A single `git status` subprocess takes
# only a few ms, well within the tolerance of an irregular render cycle.
def get_git_info(cwd):
    """Return git info for *cwd* or None if unavailable.

    Returns: {"branch": str, "dirty": bool, "ahead": int, "behind": int}
    Branch is "(detached)" for detached HEAD.
    """
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v1", "--branch"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=0.5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None

    lines = result.stdout.splitlines()
    if not lines:
        return None

    m = _GIT_BRANCH_LINE_RE.match(lines[0])
    if not m:
        return None

    if m.group('detached'):
        branch = "(detached)"
    else:
        branch = m.group('branch')

    ahead = int(m.group('ahead')) if m.group('ahead') else 0
    behind = int(m.group('behind')) if m.group('behind') else 0
    dirty = len(lines) > 1

    return {"branch": branch, "dirty": dirty, "ahead": ahead, "behind": behind}

GIT_BRANCH_ICON = '\ue0a0'  # Powerline branch icon (U+E0A0)

def format_git_info(info):
    """Format git info dict into a colored string for the statusline."""
    if not info:
        return ""
    suffix = ""
    if info.get("dirty"):
        suffix += "*"
    ahead = info.get("ahead", 0)
    behind = info.get("behind", 0)
    if ahead:
        suffix += f" ↑{ahead}"
    if behind:
        suffix += f" ↓{behind}"
    branch = info.get("branch", "")
    if not branch:
        return ""
    suffix_part = f"{RED}{suffix}{NC}" if suffix else NC
    return f"{DIM}on{NC} {PURPLE}{GIT_BRANCH_ICON} {branch}{suffix_part}"

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

# ANSI escape sequence regex:
# - CSI sequences: ESC [ ... letter  (covers SGR, cursor, scroll, etc.)
# - OSC sequences: ESC ] ... BEL/ST  (window title, etc.)
# CSI uses [0-9;?]* to also match private params like ?25l, ?2004h.
# OSC matches up to BEL (\007) or ST (ESC \).
_ANSI_RE = re.compile(r'\033\[[0-9;?]*[A-Za-z]|\033\][^\007]*\007|\033\][^\033]*\033\\')

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
    try:
        with open('/dev/tty', 'rb') as tty:
            import fcntl
            import termios
            buf = fcntl.ioctl(tty.fileno(), termios.TIOCGWINSZ, b'\x00' * 8)
            cols = struct.unpack('HHHH', buf)[1]
            if cols > 0:
                return cols
    except Exception:
        pass

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
    # Cache both positive results and zero (no-TTY) results for ~1s.
    # The previous `if cached and ...` skipped the cache when cached==0
    # (no TTY), causing a re-read every cycle and a fresh timestamp write
    # that broke the test asserting the tuple is unchanged.
    if (time.time() - last) < 1.0:
        return cached

    cols = 0
    if sys.platform != 'win32':
        try:
            import fcntl
            import termios
            with open('/dev/tty', 'rb') as tty:
                # TIOCGWINSZ: arg is a struct winsize (4 unsigned shorts)
                buf = fcntl.ioctl(tty.fileno(), termios.TIOCGWINSZ, b'\x00' * 8)
                cols = struct.unpack('HHHH', buf)[1]
        except Exception:
            cols = 0
    else:
        cols = _windows_columns()

    if cols > 0:
        _TTY_COLUMNS_CACHE = (cols, time.time())
        return cols

    # Could not read real TTY — cache the failure briefly so we don't
    # hammer the source, but return 0 so the caller knows it's unknown.
    _TTY_COLUMNS_CACHE = (0, time.time())
    return 0

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
    /dev/tty. Returns 0 when no width source is available, signalling the
    caller to skip truncation entirely.
    """
    tw = None
    if isinstance(input_data, dict):
        tw = input_data.get('terminal_width')
    if isinstance(tw, int) and tw > 0:
        return tw
    return get_statusline_width()

RECENT_CALLS_MAX = 3
RECENT_CALLS_SUMMARY_LEN = 60
# Stats fields that hold the "last value" rather than a cumulative total;
# during incremental merges they are overwritten (not summed).
_LAST_KEYS = ("last_input", "last_output", "last_cache_read", "last_credits", "last_cost")

def new_stats():
    return {
        "total_input": 0,
        "total_output": 0,
        "total_cache_read": 0,
        "total_reasoning": 0,
        "total_credits": 0.0,
        "request_count": 0,
        "tool_counts": {},
        "running_agents": 0,
        "compact_count": 0,
        "periodic_count": 0,
        "recent_calls": [],
        "last_input": 0,
        "last_output": 0,
        "last_cache_read": 0,
        "last_credits": 0.0,
        "last_cost": 0.0,
    }

def _extract_call_summary(name, args):
    """Extract a short summary from a function_call's parsed arguments.

    args should be a dict (already parsed from JSON).
    Truncation is handled by format_recent_calls, not here.
    """
    if not isinstance(args, dict) or not args:
        return name

    # Tool-specific extraction
    if name == 'Bash':
        return args.get('command', '') or name
    elif name in ('Read', 'Edit', 'Write'):
        return args.get('file_path', '') or name
    elif name == 'Grep':
        pat = args.get('pattern', '')
        path = args.get('path', '')
        if pat or path:
            return f"{pat} {path}".strip()
        return name
    elif name == 'Glob':
        return args.get('pattern', '') or name
    elif name == 'Agent':
        return args.get('description', '') or name
    elif name == 'WebFetch':
        return args.get('url', '') or name
    elif name == 'WebSearch':
        return args.get('query', '') or name
    else:
        # Generic: first string value
        for v in args.values():
            if isinstance(v, str) and v:
                return v
        return name

def add_line_to_stats(stats, data):
    """Parse a single JSONL entry and accumulate into stats."""
    entry_type = data.get('type', '')

    # Count tool calls
    if entry_type == 'function_call':
        name = data.get('name', '')
        if name:
            stats["tool_counts"][name] = stats["tool_counts"].get(name, 0) + 1
            if name == 'Agent':
                stats["running_agents"] += 1
            # Track recent calls
            adt = data.get('argumentsDisplayText', '')
            if adt:
                summary = adt
            else:
                args_raw = data.get('arguments', '')
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else {})
                except (json.JSONDecodeError, TypeError):
                    args = {}
                summary = _extract_call_summary(name, args)
            stats["recent_calls"].append({"name": name, "summary": summary})
            stats["recent_calls"] = stats["recent_calls"][-RECENT_CALLS_MAX:]

    elif entry_type == 'function_call_result' and data.get('name') == 'Agent':
        stats["running_agents"] -= 1

    # Count context compaction events
    # type=message, providerData.isCompactInternal=true + isSummary=true
    # Each compact produces 2 message entries (summary + "Please continue");
    # only the summary one has isSummary=true, to avoid double-counting.
    if entry_type == 'message':
        pd = data.get('providerData', {})
        if isinstance(pd, dict) and pd.get('isCompactInternal') and pd.get('isSummary'):
            stats["compact_count"] += 1

    # Count periodic summaries
    elif entry_type == 'summary':
        pd = data.get('providerData', {})
        if isinstance(pd, dict):
            source = pd.get('source')
            if source not in ('initial-user-message', None):
                stats["periodic_count"] += 1

    # Token usage — In/Out/Cache/Think/Credits from providerData
    pd = data.get('providerData')
    if not isinstance(pd, dict):
        return

    usage = pd.get('usage') or {}
    raw_usage = pd.get('rawUsage') or {}

    if not usage and not raw_usage:
        return

    input_tokens = usage.get('inputTokens', 0) or 0
    output_tokens = usage.get('outputTokens', 0) or 0
    # Cache read tokens are in inputTokensDetails[].cached_tokens
    cache_read = sum(
        detail.get('cached_tokens', 0) or 0
        for detail in (usage.get('inputTokensDetails') or [])
    )

    reasoning = sum(
        detail.get('reasoning_tokens', 0) or 0
        for detail in (usage.get('outputTokensDetails') or [])
    )

    credit = 0
    if raw_usage:
        if 'prompt_cache_hit_tokens' in raw_usage:
            cache_read = raw_usage['prompt_cache_hit_tokens'] or 0
        credit = raw_usage.get('credit', 0) or 0

    if input_tokens > 0 or output_tokens > 0:
        stats["total_input"] += input_tokens
        stats["total_output"] += output_tokens
        stats["total_cache_read"] += cache_read
        stats["total_reasoning"] += reasoning
        stats["total_credits"] += credit
        stats["request_count"] += 1
        # 记录最近一次交互
        stats["last_input"] = input_tokens
        stats["last_output"] = output_tokens
        stats["last_cache_read"] = cache_read
        stats["last_credits"] = credit
        # 计算 cost: 优先用 rawUsage 里的，否则从 usage 估算
        if raw_usage:
            stats["last_cost"] = raw_usage.get('cost', 0) or 0
        else:
            # 无 rawUsage 时无法精确计算单次 cost，置 0
            stats["last_cost"] = 0

def load_cache(session_id):
    """Load the cache for a session.

    The cache file ({session_id}.json) contains:
        {
            "stats": {...accumulated stats...},
            "main_offset": <int>,
            "sub_offsets": {<agent_key>: <int>, ...},
            "cache_version": <int>
        }

    Returns the parsed dict, or None if the file is missing/corrupt.
    """
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError, KeyError):
        return None

def save_cache(session_id, stats, main_offset, sub_offsets=None):
    """Save the cache for a session atomically (write-to-temp + rename)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, 'w') as f:
            json.dump({
                "stats": stats,
                "main_offset": main_offset,
                "sub_offsets": sub_offsets or {},
                "cache_version": CACHE_VERSION,
            }, f)
        os.replace(tmp_path, cache_path)
    except IOError:
        pass

def maybe_auto_update():
    """Try to git-pull the plugin repo at most once per day (git-clone mode only).

    Skipped entirely when installed via plugin marketplace (IS_PLUGIN_MODE),
    since updates are managed by `codebuddy plugin update`.

    Throttles via a marker file (mtime). The git pull runs in a fully detached
    background process so it never blocks the statusline.
    """
    if IS_PLUGIN_MODE:
        return

    git_dir = os.path.join(PLUGIN_DIR, ".git")
    if not os.path.isdir(git_dir):
        return

    try:
        last_check = os.path.getmtime(UPDATE_MARKER)
        if time.time() - last_check < UPDATE_INTERVAL_SECONDS:
            return
    except OSError:
        pass

    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time())))
    except OSError:
        return

    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        subprocess.Popen(
            ["git", "-C", PLUGIN_DIR, "pull", "--ff-only", "--quiet"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception:
        pass


def cleanup_old_caches(current_session_id):
    """Remove cache files older than CACHE_MAX_AGE_DAYS, excluding current session."""
    if not os.path.isdir(CACHE_DIR):
        return
    now = time.time()
    max_age = CACHE_MAX_AGE_DAYS * 86400  # seconds
    try:
        for fname in os.listdir(CACHE_DIR):
            fpath = os.path.join(CACHE_DIR, fname)
            # Clean up stale .tmp files from interrupted atomic writes
            if fname.endswith('.tmp'):
                try:
                    os.remove(fpath)
                except OSError:
                    pass
                continue
            if not fname.endswith('.json'):
                continue
            key = fname[:-5]  # strip .json
            # Protect current session's cache
            if key == current_session_id:
                continue
            try:
                if now - os.path.getmtime(fpath) > max_age:
                    os.remove(fpath)
            except OSError:
                pass
    except OSError:
        pass

def parse_transcript_incremental(transcript_path, session_id):
    """Parse main + sub-agent transcripts incrementally.

    Extracts In/Out/Cache/Think/Credits/Req/Tools/Compact/Periodic from all transcripts.
    Sub-agents contribute to token/credit/tool counts but NOT to
    running_agents, compact_count, or periodic_count (those are main-transcript-only).

    Skip-write: if no new data was found, skip writing the cache entirely.
    Truncation handling: if any transcript was truncated, discard all cached
    stats and re-parse everything from scratch. This avoids double-counting
    when we can't subtract old per-sub-agent contributions.
    """
    stats = new_stats()

    if not transcript_path:
        return stats, False

    # Determine sub-agent directory
    session_dir = transcript_path[:-6] if transcript_path.endswith('.jsonl') else transcript_path
    subagents_dir = os.path.join(session_dir, "subagents")

    # Load cache
    cache = load_cache(session_id)
    if cache and cache.get("cache_version") != CACHE_VERSION:
        cache = None
    previous_running_agents = 0
    main_offset = 0
    sub_offsets = {}
    if cache:
        if "stats" in cache and isinstance(cache["stats"], dict):
            stats = cache["stats"]
            # Backfill new fields and remove obsolete keys for same-version caches
            valid_keys = set(new_stats().keys())
            for key, default in new_stats().items():
                if key not in stats:
                    if isinstance(default, list):
                        stats[key] = list(default)
                    elif isinstance(default, dict):
                        stats[key] = dict(default)
                    else:
                        stats[key] = default
            for obsolete in list(stats.keys()):
                if obsolete not in valid_keys:
                    del stats[obsolete]
            previous_running_agents = stats.get("running_agents", 0)
        if "main_offset" in cache and isinstance(cache["main_offset"], (int, float)):
            main_offset = cache["main_offset"]
        if "sub_offsets" in cache and isinstance(cache["sub_offsets"], dict):
            sub_offsets = cache["sub_offsets"]

    any_new_data = False
    any_truncated = False

    # Validate offset type to handle corrupted cache
    if not isinstance(main_offset, (int, float)):
        main_offset = 0

    # --- Check for truncation across all transcripts ---
    need_full_reparse = False

    try:
        file_size = os.path.getsize(transcript_path)
        if main_offset > file_size:
            need_full_reparse = True
    except (IOError, OSError):
        pass

    if not need_full_reparse and os.path.isdir(subagents_dir):
        try:
            for fname in os.listdir(subagents_dir):
                if not fname.endswith('.jsonl'):
                    continue
                agent_key = fname[:-6]
                sub_offset = sub_offsets.get(agent_key, 0)
                if not isinstance(sub_offset, (int, float)):
                    sub_offset = 0
                sub_path = os.path.join(subagents_dir, fname)
                try:
                    if sub_offset > os.path.getsize(sub_path):
                        need_full_reparse = True
                        break
                except (IOError, OSError):
                    pass
        except OSError:
            pass

    # --- Full re-parse: discard cache, parse everything from offset 0 ---
    if need_full_reparse:
        any_truncated = True
        main_offset = 0
        sub_offsets = {}
        stats = new_stats()
        previous_running_agents = 0

    # --- Parse main transcript ---
    try:
        file_size = os.path.getsize(transcript_path)

        # Fast path: no new data in main transcript
        if main_offset == file_size and main_offset > 0:
            pass
        else:
            delta = new_stats()
            with open(transcript_path, 'rb') as f:
                if main_offset > 0:
                    f.seek(main_offset)
                has_new_data = False
                failed_line_offset = None
                while True:
                    line_start = f.tell()
                    raw_line = f.readline()
                    if not raw_line:
                        break
                    has_new_data = True
                    try:
                        line = raw_line.decode('utf-8')
                    except UnicodeDecodeError:
                        continue
                    # If line has no trailing newline, the writer is likely
                    # mid-write. Stop reading here so we don't advance the
                    # offset past this partial line. On the next cycle, we'll
                    # re-read from this offset and hopefully get the full line.
                    if not line.endswith('\n'):
                        failed_line_offset = line_start
                        break
                    # Pre-filter: skip lines that can't contribute to stats.
                    # Must cover all entry types processed by add_line_to_stats:
                    # function_call, function_call_result, summary, and anything with providerData.
                    # If add_line_to_stats is extended to handle new entry types,
                    # update this filter accordingly.
                    if ('function_call' not in line
                            and 'providerData' not in line
                            and '"summary"' not in line):
                        continue
                    try:
                        data = json.loads(line)
                        add_line_to_stats(delta, data)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue

                new_offset = failed_line_offset if failed_line_offset is not None else f.tell()

            if has_new_data:
                any_new_data = True

            if need_full_reparse:
                # Stats were reset; delta IS the new stats
                stats = delta
                stats["running_agents"] = max(0, stats["running_agents"])
            else:
                # Merge delta into existing stats
                # last_* fields are "last value" not cumulative;
                # only overwrite when delta has a non-zero value (i.e. a new API response)
                for key in delta:
                    if key == "running_agents":
                        continue
                    if key in _LAST_KEYS:
                        if delta[key]:
                            stats[key] = delta[key]
                        continue
                    if isinstance(delta[key], (int, float)):
                        stats[key] = stats.get(key, 0) + delta[key]
                    elif isinstance(delta[key], dict):
                        if not isinstance(stats.get(key), dict):
                            stats[key] = {}
                        for k, v in delta[key].items():
                            stats[key][k] = stats[key].get(k, 0) + v
                    elif isinstance(delta[key], list):
                        stats[key] = (stats.get(key) or []) + delta[key]
                        stats[key] = stats[key][-RECENT_CALLS_MAX:]
                stats["running_agents"] = max(0, delta["running_agents"] + previous_running_agents)

            if new_offset > 0:
                main_offset = new_offset

    except (IOError, OSError):
        pass

    # --- Parse sub-agent transcripts ---
    if os.path.isdir(subagents_dir):
        try:
            for fname in os.listdir(subagents_dir):
                if not fname.endswith('.jsonl'):
                    continue
                agent_key = fname[:-6]
                sub_path = os.path.join(subagents_dir, fname)
                sub_offset = sub_offsets.get(agent_key, 0)
                if not isinstance(sub_offset, (int, float)):
                    sub_offset = 0

                try:
                    sub_size = os.path.getsize(sub_path)

                    if sub_offset == sub_size and sub_offset > 0:
                        continue

                    sub_delta = new_stats()
                    with open(sub_path, 'rb') as f:
                        if sub_offset > 0:
                            f.seek(sub_offset)
                        sub_has_new = False
                        sub_failed_offset = None
                        while True:
                            line_start = f.tell()
                            raw_line = f.readline()
                            if not raw_line:
                                break
                            sub_has_new = True
                            try:
                                line = raw_line.decode('utf-8')
                            except UnicodeDecodeError:
                                continue
                            # Partial line: stop reading, retry next cycle
                            if not line.endswith('\n'):
                                sub_failed_offset = line_start
                                break
                            if ('function_call' not in line
                                    and 'providerData' not in line
                                    and '"summary"' not in line):
                                continue
                            try:
                                data = json.loads(line)
                                add_line_to_stats(sub_delta, data)
                            except (json.JSONDecodeError, KeyError, TypeError):
                                continue
                        new_sub_offset = sub_failed_offset if sub_failed_offset is not None else f.tell()

                    if sub_has_new:
                        any_new_data = True

                    # Merge sub-agent delta into main stats
                    # Sub-agents contribute tokens/credits/tools but NOT running_agents/compact_count/periodic_count
                    # last_* fields: only overwrite when sub_delta has a non-zero value
                    for key in sub_delta:
                        if key in ("running_agents", "compact_count", "periodic_count"):
                            continue
                        if key in _LAST_KEYS:
                            if sub_delta[key]:
                                stats[key] = sub_delta[key]
                            continue
                        if isinstance(sub_delta[key], (int, float)):
                            stats[key] = stats.get(key, 0) + sub_delta[key]
                        elif isinstance(sub_delta[key], dict):
                            if not isinstance(stats.get(key), dict):
                                stats[key] = {}
                            for k, v in sub_delta[key].items():
                                stats[key][k] = stats[key].get(k, 0) + v
                        elif isinstance(sub_delta[key], list):
                            # NOTE: sub-agent calls are appended after main calls,
                            # so the "most recent 3" may not reflect true chronological
                            # order across main + sub transcripts. This is acceptable
                            # since transcripts lack interleaved timestamps.
                            stats[key] = (stats.get(key) or []) + sub_delta[key]
                            stats[key] = stats[key][-RECENT_CALLS_MAX:]

                    sub_offsets[agent_key] = new_sub_offset

                except (IOError, OSError):
                    pass
        except OSError:
            pass

    # Skip cache write when nothing changed and no truncation occurred.
    if any_new_data or any_truncated or cache is None:
        save_cache(session_id, stats, main_offset, sub_offsets)

    # Cleanup old caches ~1% of the time to avoid O(n) scan every 300ms.
    if int(time.time() * 1000) % 97 < 1:
        cleanup_old_caches(session_id)

    return stats, any_truncated

def _format_tool_entry(prefix, color, name, count=None):
    """Format a single tool entry like '✓ Bash×3' or '↑ Agent'.

    Count is shown only when > 1.
    """
    entry = f"{color}{prefix}{NC} {name}"
    if count is not None and count > 1:
        entry += f"{DIM}×{count}{NC}"
    return entry


def format_tools(tool_counts, running_agents=0):
    """Format tool usage like: ✓ Bash×15 ✓ Read×2 ✓ Edit
    Agent shows running count: ↑ Agent×2 or just ✓ Agent×3"""
    if not tool_counts and running_agents == 0:
        return ""

    # Order: known tools first, then any others alphabetically
    ordered = []
    seen = set()
    for name in TOOL_ORDER:
        if name in tool_counts:
            ordered.append((name, tool_counts[name]))
            seen.add(name)
    for name in sorted(tool_counts.keys()):
        if name not in seen:
            ordered.append((name, tool_counts[name]))

    parts = []
    for name, count in ordered:
        short = TOOL_SHORT.get(name, name)
        if name == 'Agent' and running_agents > 0:
            parts.append(_format_tool_entry("↑", YELLOW, "Agent", running_agents))
            completed = count - running_agents
            if completed > 0:
                parts.append(_format_tool_entry("✓", GREEN, "Agent", completed))
        else:
            parts.append(_format_tool_entry("✓", GREEN, short, count))

    return " | ".join(parts)

def format_recent_calls(recent_calls):
    """Format the most recent function calls as line 3.

    Each call shows: ToolName summary_text(truncated)
    """
    if not recent_calls:
        return ""

    parts = []
    for call in reversed(recent_calls):
        name = call.get('name', '')
        summary = call.get('summary', '')
        short = TOOL_SHORT.get(name, name)
        if summary and summary != name:
            # Truncate to RECENT_CALLS_SUMMARY_LEN visible columns (CJK-safe).
            # Previously used len() which miscounts wide characters and can
            # split ANSI escape sequences.
            summary = truncate_to_width(summary, RECENT_CALLS_SUMMARY_LEN)
            parts.append(f"{CYAN}{short}{NC} {DIM}{summary}{NC}")
        else:
            parts.append(f"{CYAN}{short}{NC}")
    return " | ".join(parts)

def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    model = input_data.get('model') or {}
    model_name = model.get('display_name', '')
    cost = input_data.get('cost') or {}
    transcript_path = input_data.get('transcript_path', '')
    session_id = input_data.get('session_id', '')

    # Context window data (provided by CodeBuddy Code)
    ctx = input_data.get('context_window') or {}

    total_cost = cost.get('total_cost_usd', 0) or 0
    duration_ms = cost.get('total_duration_ms', 0) or 0
    lines_added = cost.get('total_lines_added', 0) or 0
    lines_removed = cost.get('total_lines_removed', 0) or 0

    # Incremental parse for all metrics from main + sub-agent transcripts
    stats, was_truncated = parse_transcript_incremental(transcript_path, session_id)

    parts = []

    cwd_name = os.path.basename(os.getcwd())

    # Git branch info (between cwd and model name)
    workspace = input_data.get('workspace') or {}
    git_cwd = workspace.get('current_dir') or os.getcwd()
    git_info = get_git_info(git_cwd)
    git_part = format_git_info(git_info) if git_info else ""

    if cwd_name and git_part:
        parts.append(f"{CYAN}{cwd_name}{NC} {git_part}")
    elif cwd_name:
        parts.append(f"{CYAN}{cwd_name}{NC}")
    elif git_part:
        parts.append(git_part)

    if model_name:
        parts.append(f"{BLUE}{model_name}{NC}")

    # Context progress bar
    used_pct = ctx.get('used_percentage')
    ctx_size = ctx.get('context_window_size', 0) or 0
    current_usage = ctx.get('current_usage') or {}
    current_tokens = 0
    if isinstance(current_usage, dict):
        current_tokens = current_usage.get('input_tokens', 0) or 0

    if used_pct is not None:
        try:
            # used_pct can be 0-100 (percentage) or 0-1 (ratio); normalize to 0-1
            pct = min(used_pct / 100.0, 1.0) if used_pct > 1 else min(used_pct, 1.0)
        except (TypeError, ValueError):
            used_pct = None
        else:
            bar, bar_color = make_progress_bar(pct, width=10)
            pct_display = int(pct * 100)
            if ctx_size > 0 and current_tokens > 0:
                ctx_str = f"{format_tokens(current_tokens)}/{format_tokens(ctx_size)}"
            elif ctx_size > 0:
                ctx_str = format_tokens(ctx_size)
            else:
                ctx_str = ""
            ctx_part = f"{bar_color}▕{bar}▏{NC}{DIM}{pct_display}%{NC}"
            if ctx_str:
                ctx_part += f" {DIM}{ctx_str}{NC}"
            parts.append(ctx_part)

    # Compact/Periodic counts: always show when present, even if
    # used_percentage is null (e.g. first call right after compact).
    cp_parts = ""
    if stats.get('compact_count', 0) > 0:
        cp_parts += f" {YELLOW}Compact×{stats['compact_count']}{NC}"
    if stats.get('periodic_count', 0) > 0:
        cp_parts += f" {DIM}Periodic×{stats['periodic_count']}{NC}"
    if cp_parts:
        if parts:
            parts[-1] += cp_parts
        else:
            parts.append(cp_parts.strip())

    if used_pct is None and ctx_size > 0:
        # No percentage data, but we still have max context size
        ctx_part = f"{DIM}Max:{format_tokens(ctx_size)}{NC}"
        parts.append(ctx_part)

    # Token usage display.
    # In/Out come from transcript parsing (main + sub-agents),
    # falling back to CodeBuddy's context_window values if transcript has no data.
    # Cache/Think have no context_window fallback — they only come from transcript parsing.
    display_in = stats.get('total_input', 0) or ctx.get('total_input_tokens') or 0
    display_out = stats.get('total_output', 0) or ctx.get('total_output_tokens') or 0
    display_cache = stats.get('total_cache_read', 0)

    token_parts = [
        f"{GREEN}In:{NC}{format_tokens(display_in)}",
        f"{GREEN}Out:{NC}{format_tokens(display_out)}",
    ]
    if display_cache > 0:
        token_parts.append(f"{DIM}Cache:{NC}{format_tokens(display_cache)}")
    if stats.get('total_reasoning', 0) > 0:
        token_parts.append(f"{DIM}Think:{NC}{format_tokens(stats['total_reasoning'])}")
    parts.append(" ".join(token_parts))

    if stats.get('request_count', 0) > 0:
        parts.append(f"{CYAN}Req:{NC}{stats['request_count']}")

    # 总费用 = 平台返回的 cost + credits 换算的美元
    credits_usd = (stats.get('total_credits', 0) or 0) * CREDITS_TO_USD
    combined_cost = total_cost + credits_usd
    cost_str = format_cost(combined_cost)
    if cost_str:
        parts.append(f"{RED}Cost:{NC}{cost_str}")

    if stats.get('total_credits', 0) > 0:
        parts.append(f"{YELLOW}Credits:{NC}{stats['total_credits']:.2f}")

    duration_str = format_duration(duration_ms)
    if duration_str:
        parts.append(f"{DIM}Time:{NC}{duration_str}")

    if lines_added > 0 or lines_removed > 0:
        parts.append(f"{GREEN}+{lines_added}{NC}/{RED}-{lines_removed}{NC}")

    output = " | ".join(parts)

    # Line 2: Tools (with Agent running/completed status)
    tool_str = format_tools(stats.get('tool_counts', {}), stats.get('running_agents', 0))
    if tool_str:
        output += f"\n{DIM}Tools:{NC} {tool_str}"

    # Line 3: Last interaction token details + Recent function calls
    recent_parts = []

    # 最近一次交互的 In/Out/Cache/Credits/Cost 详情
    last_in = stats.get('last_input', 0) or 0
    last_out = stats.get('last_output', 0) or 0
    last_cache = stats.get('last_cache_read', 0) or 0
    last_credits = stats.get('last_credits', 0) or 0
    last_cost = stats.get('last_cost', 0) or 0
    if last_in > 0 or last_out > 0:
        last_parts = [
            f"{GREEN}In:{NC}{format_tokens(last_in)}",
            f"{GREEN}Out:{NC}{format_tokens(last_out)}",
        ]
        if last_cache > 0:
            cache_pct = int(last_cache / last_in * 100) if last_in > 0 else 0
            last_parts.append(f"{DIM}Cache:{NC}{format_tokens(last_cache)}({cache_pct}%)")
        last_combined = last_cost + last_credits * CREDITS_TO_USD
        last_cost_str = format_cost(last_combined)
        if last_cost_str:
            last_parts.append(f"{RED}Cost:{NC}{last_cost_str}")
        if last_credits > 0:
            last_parts.append(f"{YELLOW}Credits:{NC}{last_credits:.2f}")
        recent_parts.append(" ".join(last_parts))

    # Recent function calls with truncated content
    recent_str = format_recent_calls(stats.get('recent_calls', []))
    if recent_str:
        recent_parts.append(recent_str)

    if recent_parts:
        output += f"\n{DIM}Recent:{NC} {' | '.join(recent_parts)}"

    # Truncate each line to terminal width so the renderer never wraps
    # a long line and visually squeezes the row below out of view.
    # We leave a small slack so the rightmost column has breathing room.
    # Width comes from the host's reported terminal_width (stdin JSON)
    # with /dev/tty TIOCGWINSZ as fallback.
    # If width is 0 (no TTY, no fallback), skip truncation entirely.
    width = get_statusline_width_from_input(input_data)
    if width > 0:
        output = "\n".join(
            truncate_to_width(line, max(20, width - 2))
            for line in output.split("\n")
        )

    print(output)

    # Auto-update (git-clone mode only, at most once per day, runs detached).
    try:
        maybe_auto_update()
    except Exception:
        pass

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # Global safety net: if anything crashes, still output something
        # so the statusline never goes blank silently.
        print(f"{RED}ERR:{NC}{type(e).__name__}: {e}")
