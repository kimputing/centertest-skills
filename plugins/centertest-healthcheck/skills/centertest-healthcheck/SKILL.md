---
name: centertest-healthcheck
description: Run a health check on CenterTest Java projects — analyze code quality, test automation patterns, and framework compliance. Generates Excel reports with configurable rules. Use when the user says "health check", "run healthcheck", "code quality report", "check CenterTest compliance", "find code smells", "analyze test classes", "code statistics", "test quality report", "CenterTest code review", "review this branch", "review the PR", "what did this branch introduce", "is this branch safe to merge", "health trend", "is the suite getting better", "monthly quality report", or wants code metrics, naming conventions, duplicate detection, XPath usage, variable substitutions, cyclomatic complexity, or security analysis.
---

# centertest-healthcheck

Automated health check for CenterTest Java projects. Parses Java files, applies configurable analysis rules, and generates Excel/Markdown reports with actionable findings.

## Purpose

Code quality assessment for CenterTest test automation projects. Checks framework compliance, naming conventions, code complexity, security issues, and common anti-patterns. Generates professional reports for team review.

## When to Use

- User asks to run a health check on a CenterTest project
- User wants a code quality or test statistics report
- User wants to check CenterTest framework compliance
- User wants to find code smells, duplicates, or security issues
- User says "run healthcheck" or "analyze test code"

## How to Use

### Quick Health Check (local directory)

Analyze the current project with the Full ruleset:

```bash
PYTHON=$(for c in "$HOME/.centertest/venv/bin/python" "$HOME/.centertest/venv/Scripts/python.exe" python3 python; do "$c" -c "import openpyxl, javalang" >/dev/null 2>&1 && { echo "$c"; break; }; done)
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/centertest/project"
```

### Choose a Ruleset

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --ruleset Statistics
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --ruleset CenterTest
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --ruleset Quality
```

### Run Specific Rules

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --rules "0001,1002,3001"
```

### Review a branch (what it introduced)

The question a reviewer asks of a tester's branch: what did *this branch* add or fix? The review
compares the branch tip with its merge-base (exported with `git archive`; nothing is checked out)
and lists only the findings that changed, trust blockers first:

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --ruleset CenterTestFull --review main feature/new-tests
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --ruleset CenterTestFull --review main   # HEAD vs main
```

- Writes `healthcheck/Review_<timestamp>.md`, a ready-to-paste PR comment; show it to the user.
- Verdict: **Changes requested** (introduces a trust blocker, exit 1), **Mergeable with follow-ups**
  (new non-blocking findings), **Clean**, or **Not verified** (a trust rule could not run on both sides, exit 1).
- Reviews committed state; uncommitted changes are not included. Branch names fall back to `origin/<name>`.
- Use it in a pipeline to block merges that add tests that cannot fail or data that cannot load.

### Health trend (for a status report)

How the suite moved month by month — health score, trust blockers, test classes and cases, findings —
from the last mainline commit of each month (exported with `git archive`, same rules as a normal run):

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --ruleset CenterTestFull --trend 6
```

Writes `healthcheck/Trend_<timestamp>.html` (one chart per measure plus the table) and prints the table.
About 3 s per month. Use `CenterTestFull` so blockers are complete; the page names trust rules a smaller
ruleset left out. Lead the summary with the direction of trust blockers and test cases.

### Git History Analysis

```bash
# Date range
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --commit-from 2024-01-01 --commit-to 2024-06-30

# Monthly sampling
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --monthly --commit-from 2023-01-01

# PR diff
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --pr main feature/new-tests
```

### Configuration

```bash
# Save project path
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --set-path "/path/to/project"

# Show current path
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --show-path

# List rules and rulesets
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --list-rules
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --list-rulesets
```

## Available Rule Sets

| Ruleset | Rules | Purpose |
|---------|-------|---------|
| **Full** | 0001-4002 (11 rules) | Core health check rules |
| **Statistics** | 0001, 1001 | General code and naming statistics |
| **PackageStatistics** | 0002 | Package-level metrics |
| **FixSet** | 1002-2002 | Code improvement suggestions |
| **XPath** | 3001 | Selenium XPath optimization |
| **Methods** | 4001, 4002 | Method-level analysis |
| **CenterTest** | 9001, 9003, 9007, 3001 | CenterTest framework compliance |
| **Quality** | 5001, 5002, 15001, 15004, 15017, 15018, 7001 | Code quality and security |
| **Security** | 7001 | Hardcoded credentials detection |
| **CenterTestFull** | All 20 rules | Complete health check |

## Individual Rules

