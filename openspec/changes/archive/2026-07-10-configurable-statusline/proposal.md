# Proposal: Configurable statusline layout

## Why

Today `build_statusline` (`render.py`) hardcodes both *which* display items
appear and *in what order* they are joined into the three-line bar. Every user
who wants a different layout must edit Python. We want the layout to be
**data-driven**: a config file decides visibility and order, and an agent-facing
slash command can edit that config on the user's behalf.

Scope already agreed with the user (explore session):

- **Visibility**: per-block show/hide, at *block* granularity (current natural
  groupings — not atomic token splitting).
- **Position**: reorder *within line 1 only*. Lines 2 (`Tools:`) and 3
  (`Recent:`) keep their semantic prefixes and fixed vertical position; they are
  toggled as whole lines.
- **Config source**: a plugin-owned JSON file, not host `settings.json`.

## What changes

1. **Config file** `~/.codebuddy/plugins/data/statusline/config.json` (reuse
   `PLUGIN_DATA` from `stats.py`):

   ```jsonc
   {
     "layout": {
       "line1_order": ["cwd_git", "model", "context_bar", "compact_periodic",
                       "tokens", "requests", "cost", "credits", "time", "lines"],
       "line1_hidden": [],
       "tools": true,
       "recent": true
     }
   }
   ```

   Resolution algorithm:
   - `line1_order` → shown, in that order.
   - `line1_hidden` → explicitly hidden (takes precedence even if also listed).
   - Any known block *not* in either list (e.g. added in a future release) →
     **auto-appended to the end and shown**. This keeps new blocks from
     silently disappearing for users with a custom config.
   - Unknown ids in `line1_order` → ignored silently.
   - Missing/garbled config → fall back to the built-in default order (all shown).

2. **Render refactor** (`render.py`): extract a `renderers` registry mapping
   block id → `fn(input_data, stats) -> str|None`. `build_statusline` walks the
   resolved order, collects non-empty parts, joins line 1 with `" | "`, and
   emits lines 2/3 only when their toggle is on. With no config file present the
   output is identical to the current rendering **except for the intended
   `compact_periodic` decoupling** (now its own `" | "`-separated slot, per
   design.md): `▕██▏12% Compact×1` becomes `▕██▏12% | Compact×1`.

3. **`compact_periodic` decoupled**: `Compact×N Periodic×N` currently gets
   *appended to the tail of the previous part* (`render.py:188-189`). It becomes
   its own `|`-separated block so it can be ordered/hidden independently. Visual
   change: `▕██▏12% Compact×1` → `▕██▏12% | Compact×1`.

4. **Agent command**: a single `/statusline` slash command (`commands/statusline-config.md`)
   plus a `config.py` helper that performs atomic edits of `config.json`.
   Subcommands: `hide`, `show`, `move`, `enable`, `disable`, `reset`, `list`.
   Changes take effect on the next `StatusLineManager` event — no restart needed.

## Non-goals

- **No cross-line free layout** (move a block from line 1 to line 2/3). Kept out
  deliberately: it requires rethinking the `Tools:`/`Recent:` prefixes and the
  join logic — a real layout engine, not a sort.
- **No atomic token splitting** (In / Out / Cache / Think as independent toggles).
  Block-level granularity only.
- **No host `settings.json` integration**; config stays plugin-local.
- **No change to `stats` structure** → `CACHE_VERSION` is NOT bumped.

## Impact

- New files: `config.py`, `commands/statusline-config.md`, `config.json` (created
  on first edit).
- Modified: `render.py` (registry + ordering), `statusline.py` (load config),
  `test_render.py` (new cases).
- Performance: one `json.load` of a tiny file per invocation (~<1ms), well within
  the cold-start budget. Each process is one-shot so no in-process caching needed.
