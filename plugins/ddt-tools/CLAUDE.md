# CLAUDE.md — ddt-tools

## What It Does

Suite of 6 tools for working with CenterTest DDT (Data-Driven Testing) xlsx files: validate references, diff cells, cleanup unused codes, check code usages in Java, and convert xlsx for git.

## Architecture

```
scripts/
├── ddt_config.py              # Shared config — ~/.centertest/ddt-tools.json
├── xlsx-validate-refs.py      # Validate #Reference columns point to valid codes
├── xlsx-diff.py               # Smart cell-level diff of xlsx against git refs
├── xlsx-cleanup-unused.py     # Find/remove codes not referenced by any DC
├── xlsx-textconv.py           # Convert xlsx to text for git diff
└── ddt-check-code-usages.py   # Find which Java classes reference specific codes
```

## Shared Config

`ddt_config.py` provides `get_project_dir()` used by all scripts. Resolution: `CENTERTEST_PROJECT_DIR` env var > `~/.centertest/ddt-tools.json` > interactive prompt.

It also provides `run_with_pr_review_report(tool_name, main)` — wraps a tool's `main()`, tees stdout+stderr, and saves the output to `pr-review/<git user.name>/<timestamp>_<tool>.txt` in the project dir (skipped if cwd has no `testdata/`). Used by all report tools; NOT by `xlsx-textconv.py` (git diff driver — would spam files). Reports are saved even on non-zero exit; the exit code is preserved.

## Key Concepts

- **`#` columns**: Reference columns in DC sheets (e.g., `#Payment` references the `payment` sheet in a Data file)
- **References sheet**: Special sheet in DC files listing which external Data files to look up
- **DataDrivenHierarchy.json**: Parent DC codes available to child DCs
- **Comma-separated codes**: A single cell can contain `code1, code2, code3`

## Gotchas

- `xlsx-validate-refs.py` loads the full hierarchy — needs `DataDrivenHierarchy.json` in testdata/
- `xlsx-diff.py` shells out to `git show` — needs to run inside a git repo
- `xlsx-textconv.py` is designed for `.gitattributes` integration: `*.xlsx diff=xlsx`
- All scripts exit 0 on success, 1 on error — usable in CI pipelines
