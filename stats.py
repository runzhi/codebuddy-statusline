#!/usr/bin/env python3
"""Stats structure, cache persistence, and git-clone auto-update.

Holds the accumulated-stats schema (new_stats), the on-disk cache
(load/save, versioned by CACHE_VERSION), periodic cache cleanup, and the
once-per-day git-clone auto-update. Imported by parsing.py (parse + cache)
and the statusline entry point (auto-update).
"""

import json
import os
import subprocess
import sys
import time

# Resolve the CodeBuddy config dir. The running process may set
# CODEBUDDY_CONFIG_DIR (e.g. ~/.workbuddy); fall back to ~/.codebuddy.
_CONFIG_DIR = os.environ.get('CODEBUDDY_CONFIG_DIR', '') or os.path.expanduser("~/.codebuddy")
_PLUGIN_DATA = os.path.join(_CONFIG_DIR, "plugins/data/statusline")
CACHE_DIR = os.path.join(_PLUGIN_DATA, "cache")
CACHE_MAX_AGE_DAYS = 7
CACHE_VERSION = 9

# PLUGIN_DIR is the directory this script lives in (the git-clone install dir).
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# Auto-update (git-clone mode only): throttled via marker file
UPDATE_MARKER = os.path.join(CACHE_DIR, ".last-update-check")
UPDATE_INTERVAL_SECONDS = 86400  # once per day

RECENT_CALLS_MAX = 3


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


# Stats fields holding the "last value" rather than a cumulative total; during
# incremental merges they are overwritten, not summed. Derived from new_stats()
# so a newly added last_* field is picked up automatically — hardcoding this
# list silently mis-merged (summed instead of overwrote) any field left out.
_LAST_KEYS = tuple(k for k in new_stats() if k.startswith("last_"))
assert _LAST_KEYS, "no last_* fields found in new_stats() — merge semantics broke"


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
    """Save the cache for a session atomically (write-to-temp + rename)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{session_id}.json")
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, 'w') as f:
            json.dump({
                "stats": stats,
                "main_offset": main_offset,
                "sub_offsets": sub_offsets or {},
                "cache_version": CACHE_VERSION,
            }, f)
        os.replace(tmp_path, cache_path)
    except IOError:
        pass


# --- Recent throughput ("Speed" line-3 item) --------------------------------
#
# The host exposes only *cumulative* API time (cost.total_api_duration_ms),
# which is an end-to-end request duration (per-request time is `Date.now()`
# minus the request's start), so it includes network/TTFT and the derived rate
# is a throughput figure rather than pure model speed. To show a recent rate we
# diff the cumulative counters against the previous invocation and divide:
# Δoutput / Δapi_time. The window is the gap between two renders, which is
# short (the host re-renders on cost/result events), so the result approximates
# the current throughput. The previous counters live in a small per-session
# sidecar next to the stats cache.

def _rate_path(session_id):
    return os.path.join(CACHE_DIR, f"{session_id}.rate.json")


def load_rate_snapshot(session_id):
    """Load {output, api_ms, rate} recorded by the previous invocation, or None."""
    try:
        with open(_rate_path(session_id), 'r') as f:
            data = json.load(f)
    except (IOError, ValueError):  # ValueError covers json.JSONDecodeError
        return None
    return data if isinstance(data, dict) else None


def save_rate_snapshot(session_id, snapshot):
    """Persist the rate snapshot dict (atomic write-to-temp + rename)."""
    path = _rate_path(session_id)
    tmp = path + ".tmp"
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(tmp, 'w') as f:
            json.dump(snapshot, f)
        os.replace(tmp, path)
    except IOError:
        pass


_RATE_SNAPSHOT_VERSION = 2


def update_rate_snapshot(session_id, output_tokens, api_ms):
    """Return the recent output rate (tokens/s), or None when not measurable.

    Rate = Δoutput ÷ Δcost.total_api_duration_ms between two statusline
    renders. That duration is the host's cumulative API time — an end-to-end
    request duration, so it includes network/TTFT and therefore understates
    pure model generation. It is the only clock the host exposes, and mixing
    in a second (transcript) clock would measure something different.

    Returns the last measured rate when this render adds no new sample, so
    the display does not flicker.
    """
    if output_tokens <= 0 or api_ms <= 0:
        return None

    prev = load_rate_snapshot(session_id)
    if prev is None or prev.get("v") != _RATE_SNAPSHOT_VERSION:
        # First call for this session, or a sidecar from an older format.
        save_rate_snapshot(session_id, {"v": _RATE_SNAPSHOT_VERSION,
                                        "output": output_tokens, "api_ms": api_ms,
                                        "rate": None})
        return None

    prev_out = prev.get("output") or 0
    prev_api = prev.get("api_ms") or 0
    last_rate = prev.get("rate")

    if output_tokens < prev_out:
        # Output counter went backwards (cache reset / reused session id):
        # re-baseline rather than compute a bogus rate.
        save_rate_snapshot(session_id, {"v": _RATE_SNAPSHOT_VERSION,
                                        "output": output_tokens, "api_ms": api_ms,
                                        "rate": None})
        return None

    # The host total can originate from different CostService instances and
    # therefore jump around; keep a high-water mark so it only advances.
    if api_ms < prev_api:
        api_ms = prev_api

    d_out = output_tokens - prev_out
    d_api = api_ms - prev_api

    if d_out > 0 and d_api > 0:
        last_rate = d_out / (d_api / 1000.0)
        save_rate_snapshot(session_id, {"v": _RATE_SNAPSHOT_VERSION,
                                        "output": output_tokens, "api_ms": api_ms,
                                        "rate": last_rate})
        return last_rate

    # Nothing new to measure. Keep the stored baseline (and rate) so the
    # pending increment accumulates into the next round instead of being
    # discarded — updating it here would make the two deltas reset forever.
    return last_rate


def maybe_auto_update():
    """Try to git-pull the install repo at most once per day.

    Throttles via a marker file (mtime). The git pull runs in a fully detached
    background process so it never blocks the statusline. No-op when the
    install dir is not a git repo.
    """
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
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        subprocess.Popen(
            ["git", "-C", PLUGIN_DIR, "pull", "--ff-only", "--quiet"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception:
        pass


def _remove_if_exists(path):
    """Remove a file, ignoring OSError (best-effort cleanup)."""
    try:
        os.remove(path)
    except OSError:
        pass


def cleanup_old_caches(current_session_id):
    """Remove cache files older than CACHE_MAX_AGE_DAYS, excluding current session."""
    if not os.path.isdir(CACHE_DIR):
        return
    now = time.time()
    max_age = CACHE_MAX_AGE_DAYS * 86400  # seconds
    try:
        for fname in os.listdir(CACHE_DIR):
            fpath = os.path.join(CACHE_DIR, fname)
            # Clean up stale .tmp files from interrupted atomic writes
            if fname.endswith('.tmp'):
                _remove_if_exists(fpath)
                continue
            if not fname.endswith('.json'):
                continue
            key = fname[:-5]  # strip .json
            # Protect current session's cache
            if key == current_session_id:
                continue
            try:
                is_old = now - os.path.getmtime(fpath) > max_age
            except OSError:
                continue
            if is_old:
                _remove_if_exists(fpath)
    except OSError:
        pass
