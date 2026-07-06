#!/usr/bin/env python3
"""
CodeBuddy Code Cost Monitor - Statusline Script (Incremental)
Displays real-time cost, token usage, context progress, tools usage, and request stats.

Thin orchestration entry point. Stats parsing lives in parsing.py, rendering
in render.py, cache/auto-update in stats.py. Each invocation is a fresh
process with an irregular (seconds-to-minutes) call cycle, so keep startup
cheap and never block.

Requires Python 3.6+.
"""

import json
import sys

# Fix Windows GBK encoding: stdout defaults to GBK on Chinese Windows,
# which cannot encode Unicode chars like ✓, █, ▕, × used in the output.
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import parsing
import render
import stats
from formatting import NC, RED


def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    transcript_path = input_data.get('transcript_path', '')
    session_id = input_data.get('session_id', '')

    # Incremental parse for all metrics from main + sub-agent transcripts
    stats_dict, _ = parsing.parse_transcript_incremental(transcript_path, session_id)

    # Assemble and print the three-line statusline
    print(render.build_statusline(input_data, stats_dict))

    # Auto-update (git-clone mode only, at most once per day, runs detached).
    try:
        stats.maybe_auto_update()
    except Exception:
        pass


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # Global safety net: if anything crashes, still output something
        # so the statusline never goes blank silently.
        print(f"{RED}ERR:{NC}{type(e).__name__}: {e}")
