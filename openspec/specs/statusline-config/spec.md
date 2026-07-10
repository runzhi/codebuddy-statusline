# Spec: statusline-config

## Purpose

This capability governs how the CodeBuddy statusline's visible display blocks and
their ordering are configured. It lets users (or an agent on their behalf) toggle
which blocks appear, reorder them within line 1, and toggle the Tools/Recent
lines, via a plugin-owned JSON config file and a slash command that edits it.

## Requirements

### Requirement: Configurable layout via config file
The statusline MUST read its layout from `~/.codebuddy/plugins/data/statusline/config.json`
when present, controlling which display blocks are shown, their order on line 1,
and whether the Tools/Recent lines are enabled.

#### Scenario: No config file present
- **Given** no `config.json` exists
- **When** the statusline renders
- **Then** all blocks are shown in the built-in canonical order and both Tools
  and Recent lines are enabled.

#### Scenario: Reordered and hidden blocks
- **Given** `line1_order` lists `["model","cost","cwd_git"]` and `line1_hidden`
  contains `["credits","time"]`
- **When** the statusline renders
- **Then** line 1 shows `model | cost | cwd_git | <remaining auto-appended blocks>`
  in that order, with `credits` and `time` absent.

#### Scenario: New block added in a later release
- **Given** a block unknown to the user's `line1_order`/`line1_hidden` exists in code
- **When** the statusline renders
- **Then** that block is appended to the end of line 1 and shown, so new blocks
  never silently disappear for users with a custom config.

#### Scenario: Corrupt or malformed config
- **Given** `config.json` is missing, invalid JSON, or has an unexpected shape
- **When** the statusline renders
- **Then** it falls back to the default layout and never blanks the statusline.

### Requirement: Agent-editable layout via command
The plugin MUST provide a `/statusline:config` command backed by a `config.py` helper
that atomically edits `config.json` to hide, show, reorder blocks, toggle the
Tools/Recent lines, reset to defaults, and print the current layout.

#### Scenario: Hiding blocks
- **Given** the user asks to hide `credits` and `time`
- **When** the agent runs `config.py hide credits time`
- **Then** those blocks are added to `line1_hidden` via an atomic write and the
  new layout is printed.

#### Scenario: Resetting to defaults
- **Given** a custom config exists
- **When** the agent runs `config.py reset`
- **Then** `config.json` is removed and the next render uses defaults.

#### Scenario: Unknown block name
- **Given** the agent runs `config.py hide bogus`
- **When** the helper validates the id
- **Then** it prints the list of valid block ids and exits non-zero without
  changing the config.
