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
    format_tools, _format_tool_entry, format_recent_calls, _extract_call_summary,
    parse_transcript_incremental as _parse_transcript_incremental,
    load_cache, save_cache,
    cleanup_old_caches, maybe_auto_update,
    CACHE_DIR, CACHE_VERSION, IS_PLUGIN_MODE,
)


def parse_transcript_incremental(transcript_path, session_id):
    """Test wrapper that unpacks the (stats, was_truncated) tuple."""
    stats, _ = _parse_transcript_incremental(transcript_path, session_id)
    return stats


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
        self.assertEqual(format_cost(0.005), "$0.01(¥0.04)")

    def test_small(self):
        self.assertEqual(format_cost(0.05), "$0.05(¥0.35)")

    def test_medium(self):
        self.assertEqual(format_cost(0.5), "$0.50(¥3.50)")

    def test_large(self):
        self.assertEqual(format_cost(5.0), "$5.00(¥35.00)")


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
        self.assertEqual(stats["total_cache_read"], 0)
        self.assertEqual(stats["total_reasoning"], 0)
        self.assertEqual(stats["total_credits"], 0.0)
        self.assertEqual(stats["request_count"], 0)
        self.assertEqual(stats["tool_counts"], {})
        self.assertEqual(stats["running_agents"], 0)
        self.assertEqual(stats["compact_count"], 0)
        self.assertEqual(stats["periodic_count"], 0)


class TestAddLineToStats(unittest.TestCase):
    def test_tool_call_counting(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash'})
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash'})
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Read'})
        self.assertEqual(stats["tool_counts"]["Bash"], 2)
        self.assertEqual(stats["tool_counts"]["Read"], 1)

    def test_recent_calls_tracked(self):
        stats = new_stats()
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash', 'arguments': '{"command": "ls"}'})
        add_line_to_stats(stats, {'type': 'function_call', 'name': 'Read', 'arguments': '{"file_path": "/tmp/f.txt"}'})
        self.assertEqual(len(stats["recent_calls"]), 2)
        self.assertEqual(stats["recent_calls"][0]["name"], "Bash")
        self.assertEqual(stats["recent_calls"][1]["name"], "Read")

    def test_recent_calls_max_three(self):
        stats = new_stats()
        for i in range(5):
            add_line_to_stats(stats, {'type': 'function_call', 'name': 'Bash', 'arguments': f'{{"command": "cmd{i}"}}'})
        self.assertEqual(len(stats["recent_calls"]), 3)
        self.assertEqual(stats["recent_calls"][0]["summary"], "cmd2")
        self.assertEqual(stats["recent_calls"][2]["summary"], "cmd4")

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

    def test_reasoning_and_credits(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'providerData': {
                'usage': {
                    'inputTokens': 1000,
                    'outputTokens': 500,
                    'outputTokensDetails': [{'reasoning_tokens': 200}],
                    'inputTokensDetails': [{'cached_tokens': 800}],
                },
                'rawUsage': {
                    'credit': 5.0,
                },
            }
        })
        self.assertEqual(stats["total_input"], 1000)
        self.assertEqual(stats["total_output"], 500)
        self.assertEqual(stats["total_cache_read"], 800)
        self.assertEqual(stats["total_reasoning"], 200)
        self.assertEqual(stats["total_credits"], 5.0)
        self.assertEqual(stats["request_count"], 1)

    def test_no_reasoning_tokens(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'providerData': {
                'usage': {
                    'inputTokens': 100,
                    'outputTokens': 50,
                },
                'rawUsage': {
                    'credit': 1.0,
                },
            }
        })
        self.assertEqual(stats["total_reasoning"], 0)
        self.assertEqual(stats["total_credits"], 1.0)
        self.assertEqual(stats["request_count"], 1)

    def test_raw_usage_cache_hit_fallback(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'providerData': {
                'usage': {
                    'inputTokens': 100,
                    'outputTokens': 50,
                },
                'rawUsage': {
                    'prompt_cache_hit_tokens': 80,
                },
            }
        })
        self.assertEqual(stats["total_cache_read"], 80)

    def test_no_raw_usage(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'providerData': {
                'usage': {
                    'inputTokens': 100,
                    'outputTokens': 50,
                },
            }
        })
        self.assertEqual(stats["total_reasoning"], 0)
        self.assertEqual(stats["total_credits"], 0.0)
        self.assertEqual(stats["request_count"], 1)

    def test_compact_count(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'summary',
            'providerData': {'source': 'pre-compact'},
        })
        self.assertEqual(stats["compact_count"], 1)

    def test_compact_count_counts_periodic_summary(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'summary',
            'providerData': {'source': 'periodic'},
        })
        self.assertEqual(stats["periodic_count"], 1)
        self.assertEqual(stats["compact_count"], 0)

    def test_compact_count_ignores_initial_user_message(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'summary',
            'providerData': {'source': 'initial-user-message'},
        })
        self.assertEqual(stats["compact_count"], 0)

    def test_compact_count_ignores_no_source(self):
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'summary',
        })
        self.assertEqual(stats["compact_count"], 0)

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


