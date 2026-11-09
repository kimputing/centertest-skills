# CLAUDE.md — suite-builder

## What It Does

Reads a CenterTest project's tests (`@CenterTest` classes, `@CenterTestCase` methods, the codes of
each method's `@DataDriven` DataCombination sheet) and its `CenterTestSuiteList.json`, resolves suite
entries the way CenterTest does, and edits suites.

## Architecture

- `scripts/suite.py` — the engine and CLI. `scan()`, `resolve_entry()`/`resolve_suite()` (each entry
  part a case-insensitive full-match regex; `Packages` regexes on the package; `Suites` recursively),
  `select()` (selectors are regex *searches*), `compact()` (`Class` / `Class method` /
  `Class method (a|b)`), `add_to()` / `remove_from()`, `serialize()` (keeps indent, EOL, trailing newline).
- `scripts/xlsx_read.py` — **vendored, byte-identical** copy of `plugins/recording-to-test/scripts/xlsx_read.py`
  (stdlib xlsx reader). Change it there and copy it over; `tests/test_suite.py` fails when they differ.

## Rules

- Never rewrite entries the user did not ask to change: `add` appends, `remove` rewrites only entries
  that overlap the removal.
- Every editing command is a dry run without `--write`.
- No third-party packages.

## Tests

    python3 -m unittest discover -s plugins/suite-builder/tests -v
