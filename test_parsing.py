#!/usr/bin/env python3
"""Unit tests for parsing.py module"""

import json
import os
import sys
import tempfile
import shutil
import time
import unittest
import unittest.mock

import stats
from stats import CACHE_VERSION, new_stats, CACHE_DIR, load_cache, save_cache
from parsing import add_line_to_stats, _extract_call_summary, parse_transcript_incremental as _parse_transcript_incremental


def parse_transcript_incremental(transcript_path, session_id):
    """Test wrapper that unpacks the (stats, was_truncated) tuple."""
    stats, _ = _parse_transcript_incremental(transcript_path, session_id)
    return stats

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
        """type=message with isCompactInternal=true + isSummary=true."""
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'role': 'user',
            'providerData': {'isCompactInternal': True, 'isSummary': True, 'agent': 'cli'},
        })
        self.assertEqual(stats["compact_count"], 1)

    def test_compact_count_no_isSummary(self):
        """Without isSummary (the "Please continue" message) should NOT count."""
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'role': 'user',
            'providerData': {'isCompactInternal': True, 'agent': 'cli'},
        })
        self.assertEqual(stats["compact_count"], 0)

    def test_compact_count_isCompactInternal_false(self):
        """isCompactInternal=false should NOT count as compact."""
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'role': 'user',
            'providerData': {'isCompactInternal': False, 'isSummary': True, 'agent': 'cli'},
        })
        self.assertEqual(stats["compact_count"], 0)

    def test_compact_count_no_isCompactInternal(self):
        """Message without isCompactInternal should NOT count as compact."""
        stats = new_stats()
        add_line_to_stats(stats, {
            'type': 'message',
            'role': 'user',
            'providerData': {'agent': 'cli'},
        })
        self.assertEqual(stats["compact_count"], 0)

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

class TestIncrementalParsing(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.transcript_path = os.path.join(self.tmpdir, "test.jsonl")
        self.cache_dir = os.path.join(self.tmpdir, "cache")
        self._orig_cache_dir = CACHE_DIR
        import statusline
        stats.CACHE_DIR = self.cache_dir

    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
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

class TestPartialLineRaceCondition(unittest.TestCase):
    """Tests for the fix: when a partial JSONL line is read (writer still
    appending), the offset should NOT advance past it, so the line gets
    re-read on the next invocation once the writer has finished."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.transcript_path = os.path.join(self.tmpdir, "test.jsonl")
        self.cache_dir = os.path.join(self.tmpdir, "cache")
        import statusline
        self._orig_cache_dir = stats.CACHE_DIR
        stats.CACHE_DIR = self.cache_dir

    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
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
