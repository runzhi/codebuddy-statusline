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
    load_rate_snapshot, update_rate_snapshot,
    CACHE_DIR, CACHE_VERSION,
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


class TestRateSnapshot(unittest.TestCase):
    """Rate sidecar: Δoutput ÷ Δhost API time across renders.

    The host's cumulative API time is the only clock. It can be absent on a
    render, or jump between CostService instances, so it is high-water-marked
    and the baseline is only advanced when a sample is actually produced.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cache_dir = stats.CACHE_DIR
        stats.CACHE_DIR = self.tmpdir

    def tearDown(self):
        stats.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir)

    def test_first_call_baselines(self):
        self.assertIsNone(update_rate_snapshot("s1", 1000, 5000))
        snap = load_rate_snapshot("s1")
        self.assertEqual(snap["output"], 1000)
        self.assertIsNone(snap["rate"])

    def test_rate_from_deltas(self):
        update_rate_snapshot("s1", 1000, 5000)
        # +2000 tokens over +10s of API time -> 200 t/s
        self.assertAlmostEqual(update_rate_snapshot("s1", 3000, 15000), 200.0)

    def test_zero_output_writes_no_baseline(self):
        self.assertIsNone(update_rate_snapshot("s1", 0, 0))
        self.assertIsNone(load_rate_snapshot("s1"))

    def test_missing_api_time_writes_no_baseline(self):
        # Host omitted the field this render; recording a 0 baseline would
        # make the next call diff against 0.
        self.assertIsNone(update_rate_snapshot("s1", 1000, 0))
        self.assertIsNone(load_rate_snapshot("s1"))

    def test_increment_accumulates_across_uneven_renders(self):
        # Regression for "Speed never appears": output and API time advance
        # on different renders. The baseline must hold until both moved.
        update_rate_snapshot("s1", 1000, 5000)
        self.assertIsNone(update_rate_snapshot("s1", 1000, 9000))  # only API
        # +1000 tokens over the accumulated +4000 ms -> 250 t/s
        self.assertAlmostEqual(update_rate_snapshot("s1", 2000, 9000), 250.0)

    def test_no_new_sample_keeps_rate_and_baseline(self):
        update_rate_snapshot("s1", 1000, 5000)
        update_rate_snapshot("s1", 3000, 15000)  # -> 200.0
        self.assertAlmostEqual(update_rate_snapshot("s1", 3000, 15000), 200.0)
        # Baseline must not advance, or the pending deltas reset forever.
        self.assertEqual(load_rate_snapshot("s1")["api_ms"], 15000)

    def test_host_clock_high_water_mark(self):
        # A smaller host total (different CostService instance) must never
        # shrink the accumulated duration.
        update_rate_snapshot("s1", 1000, 50000)
        self.assertIsNone(update_rate_snapshot("s1", 2000, 10000))  # jumped down
        self.assertEqual(load_rate_snapshot("s1")["api_ms"], 50000)
        # +1000 tokens over +10s on top of the watermark -> 100 t/s
        self.assertAlmostEqual(update_rate_snapshot("s1", 2000, 60000), 100.0)

    def test_output_reset_rebaselines(self):
        update_rate_snapshot("s1", 5000, 5000)
        self.assertIsNone(update_rate_snapshot("s1", 100, 9000))
        self.assertIsNone(load_rate_snapshot("s1")["rate"])

    def test_preupgrade_sidecar_rebaselines(self):
        # A sidecar from the previous format is discarded rather than diffed.
        with open(os.path.join(self.tmpdir, "s1.rate.json"), "w") as f:
            json.dump({"output": 114768, "api_ms": 955081,
                       "usage_ts": 1791808322200, "eff_ms": 1791809046021,
                       "rate": 2.247}, f)
        self.assertIsNone(update_rate_snapshot("s1", 114768, 955081))
        self.assertEqual(load_rate_snapshot("s1")["v"], 2)

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
        stats.CACHE_DIR = self.tmpdir
        stats.UPDATE_MARKER = os.path.join(self.tmpdir, ".last-update-check")

    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
        stats.PLUGIN_DIR = self._orig_plugin_dir
        stats.UPDATE_MARKER = self._orig_marker
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_attempts_update_in_single_mode(self):
        """In the single (git-clone) mode, maybe_auto_update runs git pull."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        stats.PLUGIN_DIR = self.tmpdir
        with open(stats.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time()) - 2 * 86400))
        old_mtime = time.time() - 2 * 86400
        os.utime(stats.UPDATE_MARKER, (old_mtime, old_mtime))
        with unittest.mock.patch("subprocess.Popen") as mock_popen:
            maybe_auto_update()
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            self.assertEqual(args, ["git", "-C", self.tmpdir, "pull", "--ff-only", "--quiet"])

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