class TestExtractCallSummary(unittest.TestCase):
    def test_bash_from_arguments(self):
        result = _extract_call_summary("Bash", {"command": "ls -la /tmp", "description": "List files"})
        self.assertEqual(result, "ls -la /tmp")

    def test_read_from_arguments(self):
        result = _extract_call_summary("Read", {"file_path": "/data/workspace/project/main.py"})
        self.assertEqual(result, "/data/workspace/project/main.py")

    def test_edit_from_arguments(self):
        result = _extract_call_summary("Edit", {"file_path": "/data/app/config.yaml", "old_string": "x", "new_string": "y"})
        self.assertEqual(result, "/data/app/config.yaml")

    def test_grep_from_arguments(self):
        result = _extract_call_summary("Grep", {"pattern": "TODO", "path": "/src"})
        self.assertIn("TODO", result)
        self.assertIn("/src", result)

    def test_glob_from_arguments(self):
        result = _extract_call_summary("Glob", {"pattern": "**/*.py"})
        self.assertEqual(result, "**/*.py")

    def test_no_args_returns_name(self):
        result = _extract_call_summary("Unknown", {})
        self.assertEqual(result, "Unknown")

    def test_non_dict_args_returns_name(self):
        result = _extract_call_summary("Bash", "not a dict")
        self.assertEqual(result, "Bash")

    def test_no_truncation(self):
        """_extract_call_summary does not truncate; format_recent_calls does."""
        result = _extract_call_summary("Bash", {"command": "x" * 100})
        self.assertEqual(len(result), 100)

    def test_grep_empty_fields(self):
        result = _extract_call_summary("Grep", {"pattern": "", "path": ""})
        self.assertEqual(result, "Grep")

    def test_empty_command_fallback(self):
        result = _extract_call_summary("Bash", {"command": ""})
        self.assertEqual(result, "Bash")

    def test_agent_from_arguments(self):
        result = _extract_call_summary("Agent", {"description": "Explore codebase for patterns"})
        self.assertEqual(result, "Explore codebase for patterns")


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
        self.assertLessEqual(len(plain), 70)  # name + space + 59 + ellipsis


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

    def _append_lines(self, lines):
        with open(self.transcript_path, 'a') as f:
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

        self._append_lines([
            {'type': 'function_call', 'name': 'Read'},
            {'type': 'function_call', 'name': 'Bash'},
        ])

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

    def test_reasoning_and_credits_incremental(self):
        self._write_lines([
            {'type': 'message', 'providerData': {
                'usage': {'inputTokens': 100, 'outputTokens': 50,
                          'outputTokensDetails': [{'reasoning_tokens': 200}]},
                'rawUsage': {'credit': 3.0},
            }},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["total_reasoning"], 200)
        self.assertEqual(stats1["total_credits"], 3.0)
        self.assertEqual(stats1["request_count"], 1)

        self._append_lines([
            {'type': 'message', 'providerData': {
                'usage': {'inputTokens': 200, 'outputTokens': 100,
                          'outputTokensDetails': [{'reasoning_tokens': 100}]},
                'rawUsage': {'credit': 2.0},
            }},
        ])
        stats2 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats2["total_reasoning"], 300)
        self.assertEqual(stats2["total_credits"], 5.0)
        self.assertEqual(stats2["request_count"], 2)

    def test_fast_path_at_eof(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["tool_counts"]["Bash"], 1)
        # Calling again with no new data should return the same stats
        stats2 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats2["tool_counts"]["Bash"], 1)

    def test_truncation_resets_stats(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
            {'type': 'function_call', 'name': 'Read'},
            {'type': 'function_call', 'name': 'Edit'},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["tool_counts"]["Bash"], 1)
        self.assertEqual(stats1["tool_counts"]["Read"], 1)
        self.assertEqual(stats1["tool_counts"]["Edit"], 1)

        # Truncate (rewrite) the file with shorter content
        self._write_lines([
            {'type': 'function_call', 'name': 'Glob'},
        ])
        stats2 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats2["tool_counts"]["Glob"], 1)
        self.assertNotIn("Bash", stats2["tool_counts"])
        self.assertNotIn("Read", stats2["tool_counts"])
        self.assertNotIn("Edit", stats2["tool_counts"])

    def test_agent_running_across_chunks(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Agent'},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["running_agents"], 1)

        self._append_lines([
            {'type': 'function_call_result', 'name': 'Agent'},
        ])
        stats2 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats2["running_agents"], 0)

    def test_multiple_agents_mixed_completion(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Agent'},
            {'type': 'function_call', 'name': 'Agent'},
            {'type': 'function_call', 'name': 'Agent'},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["running_agents"], 3)

        self._append_lines([
            {'type': 'function_call_result', 'name': 'Agent'},
            {'type': 'function_call_result', 'name': 'Agent'},
        ])
        stats2 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats2["running_agents"], 1)

    def test_no_double_counting_across_calls(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
        ])
        stats1 = parse_transcript_incremental(self.transcript_path, "test-session")
        stats2 = parse_transcript_incremental(self.transcript_path, "test-session")
        stats3 = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats1["tool_counts"]["Bash"], 1)
        self.assertEqual(stats2["tool_counts"]["Bash"], 1)
        self.assertEqual(stats3["tool_counts"]["Bash"], 1)

    def test_malformed_jsonl_lines_skipped(self):
        with open(self.transcript_path, 'w') as f:
            f.write('this is not json\n')
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write('{"broken json\n')
        stats = parse_transcript_incremental(self.transcript_path, "test-session")
        self.assertEqual(stats["tool_counts"]["Bash"], 1)

    def test_empty_path(self):
        stats = parse_transcript_incremental("", "test-session")
        self.assertEqual(stats["tool_counts"], {})

    def test_old_cache_obsolete_keys_removed(self):
        """Same-version cache with obsolete keys: backfill missing, remove unknown."""
        import statusline
        # Write a transcript first so we can get its size for a valid offset
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
        ])
        file_size = os.path.getsize(self.transcript_path)

        old_cache = {
            "stats": {
                "total_input": 4626389,
                "total_output": 8991,
                "total_cache_read": 4561920,
                "total_cache_write": 0,
                "total_reasoning": 445,
                "total_credits": 115.71,
                "request_count": 104,
                "tool_counts": {"Bash": 32},
                "running_agents": 0,
                "some_unknown_future_key": 999,
            },
            "main_offset": file_size,
            "sub_offsets": {"agent-abc": 12345},
            "cache_version": CACHE_VERSION,
        }
        os.makedirs(self.cache_dir, exist_ok=True)
        cache_path = os.path.join(self.cache_dir, "old-sess.json")
        with open(cache_path, 'w') as f:
            json.dump(old_cache, f)

        # Append new data to the transcript
        self._append_lines([
            {'type': 'function_call', 'name': 'Read'},
        ])

        stats = parse_transcript_incremental(self.transcript_path, "old-sess")
        # Known valid keys should be preserved
        self.assertEqual(stats["total_reasoning"], 445)
        self.assertEqual(stats["request_count"], 104)
        self.assertEqual(stats["tool_counts"]["Bash"], 32)
        self.assertEqual(stats["tool_counts"]["Read"], 1)
        # Missing fields should be backfilled
        self.assertEqual(stats["compact_count"], 0)
        self.assertEqual(stats["periodic_count"], 0)
        # Unknown keys should be removed
        self.assertNotIn("some_unknown_future_key", stats)

    def test_stale_compact_cache_preserved_on_fast_path(self):
        """Fast path: cached compact_count preserved when no new data."""
        self._write_lines([
            {'type': 'summary', 'providerData': {'source': 'initial-user-message'}},
            {'type': 'summary', 'providerData': {'source': 'periodic'}},
        ])
        file_size = os.path.getsize(self.transcript_path)

        old_cache = {
            "stats": dict(new_stats(), compact_count=5, periodic_count=2),
            "main_offset": file_size,
            "sub_offsets": {},
            "cache_version": CACHE_VERSION,
        }
        os.makedirs(self.cache_dir, exist_ok=True)
        cache_path = os.path.join(self.cache_dir, "compact-old-cache.json")
        with open(cache_path, 'w') as f:
            json.dump(old_cache, f)

        stats = parse_transcript_incremental(self.transcript_path, "compact-old-cache")
        # Fast path: offset matches file size, cache preserved as-is
        self.assertEqual(stats["compact_count"], 5)
        self.assertEqual(stats["periodic_count"], 2)

    def test_subagent_parsing(self):
        """Sub-agent transcripts contribute to token/credit/tool counts."""
        # Create a session directory structure with sub-agents
        session_dir = os.path.join(self.tmpdir, "subagent-test-session")
        subagents_dir = os.path.join(session_dir, "subagents")
        os.makedirs(subagents_dir)
        transcript_path = os.path.join(self.tmpdir, "subagent-test-session.jsonl")

        # Main transcript
        with open(transcript_path, 'w') as f:
            f.write(json.dumps({
                'type': 'message',
                'providerData': {
                    'usage': {'inputTokens': 1000, 'outputTokens': 500,
                              'inputTokensDetails': [{'cached_tokens': 200}]},
                    'rawUsage': {'credit': 3.0},
                },
            }) + '\n')
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write(json.dumps({'type': 'function_call', 'name': 'Agent', 'callId': 'a1'}) + '\n')

        # Sub-agent transcript
        with open(os.path.join(subagents_dir, "agent-abc123.jsonl"), 'w') as f:
            f.write(json.dumps({
                'type': 'message',
                'providerData': {
                    'usage': {'inputTokens': 500, 'outputTokens': 200,
                              'inputTokensDetails': [{'cached_tokens': 100}]},
                    'rawUsage': {'credit': 1.5},
                },
            }) + '\n')
            f.write(json.dumps({'type': 'function_call', 'name': 'Read'}) + '\n')

        stats = parse_transcript_incremental(transcript_path, "subagent-test-session")

        # Token counts should include sub-agent
        self.assertEqual(stats["total_input"], 1500)   # 1000 + 500
        self.assertEqual(stats["total_output"], 700)    # 500 + 200
        self.assertEqual(stats["total_cache_read"], 300)  # 200 + 100
        self.assertEqual(stats["total_credits"], 4.5)   # 3.0 + 1.5
        # Tools include sub-agent tools
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertEqual(stats["tool_counts"]["Agent"], 1)
        self.assertEqual(stats["tool_counts"]["Read"], 1)
        # running_agents only from main transcript
        self.assertEqual(stats["running_agents"], 1)

        # Sub-agent offset should be cached
        cache = load_cache("subagent-test-session")
        self.assertIn("sub_offsets", cache)
        self.assertIn("agent-abc123", cache["sub_offsets"])

    def test_subagent_incremental(self):
        """Sub-agent incremental parsing only reads new lines."""
        session_dir = os.path.join(self.tmpdir, "inc-sess")
        subagents_dir = os.path.join(session_dir, "subagents")
        os.makedirs(subagents_dir)
        transcript_path = os.path.join(self.tmpdir, "inc-sess.jsonl")

        # Main transcript
        with open(transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')

        stats1 = parse_transcript_incremental(transcript_path, "inc-sess")
        self.assertEqual(stats1["tool_counts"]["Bash"], 1)

        # Add sub-agent
        with open(os.path.join(subagents_dir, "agent-xyz.jsonl"), 'w') as f:
            f.write(json.dumps({
                'type': 'message',
                'providerData': {
                    'usage': {'inputTokens': 500, 'outputTokens': 100},
                },
            }) + '\n')

        stats2 = parse_transcript_incremental(transcript_path, "inc-sess")
        self.assertEqual(stats2["total_input"], 500)
        self.assertEqual(stats2["tool_counts"]["Bash"], 1)  # unchanged

    def test_no_writes_in_steady_state(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
        ])
        parse_transcript_incremental(self.transcript_path, "test-session")

        cache_files = sorted(os.listdir(self.cache_dir))
        mtimes_before = {f: os.path.getmtime(os.path.join(self.cache_dir, f))
                         for f in cache_files}

        time.sleep(0.05)

        parse_transcript_incremental(self.transcript_path, "test-session")

        cache_files_after = sorted(os.listdir(self.cache_dir))
        self.assertEqual(cache_files, cache_files_after)
        for f in cache_files:
            mtime_after = os.path.getmtime(os.path.join(self.cache_dir, f))
            self.assertEqual(mtimes_before[f], mtime_after,
                             f"{f} was rewritten despite no new data")

    def test_writes_when_new_data(self):
        self._write_lines([
            {'type': 'function_call', 'name': 'Bash'},
        ])

        parse_transcript_incremental(self.transcript_path, "test-session")
        mtime_before = os.path.getmtime(os.path.join(self.cache_dir, "test-session.json"))

        time.sleep(0.05)

        self._append_lines([
            {'type': 'function_call', 'name': 'Read'},
        ])

        parse_transcript_incremental(self.transcript_path, "test-session")
        mtime_after = os.path.getmtime(os.path.join(self.cache_dir, "test-session.json"))
        self.assertGreater(mtime_after, mtime_before)


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
        self._orig_cache_dir = statusline.CACHE_DIR
        self._orig_plugin_dir = statusline.PLUGIN_DIR
        self._orig_marker = statusline.UPDATE_MARKER
        self._orig_is_plugin_mode = statusline.IS_PLUGIN_MODE
        statusline.CACHE_DIR = self.tmpdir
        statusline.UPDATE_MARKER = os.path.join(self.tmpdir, ".last-update-check")
        statusline.IS_PLUGIN_MODE = False  # default: git-clone mode for tests

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
        statusline.PLUGIN_DIR = self._orig_plugin_dir
        statusline.UPDATE_MARKER = self._orig_marker
        statusline.IS_PLUGIN_MODE = self._orig_is_plugin_mode
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_skipped_in_plugin_mode(self):
        """When IS_PLUGIN_MODE is True, maybe_auto_update is a no-op."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        statusline.PLUGIN_DIR = self.tmpdir
        statusline.IS_PLUGIN_MODE = True
        maybe_auto_update()
        self.assertFalse(os.path.exists(statusline.UPDATE_MARKER))

    def test_no_op_when_not_a_git_repo(self):
        """When PLUGIN_DIR isn't a git repo, maybe_auto_update is a no-op."""
        import statusline
        statusline.PLUGIN_DIR = self.tmpdir
        maybe_auto_update()
        self.assertFalse(os.path.exists(statusline.UPDATE_MARKER))

    def test_skips_when_marker_recent(self):
        """If the marker file is fresh, maybe_auto_update should skip."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        statusline.PLUGIN_DIR = self.tmpdir
        with open(statusline.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time())))
        marker_mtime_before = os.path.getmtime(statusline.UPDATE_MARKER)
        time.sleep(0.05)
        maybe_auto_update()
        marker_mtime_after = os.path.getmtime(statusline.UPDATE_MARKER)
        self.assertEqual(marker_mtime_before, marker_mtime_after)

    def test_runs_when_marker_old(self):
        """If marker is older than UPDATE_INTERVAL_SECONDS, update is triggered."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        statusline.PLUGIN_DIR = self.tmpdir
        with open(statusline.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time()) - 2 * 86400))
        old_mtime = time.time() - 2 * 86400
        os.utime(statusline.UPDATE_MARKER, (old_mtime, old_mtime))

        marker_mtime_before = os.path.getmtime(statusline.UPDATE_MARKER)
        maybe_auto_update()
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
        old_mtime = time.time() - 2 * 86400
        with open(statusline.UPDATE_MARKER, 'w') as f:
            f.write("0")
        os.utime(statusline.UPDATE_MARKER, (old_mtime, old_mtime))

        t = time.perf_counter()
        maybe_auto_update()
        elapsed_ms = (time.perf_counter() - t) * 1000
        self.assertLess(elapsed_ms, 100, f"maybe_auto_update took {elapsed_ms:.1f}ms")


