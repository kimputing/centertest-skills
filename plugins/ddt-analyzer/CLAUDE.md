# CLAUDE.md — ddt-analyzer

## What It Does

Analyzes the full DDT (Data-Driven Testing) file structure of a CenterTest project. Produces a 28-sheet Excel report through Data Studio (17 sheets from the fallback script) covering DC-to-Data relationships, code usage, test mappings, orphaned files, broken references, and hierarchy validation.

## Architecture

Single monolithic script: `scripts/ddt-analyzer.py` (~900 lines)

Reuses config from ddt-tools: `~/.centertest/ddt-tools.json` (shared `project_dir`).

## Key Concepts

- **DC files** (`*DC.xlsx`): DataCombination files — define test data combinations with `#Reference` columns pointing to Data files
- **Data files** (`*Data.xlsx`): Reference data — shared data sheets with reusable codes
- **DataDrivenHierarchy.json**: Defines parent-child relationships between DC files
- **`code` column**: Every sheet has a `code` column — the unique identifier for each row

## Report Sheets

Data Studio writes 28 sheets; the fallback `scripts/ddt-analyzer.py` writes 17 in a different order.
The sheet tables are in `skills/ddt-analyzer/SKILL.md` (Report output, and The fallback script's own sheets).

## Gotchas

- Depends on `openpyxl` — check import with try/except
- Output goes to `results/DDT_Analysis_<timestamp>.xlsx`
- Large projects (50+ xlsx files) can take 10-30 seconds
