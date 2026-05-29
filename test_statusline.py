#!/usr/bin/env python3
"""Unit tests for statusline.py"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from statusline import (
    format_tokens, format_cost, format_duration,
    make_progress_bar, new_stats, add_line_to_stats,
    format_tools, _format_tool_entry,
    parse_transcript_incremental, load_cache, save_cache,
    CACHE_DIR,
)


class TestFormatTokens(unittest.TestCase):
    def test_none(self):
        self.assertEqual(format_tokens(None), "0")

    def test_zero(self):
        self.assertEqual(format_tokens(0), "0")

    def test_small(self):
        self.assertEqual(format_tokens(42), "42")

    def test_thousands(self):
        self.assertEqual(format_tokens(1500), "1.5K")

    def test_exact_thousand(self):
        self.assertEqual(format_tokens(1000), "1.0K")

    def test_millions(self):
        self.assertEqual(format_tokens(2_500_000), "2.5M")

    def test_exact_million(self):
        self.assertEqual(format_tokens(1_000_000), "1.0M")


class TestFormatCost(unittest.TestCase):
    def test_none(self):
        self.assertEqual(format_cost(None), "")

    def test_zero(self):
        self.assertEqual(format_cost(0), "")

    def test_tiny(self):
        self.assertEqual(format_cost(0.005), "$0.0050")

    def test_small(self):
        self.assertEqual(format_cost(0.05), "$0.050")

    def test_medium(self):
        self.assertEqual(format_cost(0.5), "$0.500")

    def test_large(self):
        self.assertEqual(format_cost(5.0), "$5.00")


class TestFormatDuration(unittest.TestCase):
    def test_none(self):
        self.assertEqual(format_duration(None), "")

    def test_zero(self):
        self.assertEqual(format_duration(0), "")

    def test_seconds(self):
        self.assertEqual(format_duration(45000), "45s")

    def test_minutes_seconds(self):
        self.assertEqual(format_duration(125000), "2m5s")

    def test_one_minute(self):
        self.assertEqual(format_duration(60000), "1m0s")


class TestMakeProgressBar(unittest.TestCase):
    def test_zero(self):
        bar, color = make_progress_bar(0)
        self.assertEqual(bar, ' ' * 10)

    def test_full(self):
        bar, color = make_progress_bar(1.0)
        self.assertEqual(bar, '█' * 10)

    def test_half_color_green(self):
        _, color = make_progress_bar(0.3)
        self.assertEqual(color, '\033[0;32m')  # GREEN

    def test_mid_color_yellow(self):
        _, color = make_progress_bar(0.6)
        self.assertEqual(color, '\033[1;33m')  # YELLOW

    def test_high_color_red(self):
        _, color = make_progress_bar(0.9)
        self.assertEqual(color, '\033[0;31m')  # RED


class TestNewStats(unittest.TestCase):
    def test_defaults(self):
        stats = new_stats()
        self.assertEqual(stats["total_input"], 0)
        self.assertEqual(stats["total_output"], 0)
        self.assertEqual(stats["running_agents"], 0)
        self.assertEqual(stats["tool_counts"], {})
        self.assertEqual(stats["request_count"], 0)


class TestAddLineToStats(unittest.TestCase):
    def test_tool_call_counting(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash'})
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash'})
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Read'})
        self.assertEqual(stats["tool_counts"]["Bash"], 2)
        self.assertEqual(stats["tool_counts"]["Read"], 1)

    def test_agent_running(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Agent', 'callId': 'a1'})
        self.assertEqual(stats["running_agents"], 1)
        self.assertEqual(stats["tool_counts"]["Agent"], 1)

    def test_agent_completed(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Agent', 'callId': 'a1'})
        add_line_to_stats(stats, {'type': 'function_call_result', 'name': 'Agent', 'callId': 'a1'})
        self.assertEqual(stats["running_agents"], 0)

    def test_agent_multiple_running(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Agent', 'callId': 'a1'})
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Agent', 'callId': 'a2'})
        self.assertEqual(stats["running_agents"], 2)
        add_line_to_stats(stats, {'type': 'function_call_result', 'name': 'Agent', 'callId': 'a1'})
        self.assertEqual(stats["running_agents"], 1)

    def test_token_usage(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'providerData': {
                'usage': {
                    'inputTokens': 1000,
                    'outputTokens': 500,
                    'inputTokensDetails': [{'cached_tokens': 800}],
                    'outputTokensDetails': [{'reasoning_tokens': 200}],
                },
                'rawUsage': {
                    'cache_creation_input_tokens': 100,
                    'credit': 5.0,
                },
            }
        })
        self.assertEqual(stats["total_input"], 1000)
        self.assertEqual(stats["total_output"], 500)
        self.assertEqual(stats["total_cache_read"], 800)
        self.assertEqual(stats["total_cache_write"], 100)
        self.assertEqual(stats["total_reasoning"], 200)
        self.assertEqual(stats["total_credits"], 5.0)
        self.assertEqual(stats["request_count"], 1)

    def test_raw_usage_cache_read_override(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'providerData': {
                'usage': {
                    'inputTokens': 100,
                    'outputTokens': 50,
                    'inputTokensDetails': [{'cached_tokens': 30}],
                },
                'rawUsage': {
                    'prompt_cache_hit_tokens': 2000,
                },
            }
        })
        # rawUsage.prompt_cache_hit_tokens should override
        self.assertEqual(stats["total_cache_read"], 2000)

    def test_no_provider_data(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash'})
        # Should not crash, just skip token counting
        self.assertEqual(stats["request_count"], 0)

    def test_empty_provider_data(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'message', 'providerData': {}})
        self.assertEqual(stats["request_count"], 0)


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


class TestIncrementalParsing(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.transcript_path = os.path.join(self.tmpdir, "test.jsonl")
        self.cache_dir = os.path.join(self.tmpdir, "cache")
        # Override CACHE_DIR for testing
        self._orig_cache_dir = CACHE_DIR
        import statusline
        statusline.CACHE_DIR = self.cache_dir

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
        import shutil
        shutil.rmtree(self.tmpdir)

    def _write_lines(self, lines):
        with open(self.transcript_path, 'w') as f:
            for line in lines:
                f.write(json.dumps(line) + '\n')

    def test_basic_parse(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
            {'type': 'function_call', 'name': 'Read'},
        ])
        stats = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertEqual(stats["tool_counts"]["Read"], 1)

    def test_incremental(self):
        # First write
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["tool_counts"]["Bash"], 1)

        # Append more
        with open(self.transcript_path, 'a') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Read'}) + '\n')
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')

        stats2 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats2["tool_counts"]["Bash"], 2)
        self.assertEqual(stats2["tool_counts"]["Read"], 1)

    def test_missing_transcript(self):
        stats = parse_transcript_incremental("/nonexistent/path.jsonl", "test-session")
        self.assertEqual(stats["tool_counts"], {})

    def test_empty_transcript(self):
        self._write_lines([])
        stats = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats["tool_counts"], {})


class TestCacheOperations(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = statusline.CACHE_DIR
        statusline.CACHE_DIR = self.tmpdir

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_save_and_load(self):
        stats = new_stats()
        stats["tool_counts"]["Bash"] = 5
        save_cache("test-session", 1024, stats)
        cache = load_cache("test-session")
        self.assertIsNotNone(cache)
        self.assertEqual(cache["offset"], 1024)
        self.assertEqual(cache["stats"]["tool_counts"]["Bash"], 5)

    def test_load_missing(self):
        self.assertIsNone(load_cache("nonexistent"))


if __name__ == '__main__':
    unittest.main()
