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
# which cannot encode Unicode chars like ✓, █, × used in the output.
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

    # Recent output rate (tokens/s), from the delta between renders. Uses the
    # host's cumulative API time (an end-to-end request duration, so network
    # time is included). See stats.update_rate_snapshot. The Avg block reads
    # `cost.total_api_duration_ms` as-is and is left unmodified.
    recent_rate = None
    if session_id:
        try:
            cost = input_data.get('cost') or {}
            recent_rate = stats.update_rate_snapshot(
                session_id,
                stats_dict.get('total_output', 0) or 0,
                cost.get('total_api_duration_ms', 0) or 0,
            )
        except Exception:
            recent_rate = None

    # Assemble and print the three-line statusline
    print(render.build_statusline(input_data, stats_dict, recent_rate))

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
