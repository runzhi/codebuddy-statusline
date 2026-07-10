# Design: Configurable statusline layout

## Block registry (canonical order = default layout)

```python
# render.py
BLOCKS_LINE1 = [  # canonical order, also the "auto-append" order for new blocks
    "cwd_git", "model", "context_bar", "compact_periodic",
    "tokens", "requests", "cost", "credits", "time", "lines",
]
```

Each block renders via a `renderers[id](input_data, stats)` function returning a
finished, colored string or `""`/`None` when not applicable (same empty-skip
semantics as today). Blocks and their sources:

| id              | content                                            | source |
|-----------------|----------------------------------------------------|--------|
| `cwd_git`       | `cwd` + git branch/status (joined by space)        | `os.getcwd()` + `get_git_info` |
| `model`         | model display name                                 | `input_data.model.display_name` |
| `context_bar`   | progress bar + pct + `used/total`, or `Max:` fallback | `input_data.context_window` |
| `compact_periodic` | `Compact×N Periodic×N` (own slot)               | `stats.compact_count/periodic_count` |
| `tokens`        | `In/Out[/Cache][/Think]`                           | `stats` + `context_window` fallback |
| `requests`      | `Req:N`                                            | `stats.request_count` |
| `credits`       | `Credits:N.NN`                                     | `stats.total_credits` |
| `cost`          | `Cost:$x`                                          | `cost.total_cost_usd` + credits→usd |
| `time`          | `Time:h:mm`                                        | `cost.total_duration_ms` |
| `lines`         | `+a/-b`                                            | `cost.total_lines_*` |

Lines 2/3 are whole-line toggles, not ordered:
- `tools`  → `Tools: <format_tools(...)>`
- `recent` → `Recent: <last-detail | recent_calls>`

## Config resolution (pseudo)

```
def resolve_layout(cfg):
    order  = list(cfg.get("layout", {}).get("line1_order", BLOCKS_LINE1))
    hidden = set(cfg.get("layout", {}).get("line1_hidden", []))
    # drop unknown ids from order (typos / removed blocks)
    order  = [b for b in order if b in BLOCKS_LINE1]
    # append known blocks neither ordered nor hidden (new-block safety)
    for b in BLOCKS_LINE1:
        if b not in order and b not in hidden:
            order.append(b)
    # hidden wins: never render a hidden block
    return [b for b in order if b not in hidden]
```

`tools`/`recent` default to `True`.

## Config loading (statusline.py / render.py)

- Helper `load_layout_config()` reads `PLUGIN_DATA/config.json` via `json.load`.
- Returns the raw dict; `resolve_layout` applies defaults + fallbacks.
- On any error (missing file, bad JSON, wrong shape) → return `None`, and the
  caller uses `BLOCKS_LINE1` + both lines on. **No exception may blank the
  statusline** (global safety net in `statusline.py:54` already covers crashes).

## `config.py` helper (atomic edits)

Mirrors the existing `install.sh`/`uninstall.sh` temp-file pattern:
1. Read `config.json` (or start from defaults).
2. Apply subcommand:
   - `hide <ids...>`   → add to `line1_hidden`
   - `show <ids...>`   → remove from `line1_hidden`
   - `move <id> to front|end|after <other>` → reorder `line1_order`
   - `enable|disable tools|recent` → set bool
   - `reset`           → delete the file (next render = defaults)
   - `list`            → print current resolved layout
3. Validate block names; on unknown id, print available blocks and exit non-zero
   (so the agent sees the mistake).
4. Write to a temp file, then atomic `os.replace`.
5. Print the resulting layout so the agent can confirm in one line.

No restart required: the host reads stdin + re-renders on its next event, and
`build_statusline` reloads config every call.

## `/statusline:config` command (`commands/config.md`)

Thin markdown (same shape as `cost-detail.md`): frontmatter `description` +
`argument-hint: "<hide|show|move|enable|disable|reset|list> [args]"`, body tells
the agent to run `python3 ~/.codebuddy/statusline/config.py <action> [args]`,
parse the printed layout, and confirm. Lists the valid block ids.

**Discovery / invocation.** CodeBuddy finds slash commands in
`~/.codebuddy/commands/<ns>/<name>.md` → `/<ns>:<name>`, and in an installed
plugin's `commands/` dir (auto-discovered, namespaced by plugin name). So the
file `commands/config.md` is invokable as `/statusline:config` in **both** git-clone
and plugin modes. `install.sh` / `install.ps1` link `commands/*.md` into
`~/.codebuddy/commands/statusline/` so it works immediately after a git-clone
install; the uninstall scripts remove that dir.

## Why these choices

- **List = order, hidden list = hide, neither = auto-show**: satisfies both
  "new blocks shouldn't vanish" and "I can hide any block". The one gotcha to
  document: *merely omitting* a block from `line1_order` does **not** hide it —
  you must put it in `line1_hidden`. (If a user just forgets `credits`, it
  reappears at the end via auto-append.)
- **`compact_periodic` as its own slot**: trades a slightly different look for
  consistency and independent control; the old tail-append hack is removed.
- **Reuse `PLUGIN_DATA`**: keeps all plugin state under one dir, consistent with
  the existing cache layout.
