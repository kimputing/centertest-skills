---
name: centertest-healthcheck
description: Run a health check on CenterTest Java projects — analyze code quality, test automation patterns, and framework compliance. Generates Excel reports with configurable rules. Use when the user says "health check", "run healthcheck", "code quality report", "check CenterTest compliance", "find code smells", "analyze test classes", "code statistics", "test quality report", "CenterTest code review", or wants code metrics, naming conventions, duplicate detection, XPath usage, variable substitutions, cyclomatic complexity, or security analysis.
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
PYTHON=$(python3 --version >/dev/null 2>&1 && echo python3 || echo python)
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/centertest/project"
```

### Choose a Ruleset

```bash
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/project" --ruleset Statistics
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/project" --ruleset CenterTest
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/project" --ruleset Quality
```

### Run Specific Rules

```bash
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/project" --rules "0001,1002,3001"
```

### Git History Analysis

```bash
# Date range
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/project" --commit-from 2024-01-01 --commit-to 2024-06-30

# Monthly sampling
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/project" --monthly --commit-from 2023-01-01

# PR diff
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path "/path/to/project" --pr main feature/new-tests
```

### Configuration

```bash
# Save project path
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --set-path "/path/to/project"

# Show current path
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --show-path

# List rules and rulesets
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --list-rules
"$PYTHON" ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --list-rulesets
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
| **Quality** | 5001, 5002, 15001, 15004, 7001 | Code quality and security |
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
| 9003 | CenterTest | Test classes using DDTHelper without @DataDriven |
| 9007 | CenterTest | Thread.sleep anti-pattern detection |
| 15001 | Quality | Potential null pointer risks |
| 15004 | Quality | String comparison with == |
| 15005 | Quality | Empty catch blocks |

## Report Output

Reports are saved to `{project}/results/`:
- **Excel**: `HealthCheck_YYYYMMDD_HHMMSS.xlsx` — Summary sheet + one sheet per rule
- **Markdown**: `HealthCheck_YYYYMMDD_HHMMSS.md` — Full report in Markdown

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
