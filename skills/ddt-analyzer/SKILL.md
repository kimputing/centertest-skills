---
name: ddt-analyzer
description: Analyze CenterTest Data-Driven Testing structure and generate a 15-sheet Excel report showing DC-to-Data relationships, code usage, test mappings, orphaned files, broken references, unused codes, hierarchy validation, and more. Use when the user says "analyze DDT", "DDT report", "show DDT structure", "which tests use this DC", or wants to understand the test data dependency graph. Triggers on phrases like "analyze data-driven", "DDT analysis", "generate DDT report", or "test data dependencies".
---

# Skill: DDT Analyzer

## Purpose

Analyzes the full Data-Driven Testing structure of a CenterTest project and generates a comprehensive 15-sheet Excel report. This is the Python equivalent of the Java `DDTAnalyzer` (run mode `ANALYZEDDTFILES`) — runs standalone without needing the full CenterTest application.

## When to Use

Trigger this skill when the user:
- Wants to understand the DDT file structure and dependencies
- Asks which Data files are referenced by which DC files
- Wants to know which tests use a specific datasource
- Asks for code usage counts or coverage analysis
- Needs to find orphaned files, broken references, or unused codes
- Wants an overview/report of the test data ecosystem

## How to Use

### Run the analyzer

```bash
PYTHON=$(python3 --version >/dev/null 2>&1 && echo python3 || echo python)

# Analyze everything
"$PYTHON" ~/.claude/skills/ddt-analyzer/scripts/ddt-analyzer.py

# Exclude specific paths
"$PYTHON" ~/.claude/skills/ddt-analyzer/scripts/ddt-analyzer.py --exclude testdata/archive,testdata/old
```

### Report output

The report is saved to `results/DDT_Analysis_<timestamp>.xlsx` with 15 sheets:

| # | Sheet | Content |
|---|-------|---------|
| 1 | `DC_References` | Matrix of DC files vs referenced Data files |
| 2 | `RefFiles_DC` | Inverse: Data files vs which DC files reference them |
| 3 | `Codes_Usage` | Every code with aggregated usage count |
| 4 | `Codes_Usage_Detail` | Per-DC-file code usage breakdown |
| 5 | `DC_Tests` | Maps DC datasource paths to @DataDriven test methods |
| 6 | `Orphaned_DataFiles` | xlsx files in testdata/ not referenced by any DC |
| 7 | `Broken_Datasources` | @DataDriven annotations pointing to non-existent files |
| 8 | `Untested_DC_Files` | DC files with no test method using them |
| 9 | `Unused_Codes` | Codes in Data files never referenced from any DC |
| 10 | `Hardcoded_DDTHelper` | Validation of DDTHelper.getXxx("literal") calls |
| 11 | `Hierarchy_Validation` | DataDrivenHierarchy.json integrity checks |
| 12 | `Code_Coverage` | % of codes used per Data file sheet |
| 13 | `Duplicate_Codes` | Same code appearing in multiple Data files/sheets |
| 14 | `DC_Metrics` | Complexity metrics per DC file (codes, refs, tests) |
| 15 | `Impact_Analysis` | Blast radius of each Data file (DCs + tests + hardcoded) |

## Configuration

Uses the same project path as ddt-tools (`~/.centertest/ddt-tools.json`). On first run, prompts for the project path if not configured.

The `CENTERTEST_PROJECT_DIR` environment variable overrides saved config.

## Prerequisites

- Python 3 (`python3` or `python`)
- `openpyxl` Python package
