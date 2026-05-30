#!/usr/bin/env python3
"""Unit tests for statusline.py"""

import json
import os
import sys
import tempfile
import shutil
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from statusline import (
    format_tokens, format_cost, format_duration,
    make_progress_bar, new_stats, add_line_to_stats,
    format_tools, _format_tool_entry,
    parse_transcript_incremental, _parse_single_transcript_incremental,
    _merge_delta, load_cache, save_cache,
    cleanup_old_caches, maybe_auto_update,
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

    def test_agent_decrement_allows_negative(self):
        """running_agents delta can be negative (gauge, not counter). Clamping happens at merge time."""
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call_result', 'name': 'Agent'})
        self.assertEqual(stats["running_agents"], -1)

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
        self.assertEqual(stats["total_cache_read"], 2000)

    def test_no_provider_data(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash'})
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
        self._orig_cache_dir = CACHE_DIR
        import statusline
        statusline.CACHE_DIR = self.cache_dir

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
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
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["tool_counts"]["Bash"], 1)

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
        shutil.rmtree(self.tmpdir)

    def test_save_and_load_unified(self):
        """Unified cache stores stats, main_offset, and sub_offsets in one file."""
        stats = new_stats()
        stats["tool_counts"]["Bash"] = 5
        save_cache("test-session", stats, 1024, {"agent-abc": 500})
        cache = load_cache("test-session")
        self.assertIsNotNone(cache)
        self.assertEqual(cache["main_offset"], 1024)
        self.assertEqual(cache["sub_offsets"], {"agent-abc": 500})
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
        self._orig_cache_dir = statusline.CACHE_DIR
        statusline.CACHE_DIR = self.tmpdir

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
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

    def test_preserves_legacy_split_caches(self):
        """Legacy split offset cache files (with session_id_ prefix) should be preserved."""
        for key in ["sess1_main_offset", "sess1_sub_offset_agent-abc"]:
            path = os.path.join(self.tmpdir, f"{key}.json")
            with open(path, 'w') as f:
                json.dump({}, f)
            old_time = time.time() - 8 * 86400
            os.utime(path, (old_time, old_time))

        cleanup_old_caches("sess1")
        for key in ["sess1_main_offset", "sess1_sub_offset_agent-abc"]:
            self.assertTrue(os.path.exists(os.path.join(self.tmpdir, f"{key}.json")))

    def test_ignores_non_json_files(self):
        path = os.path.join(self.tmpdir, "readme.txt")
        with open(path, 'w') as f:
            f.write("hello")
        cleanup_old_caches("other-session")
        self.assertTrue(os.path.exists(path))


class TestMergeDelta(unittest.TestCase):
    def test_merge_numeric(self):
        stats = new_stats()
        stats["total_input"] = 100
        delta = new_stats()
        delta["total_input"] = 50
        delta["total_output"] = 20
        _merge_delta(stats, delta)
        self.assertEqual(stats["total_input"], 150)
        self.assertEqual(stats["total_output"], 20)

    def test_merge_dict(self):
        stats = new_stats()
        stats["tool_counts"]["Bash"] = 3
        delta = new_stats()
        delta["tool_counts"]["Bash"] = 2
        delta["tool_counts"]["Read"] = 1
        _merge_delta(stats, delta)
        self.assertEqual(stats["tool_counts"]["Bash"], 5)
        self.assertEqual(stats["tool_counts"]["Read"], 1)

    def test_skip_keys(self):
        stats = new_stats()
        stats["total_input"] = 100
        stats["running_agents"] = 2
        delta = new_stats()
        delta["total_input"] = 50
        delta["running_agents"] = 1
        _merge_delta(stats, delta, skip_keys={"running_agents"})
        self.assertEqual(stats["total_input"], 150)
        self.assertEqual(stats["running_agents"], 2)


class TestSingleTranscriptIncremental(unittest.TestCase):
    """Tests for _parse_single_transcript_incremental.

    Note: this function now takes start_offset directly (not a cache_key),
    and does not interact with any cache.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write_lines(self, path, lines):
        with open(path, 'w') as f:
            for line in lines:
                f.write(json.dumps(line) + '\n')

    def _append_lines(self, path, lines):
        with open(path, 'a') as f:
            for line in lines:
                f.write(json.dumps(line) + '\n')

    def test_reads_all_data_from_offset_0(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
            {'type': 'function_call', 'name': 'Read'},
        ])
        delta, offset, truncated, has_new_data = _parse_single_transcript_incremental(path, 0)
        self.assertEqual(delta["tool_counts"]["Bash"], 1)
        self.assertEqual(delta["tool_counts"]["Read"], 1)
        self.assertGreater(offset, 0)
        self.assertFalse(truncated)
        self.assertTrue(has_new_data)

    def test_returns_empty_delta_at_eof(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
        ])
        # First read to get final offset
        _, offset, _, _ = _parse_single_transcript_incremental(path, 0)
        # Re-read from EOF — should return empty delta
        delta, new_offset, _, has_new_data = _parse_single_transcript_incremental(path, offset)
        self.assertEqual(delta["tool_counts"], {})
        self.assertFalse(has_new_data)

    def test_incremental_reads_only_new_lines(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
        ])
        delta1, offset1, _, _ = _parse_single_transcript_incremental(path, 0)
        self.assertEqual(delta1["tool_counts"]["Bash"], 1)

        self._append_lines(path, [
            {'type': 'function_call', 'name': 'Read'},
            {'type': 'function_call', 'name': 'Bash'},
        ])
        delta2, offset2, _, _ = _parse_single_transcript_incremental(path, offset1)
        self.assertEqual(delta2["tool_counts"]["Bash"], 1)
        self.assertEqual(delta2["tool_counts"]["Read"], 1)

    def test_missing_file_returns_empty(self):
        delta, offset, truncated, has_new_data = _parse_single_transcript_incremental("/nonexistent/path.jsonl", 0)
        self.assertEqual(delta["tool_counts"], {})
        self.assertEqual(delta["total_input"], 0)
        self.assertEqual(offset, 0)
        self.assertFalse(truncated)
        self.assertFalse(has_new_data)

    def test_empty_file(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [])
        delta, offset, truncated, has_new_data = _parse_single_transcript_incremental(path, 0)
        self.assertEqual(delta["tool_counts"], {})
        self.assertEqual(offset, 0)
        self.assertFalse(truncated)
        self.assertFalse(has_new_data)

    def test_truncation_detected(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
            {'type': 'function_call', 'name': 'Read'},
        ])
        # Pass a fake offset way past EOF
        delta, offset, truncated, has_new_data = _parse_single_transcript_incremental(path, 999999)
        self.assertTrue(truncated)
        self.assertTrue(has_new_data)
        # Should re-parse from offset 0
        self.assertEqual(delta["tool_counts"]["Bash"], 1)
        self.assertEqual(delta["tool_counts"]["Read"], 1)
        self.assertGreater(offset, 0)

    def test_eof_match_is_not_truncation(self):
        """offset == filesize is normal EOF, not truncation."""
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
        ])
        file_size = os.path.getsize(path)
        delta, offset, truncated, has_new_data = _parse_single_transcript_incremental(path, file_size)
        self.assertFalse(truncated)
        self.assertFalse(has_new_data)

    def test_corrupted_offset_type(self):
        """Non-numeric offset should be treated as 0."""
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
        ])
        delta, offset, truncated, has_new_data = _parse_single_transcript_incremental(path, "not-a-number")
        self.assertEqual(delta["tool_counts"]["Bash"], 1)
        self.assertTrue(has_new_data)

    def test_returns_4tuple(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
        ])
        result = _parse_single_transcript_incremental(path, 0)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 4)

    def test_fast_path_at_eof_returns_zero_delta(self):
        """Fast path: when start_offset == file_size, skip the open entirely."""
        path = os.path.join(self.tmpdir, "test.jsonl")
        self._write_lines(path, [
            {'type': 'function_call', 'name': 'Bash'},
        ])
        file_size = os.path.getsize(path)
        # The fast path should take effect — has_new_data should be False
        delta, offset, truncated, has_new_data = _parse_single_transcript_incremental(path, file_size)
        self.assertFalse(has_new_data)
        self.assertEqual(offset, file_size)
        self.assertEqual(delta["total_input"], 0)


class TestSubagentParsing(unittest.TestCase):
    """Tests for parse_transcript_incremental with sub-agent transcripts."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.tmpdir, "cache")
        import statusline
        self._orig_cache_dir = statusline.CACHE_DIR
        statusline.CACHE_DIR = self.cache_dir

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir)

    def _setup_session(self, session_id):
        main_path = os.path.join(self.tmpdir, f"{session_id}.jsonl")
        session_dir = os.path.join(self.tmpdir, session_id)
        subagents_dir = os.path.join(session_dir, "subagents")
        os.makedirs(subagents_dir, exist_ok=True)
        return main_path, subagents_dir

    def _write_lines(self, path, lines):
        with open(path, 'w') as f:
            for line in lines:
                f.write(json.dumps(line) + '\n')

    def _append_lines(self, path, lines):
        with open(path, 'a') as f:
            for line in lines:
                f.write(json.dumps(line) + '\n')

    def _make_entry(self, name='Bash', input_tokens=0, output_tokens=0, entry_type='function_call'):
        entry = {'type': entry_type, 'name': name}
        if input_tokens > 0 or output_tokens > 0:
            entry['providerData'] = {
                'usage': {'inputTokens': input_tokens, 'outputTokens': output_tokens}
            }
        return entry

    def test_no_subagent_dir(self):
        main_path, _ = self._setup_session("sess1")
        shutil.rmtree(os.path.join(self.tmpdir, "sess1"))
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=50),
        ])
        stats = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats["total_input"], 100)
        self.assertEqual(stats["total_output"], 50)
        self.assertEqual(stats["tool_counts"]["Bash"], 1)

    def test_single_subagent(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=50),
            self._make_entry('Agent', entry_type='function_call'),
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Read', input_tokens=200, output_tokens=30),
            self._make_entry('Edit', input_tokens=150, output_tokens=20),
        ])
        stats = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats["total_input"], 450)
        self.assertEqual(stats["total_output"], 100)
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertEqual(stats["tool_counts"]["Agent"], 1)
        self.assertEqual(stats["tool_counts"]["Read"], 1)
        self.assertEqual(stats["tool_counts"]["Edit"], 1)

    def test_multiple_subagents(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Agent', entry_type='function_call'),
            self._make_entry('Agent', entry_type='function_call'),
        ])
        sub1 = os.path.join(sub_dir, "agent-aaa.jsonl")
        sub2 = os.path.join(sub_dir, "agent-bbb.jsonl")
        self._write_lines(sub1, [
            self._make_entry('Bash', input_tokens=100, output_tokens=10),
        ])
        self._write_lines(sub2, [
            self._make_entry('Read', input_tokens=200, output_tokens=20),
        ])
        stats = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats["total_input"], 300)
        self.assertEqual(stats["total_output"], 30)
        self.assertEqual(stats["tool_counts"]["Agent"], 2)
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertEqual(stats["tool_counts"]["Read"], 1)

    def test_subagent_incremental(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Agent', entry_type='function_call'),
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=10),
        ])

        stats1 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats1["total_input"], 100)
        self.assertEqual(stats1["total_output"], 10)

        self._append_lines(sub_path, [
            self._make_entry('Read', input_tokens=200, output_tokens=20),
        ])

        stats2 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats2["total_input"], 300)
        self.assertEqual(stats2["total_output"], 30)
        self.assertEqual(stats2["tool_counts"]["Read"], 1)

    def test_new_subagent_appears_mid_session(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Agent', entry_type='function_call'),
        ])

        stats1 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats1["tool_counts"]["Agent"], 1)
        self.assertEqual(stats1["total_input"], 0)

        sub_path = os.path.join(sub_dir, "agent-new.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Bash', input_tokens=500, output_tokens=50),
        ])

        stats2 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats2["total_input"], 500)
        self.assertEqual(stats2["total_output"], 50)
        self.assertEqual(stats2["tool_counts"]["Bash"], 1)

    def test_no_double_counting_across_calls(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=10),
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Read', input_tokens=200, output_tokens=20),
        ])

        stats1 = parse_transcript_incremental(main_path, "sess1")
        stats2 = parse_transcript_incremental(main_path, "sess1")
        stats3 = parse_transcript_incremental(main_path, "sess1")

        self.assertEqual(stats1["total_input"], 300)
        self.assertEqual(stats2["total_input"], 300)
        self.assertEqual(stats3["total_input"], 300)
        self.assertEqual(stats1["total_output"], 30)
        self.assertEqual(stats3["total_output"], 30)
        self.assertEqual(stats1["request_count"], stats3["request_count"])

    def test_running_agents_from_main_only(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            {'type': 'function_call', 'name': 'Agent'},
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            {'type': 'function_call', 'name': 'Agent'},
        ])

        stats = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats["running_agents"], 1)
        self.assertEqual(stats["tool_counts"]["Agent"], 2)

    def test_running_agents_decrement(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            {'type': 'function_call', 'name': 'Agent'},
            {'type': 'function_call_result', 'name': 'Agent'},
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Bash', input_tokens=50, output_tokens=5),
        ])

        stats = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats["running_agents"], 0)
        self.assertEqual(stats["tool_counts"]["Agent"], 1)
        self.assertEqual(stats["total_input"], 50)

    def test_running_agents_decrement_across_chunks(self):
        """Agent start in one chunk, complete in next — running_agents should go to 0."""
        main_path, _ = self._setup_session("sess1")
        self._write_lines(main_path, [
            {'type': 'function_call', 'name': 'Agent'},
        ])
        stats1 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats1["running_agents"], 1)

        self._append_lines(main_path, [
            {'type': 'function_call_result', 'name': 'Agent'},
        ])
        stats2 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats2["running_agents"], 0)

    def test_multiple_agents_mixed_completion_across_chunks(self):
        main_path, _ = self._setup_session("sess1")
        self._write_lines(main_path, [
            {'type': 'function_call', 'name': 'Agent'},
            {'type': 'function_call', 'name': 'Agent'},
            {'type': 'function_call', 'name': 'Agent'},
        ])
        stats1 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats1["running_agents"], 3)

        self._append_lines(main_path, [
            {'type': 'function_call_result', 'name': 'Agent'},
            {'type': 'function_call_result', 'name': 'Agent'},
        ])
        stats2 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats2["running_agents"], 1)

    def test_unified_cache_format(self):
        """The unified cache should contain stats, main_offset, and sub_offsets in one file."""
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=10),
        ])
        sub1 = os.path.join(sub_dir, "agent-aaa.jsonl")
        sub2 = os.path.join(sub_dir, "agent-bbb.jsonl")
        self._write_lines(sub1, [
            self._make_entry('Read', input_tokens=50),
        ])
        self._write_lines(sub2, [
            self._make_entry('Edit', input_tokens=80),
        ])

        parse_transcript_incremental(main_path, "sess1")

        # Only ONE cache file should exist
        cache_files = os.listdir(self.cache_dir)
        self.assertEqual(cache_files, ["sess1.json"])

        # Verify cache structure
        cache = load_cache("sess1")
        self.assertIn("stats", cache)
        self.assertIn("main_offset", cache)
        self.assertIn("sub_offsets", cache)
        self.assertGreater(cache["main_offset"], 0)
        self.assertIn("agent-aaa", cache["sub_offsets"])
        self.assertIn("agent-bbb", cache["sub_offsets"])

    def test_main_and_subagent_incremental_growth(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=10),
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Read', input_tokens=50, output_tokens=5),
        ])

        stats1 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats1["total_input"], 150)

        self._append_lines(main_path, [
            self._make_entry('Edit', input_tokens=80, output_tokens=8),
        ])
        self._append_lines(sub_path, [
            self._make_entry('Glob', input_tokens=40, output_tokens=4),
        ])

        stats2 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats2["total_input"], 270)
        self.assertEqual(stats2["total_output"], 27)
        self.assertEqual(stats2["tool_counts"]["Bash"], 1)
        self.assertEqual(stats2["tool_counts"]["Edit"], 1)
        self.assertEqual(stats2["tool_counts"]["Read"], 1)
        self.assertEqual(stats2["tool_counts"]["Glob"], 1)

    def test_non_jsonl_files_in_subagents_dir_ignored(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100),
        ])
        with open(os.path.join(sub_dir, "README.md"), 'w') as f:
            f.write("not a transcript")
        os.makedirs(os.path.join(sub_dir, "data.jsonl"), exist_ok=True)
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Read', input_tokens=50),
        ])
        stats = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats["total_input"], 150)
        self.assertEqual(stats["tool_counts"]["Read"], 1)

    def test_subagent_file_deleted_between_calls(self):
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100),
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Read', input_tokens=50),
        ])

        stats1 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats1["total_input"], 150)

        os.remove(sub_path)

        stats2 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats2["total_input"], 150)
        self.assertEqual(stats2["tool_counts"]["Read"], 1)

    def test_malformed_jsonl_lines_skipped(self):
        main_path, _ = self._setup_session("sess1")
        with open(main_path, 'w') as f:
            f.write('this is not json\n')
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write('{"broken json\n')
        stats = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats["tool_counts"]["Bash"], 1)

    def test_main_transcript_truncation(self):
        """If main transcript is rewritten shorter, stats reset to a full re-parse."""
        main_path, _ = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=1000, output_tokens=100),
            self._make_entry('Read', input_tokens=2000, output_tokens=200),
            self._make_entry('Edit', input_tokens=500, output_tokens=50),
        ])
        stats1 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats1["total_input"], 3500)
        self.assertEqual(stats1["request_count"], 3)

        # Truncate (rewrite) the file with shorter content
        self._write_lines(main_path, [
            self._make_entry('Glob', input_tokens=42, output_tokens=4),
        ])

        stats2 = parse_transcript_incremental(main_path, "sess1")
        self.assertEqual(stats2["total_input"], 42)
        self.assertEqual(stats2["total_output"], 4)
        self.assertEqual(stats2["request_count"], 1)
        self.assertEqual(stats2["tool_counts"]["Glob"], 1)
        self.assertNotIn("Bash", stats2["tool_counts"])
        self.assertNotIn("Read", stats2["tool_counts"])
        self.assertNotIn("Edit", stats2["tool_counts"])

    def test_no_writes_in_steady_state(self):
        """When no new data, repeated calls should not modify cache files."""
        main_path, sub_dir = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=10),
        ])
        sub_path = os.path.join(sub_dir, "agent-abc.jsonl")
        self._write_lines(sub_path, [
            self._make_entry('Read', input_tokens=50, output_tokens=5),
        ])

        parse_transcript_incremental(main_path, "sess1")

        cache_files = sorted(os.listdir(self.cache_dir))
        mtimes_before = {f: os.path.getmtime(os.path.join(self.cache_dir, f))
                         for f in cache_files}

        time.sleep(0.05)

        parse_transcript_incremental(main_path, "sess1")

        cache_files_after = sorted(os.listdir(self.cache_dir))
        self.assertEqual(cache_files, cache_files_after)
        for f in cache_files:
            mtime_after = os.path.getmtime(os.path.join(self.cache_dir, f))
            self.assertEqual(mtimes_before[f], mtime_after,
                             f"{f} was rewritten despite no new data")

    def test_writes_when_new_data(self):
        """When new data appears, cache should be updated."""
        main_path, _ = self._setup_session("sess1")
        self._write_lines(main_path, [
            self._make_entry('Bash', input_tokens=100, output_tokens=10),
        ])

        parse_transcript_incremental(main_path, "sess1")
        mtime_before = os.path.getmtime(os.path.join(self.cache_dir, "sess1.json"))

        time.sleep(0.05)

        self._append_lines(main_path, [
            self._make_entry('Read', input_tokens=50, output_tokens=5),
        ])

        parse_transcript_incremental(main_path, "sess1")
        mtime_after = os.path.getmtime(os.path.join(self.cache_dir, "sess1.json"))
        self.assertGreater(mtime_after, mtime_before)


