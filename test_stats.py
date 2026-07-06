#!/usr/bin/env python3
"""Unit tests for stats.py module"""

import json
import os
import sys
import tempfile
import time
import shutil
import unittest
import unittest.mock

import stats
from stats import (
    new_stats, load_cache, save_cache, cleanup_old_caches, maybe_auto_update,
    CACHE_DIR, CACHE_VERSION, IS_PLUGIN_MODE,
)

class TestNewStats(unittest.TestCase):
    def test_defaults(self):
        stats = new_stats()
        self.assertEqual(stats["total_input"], 0)
        self.assertEqual(stats["total_output"], 0)
        self.assertEqual(stats["total_cache_read"], 0)
        self.assertEqual(stats["total_reasoning"], 0)
        self.assertEqual(stats["total_credits"], 0.0)
        self.assertEqual(stats["request_count"], 0)
        self.assertEqual(stats["tool_counts"], {})
        self.assertEqual(stats["running_agents"], 0)
        self.assertEqual(stats["compact_count"], 0)
        self.assertEqual(stats["periodic_count"], 0)

class TestCacheOperations(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = stats.CACHE_DIR
        stats.CACHE_DIR = self.tmpdir

    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir)

    def test_save_and_load(self):
        """Cache stores stats, main_offset, and sub_offsets."""
        stats = new_stats()
        stats["tool_counts"]["Bash"] = 5
        save_cache("test-session", stats, 1024)
        cache = load_cache("test-session")
        self.assertIsNotNone(cache)
        self.assertEqual(cache["main_offset"], 1024)
        self.assertIn("sub_offsets", cache)
        self.assertEqual(cache["stats"]["tool_counts"]["Bash"], 5)

    def test_load_missing(self):
        self.assertIsNone(load_cache("nonexistent"))

    def test_corrupted_cache_file(self):
        cache_path = os.path.join(self.tmpdir, "sess1.json")
        with open(cache_path, 'w') as f:
            f.write("not valid json")
        self.assertIsNone(load_cache("sess1"))

class TestCleanupOldCaches(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = stats.CACHE_DIR
        stats.CACHE_DIR = self.tmpdir

    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir)

    def test_removes_old_caches(self):
        old_path = os.path.join(self.tmpdir, "old-session.json")
        with open(old_path, 'w') as f:
            json.dump({}, f)
        old_time = time.time() - 8 * 86400
        os.utime(old_path, (old_time, old_time))

        cleanup_old_caches("current-session")
        self.assertFalse(os.path.exists(old_path))

    def test_preserves_current_session_cache(self):
        path = os.path.join(self.tmpdir, "sess1.json")
        with open(path, 'w') as f:
            json.dump({}, f)
        old_time = time.time() - 8 * 86400
        os.utime(path, (old_time, old_time))

        cleanup_old_caches("sess1")
        self.assertTrue(os.path.exists(path))

    def test_ignores_non_json_files(self):
        path = os.path.join(self.tmpdir, "readme.txt")
        with open(path, 'w') as f:
            f.write("hello")
        cleanup_old_caches("other-session")
        self.assertTrue(os.path.exists(path))