| Rule | Category | Description |
|------|----------|-------------|
| 0001 | Statistics | General test statistics per commit |
| 0002 | Statistics | General test statistics by package |
| 1001 | ClassNames | Test class naming convention statistics |
| 1002 | ClassNames | Test classes with names > 120 chars |
| 1003 | ClassNames | Test classes with package name in class name |
| 1004 | ClassNames | Possible new packages within existing package |
| 2001 | Inheritance | Method duplicates in child classes |
| 2002 | Inheritance | Inner class duplicates |
| 3001 | Selenium | Find elements by long XPaths |
| 4001 | Methods | Find possible variable substitutions |
| 4002 | Methods | Find duplicate table row selections |
| 5001 | Complexity | Methods with high cyclomatic complexity |
| 5002 | Complexity | Methods exceeding recommended length |
| 7001 | Security | Potential hardcoded credentials |
| 9001 | CenterTest | Direct Selenium usage instead of widgets |
| 9003 | CenterTest | Test reads the scenario's data row (`DDTHelper.getX(scenarioContext)`) without @DataDriven — loading by code is fine |
| 9007 | CenterTest | Thread.sleep anti-pattern detection |
| 14002 | CenterTest | @DataDriven datasource file existence |
| 14003 | CenterTest | DDT reference (`#`) column integrity — sheets/codes exist |
| 14004 | CenterTest | DDT relationship (`@`) target integrity — target DC file + `Code` exist |
| 15001 | Quality | Potential null pointer risks |
| 15004 | Quality | String comparison with == |
| 15005 | Quality | Empty catch blocks |
| 15017 | Quality | Unbounded busy-waits and recursion (no deadline / no iteration cap) |
| 15018 | Quality | Discarded .equals() return value (silent assertion bug — likely meant .assertEquals()) |

## Trust verdict

Every report opens with **"Can these tests be trusted?"**: findings that mean a test can pass while
the application is broken, or cannot run its data at all — checks that can never fail (15018),
swallowed failures (15005), tests that read data they never load (9003), missing datasources (14002), missing data codes (14003) and missing
related rows (14004). A data finding is a blocker only when a test runs it: rules 14003/14004 add a
**Runs in** column naming the classes that read the workbook (through `@DataDriven`, a `DDTHelper`
getter, the DC class, or an `@Rel` relationship from a DC they read); findings in workbooks no test
reads, or in rows marked `Disabled`, are listed as cleanup, not blockers. Any blocker caps the health
score at 59 ("At risk"). Trust rules that were not
part of the run are listed as *not checked*, never as passed — use `CenterTestFull` for a complete
verdict. When reporting results to the user, lead with these blockers.

## Finding locations

Every finding that names a class carries a **Location** (`src/.../X.java:42`): the flagged line when
the rule reports a snippet, else the method declaration, else the class. Quote it as `path:line` when
reporting — it is clickable in the terminal. In the HTML report locations open the file in IntelliJ
(`idea://` links). Branch reviews include them in the PR comment.

## Report Output

Reports are saved to `{project}/results/`:
- **Excel**: `HealthCheck_YYYYMMDD_HHMMSS.xlsx` — Summary sheet + one sheet per rule
- **Markdown**: `HealthCheck_YYYYMMDD_HHMMSS.md` — Full report in Markdown

## Python with the packages

Each command above picks the first interpreter that can import the packages: the private
CenterTest environment `~/.centertest/venv` first, then `python3`, then `python`. If `$PYTHON` comes
out empty, none has them — a plain `pip install` is refused by Homebrew and other
"externally managed" Pythons, so ask the user before creating the private environment once:

```bash
python3 -m venv "$HOME/.centertest/venv" && "$HOME/.centertest/venv/bin/python" -m pip install openpyxl javalang
# Windows (Git Bash): python -m venv "$HOME/.centertest/venv" && "$HOME/.centertest/venv/Scripts/python.exe" -m pip install openpyxl javalang
```

Every CenterTest skill finds it there afterwards.

## Prerequisites

- Python 3
- `pip install openpyxl javalang`
- `git` CLI in PATH (for git history analysis modes)

## Configuration

Config stored in `~/.centertest/centertest-healthcheck.json`. Override with environment variables (`EIR_*`) or CLI flags.

| Config Key | Env Var | CLI Flag | Default |
|------------|---------|----------|---------|
| repository_dir | EIR_REPOSITORY_DIR | --path | cwd |
| default_ruleset | EIR_REPORT_RULESET | --ruleset | Full |
| source_root | EIR_SOURCE_ROOT | --source-root | src/main/java |
| thresholds.4001 | EIR_RULE_4001_THRESHOLD | — | 2 |
| thresholds.5001 | EIR_RULE_5001_THRESHOLD | — | 10 |
| thresholds.5002 | EIR_RULE_5002_THRESHOLD | — | 50 |

## Default Exclusions

The `datadriven` package is excluded by default since it contains generated code. Override with `--exclude-package` or config.
