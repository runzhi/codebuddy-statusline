#!/usr/bin/env python3
"""Unit tests for render.py module"""

import unittest

from render import format_tools, _format_tool_entry, format_recent_calls

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
