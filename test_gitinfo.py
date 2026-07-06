#!/usr/bin/env python3
"""Unit tests for gitinfo.py module"""

import os
import sys
import unittest

import gitinfo
from gitinfo import get_git_info, format_git_info, GIT_BRANCH_ICON

class TestGitInfo(unittest.TestCase):
    """Tests for get_git_info / format_git_info."""

    def _make_run(self, stdout, returncode=0):
        """Build a fake subprocess.run that returns the given stdout/returncode."""
        from unittest.mock import MagicMock
        def fake_run(*args, **kwargs):
            m = MagicMock()
            m.stdout = stdout
            m.returncode = returncode
            return m
        return fake_run

    def setUp(self):
        # get_git_info checks os.path.isdir(cwd); use the repo dir to pass it.
        self.cwd = os.path.dirname(os.path.abspath(__file__))

    def test_clean_branch_no_upstream(self):
        from unittest.mock import patch
        with patch('gitinfo.subprocess.run', self._make_run("## master\n")):
            info = get_git_info(self.cwd)
        self.assertEqual(info, {"branch": "master", "dirty": False, "ahead": 0, "behind": 0})

    def test_clean_branch_with_upstream(self):
        from unittest.mock import patch
        with patch('gitinfo.subprocess.run', self._make_run("## master...origin/master\n")):
            info = get_git_info(self.cwd)
        self.assertEqual(info, {"branch": "master", "dirty": False, "ahead": 0, "behind": 0})

    def test_dirty_branch(self):
        from unittest.mock import patch
        out = "## master...origin/master\n M file1.py\n?? new.py\n"
        with patch('gitinfo.subprocess.run', self._make_run(out)):
            info = get_git_info(self.cwd)
        self.assertTrue(info["dirty"])
        self.assertEqual(info["branch"], "master")

    def test_ahead_only(self):
        from unittest.mock import patch
        out = "## master...origin/master [ahead 2]\n"
        with patch('gitinfo.subprocess.run', self._make_run(out)):
            info = get_git_info(self.cwd)
        self.assertEqual(info["ahead"], 2)
        self.assertEqual(info["behind"], 0)

    def test_behind_only(self):
        from unittest.mock import patch
        out = "## master...origin/master [behind 3]\n"
        with patch('gitinfo.subprocess.run', self._make_run(out)):
            info = get_git_info(self.cwd)
        self.assertEqual(info["ahead"], 0)
        self.assertEqual(info["behind"], 3)

    def test_ahead_and_behind(self):
        from unittest.mock import patch
        out = "## master...origin/master [ahead 2, behind 1]\n"
        with patch('gitinfo.subprocess.run', self._make_run(out)):
            info = get_git_info(self.cwd)
        self.assertEqual(info["ahead"], 2)
        self.assertEqual(info["behind"], 1)

    def test_dirty_with_ahead_behind(self):
        from unittest.mock import patch
        out = "## main...origin/main [ahead 1, behind 2]\n M a.py\n"
        with patch('gitinfo.subprocess.run', self._make_run(out)):
            info = get_git_info(self.cwd)
        self.assertEqual(info, {"branch": "main", "dirty": True, "ahead": 1, "behind": 2})

    def test_detached_head(self):
        from unittest.mock import patch
        with patch('gitinfo.subprocess.run', self._make_run("## HEAD (no branch)\n")):
            info = get_git_info(self.cwd)
        self.assertEqual(info["branch"], "(detached)")
        self.assertFalse(info["dirty"])

    def test_not_a_git_repo(self):
        from unittest.mock import patch
        with patch('gitinfo.subprocess.run', self._make_run("", returncode=128)):
            info = get_git_info(self.cwd)
        self.assertIsNone(info)

    def test_git_not_installed(self):
        from unittest.mock import patch
        def boom(*a, **kw):
            raise FileNotFoundError("git not found")
        with patch('gitinfo.subprocess.run', side_effect=boom):
            info = get_git_info(self.cwd)
        self.assertIsNone(info)

    def test_timeout(self):
        from unittest.mock import patch
        import subprocess as _sub
        def boom(*a, **kw):
            raise _sub.TimeoutExpired(cmd="git", timeout=0.5)
        with patch('gitinfo.subprocess.run', side_effect=boom):
            info = get_git_info(self.cwd)
        self.assertIsNone(info)

    def test_invalid_cwd(self):
        info = get_git_info("/this/does/not/exist/at/all")
        self.assertIsNone(info)

    def test_empty_cwd(self):
        self.assertIsNone(get_git_info(""))
        self.assertIsNone(get_git_info(None))

    def test_unparseable_first_line(self):
        from unittest.mock import patch
        with patch('gitinfo.subprocess.run', self._make_run("garbage line\n")):
            info = get_git_info(self.cwd)
        self.assertIsNone(info)

class TestFormatGitInfo(unittest.TestCase):
    """Pure formatting tests — strip ANSI to check the textual content."""

    @staticmethod
    def _plain(s):
        import re as _re
        return _re.sub(r'\x1b\[[0-9;]*m', '', s)

    def test_none_returns_empty(self):
        self.assertEqual(format_git_info(None), "")

    def test_clean_branch(self):
        s = format_git_info({"branch": "master", "dirty": False, "ahead": 0, "behind": 0})
        self.assertEqual(self._plain(s), f"on {GIT_BRANCH_ICON} master")

    def test_dirty(self):
        s = format_git_info({"branch": "master", "dirty": True, "ahead": 0, "behind": 0})
        self.assertEqual(self._plain(s), f"on {GIT_BRANCH_ICON} master*")

    def test_ahead(self):
        s = format_git_info({"branch": "master", "dirty": False, "ahead": 2, "behind": 0})
        self.assertEqual(self._plain(s), f"on {GIT_BRANCH_ICON} master ↑2")

    def test_behind(self):
        s = format_git_info({"branch": "master", "dirty": False, "ahead": 0, "behind": 1})
        self.assertEqual(self._plain(s), f"on {GIT_BRANCH_ICON} master ↓1")

    def test_ahead_and_behind(self):
        s = format_git_info({"branch": "master", "dirty": False, "ahead": 2, "behind": 1})
        self.assertEqual(self._plain(s), f"on {GIT_BRANCH_ICON} master ↑2 ↓1")

    def test_dirty_with_ahead_behind(self):
        s = format_git_info({"branch": "main", "dirty": True, "ahead": 1, "behind": 1})
        self.assertEqual(self._plain(s), f"on {GIT_BRANCH_ICON} main* ↑1 ↓1")

    def test_empty_branch(self):
        s = format_git_info({"branch": "", "dirty": False, "ahead": 0, "behind": 0})
        self.assertEqual(s, "")
