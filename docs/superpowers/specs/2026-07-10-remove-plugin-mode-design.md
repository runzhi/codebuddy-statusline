# Remove Plugin Mode — Design

Date: 2026-07-10

## Background

A recent change added "plugin mode" detection to the statusline plugin. The
intent was: when CodeBuddy installs the statusline via the plugin marketplace,
it would set `CODEBUDDY_PLUGIN_ROOT` and `CODEBUDDY_PLUGIN_DATA`, and the plugin
would (a) skip its own daily git-pull auto-update and (b) resolve its config/cache
dir from those env vars.

In actual runtime, **no such environment variables are ever set**. So the
plugin-mode branch never triggers, `IS_PLUGIN_MODE` is always `False`, and the
`CODEBUDDY_PLUGIN_DATA` lookup always falls through to its default. The plugin
approach is therefore infeasible. This change removes all plugin-mode code and
collapses the plugin to a single mode (git-clone mode), where the script's own
directory is the install directory and all paths derive from
`CODEBUDDY_CONFIG_DIR` (which *is* set by the running process).

## Goal

Remove every trace of plugin-mode distinction. After this change there is exactly
one mode of operation with no env-var branching.

## Non-goals

- Do **not** remove the auto-update (`maybe_auto_update`). In the single remaining
  mode it always runs the daily git-pull (existing git-clone behavior).
- Do **not** remove `install.sh` / `install.ps1` / `uninstall.sh` / `uninstall.ps1`
  or the `/statusline:setup` command — these are the git-clone installer, not
  plugin-specific.
- Do **not** rename the symbols `PLUGIN_DIR` / `_PLUGIN_DATA` / `CACHE_DIR` (they
  now simply mean "install dir" / "data dir"; keeping names minimizes churn).

## Changes

### 1. `stats.py`

- Delete the `IS_PLUGIN_MODE` flag and all references to it (including its use in
  `maybe_auto_update`).
- `PLUGIN_DIR`: drop the `CODEBUDDY_PLUGIN_ROOT` env lookup; it is always
  `os.path.dirname(os.path.abspath(__file__))` (this was already the fallback).
- `_PLUGIN_DATA`: drop the `CODEBUDDY_PLUGIN_DATA` env lookup; it is always
  `os.path.join(_CONFIG_DIR, "plugins/data/statusline")`, where `_CONFIG_DIR`
  resolves from `CODEBUDDY_CONFIG_DIR` (fallback `~/.codebuddy`).
- `maybe_auto_update()`: remove the early `if IS_PLUGIN_MODE: return`. Keep the
  existing throttle + git-pull logic. The non-git-repo early return stays.
- Update the module docstring and inline comments: "plugin auto-update" →
  "git-clone auto-update"; delete plugin-mode commentary.

### 2. `render.py`

- `_config_path()`: no longer reads `CODEBUDDY_PLUGIN_DATA` itself. Instead read
  the data dir at call time from `stats` so it stays a single source of truth and
  remains patchable by tests. Concretely: `import stats` (module-level) and in
  `_config_path()` return `os.path.join(stats._PLUGIN_DATA, "config.json")`.
  Use runtime `stats._PLUGIN_DATA` access (not a `from ... import` binding) so
  tests can monkeypatch `stats._PLUGIN_DATA`.
- Update the "plugin-owned config file" comment to "statusline-owned config file".

### 3. Tests

- `test_stats.py`:
  - Remove `IS_PLUGIN_MODE` and `PLUGIN_DIR` save/restore in setUp/tearDown.
  - Remove `test_skipped_in_plugin_mode`. Replace with an assertion that
    `maybe_auto_update` attempts the git pull in the single mode (e.g. patch
    `subprocess.Popen` and assert it is called when the dir is a git repo and the
    throttle allows it; assert no-op when not a git repo).
  - Redirect the cache dir for tests via `stats._PLUGIN_DATA = tmp` (already the
    pattern used for `PLUGIN_DIR`).
- `test_config.py` / `test_render.py`: replace
  `os.environ["CODEBUDDY_PLUGIN_DATA"] = tmp` / `os.environ.pop(...)` with
  `stats._PLUGIN_DATA = self._tmp` (and restore). `render._config_path` reads
  `stats._PLUGIN_DATA` at call time, so this redirects correctly.

### 4. Scripts & docs (prose only)

- `install.sh` / `install.ps1` / `uninstall.sh` / `uninstall.ps1`: remove
  misleading comments about "plugin mode auto-discovery". The actual logic is
  unchanged (git-clone installer).
- `commands/setup.md`: keep; adjust wording so it reads as a git-clone installer
  wrapper rather than plugin-specific.
- `README.md` / `AGENTS.md`: config/cache paths are unchanged
  (`~/.codebuddy/plugins/data/statusline`); remove any description of plugin mode.
- `CHANGELOG.md`: add an entry noting plugin mode was removed and the plugin now
  runs in a single git-clone mode.

## Data flow (after change)

```
CODEBUDDY_CONFIG_DIR (set by host)  ─┐
                                     ├─> _CONFIG_DIR
~/.codebuddy (fallback)             ─┘
        |
        v
_PLUGIN_DATA = _CONFIG_DIR/plugins/data/statusline
        |                       |
        v                       v
CACHE_DIR = _PLUGIN_DATA/cache   _config_path() = _PLUGIN_DATA/config.json
        |                                   |
        v                                   v
save/load_cache                    load_layout_config (render)
```

`PLUGIN_DIR` = script's own directory → used by `maybe_auto_update` git pull.
No env-var branching anywhere.

## Testing

- All existing unit tests must pass after redirecting dirs via `stats._PLUGIN_DATA`.
- `test_stats.py` gains coverage that auto-update is attempted in the single mode
  (and still no-ops for non-git installs).
- Run: `python3 -m unittest discover -s ~/.codebuddy/statusline -p "test_*.py" -v`
- Verify cold/warm render still works and config.json is read from the resolved
  data dir.
