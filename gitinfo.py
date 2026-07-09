#!/usr/bin/env python3
"""Git branch / status detection for the statusline."""

import os
import re
import subprocess
import sys

from formatting import CYAN, DIM, NC, PURPLE, RED

# Parses the first line of `git status --porcelain=v1 --branch` output.
# Examples:
#   ## master
#   ## master...origin/master
#   ## master...origin/master [ahead 2]
#   ## master...origin/master [ahead 2, behind 1]
#   ## HEAD (no branch)
_GIT_BRANCH_LINE_RE = re.compile(
    r'^## (?:'
    r'(?P<detached>HEAD \(no branch\))'
    r'|'
    r'(?P<branch>[^.\s]+)(?:\.\.\.[^\s]+)?'
    r'(?: \[(?:ahead (?P<ahead>\d+))?(?:, )?(?:behind (?P<behind>\d+))?\])?'
    r')$'
)

GIT_BRANCH_ICON = '\ue0a0'  # Powerline branch icon (U+E0A0)


def get_git_info(cwd):
    """Return git info for *cwd* or None if unavailable.

    Returns: {"branch": str, "dirty": bool, "ahead": int, "behind": int}
    Branch is "(detached)" for detached HEAD.
    """
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v1", "--branch"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=0.5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    lines = result.stdout.splitlines()
    if not lines:
        return None

    first = lines[0]
    m = _GIT_BRANCH_LINE_RE.match(first)
    if not m:
        return None

    if m.group('detached'):
        branch = "(detached)"
    else:
        branch = m.group('branch') or ""

    ahead = int(m.group('ahead') or 0)
    behind = int(m.group('behind') or 0)

    # Any line after the first (which is the branch line) means the tree is dirty.
    dirty = len(lines) > 1

    return {
        "branch": branch,
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
    }


def format_git_info(info):
    """Format git info dict into a colored string for the statusline."""
    if not info:
        return ""
    suffix = ""
    if info.get("dirty"):
        suffix += "*"
    ahead = info.get("ahead", 0)
    behind = info.get("behind", 0)
    if ahead:
        suffix += f" ↑{ahead}"
    if behind:
        suffix += f" ↓{behind}"
    branch = info.get("branch", "")
    if not branch:
        return ""
    suffix_part = f"{RED}{suffix}{NC}" if suffix else NC
    return f"{DIM}on{NC} {PURPLE}{GIT_BRANCH_ICON} {branch}{suffix_part}"
