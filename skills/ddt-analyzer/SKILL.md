---
name: ddt-analyzer
description: Analyze CenterTest Data-Driven Testing structure and generate an Excel report showing DC-to-Data relationships, code usage, and test mappings. Use when the user says "analyze DDT", "DDT report", "show DDT structure", "which tests use this DC", or wants to understand the test data dependency graph. Triggers on phrases like "analyze data-driven", "DDT analysis", "generate DDT report", or "test data dependencies".
---

# Skill: DDT Analyzer

## Purpose

Analyzes the full Data-Driven Testing structure of a CenterTest project and generates an Excel report. This is the Python equivalent of the Java `DDTAnalyzer` (run mode `ANALYZEDDTFILES`) — runs standalone without needing the full CenterTest application.

## When to Use

Trigger this skill when the user:
- Wants to understand the DDT file structure and dependencies
- Asks which Data files are referenced by which DC files
- Wants to know which tests use a specific datasource
- Asks for code usage counts (how many times each code is used across DC files)
- Needs an overview/report of the test data ecosystem

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

The report is saved to `results/DDT_Analysis_<timestamp>.xlsx` with 5 sheets:

| Sheet | Content |
|-------|---------|
| `DataCombination_References` | Matrix of DC files vs referenced Data files (marked with X) |
| `ReferencedFiles_DataCombination` | Inverse: Data files vs which DC files reference them |
| `Codes_Usage` | Every code in every Data file with usage count across all DCs |
| `Codes_Usage_Detail` | Per-DC-file breakdown of code usage |
| `DataCombination_Tests` | Maps DC datasource paths to `@DataDriven` test class#method |

## Configuration

Uses the same project path as ddt-tools (`~/.centertest/ddt-tools.json`). On first run, prompts for the project path if not configured.

The `CENTERTEST_PROJECT_DIR` environment variable overrides saved config.

## What It Scans

1. **testdata/*.xlsx** — finds files with both `datacombination` and `references` sheets
2. **References sheet** — resolves `location` column to find external Data files
3. **# columns in DataCombination** — tracks which codes are used per reference sheet
4. **src/**/*.java** — finds `@DataDriven(datasource = "...")` annotations to map tests to datasources

## Prerequisites

- Python 3 (`python3` or `python`)
- `openpyxl` Python package

## Relationship to Java DDTAnalyzer

This is a standalone Python port of `com.ankrpt.centertest.datadriven.data.analyzer.DDTAnalyzer` from centertest-platform. The Java version requires the full Spring Boot application running with `centertest.run=ANALYZEDDTFILES`. This skill runs independently with just Python.
