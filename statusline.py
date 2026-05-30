#!/usr/bin/env python3
"""
CodeBuddy Code Cost Monitor - Statusline Script (Incremental)
Displays real-time cost, token usage, context progress, tools usage, and request stats.

Uses incremental parsing for token/tool stats from transcript, and reads
context_window data directly from the statusline JSON input.
"""

import json
import sys
import os
import time

CACHE_DIR = os.path.expanduser("~/.codebuddy/statusline-cache")
CACHE_MAX_AGE_DAYS = 7

# Auto-update: marker file used to throttle git-pull to once per day
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_MARKER = os.path.join(CACHE_DIR, ".last-update-check")
UPDATE_INTERVAL_SECONDS = 86400  # once per day

# ANSI color codes
CYAN = '\033[0;36m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
RED = '\033[0;31m'
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

def format_cost(usd):
    if usd is None or usd == 0:
        return ""
    if usd < 0.01:
        return f"${usd:.4f}"
    elif usd < 1:
        return f"${usd:.3f}"
    else:
        return f"${usd:.2f}"

def format_duration(ms):
    if ms is None or ms == 0:
        return ""
    s = int(ms) // 1000
    if s < 60:
        return f"{s}s"
    m = s // 60
    s = s % 60
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

def new_stats():
    return {
        "total_input": 0,
        "total_output": 0,
        "total_cache_read": 0,
        "total_cache_write": 0,
        "total_reasoning": 0,
        "total_credits": 0.0,
        "request_count": 0,
        "tool_counts": {},
        "running_agents": 0,
    }

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

    elif entry_type == 'function_call_result' and data.get('name') == 'Agent':
        stats["running_agents"] -= 1

    # Token usage
    pd = data.get('providerData', {})
    if not isinstance(pd, dict):
        return

    usage = pd.get('usage', {})
    raw_usage = pd.get('rawUsage', {})

    if not usage and not raw_usage:
        return

    input_tokens = usage.get('inputTokens', 0) or 0
    output_tokens = usage.get('outputTokens', 0) or 0

    cache_read = sum(
        detail.get('cached_tokens', 0) or 0
        for detail in (usage.get('inputTokensDetails') or [])
    )
    reasoning = sum(
        detail.get('reasoning_tokens', 0) or 0
        for detail in (usage.get('outputTokensDetails') or [])
    )

    if raw_usage:
        cache_read = raw_usage.get('prompt_cache_hit_tokens', cache_read) or cache_read
        cache_write = raw_usage.get('cache_creation_input_tokens', 0) or 0
        credit = raw_usage.get('credit', 0) or 0
    else:
        cache_write = 0
        credit = 0

    if input_tokens > 0 or output_tokens > 0:
        stats["total_input"] += input_tokens
        stats["total_output"] += output_tokens
        stats["total_cache_read"] += cache_read
        stats["total_cache_write"] += cache_write
        stats["total_reasoning"] += reasoning
        stats["total_credits"] += credit
        stats["request_count"] += 1

def load_cache(session_id):
    """Load the unified cache for a session.

    The unified cache file ({session_id}.json) contains:
        {
            "stats": {...accumulated stats...},
            "main_offset": <int>,
            "sub_offsets": {"agent-abc": <int>, ...}
        }

    Returns the parsed dict, or None if the file is missing/corrupt.
    """
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError, KeyError):
        return None