class TestPartialLineRaceCondition(unittest.TestCase):
    """Tests for the fix: when a partial JSONL line is read (writer still
    appending), the offset should NOT advance past it, so the line gets
    re-read on the next invocation once the writer has finished."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.transcript_path = os.path.join(self.tmpdir, "test.jsonl")
        self.cache_dir = os.path.join(self.tmpdir, "cache")
        import statusline
        self._orig_cache_dir = statusline.CACHE_DIR
        statusline.CACHE_DIR = self.cache_dir

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir)

    def _write_lines(self, lines):
        with open(self.transcript_path, 'w') as f:
            for line in lines:
                f.write(json.dumps(line) + '\n')

    def test_partial_last_line_main_transcript(self):
        """A partial last line (no trailing \\n) should not advance offset."""
        # Write a complete line + a partial line (simulating writer mid-write)
        with open(self.transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write('{"type": "function_call", "name": "Rea')  # partial, no \n

        stats = parse_transcript_incremental(self.transcript_path, "partial-test")
        # Only the complete Bash line should be counted
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertNotIn("Read", stats["tool_counts"])

    def test_partial_line_retried_after_completion(self):
        """A partial line should be retried after the writer finishes it."""
        # First read: partial line at the end
        with open(self.transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write('{"type": "function_call", "name": "Rea')

        stats1 = parse_transcript_incremental(self.transcript_path, "partial-retry")
        self.assertEqual(stats1["tool_counts"]["Bash"], 1)
        self.assertNotIn("Read", stats1["tool_counts"])

        # Now the writer finishes the line (append the rest + newline)
        with open(self.transcript_path, 'r') as f:
            content = f.read()
        with open(self.transcript_path, 'w') as f:
            f.write(content + 'd"}\n')

        stats2 = parse_transcript_incremental(self.transcript_path, "partial-retry")
        # Read should now be counted (offset was rewound)
        self.assertEqual(stats2["tool_counts"]["Bash"], 1)
        self.assertEqual(stats2["tool_counts"]["Read"], 1)

    def test_partial_line_with_new_data_after(self):
        """After a partial line, new complete lines appended after it are
        also picked up once the partial line is completed."""
        # First read: partial line
        with open(self.transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write('{"type": "function_call", "name": "Rea')

        parse_transcript_incremental(self.transcript_path, "partial-extra")

        # Writer completes the partial line AND appends a new complete line
        with open(self.transcript_path, 'r') as f:
            content = f.read()
        with open(self.transcript_path, 'w') as f:
            f.write(content + 'd"}\n')
            f.write(json.dumps({'type': 'function_call', 'name': 'Edit'}) + '\n')

        stats = parse_transcript_incremental(self.transcript_path, "partial-extra")
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertEqual(stats["tool_counts"]["Read"], 1)
        self.assertEqual(stats["tool_counts"]["Edit"], 1)

    def test_malformed_line_with_newline_is_not_retried(self):
        """A malformed line that HAS a trailing \\n is a genuinely bad line,
        not a partial write — it should be skipped permanently."""
        with open(self.transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write('{"broken json}\n')  # has \n but invalid JSON
            f.write(json.dumps({'type': 'function_call', 'name': 'Edit'}) + '\n')

        stats = parse_transcript_incremental(self.transcript_path, "malformed-test")
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertEqual(stats["tool_counts"]["Edit"], 1)
        # broken json line is skipped, not retried

    def test_partial_subagent_line(self):
        """Sub-agent transcript: partial last line should not advance offset."""
        session_dir = os.path.join(self.tmpdir, "sub-partial-sess")
        subagents_dir = os.path.join(session_dir, "subagents")
        os.makedirs(subagents_dir)
        transcript_path = os.path.join(self.tmpdir, "sub-partial-sess.jsonl")

        # Main transcript
        with open(transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')

        # Sub-agent transcript with partial last line
        sub_path = os.path.join(subagents_dir, "agent-abc.jsonl")
        with open(sub_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Read'}) + '\n')
            f.write('{"type": "function_call", "name": "Grep", "a')  # partial

        stats = parse_transcript_incremental(transcript_path, "sub-partial-sess")
        self.assertEqual(stats["tool_counts"]["Bash"], 1)
        self.assertEqual(stats["tool_counts"]["Read"], 1)
        # Grep not counted yet
        self.assertNotIn("Grep", stats["tool_counts"])

    def test_partial_subagent_line_retried(self):
        """Sub-agent partial line is retried after completion."""
        session_dir = os.path.join(self.tmpdir, "sub-partial-retry")
        subagents_dir = os.path.join(session_dir, "subagents")
        os.makedirs(subagents_dir)
        transcript_path = os.path.join(self.tmpdir, "sub-partial-retry.jsonl")

        with open(transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')

        sub_path = os.path.join(subagents_dir, "agent-abc.jsonl")
        with open(sub_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Read'}) + '\n')
            f.write('{"type": "function_call", "name": "Grep", "a')

        parse_transcript_incremental(transcript_path, "sub-partial-retry")

        # Complete the partial line
        with open(sub_path, 'r') as f:
            content = f.read()
        with open(sub_path, 'w') as f:
            f.write(content + 'rgs": {}}\n')

        stats = parse_transcript_incremental(transcript_path, "sub-partial-retry")
        self.assertEqual(stats["tool_counts"]["Read"], 1)
        self.assertEqual(stats["tool_counts"]["Grep"], 1)

    def test_partial_line_offset_preserved_in_cache(self):
        """The rewound offset for a partial line must be saved to cache."""
        with open(self.transcript_path, 'w') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
            f.write('{"type": "function_call", "name": "Rea')

        parse_transcript_incremental(self.transcript_path, "offset-cache-test")

        cache = load_cache("offset-cache-test")
        self.assertIsNotNone(cache)
        # The offset should be right after the first complete line,
        # NOT past the partial line.
        first_line_size = len(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')
        self.assertEqual(cache["main_offset"], first_line_size)


class TestAtomicCacheWrite(unittest.TestCase):
    """Tests for atomic cache write (write-to-temp + os.replace)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = statusline.CACHE_DIR
        statusline.CACHE_DIR = self.tmpdir

    def tearDown(self):
        import statusline
        statusline.CACHE_DIR = self._orig_cache_dir
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


