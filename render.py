#!/usr/bin/env python3
"""Rendering: tool lists, recent calls, and the 3-line statusline assembly.

build_statusline(input_data, stats) assembles the full three-line output
that statusline.py's main() previously built inline. Keeping it here keeps
the entry point a thin orchestrator and groups all presentation logic.
"""

import json
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


# ---------------------------------------------------------------------------
# Configurable layout
#
# The three-line statusline is assembled from discrete "blocks". A plugin-owned
# config file (<config-dir>/plugins/data/statusline/config.json, where
# config-dir = CODEBUDDY_CONFIG_DIR or ~/.codebuddy) decides which blocks are
# shown, their order on line 1, and whether the Tools/Recent lines are enabled.
# With no config file, BLOCKS_LINE1 is the default layout and the output is
# identical to the pre-config build.
# ---------------------------------------------------------------------------

def _config_path():
    """Location of the layout config, reusing the plugin data dir."""
    base = os.environ.get('CODEBUDDY_PLUGIN_DATA', '') or os.path.join(
        os.environ.get('CODEBUDDY_CONFIG_DIR', '') or os.path.expanduser("~/.codebuddy"),
        "plugins/data/statusline",
    )
    return os.path.join(base, "config.json")


def load_layout_config():
    """Read the layout config JSON, or None if missing/invalid.

    Any failure (missing file, bad JSON, wrong shape) returns None so the
    caller falls back to the default layout — a broken config must never
    blank the statusline.
    """
    try:
        with open(_config_path(), 'r') as f:
            data = json.load(f)
    except (IOError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def resolve_layout(cfg):
    """Resolve the effective layout from a raw config dict.

    Rules:
      - line1_order: shown blocks, in this order.
      - line1_hidden: explicitly hidden (takes precedence over order).
      - any known block in neither list (e.g. added in a future release) is
        auto-appended to the end and shown, so new blocks never silently
        vanish for users with a custom config.
      - unknown ids in line1_order are ignored.
      - missing/garbled config -> built-in defaults (all shown, both lines on).
    """
    layout = cfg.get("layout", {}) if isinstance(cfg, dict) else {}
    if not isinstance(layout, dict):
        layout = {}

    order = layout.get("line1_order", BLOCKS_LINE1)
    if not isinstance(order, list):
        order = BLOCKS_LINE1

    hidden = layout.get("line1_hidden", [])
    if not isinstance(hidden, list):
        hidden = []
    hidden = set(hidden)

    # Drop unknown ids (typos / removed blocks).
    order = [b for b in order if b in RENDERERS]

    # Auto-append known blocks neither ordered nor hidden (new-block safety).
    for b in BLOCKS_LINE1:
        if b not in order and b not in hidden:
            order.append(b)

    # Hidden wins: never render a hidden block.
    order = [b for b in order if b not in hidden]

    tools = layout.get("tools", True)
    recent = layout.get("recent", True)
    return {
        "line1_order": order,
        "tools": bool(tools),
        "recent": bool(recent),
    }


# --- Block renderers (line 1) ----------------------------------------------
# Each returns the finished, colored string for its block, or "" when the
# block has nothing to show.

def _render_cwd_git(input_data, stats):
    cwd_name = os.path.basename(os.getcwd())
    workspace = input_data.get('workspace') or {}
    git_cwd = workspace.get('current_dir') or os.getcwd()
    git_info = get_git_info(git_cwd)
    git_part = format_git_info(git_info) if git_info else ""
    if cwd_name and git_part:
        return f"{CYAN}{cwd_name}{NC} {git_part}"
    elif cwd_name:
        return f"{CYAN}{cwd_name}{NC}"
    elif git_part:
        return git_part
    return ""


def _render_model(input_data, stats):
    model = input_data.get('model') or {}
    model_name = model.get('display_name', '')
    return f"{BLUE}{model_name}{NC}" if model_name else ""


def _render_context_bar(input_data, stats):
    ctx = input_data.get('context_window') or {}
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
            return ctx_part
    if used_pct is None and ctx_size > 0:
        # No percentage data, but we still have max context size
        return f"{DIM}Max:{format_tokens(ctx_size)}{NC}"
    return ""


def _render_compact_periodic(input_data, stats):
    # Compact/Periodic counts: always show when present, even if
    # used_percentage is null (e.g. first call right after compact).
    # Rendered as its own " | "-separated block (no leading space), so the
    # parts join cleanly whether only Compact, only Periodic, or both show.
    cp = ""
    if stats.get('compact_count', 0) > 0:
        cp += f"{YELLOW}Compact×{stats['compact_count']}{NC}"
    if stats.get('periodic_count', 0) > 0:
        cp += (" " if cp else "") + f"{DIM}Periodic×{stats['periodic_count']}{NC}"
    return cp


def _render_tokens(input_data, stats):
    # In/Out come from transcript parsing (main + sub-agents),
    # falling back to CodeBuddy's context_window values if transcript has no data.
    # Cache/Think have no context_window fallback — they only come from transcript parsing.
    ctx = input_data.get('context_window') or {}
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
    return " ".join(token_parts)


def _render_requests(input_data, stats):
    n = stats.get('request_count', 0) or 0
    return f"{CYAN}Req:{NC}{n}" if n > 0 else ""


def _render_cost(input_data, stats):
    cost = input_data.get('cost') or {}
    total_cost = cost.get('total_cost_usd', 0) or 0
    credits_usd = (stats.get('total_credits', 0) or 0) * CREDITS_TO_USD
    cost_str = format_cost(total_cost + credits_usd)
    return f"{RED}Cost:{NC}{cost_str}" if cost_str else ""


def _render_credits(input_data, stats):
    c = stats.get('total_credits', 0) or 0
    return f"{YELLOW}Credits:{NC}{c:.2f}" if c > 0 else ""


def _render_time(input_data, stats):
    cost = input_data.get('cost') or {}
    duration_str = format_duration(cost.get('total_duration_ms', 0) or 0)
    return f"{DIM}Time:{NC}{duration_str}" if duration_str else ""


def _render_lines(input_data, stats):
    cost = input_data.get('cost') or {}
    added = cost.get('total_lines_added', 0) or 0
    removed = cost.get('total_lines_removed', 0) or 0
    if added > 0 or removed > 0:
        return f"{GREEN}+{added}{NC}/{RED}-{removed}{NC}"
    return ""


RENDERERS = {
    "cwd_git": _render_cwd_git,
    "model": _render_model,
    "context_bar": _render_context_bar,
    "compact_periodic": _render_compact_periodic,
    "tokens": _render_tokens,
    "requests": _render_requests,
    "cost": _render_cost,
    "credits": _render_credits,
    "time": _render_time,
    "lines": _render_lines,
}

# Canonical block order = default layout, and the auto-append order for new blocks.
BLOCKS_LINE1 = list(RENDERERS.keys())


def _build_recent_parts(input_data, stats):
    """Build line 3's Recent content (last-interaction detail + recent calls)."""
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

    return recent_parts



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

    The layout (which blocks show, their order, and whether the Tools/Recent
    lines are enabled) comes from the plugin config; see load_layout_config /
    resolve_layout. With no config, BLOCKS_LINE1 is used and the output is
    identical to the pre-config build.
    """
    layout = resolve_layout(load_layout_config())

    # Line 1: ordered, filtered blocks joined by " | ".
    parts = []
    for bid in layout["line1_order"]:
        renderer = RENDERERS.get(bid)
        if renderer is None:
            continue
        block = renderer(input_data, stats)
        if block:
            parts.append(block)
    output = " | ".join(parts)

    # Line 2: Tools (with Agent running/completed status)
    if layout["tools"]:
        tool_str = format_tools(stats.get('tool_counts', {}), stats.get('running_agents', 0))
        if tool_str:
            output += f"\n{DIM}Tools:{NC} {tool_str}"

    # Line 3: Last interaction token details + Recent function calls
    if layout["recent"]:
        recent_parts = _build_recent_parts(input_data, stats)
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
