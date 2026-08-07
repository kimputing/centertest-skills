---
name: ddt-analyzer
description: Analyze CenterTest Data-Driven Testing structure and generate a 15-sheet Excel report showing DC-to-Data relationships, code usage, test mappings, orphaned files, broken references, unused codes, hierarchy validation, and more. Use when the user says "analyze DDT", "DDT report", "show DDT structure", "which tests use this DC", or wants to understand the test data dependency graph. Triggers on phrases like "analyze data-driven", "DDT analysis", "generate DDT report", or "test data dependencies".
---

# Skill: DDT Analyzer

## Purpose

Analyzes the full Data-Driven Testing structure of a CenterTest project and generates a comprehensive 15-sheet Excel report. This is the Python equivalent of the Java `DDTAnalyzer` (run mode `ANALYZEDDTFILES`) — runs standalone without needing the full CenterTest application.

There are two implementations. **Prefer Data Studio's `--analyze` CLI when the
`DataStudio` binary is installed** — it is the actively-developed, more accurate
implementation. **`${CLAUDE_PLUGIN_ROOT}/scripts/ddt-analyzer.py` is a permanent
fallback**, maintained for machines where Data Studio is not installed — it is not
being retired. The two do not produce identical numbers (see "Which implementation ran"
below), so always know which one you used.

## When to Use

Trigger this skill when the user:
- Wants to understand the DDT file structure and dependencies
- Asks which Data files are referenced by which DC files
- Wants to know which tests use a specific datasource
- Asks for code usage counts or coverage analysis
- Needs to find orphaned files, broken references, or unused codes
- Wants an overview/report of the test data ecosystem

## How to Use

### Step 1: probe for Data Studio, fall back if absent

```bash
PYTHON=$(python3 --version >/dev/null 2>&1 && echo python3 || echo python)

if command -v DataStudio >/dev/null 2>&1; then
    # Preferred path — Data Studio is installed.
    DataStudio --analyze /path/to/project/testdata
else
    # Fallback path — Data Studio is not on PATH.
    "$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/ddt-analyzer.py"
fi
```

`command -v DataStudio` only checks whether the binary exists on `PATH` — it does not
start a server, open the app, or probe any port. There is nothing to "run and leave
open"; the CLI exits when the analysis is done.

### Preferred path: Data Studio's `--analyze`

```bash
DataStudio --analyze /path/to/project/testdata            # JSON to stdout
DataStudio --analyze /path/to/project/testdata --xlsx results/DDT_Analysis.xlsx
DataStudio --analyze /path/to/project/testdata --only unusedCodes
```

Exit codes: 0 the analysis completed (regardless of findings); 1 only when a
`--fail-on <analysis>` gate actually fires; 2 for an unusable directory, an invalid
`--only`/`--fail-on` key, a `--fail-on` analysis that is unavailable (e.g. Java sources
not found), or a failed `--xlsx` write. Findings do not gate by default; `--fail-on`
opts into gating in CI.

