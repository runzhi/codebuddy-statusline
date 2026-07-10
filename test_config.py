#!/usr/bin/env python3
"""Unit tests for config.py (layout config helper)."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

# Make sibling modules importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as config_mod


class TestConfigHelper(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ["CODEBUDDY_PLUGIN_DATA"] = self._tmp
        self._path = os.path.join(self._tmp, "config.json")

    def tearDown(self):
        os.environ.pop("CODEBUDDY_PLUGIN_DATA", None)

    def _read(self):
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_hide_round_trip(self):
        config_mod.main(["config.py", "hide", "credits", "time"])
        self.assertIn("credits", self._read()["layout"]["line1_hidden"])
        self.assertIn("time", self._read()["layout"]["line1_hidden"])

    def test_show_round_trip(self):
        config_mod.main(["config.py", "hide", "credits"])
        config_mod.main(["config.py", "show", "credits"])
        self.assertNotIn("credits", self._read()["layout"]["line1_hidden"])

    def test_move_front(self):
        config_mod.main(["config.py", "move", "cost", "front"])
        self.assertEqual(self._read()["layout"]["line1_order"][0], "cost")

    def test_move_after(self):
        config_mod.main(["config.py", "move", "cost", "after", "model"])
        order = self._read()["layout"]["line1_order"]
        self.assertEqual(order[order.index("model") + 1], "cost")

    def test_move_end(self):
        config_mod.main(["config.py", "move", "cwd_git", "end"])
        self.assertEqual(self._read()["layout"]["line1_order"][-1], "cwd_git")

    def test_move_accepts_optional_to(self):
        # Docs/README use `move X to front`; the CLI must accept the `to`.
        config_mod.main(["config.py", "move", "tokens", "to", "front"])
        self.assertEqual(self._read()["layout"]["line1_order"][0], "tokens")

    def test_move_after_with_to(self):
        config_mod.main(["config.py", "move", "model", "to", "after", "context_bar"])
        order = self._read()["layout"]["line1_order"]
        self.assertEqual(order[order.index("context_bar") + 1], "model")

    def test_disable_enable(self):
        config_mod.main(["config.py", "disable", "tools"])
        self.assertFalse(self._read()["layout"]["tools"])
        config_mod.main(["config.py", "enable", "tools"])
        self.assertTrue(self._read()["layout"]["tools"])

    def test_reset_deletes_file(self):
        config_mod.main(["config.py", "hide", "credits"])
        self.assertTrue(os.path.exists(self._path))
        config_mod.main(["config.py", "reset"])
        self.assertFalse(os.path.exists(self._path))

    def test_unknown_block_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            config_mod.main(["config.py", "hide", "bogus"])
        self.assertEqual(ctx.exception.code, 2)
        # No config file should be written on rejection.
        self.assertFalse(os.path.exists(self._path))

    def test_unknown_action_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            config_mod.main(["config.py", "frobnicate"])
        self.assertEqual(ctx.exception.code, 2)

    def test_atomic_write_leaves_no_tmp(self):
        config_mod.main(["config.py", "hide", "credits"])
        # No leftover temp file from the atomic write.
        self.assertFalse(any(f.endswith(".tmp") for f in os.listdir(self._tmp)))

    def test_list_shows_resolved_auto_append(self):
        # Hiding then showing a block must re-surface it at the END of the
        # resolved order (auto-append rule), and `list` must reflect that.
        config_mod.main(["config.py", "hide", "time"])
        config_mod.main(["config.py", "show", "time"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            config_mod.main(["config.py", "list"])
        out = buf.getvalue()
        # 'time' must appear in the resolved order line and at the end of it.
        line = [l for l in out.splitlines() if l.strip().startswith("line1 order:")][0]
        order = [b.strip() for b in line.split(":", 1)[1].strip().split("|")]
        self.assertIn("time", order)
        self.assertEqual(order[-1], "time")
        # And nothing should remain hidden after the show.
        self.assertIn("(none)", out)

    def test_first_edit_without_existing_file(self):
        # hide should work even when no config.json exists yet.
        config_mod.main(["config.py", "hide", "time"])
        self.assertTrue(os.path.exists(self._path))
        self.assertIn("time", self._read()["layout"]["line1_hidden"])


if __name__ == "__main__":
    unittest.main()