class TestAutoUpdate(unittest.TestCase):
    """Tests for the auto-update feature (maybe_auto_update)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = stats.CACHE_DIR
        self._orig_plugin_dir = stats.PLUGIN_DIR
        self._orig_marker = stats.UPDATE_MARKER
        self._orig_is_plugin_mode = stats.IS_PLUGIN_MODE
        stats.CACHE_DIR = self.tmpdir
        stats.UPDATE_MARKER = os.path.join(self.tmpdir, ".last-update-check")
        stats.IS_PLUGIN_MODE = False  # default: git-clone mode for tests

    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
        stats.PLUGIN_DIR = self._orig_plugin_dir
        stats.UPDATE_MARKER = self._orig_marker
        stats.IS_PLUGIN_MODE = self._orig_is_plugin_mode
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_skipped_in_plugin_mode(self):
        """When IS_PLUGIN_MODE is True, maybe_auto_update is a no-op."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        stats.PLUGIN_DIR = self.tmpdir
        stats.IS_PLUGIN_MODE = True
        maybe_auto_update()
        self.assertFalse(os.path.exists(stats.UPDATE_MARKER))

    def test_no_op_when_not_a_git_repo(self):
        """When PLUGIN_DIR isn't a git repo, maybe_auto_update is a no-op."""
        import statusline
        stats.PLUGIN_DIR = self.tmpdir
        maybe_auto_update()
        self.assertFalse(os.path.exists(stats.UPDATE_MARKER))

    def test_skips_when_marker_recent(self):
        """If the marker file is fresh, maybe_auto_update should skip."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        stats.PLUGIN_DIR = self.tmpdir
        with open(stats.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time())))
        marker_mtime_before = os.path.getmtime(stats.UPDATE_MARKER)
        time.sleep(0.05)
        maybe_auto_update()
        marker_mtime_after = os.path.getmtime(stats.UPDATE_MARKER)
        self.assertEqual(marker_mtime_before, marker_mtime_after)

    def test_runs_when_marker_old(self):
        """If marker is older than UPDATE_INTERVAL_SECONDS, update is triggered."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        stats.PLUGIN_DIR = self.tmpdir
        with open(stats.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time()) - 2 * 86400))
        old_mtime = time.time() - 2 * 86400
        os.utime(stats.UPDATE_MARKER, (old_mtime, old_mtime))

        marker_mtime_before = os.path.getmtime(stats.UPDATE_MARKER)
        maybe_auto_update()
        marker_mtime_after = os.path.getmtime(stats.UPDATE_MARKER)
        self.assertGreater(marker_mtime_after, marker_mtime_before)

    def test_creates_marker_on_first_run(self):
        """First run (no marker yet) should create the marker."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        stats.PLUGIN_DIR = self.tmpdir
        self.assertFalse(os.path.exists(stats.UPDATE_MARKER))
        maybe_auto_update()
        self.assertTrue(os.path.exists(stats.UPDATE_MARKER))

    def test_returns_quickly(self):
        """maybe_auto_update must not block the statusline (returns in << 100ms)."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        stats.PLUGIN_DIR = self.tmpdir
        old_mtime = time.time() - 2 * 86400
        with open(stats.UPDATE_MARKER, 'w') as f:
            f.write("0")
        os.utime(stats.UPDATE_MARKER, (old_mtime, old_mtime))

        t = time.perf_counter()
        maybe_auto_update()
        elapsed_ms = (time.perf_counter() - t) * 1000
        self.assertLess(elapsed_ms, 100, f"maybe_auto_update took {elapsed_ms:.1f}ms")

class TestAtomicCacheWrite(unittest.TestCase):
    """Tests for atomic cache write (write-to-temp + os.replace)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = stats.CACHE_DIR
        stats.CACHE_DIR = self.tmpdir

    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir)

    def test_no_tmp_file_left_after_save(self):
        """save_cache should not leave .tmp files behind."""
        stats = new_stats()
        stats["tool_counts"]["Bash"] = 3
        save_cache("atomic-test", stats, 512)

        files = os.listdir(self.tmpdir)
        tmp_files = [f for f in files if f.endswith('.tmp')]
        self.assertEqual(tmp_files, [], f"Leftover .tmp files: {tmp_files}")

    def test_cache_is_valid_json_after_save(self):
        """The cache file should always be valid JSON (never partially written)."""
        stats = new_stats()
        stats["total_input"] = 99999
        save_cache("atomic-json-test", stats, 2048)

        cache = load_cache("atomic-json-test")
        self.assertIsNotNone(cache)
        self.assertEqual(cache["stats"]["total_input"], 99999)
        self.assertEqual(cache["main_offset"], 2048)

    def test_overwrite_existing_cache_atomically(self):
        """Overwriting an existing cache should not corrupt it."""
        stats1 = new_stats()
        stats1["total_input"] = 100
        save_cache("overwrite-test", stats1, 100)

        stats2 = new_stats()
        stats2["total_input"] = 200
        save_cache("overwrite-test", stats2, 200)

        cache = load_cache("overwrite-test")
        self.assertEqual(cache["stats"]["total_input"], 200)
        self.assertEqual(cache["main_offset"], 200)
