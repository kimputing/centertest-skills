# CLAUDE.md — cssid-finder

## What It Does

Looks up the Java getter chain for a Guidewire CSS ID. Input: app name + CSS ID. Output: `new PageName(getContext()).getWidgetGetter()` chain.

## Architecture

Single script: `scripts/find_getter.py`

Config: `~/.centertest/cssid-finder.json` — path to generated project's `src/main/resources` directory.

## How CSS ID Lookup Works

1. Normalize the runtime CSS ID into the key forms the generator stores:
   - Each numeric segment is an iterator index (`#`) or a table-row index (`[ROW]`). A single
     id can contain both, so the script tries every `#`/`[ROW]` combination of the numeric
     segments and matches whichever key exists (exact match preferred).
   - Conditional toolbar segments `[X_tb]` are expanded to three variants: kept, brackets
     removed, and the whole segment dropped.
   - Trailing `_Input` suffix is stripped.
2. Searches `.properties` files (new format) or `.cssids` files (legacy) using `grep -F`
3. Properties format: `cssId=getterChain` (one file per page, under `cssids/<app>/`)
4. Legacy format: single JSON-like file per app (`<app>.cssids`)

## How the generated keys are built (background)

See the "How CSS IDs map to page-object getters" doc and `GuidewireElement.getId` in
centertest-core. `#` replaces an iterator's numeric index, `[ROW]` marks a table/list-view
row, and `[X_tb]` flags a toolbar segment that may or may not appear in the live DOM id —
which is why the script tries multiple variants.

## Gotchas

- A single id can mix `#` and `[ROW]` (iterator containing a table); whole-string `[ROW]`-only
  or `#`-only normalization is not enough, hence the per-segment combination search
- The generated value can keep a literal `#` (e.g. `getClauseIterator(#)`) — the developer
  replaces it with the concrete row index
- Path must point to `src/main/resources` of the **generated** project (not the main centertest project)
- Environment variable `CENTERTEST_CSSIDS_DIR` overrides saved config
