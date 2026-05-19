# centertest-healthcheck

Automated health check for CenterTest Java projects. Analyzes code quality, test automation patterns, and framework compliance. Generates HTML dashboards and Excel reports with actionable findings.

## Install

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install centertest-healthcheck@centertest-skills
```

To update later: `/plugin marketplace update centertest-skills`.

See [`skills/centertest-healthcheck/SKILL.md`](skills/centertest-healthcheck/SKILL.md) for trigger phrases, rulesets, and the full skill definition.

## Prerequisites

- Python 3
- Required packages:
  ```bash
  pip install openpyxl javalang
  ```
- `git` CLI (only needed for git history analysis modes)

## Features

- **20+ analysis rules** — code statistics, naming conventions, complexity, security, CenterTest compliance
- **Excel + HTML + Markdown reports** — summary sheet with one detail sheet per rule, plus a scored HTML dashboard
- **Git history analysis** — date range, monthly sampling, PR diff, specific commits
- **Local-first** — analyzes working directory instantly, no clone needed
- **Non-destructive git** — uses `git show` instead of checkout
- **Extensible** — drop a `rule_*.py` file in `scripts/rules/` to add new rules
- **Smart exclusions** — skips generated `datadriven` package by default

## Supported apps

Works with any CenterTest project using the `src/main/java/` layout:

- PolicyCenter (PC)
- BillingCenter (BC)
- ClaimCenter (CC)
- ContactManager (AB/CM)

## Configuration

Config is stored in `~/.centertest/centertest-healthcheck.json`. Override with `EIR_*` environment variables or CLI flags (see SKILL.md for the full table).
