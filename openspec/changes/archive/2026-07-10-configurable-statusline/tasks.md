# Tasks: Configurable statusline layout

## 1. Render registry + block functions
- [x] Add `BLOCKS_LINE1` canonical-order list to `render.py`.
- [x] Extract per-block render functions (`cwd_git`, `model`, `context_bar`,
      `compact_periodic`, `tokens`, `requests`, `credits`, `cost`, `time`,
      `lines`) returning a string or `""`/`None`.
- [x] Build `renderers` dict mapping id → function, signed `(input_data, stats)`.

## 2. Config loading + resolution
- [x] Add `load_layout_config()` reading `PLUGIN_DATA/config.json` (json.load,
      wrapped so any error → `None`).
- [x] Add `resolve_layout(cfg)` implementing the list/hidden/auto-append algorithm
      from `design.md`; defaults when `cfg is None`.
- [x] Wire `build_statusline` to use the resolved order for line 1, and the
      `tools`/`recent` bools for lines 2/3.

## 3. Decouple `compact_periodic`
- [x] Remove the tail-append hack at `render.py:188-189`; emit `compact_periodic`
      as its own `|`-separated block via the registry.

## 4. `config.py` helper
- [x] Create `config.py` with atomic temp-file write + `os.replace`.
- [x] Implement subcommands: `hide`, `show`, `move` (front/end/after),
      `enable`/`disable tools|recent`, `reset`, `list`.
- [x] Validate block ids; print available blocks + non-zero exit on unknown.

## 5. `/statusline:config` command
- [x] Add `commands/config.md` (frontmatter + body invoking `config.py`),
      matching `cost-detail.md` style. Invocation is `/statusline:config`
      (file lives under `commands/`, namespaced `statusline` by CodeBuddy).
- [x] Wire install scripts (`install.sh` / `install.ps1`) to link
      `commands/*.md` into `~/.codebuddy/commands/statusline/` so the command
      works in git-clone mode; uninstall scripts remove that dir. (In plugin
      mode the `commands/` dir is auto-discovered.)

## 6. Tests
- [x] `test_render.py`: no-config output matches the pre-config build (the one
      intentional difference is `compact_periodic` now rendering as its own
      `|`-separated slot, per design.md).
- [x] Hidden block omitted; reorder changes join order; bad config → default.
- [x] New (unknown) block auto-appended to end; `hidden` overrides `order`.
- [x] `config.py`: `hide`/`show`/`move`/`reset`/`list` round-trip; atomic write;
      unknown id rejected.

## 7. Docs
- [x] README: document `config.json` schema, the auto-append rule, and the
      "omit ≠ hide" gotcha; mention `/statusline`.

## Verification
- Run `python3 -m unittest discover -s . -p "test_*.py" -v`; confirm no
  regression and new cases pass.
- Manual: `python3 config.py hide credits time && python3 statusline.py < sample`
  shows credits/time gone; `python3 config.py reset` restores defaults.
