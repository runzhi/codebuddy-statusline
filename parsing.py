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


# Tool name -> argument key used to build its one-line call summary.
_SUMMARY_ARG_KEY = {
    'Bash': 'command',
    'Read': 'file_path',
    'Edit': 'file_path',
    'Write': 'file_path',
    'Glob': 'pattern',
    'Agent': 'description',
    'WebFetch': 'url',
    'WebSearch': 'query',
}


def _extract_call_summary(name, args):
    """Extract a short summary from a function_call's parsed arguments.

    args should be a dict (already parsed from JSON).
    Truncation is handled by format_recent_calls, not here.
    """
    if not isinstance(args, dict) or not args:
        return name

    key = _SUMMARY_ARG_KEY.get(name)
    if key:
        return args.get(key, '') or name

    if name == 'Grep':
        pat = args.get('pattern', '')
        path = args.get('path', '')
        if pat or path:
            return f"{pat} {path}".strip()
        return name

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
                if isinstance(args_raw, dict):
                    args = args_raw
                elif isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                else:
                    args = {}
                summary = _extract_call_summary(name, args)
            recent = stats["recent_calls"]
            recent.append({"name": name, "summary": summary})
            # Trim only when over the cap; re-slicing on every append copies
            # the list for each recorded call.
            if len(recent) > RECENT_CALLS_MAX:
                del recent[:-RECENT_CALLS_MAX]

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
    """Read a transcript from *offset*; return (delta, new_offset, has_new, truncated).

    Shared read loop for both the main transcript and sub-agent transcripts:
      - truncation: an offset past EOF means the file shrank (rewritten), so
        report it and let the caller re-parse everything from 0.
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
        return new_stats(), offset, False, False
    if offset > file_size:
        # Cached offset is past EOF. The caller cannot subtract the removed
        # lines' per-transcript contributions, so it must discard the cached
        # stats and re-read this transcript from 0.
        return new_stats(), offset, False, True
    if offset == file_size and offset > 0:
        return new_stats(), offset, False, False

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
        return new_stats(), offset, False, False

    if not has_new_data:
        return new_stats(), offset, False, False
    return delta, new_offset, True, False


def _merge_delta(stats, delta, is_main, previous_running_agents=0):
    """Merge a transcript *delta* into the accumulated *stats*.

    Shared by the main transcript and sub-agent transcripts. Sub-agent
    transcripts (is_main=False) contribute tokens/credits/tools but NOT
    running_agents/compact_count/periodic_count, because those counters are
    main-transcript-only.

    last_* fields are "last value" not cumulative; they are overwritten only
    when the delta carries a non-zero value (i.e. a new API response).
    """
    # Sub-agent transcripts contribute tokens/credits/tools only; these three
    # counters are main-transcript-only. running_agents is merged after the
    # loop because it needs the previous cached value.
    skip_keys = {"running_agents"} if is_main else {"running_agents", "compact_count", "periodic_count"}

    for key in delta:
        if key in skip_keys:
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


def _sub_agent_transcripts(subagents_dir, sub_offsets):
    """Return [(agent_key, path, offset)] for each sub-agent transcript.

    Materialized as a list (not a generator) because the caller needs the
    same set twice — once for the offsets bookkeeping, once for the read
    loop — and a generator would list the directory twice. Cached offsets
    are validated here so a corrupted cache value falls back to 0.
    """
    entries = []
    if not os.path.isdir(subagents_dir):
        return entries
    try:
        for fname in os.listdir(subagents_dir):
            if not fname.endswith('.jsonl'):
                continue
            agent_key = fname[:-6]
            offset = sub_offsets.get(agent_key, 0)
            if not isinstance(offset, (int, float)):
                offset = 0
            entries.append((agent_key, os.path.join(subagents_dir, fname), offset))
    except OSError:
        pass
    return entries


def _collect_deltas(transcript_path, subs, main_offset, stats, previous_running_agents):
    """Read main + sub-agent transcripts from their offsets and merge into *stats*.

    *subs* is the materialized list from _sub_agent_transcripts.

    Returns (any_new, truncated, main_offset, sub_offsets). When *truncated*
    is True nothing has been merged, so the caller discards *stats* and
    calls this again with every offset at 0 — the first pass is then free of
    double-counting by construction.
    """
    main_delta, main_new_offset, main_has_new, truncated = _read_transcript_delta(
        transcript_path, main_offset)
    if truncated:
        return False, True, main_offset, {}
    any_new = main_has_new
    _merge_delta(stats, main_delta, is_main=True,
                 previous_running_agents=previous_running_agents)

    sub_offsets = {}
    for agent_key, sub_path, sub_offset in subs:
        sub_delta, sub_new_offset, sub_has_new, sub_truncated = _read_transcript_delta(
            sub_path, sub_offset)
        if sub_truncated:
            return False, True, main_offset, {}
        sub_offsets[agent_key] = sub_new_offset
        if sub_has_new:
            any_new = True
        # Sub-agents contribute tokens/credits/tools but NOT
        # running_agents/compact_count/periodic_count.
        _merge_delta(stats, sub_delta, is_main=False)

    return any_new, False, main_new_offset, sub_offsets


def parse_transcript_incremental(transcript_path, session_id):
    """Parse main + sub-agent transcripts incrementally.

    Extracts In/Out/Cache/Think/Credits/Req/Tools/Compact/Periodic from all transcripts.
    Sub-agents contribute to token/credit/tool counts but NOT to
    running_agents, compact_count, or periodic_count (those are main-transcript-only).

    Skip-write: if no new data was found, skip writing the cache entirely.
    Truncation handling: truncation is detected while reading (a cached offset
    past EOF), which is also the only getsize each transcript needs. If any
    transcript was truncated, discard all cached stats and re-parse everything
    from scratch. This avoids double-counting when we can't subtract old
    per-sub-agent contributions.
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
            defaults = new_stats()
            valid_keys = set(defaults)
            for key, default in defaults.items():
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

    # Materialize the sub-agent list once; it drives both passes below.
    subs = _sub_agent_transcripts(subagents_dir, sub_offsets)

    any_new_data, any_truncated, main_offset, sub_offsets = _collect_deltas(
        transcript_path, subs, main_offset, stats, previous_running_agents)

    # --- Full re-parse: discard cache, parse everything from offset 0 ---
    if any_truncated:
        stats = new_stats()
        subs = [(agent_key, path, 0) for agent_key, path, _ in subs]
        any_new_data, _, main_offset, sub_offsets = _collect_deltas(
            transcript_path, subs, 0, stats, 0)

    # Skip cache write when nothing changed and no truncation occurred.
    if any_new_data or any_truncated or cache is None:
        save_cache(session_id, stats, main_offset, sub_offsets)

    # Cleanup old caches ~1% of the time to avoid O(n) scan every 300ms.
    if int(time.time() * 1000) % 97 < 1:
        cleanup_old_caches(session_id)

    return stats, any_truncated
