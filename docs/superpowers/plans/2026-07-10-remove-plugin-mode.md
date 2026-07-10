# Remove Plugin Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all plugin-mode code from the statusline plugin and collapse it to a single git-clone mode (no env-var branching for `CODEBUDDY_PLUGIN_ROOT` / `CODEBUDDY_PLUGIN_DATA` / `IS_PLUGIN_MODE`).

**Architecture:** `stats.py` resolves directories purely from `CODEBUDDY_CONFIG_DIR` (fallback `~/.codebuddy`); `render._config_path()` reads the data dir from `stats._PLUGIN_DATA` at call time (single source of truth, still monkeypatchable by tests). `maybe_auto_update()` always runs its daily git-pull (no-op when not a git repo).

**Tech Stack:** Python 3.6+ (stdlib only), `unittest`, `unittest.mock`.

## Global Constraints

- Python 3.6+ compatibility required (`statusline.py` and modules must run on 3.6).
- Do NOT remove `maybe_auto_update` — in the single remaining mode it always runs the daily git-pull.
- Do NOT remove `install.sh`/`install.ps1`/`uninstall.sh`/`uninstall.ps1` or `/statusline:setup`.
- Do NOT rename symbols `PLUGIN_DIR` / `_PLUGIN_DATA` / `CACHE_DIR` (they now mean "install dir" / "data dir").
- Paths must still resolve from `CODEBUDDY_CONFIG_DIR` (this env var IS set by the host) with fallback `~/.codebuddy`.
- Tests redirect dirs by monkeypatching `stats._PLUGIN_DATA` / `stats.PLUGIN_DIR` (NOT via env vars).
- No env-var branching anywhere after this change.

---

### Task 1: Remove plugin-mode symbols from `stats.py`

**Files:**
- Modify: `stats.py:2` (docstring), `stats.py:19` (config dir), `stats.py:24-27` (plugin symbols), `stats.py:99-111` (`maybe_auto_update` docstring + early return)
- Test: `test_stats.py:14-17` (imports), `test_stats.py:104-133` (`TestAutoUpdate` setup + plugin-mode test)

**Interfaces:**
- Consumes: nothing new.
- Produces: `stats.PLUGIN_DIR` (still exists, now always `dirname(__file__)`), `stats._PLUGIN_DATA` (now always `_CONFIG_DIR/plugins/data/statusline`), `stats.maybe_auto_update` (no `IS_PLUGIN_MODE` early return). `IS_PLUGIN_MODE` no longer exists.

- [ ] **Step 1: Edit the module docstring (line 2)**

Replace:
```python
"""Stats structure, cache persistence, and plugin auto-update.
```
with:
```python
"""Stats structure, cache persistence, and git-clone auto-update.
```

- [ ] **Step 2: Replace the config/data dir + plugin symbols (lines 19, 24-27)**

Replace:
```python
_PLUGIN_DATA = os.environ.get('CODEBUDDY_PLUGIN_DATA', '') or os.path.join(_CONFIG_DIR, "plugins/data/statusline")
CACHE_DIR = os.path.join(_PLUGIN_DATA, "cache")
CACHE_MAX_AGE_DAYS = 7
CACHE_VERSION = 8

# Plugin mode: CODEBUDDY_PLUGIN_ROOT is set when installed via marketplace
# Git-clone mode: fallback to script's own directory
PLUGIN_DIR = os.environ.get('CODEBUDDY_PLUGIN_ROOT', '') or os.path.dirname(os.path.abspath(__file__))
IS_PLUGIN_MODE = bool(os.environ.get('CODEBUDDY_PLUGIN_ROOT', ''))
```
with:
```python
_PLUGIN_DATA = os.path.join(_CONFIG_DIR, "plugins/data/statusline")
CACHE_DIR = os.path.join(_PLUGIN_DATA, "cache")
CACHE_MAX_AGE_DAYS = 7
CACHE_VERSION = 8

# PLUGIN_DIR is the directory this script lives in (the git-clone install dir).
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
```

- [ ] **Step 3: Remove the `IS_PLUGIN_MODE` early return in `maybe_auto_update` (lines 99-111)**

