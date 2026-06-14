#!/usr/bin/env python3
"""
CodeBuddy Code Cost Detail Viewer
Prints a detailed breakdown of token usage by model from the transcript file.
"""

import json
import sys
import os
import glob

def format_tokens(n):
    if n >= 1_000_000:
        return f"{n:,} ({n/1_000_000:.1f}M)"
    elif n >= 1_000:
        return f"{n:,} ({n/1_000:.1f}K)"
    return f"{n:,}"

def format_cost(usd):
    if usd < 0.01:
        return f"${usd:.4f}"
    elif usd < 1:
        return f"${usd:.3f}"
    return f"${usd:.2f}"

def find_latest_transcript():
    """Find the most recent transcript for the current project."""
    # Try to find from hook input
    if not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin)
            tp = data.get('transcript_path', '')
            if tp and os.path.exists(tp):
                return tp
        except Exception:
            pass

    # Find latest transcript in project dirs
    base = os.path.expanduser("~/.codebuddy/projects")
    if not os.path.exists(base):
        return None

    latest = None
    latest_mtime = 0
    for project_dir in os.listdir(base):
        project_path = os.path.join(base, project_dir)
        if not os.path.isdir(project_path):
            continue
        for jsonl in glob.glob(os.path.join(project_path, "*.jsonl")):
            mtime = os.path.getmtime(jsonl)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest = jsonl

    return latest

def parse_transcript(transcript_path):
    stats = {
        "total_input": 0,
        "total_output": 0,
        "total_cache_read": 0,
        "total_cache_write": 0,
        "total_reasoning": 0,
        "total_credits": 0.0,
        "request_count": 0,
        "by_model": {},
    }

    if not transcript_path or not os.path.exists(transcript_path):
        return stats

    # Collect all transcript paths (main + sub-agents)
    transcript_paths = [transcript_path]
    if transcript_path.endswith('.jsonl'):
        session_dir = transcript_path[:-6]
        subagents_dir = os.path.join(session_dir, 'subagents')
        if os.path.isdir(subagents_dir):
            for fname in os.listdir(subagents_dir):
                if fname.endswith('.jsonl'):
                    transcript_paths.append(os.path.join(subagents_dir, fname))

    for tp in transcript_paths:
        with open(tp, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    pd = data.get('providerData', {})
                    if not isinstance(pd, dict):
                        continue

                    usage = pd.get('usage', {})
                    raw_usage = pd.get('rawUsage', {})
                    model = pd.get('requestModelName') or pd.get('requestModelId') or pd.get('model', 'unknown')

                    if not usage and not raw_usage:
                        continue

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

                        if model not in stats["by_model"]:
                            stats["by_model"][model] = {
                                "input": 0, "output": 0, "cache_read": 0,
                                "cache_write": 0, "reasoning": 0, "requests": 0, "credits": 0.0
                            }
                        m = stats["by_model"][model]
                        m["input"] += input_tokens
                        m["output"] += output_tokens
                        m["cache_read"] += cache_read
                        m["cache_write"] += cache_write
                        m["reasoning"] += reasoning
                        m["requests"] += 1
                        m["credits"] += credit

                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

    return stats

def main():
    transcript_path = find_latest_transcript()
    if not transcript_path:
        print("No transcript file found.")
        sys.exit(1)

    stats = parse_transcript(transcript_path)

    if stats["request_count"] == 0:
        print("No API requests found in this session.")
        return

    # Print header
    print("=" * 80)
    print("  CodeBuddy Code - Cost & Token Usage Report")
    print("=" * 80)
    print()

    # Per-model breakdown
    for model_name, m in stats["by_model"].items():
        print(f"  {model_name}:")
        print(f"    Requests:     {m['requests']}")
        print(f"    Input:        {format_tokens(m['input'])}")
        print(f"    Output:       {format_tokens(m['output'])}")
        print(f"    Cache Read:   {format_tokens(m['cache_read'])}")
        if m['cache_write'] > 0:
            print(f"    Cache Write:  {format_tokens(m['cache_write'])}")
        if m['reasoning'] > 0:
            print(f"    Reasoning:    {format_tokens(m['reasoning'])}")
        if m['credits'] > 0:
            print(f"    Credits:      {m['credits']:.2f}")
        print()

    # Totals
    print("-" * 80)
    print(f"  TOTALS:")
    print(f"    Requests:     {stats['request_count']}")
    print(f"    Input:        {format_tokens(stats['total_input'])}")
    print(f"    Output:       {format_tokens(stats['total_output'])}")
    print(f"    Cache Read:   {format_tokens(stats['total_cache_read'])}")
    if stats['total_cache_write'] > 0:
        print(f"    Cache Write:  {format_tokens(stats['total_cache_write'])}")
    if stats['total_reasoning'] > 0:
        print(f"    Reasoning:    {format_tokens(stats['total_reasoning'])}")
    if stats['total_credits'] > 0:
        print(f"    Credits:      {stats['total_credits']:.2f}")
    print("=" * 80)

if __name__ == '__main__':
    main()