class TestMainNullSafety(unittest.TestCase):
    """Regression tests: CodeBuddy may send null for model/cost/context_window."""

    def _run_main(self, input_data):
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), 'statusline.py')],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result

    def test_null_cost(self):
        r = self._run_main({"cost": None, "session_id": "t", "transcript_path": ""})
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_null_model(self):
        r = self._run_main({"model": None, "session_id": "t", "transcript_path": ""})
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_null_context_window(self):
        r = self._run_main({"context_window": None, "session_id": "t", "transcript_path": ""})
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_null_current_usage(self):
        r = self._run_main({
            "context_window": {"used_percentage": 50, "current_usage": None},
            "session_id": "t", "transcript_path": "",
        })
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_all_null(self):
        r = self._run_main({
            "model": None, "cost": None, "context_window": None,
            "session_id": "", "transcript_path": "",
        })
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_empty_object(self):
        r = self._run_main({})
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_normal_data_still_works(self):
        r = self._run_main({
            "model": {"display_name": "TestModel"},
            "context_window": {
                "used_percentage": 60,
                "context_window_size": 200000,
                "current_usage": {"input_tokens": 100000, "cache_read_input_tokens": 50000},
                "total_input_tokens": 1500000,
                "total_output_tokens": 50000,
            },
            "cost": {"total_cost_usd": 0.05, "total_duration_ms": 30000},
            "session_id": "t", "transcript_path": "",
        })
        self.assertEqual(r.returncode, 0)
        # Strip ANSI escape codes for assertion
        import re
        plain = re.sub(r'\x1b\[[0-9;]*m', '', r.stdout)
        self.assertIn("TestModel", plain)
        self.assertIn("In:1.5M", plain)

    def test_compact_count_in_output(self):
        """End-to-end: Compact×N and Periodic×M appear separately in statusline output."""
        # Create a transcript with compact events
        tmpdir = tempfile.mkdtemp()
        transcript = os.path.join(tmpdir, "compact-test.jsonl")
        with open(transcript, 'w') as f:
            # initial summary (should NOT count)
            f.write(json.dumps({
                'type': 'summary',
                'providerData': {'source': 'initial-user-message'},
            }) + '\n')
            # periodic and pre-compact summaries counted separately
            for src in ['periodic', 'pre-compact', 'pre-compact', 'pre-compact']:
                f.write(json.dumps({
                    'type': 'summary',
                    'providerData': {'source': src},
                }) + '\n')
            # some tool calls
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash'}) + '\n')

        try:
            r = self._run_main({
                "context_window": {
                    "used_percentage": 50,
                    "context_window_size": 200000,
                    "current_usage": {"input_tokens": 50000},
                    "total_input_tokens": 50000,
                    "total_output_tokens": 1000,
                },
                "session_id": "compact-test",
                "transcript_path": transcript,
            })
            self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
            import re
            plain = re.sub(r'\x1b\[[0-9;]*m', '', r.stdout)
            self.assertIn("Compact×3", plain)
            self.assertIn("Periodic×1", plain)
        finally:
            shutil.rmtree(tmpdir)

    def test_lines_display(self):
        """End-to-end: +N/-M shows raw cumulative values from cost."""
        r = self._run_main({
            "cost": {"total_lines_added": 100, "total_lines_removed": 30},
            "context_window": {
                "used_percentage": 50,
                "context_window_size": 200000,
                "current_usage": {"input_tokens": 50000},
                "total_input_tokens": 50000,
                "total_output_tokens": 1000,
            },
            "session_id": "lines-test",
            "transcript_path": "",
        })
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        import re
        plain = re.sub(r'\x1b\[[0-9;]*m', '', r.stdout)
        self.assertIn("+100", plain)
        self.assertIn("-30", plain)