class TestAutoUpdate(unittest.TestCase):
    """Tests for the auto-update feature (maybe_auto_update)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = statusline.CACHE_DIR
        self._orig_plugin_dir = statusline.PLUGIN_DIR
        self._orig_marker = statusline.UPDATE_MARKER
        statusline.CACHE_DIR = self.tmpdir
        statusline.UPDATE_MARKER = os.path.join(self.tmpdir, ".last-update-check")

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
        statusline.PLUGIN_DIR = self._orig_plugin_dir
        statusline.UPDATE_MARKER = self._orig_marker
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_op_when_not_a_git_repo(self):
        """When PLUGIN_DIR isn't a git repo, maybe_auto_update is a no-op."""
        import statusline
        statusline.PLUGIN_DIR = self.tmpdir  # not a git repo
        # Should return without raising and without creating the marker
        maybe_auto_update()
        self.assertFalse(os.path.exists(statusline.UPDATE_MARKER))

    def test_skips_when_marker_recent(self):
        """If the marker file is fresh, maybe_auto_update should skip."""
        import statusline
        # Set up a fake git repo
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        statusline.PLUGIN_DIR = self.tmpdir
        # Create a fresh marker
        with open(statusline.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time())))
        marker_mtime_before = os.path.getmtime(statusline.UPDATE_MARKER)
        time.sleep(0.05)
        maybe_auto_update()
        # Marker should NOT be touched (no fork/pull triggered)
        marker_mtime_after = os.path.getmtime(statusline.UPDATE_MARKER)
        self.assertEqual(marker_mtime_before, marker_mtime_after)

    def test_runs_when_marker_old(self):
        """If marker is older than UPDATE_INTERVAL_SECONDS, update is triggered."""
        import statusline
        # Set up a fake git repo (won't actually have a remote, so pull will fail
        # silently in the grandchild — but the marker should be touched).
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        statusline.PLUGIN_DIR = self.tmpdir
        # Create an old marker (2 days ago)
        with open(statusline.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time()) - 2 * 86400))
        old_mtime = time.time() - 2 * 86400
        os.utime(statusline.UPDATE_MARKER, (old_mtime, old_mtime))

        marker_mtime_before = os.path.getmtime(statusline.UPDATE_MARKER)
        maybe_auto_update()
        # Marker should be refreshed (mtime advanced)
        marker_mtime_after = os.path.getmtime(statusline.UPDATE_MARKER)
        self.assertGreater(marker_mtime_after, marker_mtime_before)

    def test_creates_marker_on_first_run(self):
        """First run (no marker yet) should create the marker."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        statusline.PLUGIN_DIR = self.tmpdir
        self.assertFalse(os.path.exists(statusline.UPDATE_MARKER))
        maybe_auto_update()
        self.assertTrue(os.path.exists(statusline.UPDATE_MARKER))

    def test_returns_quickly(self):
        """maybe_auto_update must not block the statusline (returns in << 100ms)."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        statusline.PLUGIN_DIR = self.tmpdir
        # Force an update attempt
        old_mtime = time.time() - 2 * 86400
        with open(statusline.UPDATE_MARKER, 'w') as f:
            f.write("0")
        os.utime(statusline.UPDATE_MARKER, (old_mtime, old_mtime))

        t = time.perf_counter()
        maybe_auto_update()
        elapsed_ms = (time.perf_counter() - t) * 1000
        # Even with fork() overhead, should return well under 100ms
        self.assertLess(elapsed_ms, 100, f"maybe_auto_update took {elapsed_ms:.1f}ms")


if __name__ == '__main__':
    unittest.main()
