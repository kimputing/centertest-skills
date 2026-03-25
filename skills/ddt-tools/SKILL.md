---
name: ddt-tools
description: Data-Driven Testing tools for CenterTest — validate DC references, diff xlsx test data, report unused codes, and convert xlsx for git. Use when the user says "check references", "validate DC", "diff testdata", "cleanup unused codes", "DDT check", or works with DataCombination xlsx files. Triggers on phrases like "run DDT check", "validate references", "diff xlsx", "unused codes", or any DDT/DC file work.
---

# Skill: DDT Tools

## Purpose

A suite of tools for working with CenterTest Data-Driven Testing (DDT) xlsx files:
- **Validate references** — ensure DC DataCombination sheets only reference codes that exist
- **Diff xlsx** — smart cell-level diff of test data files against git refs
- **Cleanup unused** — find and remove codes no longer referenced by any DC file
- **Textconv** — convert xlsx to readable text for git diff

## When to Use

Trigger this skill when the user:
- Asks to validate or check DDT/DC references
- Wants to see what changed in testdata xlsx files
- Asks to find or clean up unused codes in Data files
- Works with DataCombination xlsx files and needs tooling help
- Mentions "DDT check", "validate references", "diff testdata", or "unused codes"

## Configuration

All scripts need to run from the **root of a CenterTest project** that contains a `testdata/` directory with DC xlsx files.

On first run, the scripts will prompt for the project path and save it to `~/.centertest/ddt-tools.json`. The `CENTERTEST_PROJECT_DIR` environment variable overrides the saved config.

```bash
# Set/override project path
PYTHON=$(command -v python3 || command -v python)
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/ddt_config.py --set-path "/path/to/centertest-project"

# Show current path
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/ddt_config.py --show-path
```

## Tools

### 1. Validate References (`xlsx-validate-refs.py`)

Validates that DC DataCombination sheets only reference codes that exist in their reference data sheets.

```bash
PYTHON=$(command -v python3 || command -v python)

# Validate all DC files
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/xlsx-validate-refs.py

# Validate a specific DC file
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/xlsx-validate-refs.py testdata/WorkersCompDC.xlsx
```

**What it checks:**
- Columns starting with `#` in the DataCombination sheet reference valid sheet names
- Every code in those columns exists in the corresponding reference sheet
- Handles comma-separated codes
- Supports hierarchy via `testdata/DataDrivenHierarchy.json` (child DCs inherit parent codes)
- Provides case-sensitivity hints when a near-match exists

**Exit code:** 0 if all valid, 1 if broken references found.

### 2. Diff xlsx (`xlsx-diff.py`)

Smart cell-level diff for xlsx test data files.

```bash
PYTHON=$(command -v python3 || command -v python)

# Diff working copy vs origin/main
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/xlsx-diff.py testdata/WorkersCompDC.xlsx

# Diff vs a specific git ref
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/xlsx-diff.py --ref HEAD~1 testdata/WorkersCompDC.xlsx

# Diff two files directly
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/xlsx-diff.py old.xlsx new.xlsx
```

**Output includes:** new/removed sheets, added/removed columns, cell-level changes grouped by code, added/removed rows.

### 3. Report Unused Codes (`xlsx-cleanup-unused.py`)

Reports codes in Data files that are not referenced by any DC DataCombination sheet. This is a **report-only** tool — it never modifies files.

```bash
PYTHON=$(command -v python3 || command -v python)
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/xlsx-cleanup-unused.py
```

### 4. Check Code Usages (`ddt-check-code-usages.py`)

Validates that hardcoded string codes in `DDTHelper.getXxx("code")` Java calls reference codes that actually exist in the corresponding xlsx files. This is a **report-only** tool.

```bash
PYTHON=$(command -v python3 || command -v python)

# Check all Java source files
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/ddt-check-code-usages.py

# Check a specific file
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/ddt-check-code-usages.py src/main/java/com/example/SomeTest.java
```

**How it works:**
1. Parses `DDTHelper.java` to build a map of method name → (xlsx file, sheet)
2. Scans Java source for `DDTHelper.getXxx("literal")` calls
3. Checks if the literal code exists in the corresponding xlsx file/sheet
4. Reports missing codes with case-sensitivity hints

**Note:** Only catches hardcoded string literals. Dynamic codes (from variables or data fields) cannot be statically validated.

### 5. Textconv (`xlsx-textconv.py`)

Converts xlsx to human-readable text. Useful as a git textconv driver.

```bash
PYTHON=$(command -v python3 || command -v python)
"$PYTHON" ~/.claude/skills/ddt-tools/scripts/xlsx-textconv.py testdata/WorkersCompDC.xlsx
```

## Script Details

- **Dependency**: `openpyxl` (auto-installed or prompt user: `pip install openpyxl`)
- **Hierarchy**: `testdata/DataDrivenHierarchy.json` maps parent DC files to child DC patterns
- **DC files**: Named `*DC.xlsx` in `testdata/` or subdirectories
- **Data files**: Named `*Data.xlsx` in `testdata/`
- **Reference columns**: Start with `#` in the DataCombination sheet — the part after `#` maps to a sheet name

## Prerequisites

- Python 3 (`python3` or `python`)
- `openpyxl` Python package
- Git (for diff and textconv tools)