def save_cache(session_id, stats, main_offset, sub_offsets):
    """Save the unified cache for a session.

    Args:
        session_id: Session identifier (used as cache filename).
        stats: Accumulated stats dict.
        main_offset: Byte offset into the main transcript.
        sub_offsets: Dict mapping sub-agent name to byte offset.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    try:
        with open(cache_path, 'w') as f:
            json.dump({
                "stats": stats,
                "main_offset": main_offset,
                "sub_offsets": sub_offsets,
            }, f)
    except IOError:
        pass

def maybe_auto_update():
    """Try to git-pull the plugin repo at most once per day.

    Throttles via a marker file (mtime). The git pull runs in a fully detached
    background process so it never blocks the statusline. Failures are silent:
    no network, no git, not a git repo, etc. all just no-op.

    Design choices:
    - Daemonized via double-fork so the parent (statusline) returns immediately
      without waiting for git. The grandchild is reparented to PID 1.
    - All git output is discarded (we don't surface errors).
    - Marker file is written BEFORE the pull starts so even if git hangs or
      fails, we still wait a full day before retrying.
    - Uses --ff-only to avoid merge commits or conflicts; if local changes
      exist, the pull simply fails harmlessly.
    """
    # Quick check: is the plugin directory a git repo?
    git_dir = os.path.join(PLUGIN_DIR, ".git")
    if not os.path.isdir(git_dir):
        return

    # Throttle: only attempt once per UPDATE_INTERVAL_SECONDS
    try:
        last_check = os.path.getmtime(UPDATE_MARKER)
        if time.time() - last_check < UPDATE_INTERVAL_SECONDS:
            return
    except OSError:
        pass  # marker doesn't exist yet — proceed

    # Touch the marker first so a hanging git doesn't keep us retrying
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time())))
    except OSError:
        return  # can't write marker — skip update to avoid retry storm

    # Double-fork to fully detach the git process from the statusline.
    # The first child forks again and exits; the grandchild does the work
    # and is adopted by init (PID 1), so we don't leave zombies.
    try:
        pid = os.fork()
    except OSError:
        return  # fork failed — give up

    if pid != 0:
        # Parent: reap the first child to avoid a zombie, then return immediately.
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        return

    # First child: detach from parent's session and fork again
    try:
        os.setsid()
    except OSError:
        os._exit(0)

    try:
        pid2 = os.fork()
    except OSError:
        os._exit(0)

    if pid2 != 0:
        # First child exits immediately; grandchild is reparented to init.
        os._exit(0)

    # Grandchild: actually run the git pull.
    try:
        # Redirect stdin/stdout/stderr to /dev/null so git can't write anywhere.
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)
    except OSError:
        os._exit(0)

    try:
        import subprocess
        subprocess.run(
            ["git", "-C", PLUGIN_DIR, "pull", "--ff-only", "--quiet"],
            timeout=30,
            check=False,
        )
    except Exception:
        pass
    finally:
        os._exit(0)


def cleanup_old_caches(current_session_id):
    """Remove cache files older than CACHE_MAX_AGE_DAYS, excluding current session."""
    if not os.path.isdir(CACHE_DIR):
        return
    now = time.time()
    max_age = CACHE_MAX_AGE_DAYS * 86400  # seconds
    try:
        for fname in os.listdir(CACHE_DIR):
            if not fname.endswith('.json'):
                continue
            fpath = os.path.join(CACHE_DIR, fname)
            key = fname[:-5]  # strip .json
            # Protect current session's cache (and any legacy split caches
            # that started with the session_id prefix)
            if key == current_session_id or key.startswith(current_session_id + "_"):
                continue
            try:
                if now - os.path.getmtime(fpath) > max_age:
                    os.remove(fpath)
            except OSError:
                pass
    except OSError:
        pass

def _parse_single_transcript_incremental(transcript_path, start_offset):
    """Parse a single transcript file incrementally from start_offset.

    Handles file truncation: if start_offset is beyond the current file size
    (e.g., file was rewritten or truncated), re-parses from offset 0.

    Returns:
        A tuple of (delta_stats, new_offset, truncated, has_new_data) where:
        - delta_stats: stats dict with new token/tool data from this read
        - new_offset: byte position after the last line read (0 on error)
        - truncated: True if the file was detected as truncated (caller
          should reset accumulated stats since delta_stats is a full
          re-parse from offset 0, not an incremental delta)
        - has_new_data: True if any data was actually read from the file.
    """
    new_stats_data = new_stats()

    if not transcript_path:
        return new_stats_data, 0, False, False

    # Validate offset type to handle corrupted cache (e.g., {"offset": "abc"})
    if not isinstance(start_offset, (int, float)):
        start_offset = 0

    truncated = False
    try:
        # Use os.path.getsize as the existence check (single stat call).
        # If the file doesn't exist, raises OSError caught below.
        file_size = os.path.getsize(transcript_path)

        # Fast path: file size unchanged since last read — nothing new.
        # Skips the open()/seek()/iterate() syscalls entirely. This is the
        # common case in steady state for sub-agents that have completed.
        if start_offset == file_size and start_offset > 0:
            return new_stats_data, start_offset, False, False

        # Detect truncation: cached offset is past current EOF
        if start_offset > file_size:
            start_offset = 0
            truncated = True

        with open(transcript_path, 'r', encoding='utf-8') as f:
            if start_offset > 0:
                f.seek(start_offset)
            has_new_data = False
            for line in f:
                has_new_data = True
                # Cheap string pre-filter: skip lines that don't contain any
                # of the markers we care about. Most transcript lines are
                # assistant text messages or tool results we don't track.
                # Avoids the json.loads cost for ~75% of lines on cold parses.
                if ('function_call' not in line
                        and 'providerData' not in line):
                    continue
                try:
                    data = json.loads(line)
                    add_line_to_stats(new_stats_data, data)
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

            new_offset = f.tell()

        return new_stats_data, new_offset, truncated, has_new_data

    except (IOError, OSError):
        return new_stats_data, 0, False, False


def _merge_delta(stats, delta, skip_keys=None):
    """Merge a delta stats dict into stats, adding numeric values and merging dicts."""
    skip_keys = skip_keys or set()
    for key in stats:
        if key in skip_keys:
            continue
        if isinstance(stats[key], (int, float)):
            stats[key] += delta[key]
        elif isinstance(stats[key], dict):
            for k, v in delta[key].items():
                stats[key][k] = stats[key].get(k, 0) + v


def parse_transcript_incremental(transcript_path, session_id):
    """Parse transcript incrementally, only reading new lines since last run.

    Also scans subagents/ directory for child agent transcripts and merges
    their token/tool stats into the total.

    All cache state (accumulated stats, main offset, sub-agent offsets) is
    stored in a single unified cache file per session, reducing I/O from
    2+N file opens to 1 in steady state.

    Note: running_agents is a gauge (not a counter), computed only from the
    main transcript's delta. Sub-agent deltas may contain their own Agent
    calls, but those don't affect the top-level running count.

    Skip-write: if no new data was found, skip writing the cache entirely.
    This avoids unnecessary I/O in steady state and eliminates the crash
    window for over-counts when nothing changed.

    Truncation handling: if the main transcript was truncated, the accumulated
    stats are discarded and replaced with a full re-parse. If a sub-agent
    was truncated, its delta is merged but a flag is set so the cache is
    still written (preventing a stuck state).
    """
    stats = new_stats()

    if not transcript_path:
        return stats

    # Load unified cache (single file open in steady state)
    cache = load_cache(session_id)
    previous_running_agents = 0
    main_offset = 0
    sub_offsets = {}
    if cache:
        if "stats" in cache and isinstance(cache["stats"], dict):
            stats = cache["stats"]
            previous_running_agents = stats.get("running_agents", 0)
        if "main_offset" in cache and isinstance(cache["main_offset"], (int, float)):
            main_offset = cache["main_offset"]
        if "sub_offsets" in cache and isinstance(cache["sub_offsets"], dict):
            sub_offsets = dict(cache["sub_offsets"])

    any_new_data = False
    any_truncated = False

    # Parse main transcript for new data
    main_delta, main_new_offset, main_truncated, main_has_new_data = (
        _parse_single_transcript_incremental(transcript_path, main_offset)
    )
    if main_truncated:
        # Main was truncated: discard cached stats; main_delta is a full re-parse
        any_truncated = True
        stats = main_delta
        previous_running_agents = 0
        sub_offsets = {}  # also reset sub-offsets — full re-parse implies fresh start
        stats["running_agents"] = max(0, stats["running_agents"])
    else:
        _merge_delta(stats, main_delta, skip_keys={"running_agents"})
        # running_agents is a gauge — compute from previous + delta, clamped to >= 0
        stats["running_agents"] = max(0, main_delta["running_agents"] + previous_running_agents)
    if main_has_new_data:
        any_new_data = True
    if main_new_offset > 0:
        main_offset = main_new_offset

    # Parse sub-agent transcripts
    # Directory structure: {session_id}.jsonl (main) and {session_id}/subagents/ (sub-agents)
    if transcript_path.endswith('.jsonl'):
        session_dir = transcript_path[:-6]  # strip .jsonl
    else:
        session_dir = transcript_path
    subagents_dir = os.path.join(session_dir, 'subagents')
    if os.path.isdir(subagents_dir):
        try:
            for fname in os.listdir(subagents_dir):
                if not fname.endswith('.jsonl'):
                    continue
                sub_path = os.path.join(subagents_dir, fname)
                if not os.path.isfile(sub_path):
                    continue
                sub_key = fname[:-6]  # strip .jsonl, use as dict key
                start_offset = sub_offsets.get(sub_key, 0)
                sub_delta, sub_new_offset, sub_truncated, sub_has_new_data = (
                    _parse_single_transcript_incremental(sub_path, start_offset)
                )
                if sub_truncated:
                    any_truncated = True
                _merge_delta(stats, sub_delta, skip_keys={"running_agents"})
                if sub_has_new_data:
                    any_new_data = True
                if sub_new_offset > 0:
                    sub_offsets[sub_key] = sub_new_offset
        except OSError:
            pass

    # Skip cache write when nothing changed and no truncation occurred.
    if any_new_data or any_truncated or cache is None:
        save_cache(session_id, stats, main_offset, sub_offsets)

    # Cleanup old caches ~1% of the time to avoid O(n) scan every 300ms.
    # Use time-based pseudo-randomness to avoid importing the `random` module
    # (saves ~1.2ms on cold start). 97 is prime and coprime to 300_000_000ns.
    if time.time_ns() % 97 < 1:
        cleanup_old_caches(session_id)

    return stats

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

    return " ".join(parts)

def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    model = input_data.get('model', {})
    model_name = model.get('display_name', '')
    cost = input_data.get('cost', {})
    transcript_path = input_data.get('transcript_path', '')
    session_id = input_data.get('session_id', '')

    # Context window data (provided by CodeBuddy Code)
    ctx = input_data.get('context_window', {})

    total_cost = cost.get('total_cost_usd', 0) or 0
    duration_ms = cost.get('total_duration_ms', 0) or 0
    lines_added = cost.get('total_lines_added', 0) or 0
    lines_removed = cost.get('total_lines_removed', 0) or 0

    # Incremental parse for token and tool stats
    stats = parse_transcript_incremental(transcript_path, session_id)

    parts = []

    if model_name:
        parts.append(f"{BLUE}{model_name}{NC}")

    # Context progress bar
    used_pct = ctx.get('used_percentage')
    ctx_size = ctx.get('context_window_size', 0) or 0
    current_usage = ctx.get('current_usage', {})
    current_tokens = 0
    if isinstance(current_usage, dict):
        current_tokens = current_usage.get('input_tokens', 0) or 0

    if used_pct is not None and used_pct > 0:
        # used_pct can be 0-100 (percentage) or 0-1 (ratio); normalize to 0-1
        pct = min(used_pct / 100.0, 1.0) if used_pct > 1 else min(used_pct, 1.0)
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

    # Token usage display.
    # `In` shows the total prompt size (inputTokens), matching CodeBuddy's
    # built-in display. `Cache` shows the cached portion (cache hits) which
    # is a subset of `In` — i.e. In already includes Cache. We don't subtract
    # Cache from In because users compare against the system's display, which
    # uses the raw inputTokens value.
    token_parts = [
        f"{GREEN}In:{NC}{format_tokens(stats['total_input'])}",
        f"{GREEN}Out:{NC}{format_tokens(stats['total_output'])}",
    ]
    if stats['total_cache_read'] > 0:
        token_parts.append(f"{DIM}Cache:{NC}{format_tokens(stats['total_cache_read'])}")
    if stats['total_reasoning'] > 0:
        token_parts.append(f"{DIM}Think:{NC}{format_tokens(stats['total_reasoning'])}")
    parts.append(" ".join(token_parts))

    if stats['request_count'] > 0:
        parts.append(f"{CYAN}Req:{NC}{stats['request_count']}")

    cost_str = format_cost(total_cost)
    if cost_str:
        if total_cost < 0.01:
            cost_color = GREEN
        elif total_cost < 0.1:
            cost_color = YELLOW
        else:
            cost_color = RED
        parts.append(f"{cost_color}Cost:{NC}{cost_str}")

    if stats['total_credits'] > 0:
        parts.append(f"{YELLOW}Credits:{NC}{stats['total_credits']:.2f}")

    duration_str = format_duration(duration_ms)
    if duration_str:
        parts.append(f"{DIM}Time:{NC}{duration_str}")

    if lines_added > 0 or lines_removed > 0:
        parts.append(f"{GREEN}+{lines_added}{NC}/{RED}-{lines_removed}{NC}")

    output = " | ".join(parts)

    # Line 2: Tools (with Agent running/completed status)
    tool_str = format_tools(stats['tool_counts'], stats['running_agents'])
    if tool_str:
        output += f"\n{tool_str}"

    print(output)

    # Try to auto-update the plugin (at most once per day, runs detached).
    # Done last so it never delays the statusline output.
    try:
        maybe_auto_update()
    except Exception:
        pass

if __name__ == '__main__':
    main()
