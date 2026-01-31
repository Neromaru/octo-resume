# OctoPrint Plugin: Octo Resume

This repository is an **OctoPrint plugin** that generates a resume-ready recovery G-code file when a print fails mid-way.

It adds a **wrench icon** next to every local G-code file in OctoPrint’s Files list.

## What you need

- OctoPrint installed in a Python environment (typically a virtualenv)
- Python version matching your OctoPrint installation

## Install (development)

From your OctoPrint environment:

```bash
pip install -e .
```

Then restart OctoPrint.

## Mid-print recovery (Continue print where…)

In OctoPrint:

- Click the **wrench** icon next to the file you want to recover, then enter layer + safety Z
- Or open the sidebar panel **Octo Resume** and enter:

- **Source file**: the G-code file path as shown in OctoPrint’s Files list
- **Target layer**: e.g. `102` (matches `;LAYER:102` or `; layer 102`)
- **Safety Z** (optional): a “leap” height to avoid collisions before the first X/Y move

The plugin will create a new file with suffix **`_RECOVERY.gcode`** in the same folder.

### What the generator does

- Preserves the original “start G-code” header (temps, absolute positioning, etc.)
- Rewrites any header `G28` (home all) into **`G28 X Y`** to avoid Z homing into an existing print
- Strips all commands before the requested layer
- Injects `G92 E0` before the resume layer
- Injects a safe Z lift before the first X/Y move in the resume layer

## Files to edit first

- `octoprint_myplugin/__init__.py`: plugin id/name/version and implementation
- `pyproject.toml`: package name/version/metadata and entry point

## Documentation

- Cursor project docs: add/inspect via `@Docs`
- OctoPrint general concepts: `https://docs.octoprint.org/en/main/plugins/concepts.html`


