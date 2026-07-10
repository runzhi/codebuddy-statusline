#!/usr/bin/env python3
"""Stats structure, cache persistence, and plugin auto-update.

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
_PLUGIN_DATA = os.environ.get('CODEBUDDY_PLUGIN_DATA', '') or os.path.join(_CONFIG_DIR, "plugins/data/statusline")
CACHE_DIR = os.path.join(_PLUGIN_DATA, "cache")
CACHE_MAX_AGE_DAYS = 7
CACHE_VERSION = 8

# Plugin mode: CODEBUDDY_PLUGIN_ROOT is set when installed via marketplace
# Git-clone mode: fallback to script's own directory
PLUGIN_DIR = os.environ.get('CODEBUDDY_PLUGIN_ROOT', '') or os.path.dirname(os.path.abspath(__file__))
IS_PLUGIN_MODE = bool(os.environ.get('CODEBUDDY_PLUGIN_ROOT', ''))

# Auto-update (git-clone mode only): throttled via marker file
UPDATE_MARKER = os.path.join(CACHE_DIR, ".last-update-check")
UPDATE_INTERVAL_SECONDS = 86400  # once per day

RECENT_CALLS_MAX = 3
# Stats fields that hold the "last value" rather than a cumulative total;
# during incremental merges they are overwritten (not summed).
_LAST_KEYS = ("last_input", "last_output", "last_cache_read", "last_credits", "last_cost")


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


def maybe_auto_update():
    """Try to git-pull the plugin repo at most once per day (git-clone mode only).

    Skipped entirely when installed via plugin marketplace (IS_PLUGIN_MODE),
    since updates are managed by `codebuddy plugin update`.

    Throttles via a marker file (mtime). The git pull runs in a fully detached
    background process so it never blocks the statusline.
    """
    if IS_PLUGIN_MODE:
        return

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
                try:
                    os.remove(fpath)
                except OSError:
                    pass
                continue
            if not fname.endswith('.json'):
                continue
            key = fname[:-5]  # strip .json
            # Protect current session's cache
            if key == current_session_id:
                continue
            try:
                if now - os.path.getmtime(fpath) > max_age:
                    os.remove(fpath)
            except OSError:
                pass
    except OSError:
        pass