Replace:
```python
def maybe_auto_update():
    """Try to git-pull the plugin repo at most once per day (git-clone mode only).

    Skipped entirely when installed via plugin marketplace (IS_PLUGIN_MODE),
    since updates are managed by `codebuddy plugin update`.

    Throttles via a marker file (mtime). The git pull runs in a fully detached
    background process so it never blocks the statusline.
    """
    if IS_PLUGIN_MODE:
        return

    git_dir = os.path.join(PLUGIN_DIR, ".git")
```
with:
```python
def maybe_auto_update():
    """Try to git-pull the install repo at most once per day.

    Throttles via a marker file (mtime). The git pull runs in a fully detached
    background process so it never blocks the statusline. No-op when the
    install dir is not a git repo.
    """
    git_dir = os.path.join(PLUGIN_DIR, ".git")
```

- [ ] **Step 4: Update `test_stats.py` imports and `TestAutoUpdate`**

In `test_stats.py`, remove `IS_PLUGIN_MODE` from the import block (line 16):
```python
from stats import (
    new_stats, load_cache, save_cache, cleanup_old_caches, maybe_auto_update,
    CACHE_DIR, CACHE_VERSION, IS_PLUGIN_MODE,
)
```
becomes:
```python
from stats import (
    new_stats, load_cache, save_cache, cleanup_old_caches, maybe_auto_update,
    CACHE_DIR, CACHE_VERSION,
)
```

In `TestAutoUpdate.setUp` (lines 107-116), remove the `IS_PLUGIN_MODE` patch line and keep `PLUGIN_DIR` save/restore:
```python
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import statusline
        self._orig_cache_dir = stats.CACHE_DIR
        self._orig_plugin_dir = stats.PLUGIN_DIR
        self._orig_marker = stats.UPDATE_MARKER
        stats.CACHE_DIR = self.tmpdir
        stats.UPDATE_MARKER = os.path.join(self.tmpdir, ".last-update-check")
```

In `TestAutoUpdate.tearDown` (lines 118-124), remove the `IS_PLUGIN_MODE` restore:
```python
    def tearDown(self):
        import statusline
        stats.CACHE_DIR = self._orig_cache_dir
        stats.PLUGIN_DIR = self._orig_plugin_dir
        stats.UPDATE_MARKER = self._orig_marker
        shutil.rmtree(self.tmpdir, ignore_errors=True)
```

Replace `test_skipped_in_plugin_mode` (lines 126-133) with a test asserting the
pull is attempted in the single mode (git repo + stale marker → `subprocess.Popen`
called with the expected args):
```python
    def test_attempts_update_in_single_mode(self):
        """In the single (git-clone) mode, maybe_auto_update runs git pull."""
        import statusline
        os.makedirs(os.path.join(self.tmpdir, ".git"), exist_ok=True)
        stats.PLUGIN_DIR = self.tmpdir
        with open(stats.UPDATE_MARKER, 'w') as f:
            f.write(str(int(time.time()) - 2 * 86400))
        old_mtime = time.time() - 2 * 86400
        os.utime(stats.UPDATE_MARKER, (old_mtime, old_mtime))
        with unittest.mock.patch("subprocess.Popen") as mock_popen:
            maybe_auto_update()
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            self.assertEqual(args, ["git", "-C", self.tmpdir, "pull", "--ff-only", "--quiet"])
```

- [ ] **Step 5: Run the stats tests**

Run:
```bash
cd /Users/runzhi/.codebuddy/statusline && python3 -m unittest test_stats -v
```
Expected: PASS (no `IS_PLUGIN_MODE`, auto-update attempts pull in single mode).

- [ ] **Step 6: Commit**
```bash
cd /Users/runzhi/.codebuddy/statusline && git add stats.py test_stats.py && git commit -m "refactor(stats): drop plugin mode; single git-clone mode"
```

---

### Task 2: Make `render._config_path` read from `stats._PLUGIN_DATA`

