#!/usr/bin/env python3
"""
CodeBuddy Code Cost Monitor - Statusline Script (Incremental)
Displays real-time cost, token usage, context progress, tools usage, and request stats.

Uses incremental parsing for all metrics from main + sub-agent transcripts.
In/Out/Cache/Credits include sub-agent data for a complete picture.
"""

import json
import sys
import os
import time

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
CACHE_VERSION = 7

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

RECENT_CALLS_MAX = 3
RECENT_CALLS_SUMMARY_LEN = 60

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
            stats["recent_calls"] = stats.get("recent_calls", [])
            stats["recent_calls"].append({"name": name, "summary": summary})
            stats["recent_calls"] = stats["recent_calls"][-RECENT_CALLS_MAX:]

    elif entry_type == 'function_call_result' and data.get('name') == 'Agent':
        stats["running_agents"] -= 1

    # Count context compaction events
    elif entry_type == 'summary':
        pd = data.get('providerData', {})
        if isinstance(pd, dict):
            source = pd.get('source')
            if source == 'pre-compact':
                stats["compact_count"] += 1
            elif source not in ('initial-user-message', None):
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
    """Save the cache for a session."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    try:
        with open(cache_path, 'w') as f:
            json.dump({
                "stats": stats,
                "main_offset": main_offset,
                "sub_offsets": sub_offsets or {},
                "cache_version": CACHE_VERSION,
            }, f)
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
        pid = os.fork()
    except OSError:
        return

    if pid != 0:
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        return

    try:
        os.setsid()
    except OSError:
        os._exit(0)

    try:
        pid2 = os.fork()
    except OSError:
        os._exit(0)

    if pid2 != 0:
        os._exit(0)

    try:
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
            with open(transcript_path, 'r', encoding='utf-8') as f:
                if main_offset > 0:
                    f.seek(main_offset)
                has_new_data = False
                for line in f:
                    has_new_data = True
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

                new_offset = f.tell()

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
                _LAST_KEYS = ("last_input", "last_output", "last_cache_read", "last_credits", "last_cost")
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
                    with open(sub_path, 'r', encoding='utf-8') as f:
                        if sub_offset > 0:
                            f.seek(sub_offset)
                        sub_has_new = False
                        for line in f:
                            sub_has_new = True
                            if ('function_call' not in line
                                    and 'providerData' not in line
                                    and '"summary"' not in line):
                                continue
                            try:
                                data = json.loads(line)
                                add_line_to_stats(sub_delta, data)
                            except (json.JSONDecodeError, KeyError, TypeError):
                                continue
                        new_sub_offset = f.tell()

                    if sub_has_new:
                        any_new_data = True

                    # Merge sub-agent delta into main stats
                    # Sub-agents contribute tokens/credits/tools but NOT running_agents/compact_count/periodic_count
                    # last_* fields: only overwrite when sub_delta has a non-zero value
                    _LAST_KEYS = ("last_input", "last_output", "last_cache_read", "last_credits", "last_cost")
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
            # Truncate and add ellipsis if needed
            if len(summary) > RECENT_CALLS_SUMMARY_LEN:
                summary = summary[:RECENT_CALLS_SUMMARY_LEN - 1] + "…"
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

    if model_name:
        parts.append(f"{BLUE}{model_name}{NC}")

    # Context progress bar
    used_pct = ctx.get('used_percentage')
    ctx_size = ctx.get('context_window_size', 0) or 0
    current_usage = ctx.get('current_usage') or {}
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
        if stats.get('compact_count', 0) > 0:
            ctx_part += f" {YELLOW}Auto-Compact×{stats['compact_count']}{NC}"
        if stats.get('periodic_count', 0) > 0:
            ctx_part += f" {DIM}Periodic×{stats['periodic_count']}{NC}"
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
