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

Data Studio is the single implementation. Run its headless analyzer — no server needed:

```bash
DataStudio --analyze /path/to/project/testdata            # JSON to stdout
DataStudio --analyze /path/to/project/testdata --xlsx results/DDT_Analysis.xlsx
DataStudio --analyze /path/to/project/testdata --only unusedCodes
```

Exit codes: 0 completed, 2 unusable directory. Findings do not gate; use
`--fail-on <analysis>` to opt into gating in CI.

### Counts may differ from archived reports

The retired `ddt-analyzer.py` bucketed codes by sheet NAME across the whole project, so
several files each defining a `Coverage` sheet merged into one. Data Studio keys
`(file, sheet, code)`, so those stay separate — **unused-code counts will typically be
higher, and they are now correct**. It also counts hardcoded `DDTHelper` usage in both
unused-codes and coverage, where the old report counted it in coverage only. A third
correction: a reference from one Data sheet to another now counts as usage.

### When Java sources are not found

Data Studio finds the Java root by walking up from the testdata path. If no
`src/**/*.java` exists above it, `javaAvailable` is `false`, the four Java-dependent
analyses (`dcTests`, `brokenDatasources`, `untestedDcFiles`, `hardcodedHelper`) are `null`
(never `[]`), and `degraded` names the four whose numbers are affected instead
(`unusedCodes`, `codeCoverage`, `dcMetrics`, `impactAnalysis`). Treat `null` as "could not
look", not "nothing found".

### Report output

`--xlsx` writes the same 15-sheet workbook the retired script produced (sheet names are
unchanged, so an archived report lines up column-for-column):

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

`--only <key>` emits a single analysis key's JSON instead of all 15 (the xlsx report
still writes all 15 sheets regardless of `--only`). The 15 list-valued keys are:
`dcReferences`, `refFilesDc`, `codesUsage`, `codesUsageDetail`, `dcTests`,
`orphanedDataFiles`, `brokenDatasources`, `untestedDcFiles`, `unusedCodes`,
`hardcodedHelper`, `hierarchyValidation`, `codeCoverage`, `duplicateCodes`, `dcMetrics`,
`impactAnalysis`.

## Configuration

No config file needed — pass the testdata directory directly as an argument (or via
Data Studio's `--project-root` / `--testdata-dir`, same as `--validate`).

## Prerequisites

- The `DataStudio` binary (self-contained, no Python required at runtime).

The retired `ddt-analyzer.py` (Python 3 + `openpyxl`) is superseded and should be
retired once parity with Data Studio's `--analyze` is confirmed; it has not been
deleted yet.
