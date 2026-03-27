# CLAUDE.md — ddt-analyzer

## What It Does

Analyzes the full DDT (Data-Driven Testing) file structure of a CenterTest project. Produces a 15-sheet Excel report covering DC-to-Data relationships, code usage, test mappings, orphaned files, broken references, and hierarchy validation.

## Architecture

Single monolithic script: `scripts/ddt-analyzer.py` (~900 lines)

Reuses config from ddt-tools: `~/.centertest/ddt-tools.json` (shared `project_dir`).

## Key Concepts

- **DC files** (`*DC.xlsx`): DataCombination files — define test data combinations with `#Reference` columns pointing to Data files
- **Data files** (`*Data.xlsx`): Reference data — shared data sheets with reusable codes
- **DataDrivenHierarchy.json**: Defines parent-child relationships between DC files
- **`code` column**: Every sheet has a `code` column — the unique identifier for each row

## 15 Analysis Sheets

1. DC_Summary, DC_Tests, DC_Sheets, DC_References, DC_UnusedCodes
2. Data_Summary, Data_Sheets, Data_CodeUsage, Data_SharedAcrossDC
3. Hierarchy_Tree, Hierarchy_Inheritance
4. Issues_BrokenRefs, Issues_OrphanFiles, Issues_MissingSheets
5. Coverage_Matrix

## Gotchas

- Depends on `openpyxl` — check import with try/except
- Output goes to `results/DDT_Analysis_<timestamp>.xlsx`
- Large projects (50+ xlsx files) can take 10-30 seconds
