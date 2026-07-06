#!/usr/bin/env python3
"""Rendering: tool lists, recent calls, and the 3-line statusline assembly.

build_statusline(input_data, stats) assembles the full three-line output
that statusline.py's main() previously built inline. Keeping it here keeps
the entry point a thin orchestrator and groups all presentation logic.
"""

import os

from formatting import (
    BLUE,
    CYAN,
    CREDITS_TO_USD,
    DIM,
    GREEN,
    NC,
    RED,
    YELLOW,
    format_cost,
    format_duration,
    format_tokens,
    get_statusline_width_from_input,
    make_progress_bar,
    truncate_to_width,
)
from gitinfo import format_git_info, get_git_info

# Tool display order and short names
TOOL_ORDER = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Agent", "WebFetch", "WebSearch"]
TOOL_SHORT = {
    "Bash": "Bash", "Read": "Read", "Edit": "Edit", "Write": "Write",
    "Glob": "Glob", "Grep": "Grep", "Agent": "Agent",
    "WebFetch": "Fetch", "WebSearch": "Search",
}

RECENT_CALLS_SUMMARY_LEN = 60


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


def build_statusline(input_data, stats):
    """Assemble the full three-line statusline output from the parsed stats.

    Returns the string to print (already truncated to terminal width).
    Null-safe: model/cost/context_window fields may be missing.
    """
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
            # used_percentage is always 0-100 (host computes it as
            # Math.round(ratio * 1e4) / 100). The old `used_pct > 1`
            # heuristic misread sub-1% values (e.g. 0.81 meaning 0.81%)
            # as a 0-1 ratio (81%).
            pct = min(used_pct / 100.0, 1.0)
        except (TypeError, ValueError):
            used_pct = None
        else:
            bar, bar_color = make_progress_bar(pct, width=10)
            pct_display = round(pct * 100)
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

    if used_pct is None and ctx_size > 0:
        # No percentage data, but we still have max context size
        parts.append(f"{DIM}Max:{format_tokens(ctx_size)}{NC}")

    # Compact/Periodic counts: always show when present, even if
    # used_percentage is null (e.g. first call right after compact).
    cp_parts = ""
    if stats.get('compact_count', 0) > 0:
        cp_parts += f" {YELLOW}Compact×{stats['compact_count']}{NC}"
    if stats.get('periodic_count', 0) > 0:
        cp_parts += f" {DIM}Periodic×{stats['periodic_count']}{NC}"
    if cp_parts and parts:
        parts[-1] += cp_parts

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

    return output
