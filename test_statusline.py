#!/usr/bin/env python3
"""Unit tests for statusline.py module"""

import json
import os
import sys
import tempfile
import shutil
import unittest

class TestMainNullSafety(unittest.TestCase):
    """Regression tests: CodeBuddy may send null for model/cost/context_window."""

    def _run_main(self, input_data):
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), 'statusline.py')],
            input=json.dumps(input_data),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
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

    def test_low_used_percentage_not_inflated(self):
        """used_percentage=0.81 (0-100 scale, meaning 0.81%) must render as ~1%, not 81%.

        Host computes used_percentage = round(ratio * 1e4) / 100 (0-100 scale,
        2 decimals). For 8121/1_000_000 = 0.81%, host sends 0.81. The old
        heuristic (used_pct > 1 ? ratio : percentage) misread this as 81%.
        """
        r = self._run_main({
            "context_window": {
                "used_percentage": 0.81,
                "context_window_size": 1_000_000,
                "current_usage": {"input_tokens": 8121},
            },
            "session_id": "t-low-pct", "transcript_path": "",
        })
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        import re
        plain = re.sub(r'\x1b\[[0-9;]*m', '', r.stdout)
        m = re.search(r'(\d+)%', plain)
        self.assertIsNotNone(m, f"no %% in output: {plain!r}")
        self.assertEqual(m.group(1), "1",
                         f"0.81% should round to 1%, got {m.group(1)}%: {plain!r}")

    def test_used_percentage_one_means_one_percent(self):
        """used_percentage=1 on 0-100 scale means 1%, not 100%.

        Boundary case that also broke under the old heuristic:
        `used_pct > 1` is False when used_pct == 1.
        """
        r = self._run_main({
            "context_window": {
                "used_percentage": 1,
                "context_window_size": 1_000_000,
                "current_usage": {"input_tokens": 10000},
            },
            "session_id": "t-one-pct", "transcript_path": "",
        })
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        import re
        plain = re.sub(r'\x1b\[[0-9;]*m', '', r.stdout)
        m = re.search(r'(\d+)%', plain)
        self.assertIsNotNone(m, f"no %% in output: {plain!r}")
        self.assertEqual(m.group(1), "1",
                         f"1% should display as 1%, got {m.group(1)}%: {plain!r}")

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
            # periodic summary
            f.write(json.dumps({
                'type': 'summary',
                'providerData': {'source': 'periodic'},
            }) + '\n')
            # 3 compact events (each = summary msg + "Please continue" msg)
            for _ in range(3):
                f.write(json.dumps({
                    'type': 'message',
                    'role': 'user',
                    'providerData': {'isCompactInternal': True, 'isSummary': True},
                }) + '\n')
                f.write(json.dumps({
                    'type': 'message',
                    'role': 'user',
                    'providerData': {'isCompactInternal': True},
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

    def test_compact_periodic_shown_without_used_percentage(self):
        """Compact×N and Periodic×M show even when used_percentage is null (post-compact first call)."""
        tmpdir = tempfile.mkdtemp()
        transcript = os.path.join(tmpdir, "no-pct-test.jsonl")
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                'type': 'summary',
                'providerData': {'source': 'periodic'},
            }) + '\n')
            f.write(json.dumps({
                'type': 'message',
                'role': 'user',
                'providerData': {'isCompactInternal': True, 'isSummary': True},
            }) + '\n')
            f.write(json.dumps({
                'type': 'message',
                'role': 'user',
                'providerData': {'isCompactInternal': True},
            }) + '\n')

        try:
            r = self._run_main({
                "context_window": {
                    "used_percentage": None,
                    "context_window_size": 200000,
                },
                "session_id": "no-pct-test",
                "transcript_path": transcript,
            })
            self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
            import re
            plain = re.sub(r'\x1b\[[0-9;]*m', '', r.stdout)
            self.assertIn("Compact×1", plain)
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
