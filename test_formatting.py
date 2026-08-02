#!/usr/bin/env python3
"""Unit tests for formatting.py module"""

import os
import sys
import unittest
import unittest.mock

import formatting
from formatting import (
    format_tokens, format_cost, format_duration, make_progress_bar,
    truncate_to_width, get_statusline_width, get_statusline_width_from_input,
    _tty_columns, _windows_columns, _visible_len,
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
        self.assertEqual(format_cost(0.005), "$0.01(¥0.04)")

    def test_tiny_no_zero(self):
        # Would round to 0.00 at 2 dp; must show more digits instead.
        self.assertEqual(format_cost(0.0005), "$0.001(¥0.004)")

    def test_tiny_no_zero_four_dp(self):
        self.assertEqual(format_cost(0.00005), "$0.0001(¥0.0003)")

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
        self.assertEqual(color, '\033[0;31m')

class TestTruncateToWidth(unittest.TestCase):
    """ANSI-safe line truncation for the 3-line statusline.

    The statusline renderer only shows 3 rows. If a line is longer than
    the terminal width it auto-wraps, and the wrapped half visually
    pushes the next row out of view. truncate_to_width prevents that.
    """

    def test_short_string_unchanged(self):
        self.assertEqual(truncate_to_width("hello", 10), "hello")

    def test_exact_length_unchanged(self):
        self.assertEqual(truncate_to_width("hello", 5), "hello")

    def test_truncates_with_ellipsis(self):
        out = truncate_to_width("abcdefghij", 5)
        # 4 visible chars + ellipsis = 5 columns
        self.assertEqual(_visible_len(out), 5)
        self.assertTrue(out.endswith("…"))

    def test_preserves_ansi_codes_intact(self):
        # Cyan "hello" then reset, in 12 visible chars
        s = "\033[0;36mhello\033[0m"
        out = truncate_to_width(s, 3)
        # Opening cyan code must be preserved verbatim (never sliced in half)
        self.assertIn("\033[0;36m", out)
        # Visible width is 2 chars + ellipsis = 3
        self.assertEqual(_visible_len(out), 3)
        self.assertTrue(out.endswith("…"))

    def test_closes_unterminated_sgr_before_ellipsis(self):
        # Mid-color truncation: red is opened, never closed in the kept
        # prefix. truncate_to_width must inject a reset before the
        # ellipsis so the next statusline row does not inherit red.
        s = "\033[0;31mfoo\033[0m \033[0;32mbar\033[0m"
        out = truncate_to_width(s, 4)
        # The red prefix survives; green did not get rendered.
        self.assertIn("\033[0;31m", out)
        self.assertNotIn("\033[0;32m", out)
        # There must be a bare reset ("\033[0m") between the content
        # and the ellipsis — that's what stops the color leak.
        self.assertRegex(out, r"\033\[0m…$")

    def test_zero_or_negative_width(self):
        # width=0 means "unknown width, don't truncate" — return input unchanged
        self.assertEqual(truncate_to_width("hello", 0), "hello")
        # Negative width is invalid — return empty string
        self.assertEqual(truncate_to_width("hello", -3), "")

    def test_empty_string(self):
        self.assertEqual(truncate_to_width("", 5), "")

    def test_ellipsis_never_split(self):
        out = truncate_to_width("a" * 100, 1)
        # With width=1, budget for content is 0, so we just emit an ellipsis
        # truncated to the requested width.
        self.assertEqual(_visible_len(out), 1)

    def test_multiple_ansi_codes_preserved(self):
        # When truncating mid-content, the opening color codes seen so far
        # are kept; later codes are dropped along with their content.
        s = "\033[0;31mfoo\033[0m \033[0;32mbar\033[0m baz"
        out = truncate_to_width(s, 4)
        # Red "foo" survived (its opening code is present), green was cut
        self.assertIn("\033[0;31m", out)
        self.assertNotIn("\033[0;32m", out)
        self.assertLessEqual(_visible_len(out), 4)

    def test_cjk_wide_chars_count_as_two(self):
        # CJK characters each occupy 2 terminal columns.
        # "你好世界" = 8 columns. Truncating to 5 should keep 2 chars
        # (4 cols) + ellipsis (1 col) = 5 columns.
        s = "你好世界"
        self.assertEqual(_visible_len(s), 8)
        out = truncate_to_width(s, 5)
        self.assertEqual(_visible_len(out), 5)
        self.assertTrue(out.endswith("…"))

    def test_cjk_wide_char_not_split(self):
        # A wide char that doesn't fit in the remaining budget is dropped
        # entirely rather than being split.
        # "a你好" = 1+2+2 = 5 cols. Truncating to 4:
        # budget = 4 - 1(ellipsis) = 3. "a" (1) + "你" (2) = 3 fits,
        # "好" (2) would make 5 > 3, so "好" is dropped.
        s = "a你好"
        out = truncate_to_width(s, 4)
        self.assertLessEqual(_visible_len(out), 4)
        self.assertTrue(out.endswith("…"))
        # Verify "好" was dropped but "你" survived
        self.assertIn("你", out)
        self.assertNotIn("好", out)

    def test_cjk_with_ansi(self):
        # CJK + ANSI: color codes are zero-width, CJK chars are 2 cols.
        s = "\033[0;31m你好\033[0m世界"
        out = truncate_to_width(s, 3)
        # "你好" = 4 cols, budget = 3 - 1(ellipsis) = 2.
        # "你" = 2 cols fits, "好" would exceed, so stop at "你".
        self.assertIn("\033[0;31m", out)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(_visible_len(out), 3)

class TestGetStatuslineWidth(unittest.TestCase):
    def test_returns_positive_int_or_zero(self):
        w = get_statusline_width()
        self.assertIsInstance(w, int)
        self.assertGreaterEqual(w, 0)

    def test_falls_back_when_columns_unset(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ('COLUMNS', 'LINES')}
        w = None
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            w = get_statusline_width()
        self.assertIsInstance(w, int)
        self.assertGreaterEqual(w, 0)

class TestGetStatuslineWidthFromInput(unittest.TestCase):
    """Width resolution from the host's stdin JSON.

    The statusline runs through a pipe. CodeBuddy reports the live width
    in the `terminal_width` field of the input JSON. This is the primary
    source; /dev/tty (Unix) or shutil (Windows) is the fallback.
    """

    def test_prefers_terminal_width_from_input(self):
        self.assertEqual(get_statusline_width_from_input({"terminal_width": 200}), 200)
        self.assertEqual(get_statusline_width_from_input({"terminal_width": 80}), 80)

    def test_passes_through_extreme_terminal_width(self):
        # No clamping — caller decides how to use the raw value
        self.assertEqual(get_statusline_width_from_input({"terminal_width": 4000}), 4000)
        self.assertEqual(get_statusline_width_from_input({"terminal_width": 5}), 5)

    def test_falls_back_when_field_missing(self):
        # Older CodeBuddy builds may not send the field — must not crash.
        w = get_statusline_width_from_input({"model": {}})
        self.assertIsInstance(w, int)
        self.assertGreaterEqual(w, 0)

    def test_falls_back_when_field_invalid(self):
        for bad in (None, "200", -1, 0, [], {}):
            w = get_statusline_width_from_input({"terminal_width": bad})
            self.assertIsInstance(w, int, msg=f"bad value: {bad!r}")
            self.assertGreaterEqual(w, 0, msg=f"bad value: {bad!r}")

    def test_falls_back_when_input_not_dict(self):
        self.assertIsInstance(get_statusline_width_from_input(None), int)
        self.assertIsInstance(get_statusline_width_from_input("garbage"), int)

class TestTtyColumns(unittest.TestCase):
    """/dev/tty TIOCGWINSZ is the only path that sees the real TTY when
    the statusline is invoked through a pipe. shutil cannot help here."""

    def test_returns_non_negative_int(self):
        # _tty_columns() returns 0 when no TTY is available (pipe/CI),
        # which is valid.  Positive values are returned when a real TTY
        # is attached (e.g. interactive terminal).
        w = _tty_columns()
        self.assertIsInstance(w, int)
        self.assertGreaterEqual(w, 0)

    def test_caches_within_one_second(self):
        # First call populates cache, second call within 1s must hit it
        # (we verify by checking the module-level cache tuple directly).
        import statusline
        _tty_columns()  # warm
        cached_before = formatting._TTY_COLUMNS_CACHE
        again = _tty_columns()
        cached_after = formatting._TTY_COLUMNS_CACHE
        self.assertEqual(cached_before, cached_after)  # unchanged
        self.assertEqual(again, cached_after[0])

    def test_uses_zero_when_no_tty(self):
        # Simulate a no-tty environment (e.g. CI sandbox) — must return
        # 0 (meaning "unknown width") rather than raising.
        import statusline
        # Force cache miss so _tty_columns re-reads /dev/tty
        formatting._TTY_COLUMNS_CACHE = (0, 0.0)
        with unittest.mock.patch('builtins.open', side_effect=OSError("no tty")):
            w = _tty_columns()
            self.assertEqual(w, 0)

class TestWindowsColumns(unittest.TestCase):
    """_windows_columns() tries /dev/tty then ctypes, returns 0 on failure."""

    def test_returns_non_negative_int(self):
        w = _windows_columns()
        self.assertIsInstance(w, int)
        self.assertGreaterEqual(w, 0)

    def test_returns_zero_when_no_tty_and_no_console(self):
        # Mock /dev/tty to fail, mock GetConsoleScreenBufferInfo to fail
        import statusline
        with unittest.mock.patch('builtins.open', side_effect=OSError("no tty")):
            # Also patch the kernel32 call to return failure
            mock_kernel32 = unittest.mock.MagicMock()
            mock_kernel32.GetConsoleScreenBufferInfo.return_value = 0
            mock_kernel32.GetStdHandle.return_value = 0
            with unittest.mock.patch.dict('sys.modules', {'ctypes.windll': unittest.mock.MagicMock(kernel32=mock_kernel32)}):
                w = _windows_columns()
                self.assertEqual(w, 0)

    def test_dev_tty_tried_first(self):
        # Verify /dev/tty is attempted by checking that open is called with it
        calls = []
        orig_open = open

        def tracking_open(path, *args, **kwargs):
            calls.append(str(path))
            raise OSError("mock: no tty")

        with unittest.mock.patch('builtins.open', side_effect=tracking_open):
            _windows_columns()
        self.assertTrue(any('/dev/tty' in c for c in calls),
                        f"Expected /dev/tty in open calls, got: {calls}")