**Files:**
- Modify: `render.py:9-28` (add `import stats`), `render.py:41-58` (config comment + `_config_path`), `render.py:375` (stale comment if any)
- Test: `test_config.py:18-25` (setUp/tearDown), `test_render.py:158-165` (setUp/tearDown)

**Interfaces:**
- Consumes: `stats._PLUGIN_DATA` (string path, set in Task 1).
- Produces: `render._config_path()` returns `os.path.join(stats._PLUGIN_DATA, "config.json")`; `render.load_layout_config()` now resolves via that path. Tests redirect by setting `stats._PLUGIN_DATA`.

- [ ] **Step 1: Add `import stats` to render.py**

After `from gitinfo import format_git_info, get_git_info` (line 28), add:
```python
import stats
```
(Use `import stats` — not `from stats import ...` — so `_config_path` reads
`stats._PLUGIN_DATA` at call time and tests can monkeypatch it.)

- [ ] **Step 2: Update the configurable-layout comment block (lines 41-50)**

Replace the "plugin-owned config file" wording:
```python
# The three-line statusline is assembled from discrete "blocks". A plugin-owned
# config file (<config-dir>/plugins/data/statusline/config.json, where
# config-dir = CODEBUDDY_CONFIG_DIR or ~/.codebuddy) decides which blocks are
```
with:
```python
# The three-line statusline is assembled from discrete "blocks". A statusline-owned
# config file (<config-dir>/plugins/data/statusline/config.json, where
# config-dir = CODEBUDDY_CONFIG_DIR or ~/.codebuddy) decides which blocks are
```

- [ ] **Step 3: Replace `_config_path` (lines 52-58)**

Replace:
```python
def _config_path():
    """Location of the layout config, reusing the plugin data dir."""
    base = os.environ.get('CODEBUDDY_PLUGIN_DATA', '') or os.path.join(
        os.environ.get('CODEBUDDY_CONFIG_DIR', '') or os.path.expanduser("~/.codebuddy"),
        "plugins/data/statusline",
    )
    return os.path.join(base, "config.json")
```
with:
```python
def _config_path():
    """Location of the layout config, reusing the data dir (stats._PLUGIN_DATA)."""
    return os.path.join(stats._PLUGIN_DATA, "config.json")
```

- [ ] **Step 4: Redirect `test_config.py` via `stats._PLUGIN_DATA`**

Replace the `setUp`/`tearDown` (lines 18-25):
```python
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ["CODEBUDDY_PLUGIN_DATA"] = self._tmp
        self._path = os.path.join(self._tmp, "config.json")

    def tearDown(self):
        os.environ.pop("CODEBUDDY_PLUGIN_DATA", None)
```
with:
```python
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_plugin_data = stats._PLUGIN_DATA
        stats._PLUGIN_DATA = self._tmp
        self._path = os.path.join(self._tmp, "config.json")

    def tearDown(self):
        stats._PLUGIN_DATA = self._orig_plugin_data
```
And add `import stats` near the top of `test_config.py` (after `import config as config_mod` or with the other imports).

- [ ] **Step 5: Redirect `test_render.py::TestBuildStatuslineConfig` via `stats._PLUGIN_DATA`**

Replace the `setUp`/`tearDown` (lines 158-165):
```python
    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        os.environ["CODEBUDDY_PLUGIN_DATA"] = self._tmp

    def tearDown(self):
        os.environ.pop("CODEBUDDY_PLUGIN_DATA", None)
```
with:
```python
    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self._orig_plugin_data = stats._PLUGIN_DATA
        stats._PLUGIN_DATA = self._tmp

    def tearDown(self):
        stats._PLUGIN_DATA = self._orig_plugin_data
```
And add `import stats` near the top of `test_render.py`.

- [ ] **Step 6: Run the config + render tests**

Run:
```bash
cd /Users/runzhi/.codebuddy/statusline && python3 -m unittest test_config test_render -v
```
Expected: PASS (config written/read under redirected `stats._PLUGIN_DATA`).

- [ ] **Step 7: Commit**
```bash
cd /Users/runzhi/.codebuddy/statusline && git add render.py test_config.py test_render.py && git commit -m "refactor(render): resolve config path from stats._PLUGIN_DATA"
```