`--analyze` also writes `pr-review/<sanitized git user.name>/<yyyy-MM-dd_HH-mm-ss>_analyze.txt`
into the project (next to `testdata/`) every time it runs, mirroring the `DDT_check_*`
Gradle tasks and the ddt-tools scripts' pr-review behavior. It is a courtesy artifact:
if it fails to write, Data Studio only prints a warning to stderr — the exit code is
unaffected. The HTTP endpoint (`GET /api/analysis`, used by Data Studio's UI) never
writes this file — the pr-review write is CLI-only, and only on this preferred path;
the fallback script below has its own, separate pr-review behavior (see ddt-tools'
"PR-Review Reports" section).

Data Studio finds the Java root by walking up from the testdata path. If no
`src/**/*.java` exists above it, `javaAvailable` is `false`, the four Java-dependent
analyses (`dcTests`, `brokenDatasources`, `untestedDcFiles`, `hardcodedHelper`) are `null`
(never `[]`), and `degraded` names the four whose numbers are affected instead
(`unusedCodes`, `codeCoverage`, `dcMetrics`, `impactAnalysis`). Treat `null` as "could not
look", not "nothing found". **This javaAvailable/degraded/null contract only exists on
this path — see below, the fallback script has none of it.**

### Fallback path: `ddt-analyzer.py`

```bash
PYTHON=$(python3 --version >/dev/null 2>&1 && echo python3 || echo python)

# Analyze everything
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/ddt-analyzer.py"

# Exclude specific paths
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/ddt-analyzer.py" --exclude testdata/archive,testdata/old
```

The script has no `javaAvailable`/`degraded`/`null` semantics at all — it does not
distinguish "Java sources could not be found" from "found nothing"; every analysis
that touches Java source (tests, hardcoded-helper validation) simply reports what its
regex-based scan found, silently, with no flag telling you the scan came up empty
versus never ran. Do not expect those fields from this path's output.

### Which implementation ran — read the output shape to tell

The two paths don't just differ in numbers, they differ in output shape:
- **Data Studio's `--analyze`** prints the full JSON result to stdout, and writes an
  xlsx report only when you pass `--xlsx`.
- **`ddt-analyzer.py`** prints a step-by-step console log (`[1/6] ... [6/6] ...` plus a
  `Summary:` block) — never JSON — and *always* writes an xlsx report, unconditionally,
  to `results/DDT_Analysis_<timestamp>.xlsx` (timestamp format `%Y%m%d_%H%M%S`, e.g.
  `results/DDT_Analysis_20260807_113000.xlsx`).

If you need to parse the result programmatically, use the preferred path — the fallback
gives you a human-readable console summary and a file on disk, not structured stdout.

### Counts differ by which implementation ran — direction is not predictable in general

The two implementations correct three things differently, and the corrections pull in
**opposite directions**, so whether a given project's unused-code count goes up or down
under Data Studio depends on which effect dominates for that project. Do not assume a
direction — measure it.

- **Scope-awareness can RAISE the count.** `ddt-analyzer.py` buckets codes by sheet NAME
  across the whole project, so if two different files each define a same-named sheet
  (e.g. two files that both have a `Coverage` sheet) with an overlapping code name, the
  fallback merges them into one bucket and can under-count unused codes. Data Studio
  keys `(file, sheet, code)`, so same-named sheets in different files never mask each
  other. **This bug only bites when a shared code name actually appears in same-named
  sheets across files — plenty of projects will see no change from this correction at
  all**, because their same-named sheets across files don't share code names.
- **Counting hardcoded Java usage and Data-sheet-to-Data-sheet references can LOWER the
  count.** The fallback counts hardcoded `DDTHelper` usage in coverage but not in
  unused-codes, and does not credit a reference from one Data sheet to another as usage
  at all. Data Studio counts both, so codes the fallback reports as unused because their
  only reference is a hardcoded Java call or a sheet-to-sheet reference are correctly
  reported as used under Data Studio — lowering its unused-code count relative to the
  fallback's.

**Measured on `ootb-v10-centertest`** (Data Studio vs. `ddt-analyzer.py`):

| Metric | Data Studio | `ddt-analyzer.py` |
|---|---|---|
| Unused codes | 34 | 35 |
| Orphaned files | 3 | 2 |
| Untested DC files | 4 | 4 |
| Duplicate codes | 5 | 5 |
| Broken datasources | 0 | 0 |
| Hardcoded invalid | 0 | 0 |

Here Data Studio's unused-code count was **lower**, not higher: the two unused-code sets
were identical except for one entry, `SharedData.xlsx / Address / Inland`, which the
fallback reports unused and Data Studio reports used — its only reference in this
project is a Data-sheet-to-Data-sheet one, with zero DC-sourced references and zero
hardcoded Java calls, so only Data Studio's sheet-to-sheet correction sees it as used.
The scope-blindness bug was present but latent in this project: `ootb-v10` does have a
`Coverage` sheet in both `BusinessOwnersData.xlsx` and `PersonalAutoData.xlsx`, but their
code names are disjoint (`Building`/`Fungi` vs. `Collision`), so nothing was masked.
Always note which path produced a given report before comparing numbers across runs.

### Report output (Data Studio's `--xlsx`)

`DataStudio --analyze ... --xlsx <path>` writes the same 15-sheet workbook the fallback
script produces (sheet names are unchanged, so a report from either path lines up
column-for-column):

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

- **Data Studio path:** no config file needed — pass the testdata directory directly as
  an argument (or via Data Studio's `--project-root` / `--testdata-dir`, same as
  `--validate`).
- **Fallback path:** `ddt-analyzer.py` uses the same project path as ddt-tools
  (`~/.centertest/ddt-tools.json`), prompting for it on first run if unset. The
  `CENTERTEST_PROJECT_DIR` environment variable overrides the saved config.

## Prerequisites

- **Preferred:** the `DataStudio` binary (self-contained, no Python required at
  runtime) on `PATH`.
- **Fallback:** Python 3 (`python3` or `python`) + the `openpyxl` package, always
  available as `${CLAUDE_PLUGIN_ROOT}/scripts/ddt-analyzer.py` — this is a maintained,
  permanent fallback for machines without Data Studio installed, not a script pending
  removal.
