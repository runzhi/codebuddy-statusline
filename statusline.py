#!/usr/bin/env python3
"""
CodeBuddy Code Cost Monitor - Statusline Script (Incremental)
Displays real-time cost, token usage, context progress, and request stats.

Uses incremental parsing for token stats from transcript, and reads
context_window data directly from the statusline JSON input.
"""

import json
import sys
import os

CACHE_DIR = os.path.expanduser("~/.codebuddy/cost-monitor-cache")

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
    partial = pct * width - filled
    partial_idx = int(partial * 8)

    if filled >= width:
        bar = '█' * width
    elif filled > 0:
        bar = '█' * filled
        if filled < width:
            partial_chars = ' ▏▎▍▌▋▊▉█'
            if partial_idx > 0:
                bar += partial_chars[min(partial_idx, 7)]
                bar += ' ' * (width - filled - 1)
            else:
                bar += ' ' * (width - filled)
    else:
        bar = ' ' * width

    if pct < 0.5:
        color = '\033[0;32m'
    elif pct < 0.8:
        color = '\033[1;33m'
    else:
        color = '\033[0;31m'

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
    }

def add_line_to_stats(stats, data):
    """Parse a single JSONL entry and accumulate into stats."""
    pd = data.get('providerData', {})
    if not isinstance(pd, dict):
        return

    usage = pd.get('usage', {})
    raw_usage = pd.get('rawUsage', {})

    if not usage and not raw_usage:
        return

    input_tokens = usage.get('inputTokens', 0) or 0
    output_tokens = usage.get('outputTokens', 0) or 0

    cache_read = 0
    for detail in (usage.get('inputTokensDetails') or []):
        cache_read += detail.get('cached_tokens', 0) or 0

    reasoning = 0
    for detail in (usage.get('outputTokensDetails') or []):
        reasoning += detail.get('reasoning_tokens', 0) or 0

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
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError, KeyError):
        return None

def save_cache(session_id, offset, stats):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    try:
        with open(cache_path, 'w') as f:
            json.dump({"offset": offset, "stats": stats}, f)
    except IOError:
        pass

def cleanup_old_caches(current_session_id):
    if not os.path.isdir(CACHE_DIR):
        return
    try:
        for fname in os.listdir(CACHE_DIR):
            if not fname.endswith('.json'):
                continue
            sid = fname[:-5]
            if sid != current_session_id:
                try:
                    os.remove(os.path.join(CACHE_DIR, fname))
                except OSError:
                    pass
    except OSError:
        pass

def parse_transcript_incremental(transcript_path, session_id):
    """Parse transcript incrementally, only reading new lines since last run."""
    stats = new_stats()
    start_offset = 0

    if not transcript_path or not os.path.exists(transcript_path):
        return stats

    cache = load_cache(session_id)
    if cache:
        start_offset = cache["offset"]
        stats = cache["stats"]

    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            f.seek(start_offset)
            new_data_found = False
            for line in f:
                try:
                    data = json.loads(line)
                    add_line_to_stats(stats, data)
                    new_data_found = True
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

            new_offset = f.tell()

        if new_data_found or start_offset == 0:
            save_cache(session_id, new_offset, stats)

        cleanup_old_caches(session_id)

    except (IOError, OSError):
        pass

    return stats

def main():
    try:
        input_data = json.load(sys.stdin)
    except:
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

    # Incremental parse for token stats
    stats = parse_transcript_incremental(transcript_path, session_id)

    # ANSI colors
    CYAN = '\033[0;36m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    RED = '\033[0;31m'
    DIM = '\033[2m'
    NC = '\033[0m'

    parts = []

    if model_name:
        parts.append(f"{BLUE}{model_name}{NC}")

    # Context progress bar from statusline JSON
    used_pct = ctx.get('used_percentage')
    ctx_size = ctx.get('context_window_size', 0) or 0
    current_usage = ctx.get('current_usage', {})
    current_tokens = 0
    if isinstance(current_usage, dict):
        current_tokens = current_usage.get('input_tokens', 0) or 0

    if used_pct is not None and used_pct > 0:
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

    token_str = f"{GREEN}In:{NC}{format_tokens(stats['total_input'])}"
    token_str += f" {GREEN}Out:{NC}{format_tokens(stats['total_output'])}"
    if stats['total_cache_read'] > 0:
        token_str += f" {DIM}Cache:{NC}{format_tokens(stats['total_cache_read'])}"
    if stats['total_reasoning'] > 0:
        token_str += f" {DIM}Think:{NC}{format_tokens(stats['total_reasoning'])}"
    parts.append(token_str)

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

    print(" | ".join(parts))

if __name__ == '__main__':
    main()