---

### Task 3: Clean misleading "plugin mode" prose in scripts and docs

**Files:**
- Modify: `install.sh:13`, `install.sh:175-176`, `install.ps1:8`, `install.ps1:150-151`, `commands/setup.md`, `README.md`, `CHANGELOG.md`
- (Uninstall scripts only mention "plugin" as a generic noun in comments — leave them.)

**Interfaces:** Documentation-only; no code/interface changes.

- [ ] **Step 1: install.sh comment fixes**

Line 13 comment:
```bash
# are derived from this so the plugin lands in the same dir CodeBuddy reads from.
```
→
```bash
# are derived from this so the statusline lands in the same dir CodeBuddy reads from.
```

Lines 175-176 (inside the step-5 comment block):
```bash
#    the commands available in any project under git-clone install (in plugin
#    mode they are auto-discovered from the plugin's commands/ dir).
```
→
```bash
#    the commands available in any project under git-clone install.
```

- [ ] **Step 2: install.ps1 comment fixes**

Line 8:
```powershell
# are derived from this so the plugin lands in the same dir CodeBuddy reads from.
```
→
```powershell
# are derived from this so the statusline lands in the same dir CodeBuddy reads from.
```

Lines 150-151:
```powershell
#    commands available in any project under git-clone install (in plugin mode
#    they are auto-discovered from the plugin's commands/ dir).
```
→
```powershell
#    commands available in any project under git-clone install.
```

- [ ] **Step 3: `commands/setup.md` wording**

Read `commands/setup.md`; reword any "plugin" framing so it reads as a git-clone
installer wrapper. (The command itself is kept — only prose changes.)

- [ ] **Step 4: `README.md`**

Read `README.md`; remove any sentence describing a plugin-marketplace mode / env-var
based config dir. The config path `~/.codebuddy/plugins/data/statusline/config.json`
stays unchanged.

- [ ] **Step 5: Add a `CHANGELOG.md` entry**

Append under the top (Unreleased / latest) section:
```markdown
- **Removed plugin mode**: `IS_PLUGIN_MODE`, `CODEBUDDY_PLUGIN_ROOT`, and
  `CODEBUDDY_PLUGIN_DATA` are no longer read. The statusline now runs in a single
  git-clone mode: the install dir is the script's own directory and all paths derive
  from `CODEBUDDY_CONFIG_DIR` (fallback `~/.codebuddy`). Auto-update (daily git pull)
  always runs when the install is a git repo.
```

- [ ] **Step 6: Commit**
```bash
cd /Users/runzhi/.codebuddy/statusline && git add install.sh install.ps1 commands/setup.md README.md CHANGELOG.md && git commit -m "docs: remove plugin-mode prose from scripts and docs"
```

---

### Task 4: Full test suite + smoke check

**Files:** none new; verification only.

**Interfaces:** n/a.

- [ ] **Step 1: Run the entire test suite**

Run:
```bash
cd /Users/runzhi/.codebuddy/statusline && python3 -m unittest discover -s . -p "test_*.py" -v
```
Expected: all tests PASS (170 cases).

- [ ] **Step 2: Smoke-check rendering resolves the real data dir**

Run a representative render with a minimal stdin payload and confirm no traceback
and that it reads config from `~/.codebuddy/plugins/data/statusline` (or
`$CODEBUDDY_CONFIG_DIR/plugins/data/statusline`):
```bash
cd /Users/runzhi/.codebuddy/statusline && echo '{"model":{"display_name":"x"},"cost":{},"context_window":{}}' | python3 statusline.py
```
Expected: prints the three-line statusline without error.

- [ ] **Step 3: Grep for leftover plugin-mode references**

Run:
```bash
cd /Users/runzhi/.codebuddy/statusline && grep -rn "IS_PLUGIN_MODE\|CODEBUDDY_PLUGIN_ROOT\|CODEBUDDY_PLUGIN_DATA" --include=*.py .
```
Expected: no matches in `.py` files. (Shell scripts/docs may keep the generic word
"plugin" only as a noun, not as a mode or env var.)
