#!/usr/bin/env python3
"""Edit the statusline layout config atomically.

Backs the `/statusline` slash command. Reads/writes the layout config under
the plugin data dir (`CODEBUDDY_CONFIG_DIR` or ~/.codebuddy, then
`plugins/data/statusline/config.json`), reusing the same dir as the cache.
Subcommands:

    hide   <block>...          add block(s) to line1_hidden
    show   <block>...          remove block(s) from line1_hidden
    move   <block> front|end   reorder line1_order
    move   <block> after <other>
    move   <block> before <other>
    enable  tools|recent        set a whole-line toggle on
    disable tools|recent        set a whole-line toggle off
    reset                      delete the config (next render = defaults)
    list                       print the effective layout

On any unknown block id the command prints the valid ids and exits non-zero
so the calling agent can correct itself. Writes are atomic (temp file + rename).
"""

import json
import os
import sys

# Make sibling modules importable when run as an absolute-path script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from render import BLOCKS_LINE1, _config_path, load_layout_config, resolve_layout


def _err(msg):
    print(msg, file=sys.stderr)
    print("Valid blocks: " + ", ".join(BLOCKS_LINE1), file=sys.stderr)
    print("Valid line toggles: tools, recent", file=sys.stderr)
    sys.exit(2)


def _load_editable():
    """Return a normalized, fully-populated layout dict for editing.

    Starts from defaults if no config exists, so a first edit (e.g. `hide
    credits`) works without a pre-existing file.
    """
    cfg = load_layout_config() or {}
    layout = cfg.get("layout", {}) if isinstance(cfg, dict) else {}
    return {
        "line1_order": list(layout.get("line1_order", BLOCKS_LINE1)),
        "line1_hidden": list(layout.get("line1_hidden", [])),
        "tools": bool(layout.get("tools", True)),
        "recent": bool(layout.get("recent", True)),
    }


def _write(layout):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"layout": layout}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except IOError as e:
        print(f"write failed: {e}", file=sys.stderr)
        sys.exit(3)


def _check_ids(ids):
    valid = set(BLOCKS_LINE1)
    bad = [i for i in ids if i not in valid]
    if bad:
        _err("Unknown block(s): " + ", ".join(bad))


def _move(layout, block, where, other=None):
    order = layout["line1_order"]
    if block not in order:
        order.append(block)
    order.remove(block)
    if where == "front":
        order.insert(0, block)
    elif where == "end":
        order.append(block)
    elif where in ("after", "before"):
        if other is None:
            _err(f"move {where} requires a reference block, e.g. "
                 f"'move {block} {where} model'")
        elif other not in order:
            # Referenced block absent -> fall back to end/front.
            if where == "after":
                order.append(block)
            else:
                order.insert(0, block)
        else:
            idx = order.index(other)
            order.insert(idx + (1 if where == "after" else 0), block)
    else:
        _err(f"unknown move target '{where}'")


def _print_layout(layout):
    resolved = resolve_layout({"layout": layout})
    print("Layout (effective):")
    print("  line1 order: " + " | ".join(resolved["line1_order"]))
    print("  hidden:      " + (", ".join(layout["line1_hidden"]) or "(none)"))
    print("  tools:       " + ("on" if resolved["tools"] else "off"))
    print("  recent:      " + ("on" if resolved["recent"] else "off"))
    print("Valid blocks: " + ", ".join(BLOCKS_LINE1))


def main(argv):
    if len(argv) < 2:
        _err("usage: config.py <hide|show|move|enable|disable|reset|list> [args]")

    action = argv[1]
    layout = _load_editable()

    if action == "list":
        _print_layout(layout)
        return

    if action == "reset":
        path = _config_path()
        if os.path.exists(path):
            os.remove(path)
            print("reset: config deleted, using defaults")
        else:
            print("reset: no config present, already defaults")
        return

    if action == "hide":
        _check_ids(argv[2:])
        hidden = set(layout["line1_hidden"])
        for b in argv[2:]:
            hidden.add(b)
            # Keep order list clean: a hidden block need not be ordered.
            if b in layout["line1_order"]:
                layout["line1_order"].remove(b)
        layout["line1_hidden"] = list(hidden)
        _write(layout)
        _print_layout(layout)
        return

    if action == "show":
        _check_ids(argv[2:])
        hidden = set(layout["line1_hidden"]) - set(argv[2:])
        layout["line1_hidden"] = list(hidden)
        _write(layout)
        _print_layout(layout)
        return

    if action == "move":
        if len(argv) < 4:
            _err("usage: config.py move <block> [to] front|end|after <other>|before <other>")
        block = argv[2]
        _check_ids([block])
        # Optional "to" word: accept both `move X to front` and `move X front`.
        rest = argv[3:]
        if rest and rest[0] == "to":
            rest = rest[1:]
        if not rest:
            _err("usage: config.py move <block> [to] front|end|after <other>|before <other>")
        where = rest[0]
        other = rest[1] if len(rest) > 1 else None
        if where in ("after", "before") and other is not None:
            _check_ids([other])
        _move(layout, block, where, other)
        _write(layout)
        _print_layout(layout)
        return

    if action in ("enable", "disable"):
        if len(argv) < 3:
            _err(f"usage: config.py {action} tools|recent")
        toggle = argv[2]
        if toggle not in ("tools", "recent"):
            _err(f"unknown toggle '{toggle}'")
        layout[toggle] = (action == "enable")
        _write(layout)
        _print_layout(layout)
        return

    _err(f"unknown action '{action}'")


if __name__ == "__main__":
    main(sys.argv)
