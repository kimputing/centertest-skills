# centertest-healthcheck

Automated health check for CenterTest Java projects. Analyzes code quality, test automation patterns, and framework compliance. Generates Excel reports with actionable findings.

## Latest Version

[View on GitHub](https://github.com/Kimputing/centertest-skills/tree/main/skills/centertest-healthcheck)

## Update

```bash
cd ~/.claude/skills/centertest-healthcheck && git pull
```

## Prerequisites

- Python 3
- Required packages:
  ```bash
  pip install openpyxl javalang
  ```
- `git` CLI (only needed for git history analysis modes)

## Quick Start

```bash
# Run health check on a CenterTest project
python3 ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path /path/to/project

# List available rules
python3 ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --list-rules

# Run CenterTest compliance check
python3 ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --path /path/to/project --ruleset CenterTest
```

## Features

- **20 analysis rules** — code statistics, naming conventions, complexity, security, CenterTest compliance
- **Excel + Markdown reports** — Summary sheet with one detail sheet per rule
- **Git history analysis** — Date range, monthly sampling, PR diff, specific commits
- **Local-first** — Analyzes working directory instantly, no clone needed
- **Non-destructive git** — Uses `git show` instead of checkout
- **Extensible** — Drop a `rule_*.py` file to add new rules
- **Smart exclusions** — Skips generated `datadriven` package by default

## Supported Apps

Works with any CenterTest project using `src/main/java/` layout:
- PolicyCenter (PC)
- BillingCenter (BC)
- ClaimCenter (CC)
- ContactManager (AB/CM)

## Configuration

Save your project path for quick access:

```bash
python3 ~/.claude/skills/centertest-healthcheck/scripts/eir_analyzer.py --set-path /path/to/project
```

Config stored in `~/.centertest/centertest-healthcheck.json`.
