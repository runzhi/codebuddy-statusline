#!/usr/bin/env python3
"""Unit tests for render.py module"""

import json
import os
import re
import unittest
from unittest import mock

import stats

from render import (
    BLOCKS_LINE1,
    build_statusline,
    format_recent_calls,
    format_tools,
    resolve_layout,
    _display_dir_name,
    _format_tool_entry,
    _render_cwd_git,
)

class TestFormatTools(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(format_tools({}), "")

    def test_single_tool(self):
        result = format_tools({"Bash": 1})
        self.assertIn("Bash", result)
        self.assertIn("✓", result)

    def test_tool_with_count(self):
        result = format_tools({"Bash": 5})
        self.assertIn("×5", result)

    def test_tool_order(self):
        result = format_tools({"Grep": 1, "Bash": 1, "Read": 1})
        bash_pos = result.index("Bash")
        read_pos = result.index("Read")
        grep_pos = result.index("Grep")
        self.assertLess(bash_pos, read_pos)
        self.assertLess(read_pos, grep_pos)

    def test_agent_running(self):
        result = format_tools({"Agent": 3}, running_agents=1)
        self.assertIn("↑", result)
        self.assertIn("✓", result)

    def test_agent_all_completed(self):
        result = format_tools({"Agent": 3}, running_agents=0)
        self.assertIn("✓", result)
        self.assertNotIn("↑", result)

    def test_agent_all_running(self):
        result = format_tools({"Agent": 2}, running_agents=2)
        self.assertIn("↑", result)
        self.assertNotIn("✓", result)

class TestFormatToolEntry(unittest.TestCase):
    def test_single(self):
        result = _format_tool_entry("✓", "\033[0;32m", "Bash", 1)
        self.assertIn("Bash", result)
        self.assertNotIn("×", result)

    def test_multiple(self):
        result = _format_tool_entry("✓", "\033[0;32m", "Bash", 5)
        self.assertIn("×5", result)

    def test_no_count(self):
        result = _format_tool_entry("↑", "\033[1;33m", "Agent")
        self.assertIn("Agent", result)
        self.assertNotIn("×", result)

class TestFormatRecentCalls(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(format_recent_calls([]), "")

    def test_single_call(self):
        calls = [{"name": "Bash", "summary": "ls -la"}]
        result = format_recent_calls(calls)
        self.assertIn("Bash", result)
        self.assertIn("ls -la", result)

    def test_multiple_calls_pipe_separated(self):
        calls = [
            {"name": "Bash", "summary": "ls -la"},
            {"name": "Read", "summary": "/data/app/main.py"},
        ]
        result = format_recent_calls(calls)
        self.assertIn("|", result)
        self.assertIn("Bash", result)
        self.assertIn("Read", result)

    def test_short_name_used(self):
        calls = [{"name": "WebSearch", "summary": "python async"}]
        result = format_recent_calls(calls)
        self.assertIn("Search", result)

    def test_no_summary(self):
        calls = [{"name": "Bash", "summary": "Bash"}]
        result = format_recent_calls(calls)
        self.assertIn("Bash", result)
        # Should not duplicate name when summary equals name

    def test_truncation_with_ellipsis(self):
        calls = [{"name": "Bash", "summary": "x" * 100}]
        result = format_recent_calls(calls)
        # Strip ANSI
        import re
        plain = re.sub(r'\033\[[0-9;]*m', '', result)
        self.assertIn("…", plain)
        self.assertLessEqual(len(plain), 70)


class TestResolveLayout(unittest.TestCase):
    def test_default_when_no_config(self):
        layout = resolve_layout(None)
        self.assertEqual(layout["line1_order"], BLOCKS_LINE1)
        self.assertTrue(layout["tools"])
        self.assertTrue(layout["recent"])

    def test_default_when_garbled(self):
        # Wrong shape must fall back to defaults, never raise.
        self.assertEqual(resolve_layout({"layout": "nope"})["line1_order"], BLOCKS_LINE1)
        self.assertEqual(resolve_layout({"layout": {"line1_order": 123}})["line1_order"], BLOCKS_LINE1)

    def test_hidden_omitted(self):
        cfg = {"layout": {"line1_hidden": ["credits", "time"]}}
        order = resolve_layout(cfg)["line1_order"]
        self.assertNotIn("credits", order)
        self.assertNotIn("time", order)

    def test_reorder_then_auto_append(self):
        # Only two blocks listed -> the rest auto-append in canonical order.
        cfg = {"layout": {"line1_order": ["model", "cost"]}}
        order = resolve_layout(cfg)["line1_order"]
        self.assertEqual(order[0], "model")
        self.assertEqual(order[1], "cost")
        # All known blocks still present (auto-appended).
        self.assertEqual(set(order), set(BLOCKS_LINE1))

    def test_hidden_overrides_order(self):
        # A block in both order and hidden must be excluded.
        cfg = {"layout": {"line1_order": ["cwd_git", "credits"], "line1_hidden": ["credits"]}}
        order = resolve_layout(cfg)["line1_order"]
        self.assertNotIn("credits", order)
        self.assertIn("cwd_git", order)

    def test_unknown_id_ignored(self):
        cfg = {"layout": {"line1_order": ["cwd_git", "bogus", "model"]}}
        order = resolve_layout(cfg)["line1_order"]
        self.assertNotIn("bogus", order)
        self.assertEqual(order[0], "cwd_git")
        self.assertEqual(order[1], "model")

    def test_line_toggles_default_on(self):
        cfg = {"layout": {"tools": False, "recent": False}}
        layout = resolve_layout(cfg)
        self.assertFalse(layout["tools"])
        self.assertFalse(layout["recent"])


class TestDisplayDirName(unittest.TestCase):
    def test_normal_dir(self):
        self.assertEqual(_display_dir_name("/home/user/myproject"), "myproject")

    def test_trailing_slash(self):
        self.assertEqual(_display_dir_name("/home/user/myproject/"), "myproject")

    def test_codebuddy_worktree_shows_project_name(self):
        path = "/Users/runzhi/.codebuddy/statusline/.codebuddy/worktrees/worktree"
        self.assertEqual(_display_dir_name(path), "statusline")

    def test_git_linked_worktree_absolute_gitdir(self):
        # Simulate a git-linked worktree: .git is a file pointing at the
        # main repo's .git/worktrees/<name>.
        import tempfile
        import textwrap
        with tempfile.TemporaryDirectory() as d:
            wt = os.path.join(d, "my-wt")
            os.makedirs(wt)
            with open(os.path.join(wt, ".git"), "w") as f:
                f.write("gitdir: %s/myproject/.git/worktrees/my-wt\n"
                        % d)
            self.assertEqual(_display_dir_name(wt), "myproject")

    def test_git_linked_worktree_relative_gitdir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            # Layout: <d>/checkouts/<wt>  with .git pointing at
            # ../myproject/.git/worktrees/<wt>
            wt = os.path.join(d, "checkouts", "wt")
            os.makedirs(wt)
            with open(os.path.join(wt, ".git"), "w") as f:
                f.write("gitdir: ../myproject/.git/worktrees/wt\n")
            self.assertEqual(_display_dir_name(wt), "myproject")

    def test_regular_git_repo_not_worktree(self):
        # A normal repo has a .git *directory*, not a link file.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "realproject")
            os.makedirs(os.path.join(repo, ".git"))
            self.assertEqual(_display_dir_name(repo), "realproject")

    def test_empty(self):
        self.assertEqual(_display_dir_name(""), "")
        self.assertEqual(_display_dir_name(None), "")


class TestRenderCwdGit(unittest.TestCase):
    def _call(self, current_dir, git_info):
        with mock.patch("render.get_git_info", return_value=git_info):
            return _render_cwd_git({"workspace": {"current_dir": current_dir}}, {})

    def test_worktree_shows_project_name_with_branch(self):
        out = self._call(
            "/Users/runzhi/.codebuddy/statusline/.codebuddy/worktrees/worktree",
            {"branch": "main", "dirty": False, "ahead": 0, "behind": 0},
        )
        self.assertIn("statusline", out)
        self.assertIn("main", out)

    def test_normal_dir(self):
        out = self._call(
            "/home/user/myproject",
            {"branch": "dev", "dirty": True, "ahead": 0, "behind": 0},
        )
        self.assertIn("myproject", out)
        self.assertIn("dev", out)


class TestBuildStatuslineConfig(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self._orig_plugin_data = stats._PLUGIN_DATA
        stats._PLUGIN_DATA = self._tmp

    def tearDown(self):
        stats._PLUGIN_DATA = self._orig_plugin_data

    def _write_config(self, layout):
        with open(os.path.join(self._tmp, "config.json"), "w") as f:
            json.dump({"layout": layout}, f)

    def _sample(self):
        inp = {
            "model": {"display_name": "claude-sonnet"},
            "cost": {"total_cost_usd": 0.02, "total_duration_ms": 65000,
                     "total_lines_added": 3, "total_lines_removed": 1},
            "context_window": {"used_percentage": 12.5, "context_window_size": 200000,
                              "current_usage": {"input_tokens": 25000}},
        }
        stats = {
            "total_input": 3200, "total_output": 800, "total_cache_read": 1500,
            "total_reasoning": 0, "total_credits": 0, "request_count": 5,
            "tool_counts": {"Bash": 2, "Read": 1}, "running_agents": 0,
            "compact_count": 0, "periodic_count": 0,
            "recent_calls": [{"name": "Bash", "summary": "ls -la"}],
            "last_input": 3200, "last_output": 800, "last_cache_read": 1500,
            "last_credits": 0, "last_cost": 0.01,
        }
        return inp, stats

    def test_default_output_unchanged(self):
        # No config file -> identical to the pre-config build.
        inp, stats = self._sample()
        out = build_statusline(inp, stats)
        self.assertIn("claude-sonnet", out)
        # cost value is contiguous (no ANSI inside format_cost output)
        self.assertIn("$0.02(¥0.14)", out)
        self.assertIn("Tools:", out)
        self.assertIn("Recent:", out)

    def test_hidden_removes_from_output(self):
        self._write_config({"line1_hidden": ["credits", "time"]})
        inp, stats = self._sample()
        out = build_statusline(inp, stats)
        # credits value 0 here so weak signal; check 'Time:' absence instead.
        self.assertNotIn("Time:", out)

    def test_disable_lines(self):
        self._write_config({"tools": False, "recent": False})
        inp, stats = self._sample()
        out = build_statusline(inp, stats)
        self.assertNotIn("Tools:", out)
        self.assertNotIn("Recent:", out)

    def test_compact_periodic_own_slot(self):
        # compact_periodic must render as its own " | "-separated block,
        # not glued onto the previous segment (the pre-config behavior).
        self._write_config({})
        inp, stats = self._sample()
        stats["compact_count"] = 1
        stats["periodic_count"] = 2
        out = re.sub(r'\033\[[0-9;]*m', '', build_statusline(inp, stats))
        self.assertIn("| Compact×1", out)
        self.assertIn("Compact×1 Periodic×2", out)

    def test_compact_periodic_only_periodic_no_double_space(self):
        # When only Periodic is present, the block must not gain a leading
        # space (which would produce " |  Periodic" with a double space).
        self._write_config({})
        inp, stats = self._sample()
        stats["compact_count"] = 0
        stats["periodic_count"] = 1
        out = re.sub(r'\033\[[0-9;]*m', '', build_statusline(inp, stats))
        self.assertIn("| Periodic×1", out)
        self.assertNotIn("|  Periodic", out)


if __name__ == "__main__":
    unittest.main()
