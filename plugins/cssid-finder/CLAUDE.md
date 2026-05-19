# CLAUDE.md — cssid-finder

## What It Does

Looks up the Java getter chain for a Guidewire CSS ID. Input: app name + CSS ID. Output: `new PageName(getContext()).getWidgetGetter()` chain.

## Architecture

Single script: `scripts/find_getter.py`

Config: `~/.centertest/cssid-finder.json` — path to generated project's `src/main/resources` directory.

## How CSS ID Lookup Works

1. Numeric segments in CSS ID replaced with `[ROW]` placeholder (e.g., `LV-5-Name` → `LV-[ROW]-Name`)
2. Trailing `_Input` suffix stripped
3. Searches `.properties` files (new format) or `.cssids` files (legacy) using `grep -F`
4. Properties format: `getterChain = cssId` (one file per page, under `cssids/<app>/`)
5. Legacy format: single JSON-like file per app (`<app>.cssids`)

## Gotchas

- The script tries both `[ROW]` and `# row` placeholders for row normalization — different generated project versions use different formats
- Path must point to `src/main/resources` of the **generated** project (not the main centertest project)
- Environment variable `CENTERTEST_CSSIDS_DIR` overrides saved config
