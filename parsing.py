#!/usr/bin/env python3
"""Incremental transcript parsing.

Parses main + sub-agent transcripts into the accumulated stats dict,
reusing an on-disk cache so each invocation only processes new lines.
The read loop and the delta-merge logic are shared between the main
transcript and sub-agent transcripts via `_read_transcript_delta` and
`_merge_delta` to avoid the two near-identical copies that previously
lived in parse_transcript_incremental.
"""

import json
import os
import time

from stats import (
    CACHE_VERSION,
    RECENT_CALLS_MAX,
    _LAST_KEYS,
    cleanup_old_caches,
    load_cache,
    new_stats,
    save_cache,
)


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


def _read_transcript_delta(path, offset):
    """Read a transcript from *offset* and return (delta, new_offset, has_new).

    A near-verbatim copy of the shared read loop used for both the main
    transcript and sub-agent transcripts:
      - fast path: if offset is at EOF (and > 0), nothing to read.
      - partial last line (mid-write): stop before it and report the offset
        of the incomplete line so the next cycle re-reads it.
      - pre-filter skips lines that cannot contribute to stats.

    Returns an empty delta (new_stats()) when there is nothing new or the
    file is unavailable, so callers can treat it as a no-op.
    """
    try:
        file_size = os.path.getsize(path)
    except (IOError, OSError):
        return new_stats(), offset, False
    if offset == file_size and offset > 0:
        return new_stats(), offset, False

    delta = new_stats()
    has_new_data = False
    failed_line_offset = None
    try:
        with open(path, 'rb') as f:
            if offset > 0:
                f.seek(offset)
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
    except (IOError, OSError):
        return new_stats(), offset, False

    if not has_new_data:
        return new_stats(), offset, False
    return delta, new_offset, True


def _merge_delta(stats, delta, is_main, previous_running_agents=0):
    """Merge a transcript *delta* into the accumulated *stats*.

    Shared by the main transcript and sub-agent transcripts. Sub-agent
    transcripts (is_main=False) contribute tokens/credits/tools but NOT
    running_agents/compact_count/periodic_count, because those counters are
    main-transcript-only.

    last_* fields are "last value" not cumulative; they are overwritten only
    when the delta carries a non-zero value (i.e. a new API response).
    """
    skip_keys = set()
    if not is_main:
        skip_keys = {"running_agents", "compact_count", "periodic_count"}

    for key in delta:
        if key in skip_keys:
            continue
        if key == "running_agents":
            # main-only, handled after the loop
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

    if is_main:
        stats["running_agents"] = max(0, delta["running_agents"] + previous_running_agents)


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
    main_delta, main_new_offset, main_has_new = _read_transcript_delta(transcript_path, main_offset)
    if main_has_new:
        any_new_data = True
    if need_full_reparse:
        # Stats were reset; delta IS the new stats
        stats = main_delta
        stats["running_agents"] = max(0, stats["running_agents"])
    else:
        _merge_delta(stats, main_delta, is_main=True, previous_running_agents=previous_running_agents)
    if main_new_offset > 0:
        main_offset = main_new_offset

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

                sub_delta, sub_new_offset, sub_has_new = _read_transcript_delta(sub_path, sub_offset)
                if sub_has_new:
                    any_new_data = True

                # Sub-agents contribute tokens/credits/tools but NOT
                # running_agents/compact_count/periodic_count.
                _merge_delta(stats, sub_delta, is_main=False)
                sub_offsets[agent_key] = sub_new_offset
        except OSError:
            pass

    # Skip cache write when nothing changed and no truncation occurred.
    if any_new_data or any_truncated or cache is None:
        save_cache(session_id, stats, main_offset, sub_offsets)

    # Cleanup old caches ~1% of the time to avoid O(n) scan every 300ms.
    if int(time.time() * 1000) % 97 < 1:
        cleanup_old_caches(session_id)

    return stats, any_truncated
