#!/usr/bin/env python3
"""
CodeBuddy Code Cost Monitor - Lightweight Statusline Script
Fast version that only uses statusline JSON input (no transcript parsing).
Slightly less detailed but much faster.
"""

import json
import sys

def format_tokens(n):
    if n is None:
        return "0"
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

def format_cost(usd):
    if usd is None or usd == 0:
        return ""
    if usd < 0.01:
        return f"${usd:.4f}"
    elif usd < 1:
        return f"${usd:.3f}"
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

def main():
    try:
        data = json.load(sys.stdin)
    except:
        data = {}

    model = data.get('model', {}).get('display_name', '')
    cost = data.get('cost', {})
    total_cost = cost.get('total_cost_usd', 0) or 0
    duration = cost.get('total_duration_ms', 0) or 0
    added = cost.get('total_lines_added', 0) or 0
    removed = cost.get('total_lines_removed', 0) or 0

    # ANSI colors
    C = '\033[0;36m'  # cyan
    G = '\033[0;32m'  # green
    Y = '\033[1;33m'  # yellow
    B = '\033[0;34m'  # blue
    R = '\033[0;31m'  # red
    D = '\033[2m'     # dim
    N = '\033[0m'     # reset

    parts = []
    if model:
        parts.append(f"{B}{model}{N}")

    # Cost with color coding
    if total_cost > 0:
        if total_cost < 0.01:
            cc = G
        elif total_cost < 0.1:
            cc = Y
        else:
            cc = R
        parts.append(f"{cc}Cost:{N}{format_cost(total_cost)}")

    if duration:
        parts.append(f"{D}Time:{N}{format_duration(duration)}")

    if added or removed:
        parts.append(f"{G}+{added}{N}/{R}-{removed}{N}")

    print(" | ".join(parts))

if __name__ == '__main__':
    main()
