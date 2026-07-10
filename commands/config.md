---
description: "Adjust statusline display: show/hide blocks, reorder, toggle lines"
argument-hint: "<hide|show|move|enable|disable|reset|list> [args]"
---

Invoke as `/statusline:config`. Adjust the statusline layout by running the
`config.py` helper. The helper reads
and writes `~/.codebuddy/plugins/data/statusline/config.json` atomically; changes
take effect on the next statusline render (no restart needed).

Translate the user's request into one of these commands and run it with Bash:

```bash
# Hide / show blocks (block-level)
python3 ~/.codebuddy/statusline/config.py hide credits time
python3 ~/.codebuddy/statusline/config.py show credits

# Reorder blocks on line 1
python3 ~/.codebuddy/statusline/config.py move cost to front
python3 ~/.codebuddy/statusline/config.py move tokens after model
python3 ~/.codebuddy/statusline/config.py move requests to end

# Toggle whole lines (Tools / Recent)
python3 ~/.codebuddy/statusline/config.py disable tools
python3 ~/.codebuddy/statusline/config.py enable recent

# Reset to defaults (deletes the config file)
python3 ~/.codebuddy/statusline/config.py reset

# Show the current effective layout
python3 ~/.codebuddy/statusline/config.py list
```

Available blocks: `cwd_git`, `model`, `context_bar`, `compact_periodic`,
`tokens`, `requests`, `cost`, `credits`, `time`, `lines`.

After running the command, read its printed "Layout (effective)" output and
confirm the change to the user in one short line. If the helper prints "Unknown
block(s)", correct the block name from the "Valid blocks" list and retry.
