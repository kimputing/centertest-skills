# ddt-analyzer

Analyze CenterTest Data-Driven Testing structure and generate a comprehensive 15-sheet Excel report.

## Install

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install ddt-analyzer@centertest-skills
```

To update later: `/plugin marketplace update centertest-skills`.

See [`skills/ddt-analyzer/SKILL.md`](skills/ddt-analyzer/SKILL.md) for trigger phrases and the full skill definition.

## Prerequisites

- Python 3 (`python3` or `python`)
- `openpyxl` Python package (`pip install openpyxl`)

## Report sheets (15)

| # | Sheet | Content |
|---|-------|---------|
| 1 | DC_References | DC files vs referenced Data files |
| 2 | RefFiles_DC | Data files vs DC files that reference them |
| 3 | Codes_Usage | Code usage counts |
| 4 | Codes_Usage_Detail | Per-DC code usage |
| 5 | DC_Tests | Test classes mapped to datasources |
| 6 | Orphaned_DataFiles | Unreferenced xlsx files |
| 7 | Broken_Datasources | @DataDriven pointing to missing files |
| 8 | Untested_DC_Files | DC files with no tests |
| 9 | Unused_Codes | Dead codes in Data files |
| 10 | Hardcoded_DDTHelper | DDTHelper string code validation |
| 11 | Hierarchy_Validation | DataDrivenHierarchy.json checks |
| 12 | Code_Coverage | Usage % per Data file sheet |
| 13 | Duplicate_Codes | Same code in multiple files |
| 14 | DC_Metrics | Complexity metrics per DC |
| 15 | Impact_Analysis | Blast radius per Data file |

## Configuration

Reuses the project path saved by `ddt-tools` in `~/.centertest/ddt-tools.json`. The `CENTERTEST_PROJECT_DIR` environment variable overrides saved config.
