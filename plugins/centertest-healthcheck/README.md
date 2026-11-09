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

If `pip install` is refused (Homebrew and other "externally managed" Pythons), create the shared
CenterTest environment once — every skill finds it automatically:

```bash
python3 -m venv ~/.centertest/venv && ~/.centertest/venv/bin/python -m pip install openpyxl javalang
```

## Features

- **20+ analysis rules** — code statistics, naming conventions, complexity, security, CenterTest compliance
- **Excel + HTML + Markdown reports** — summary sheet with one detail sheet per rule, plus a scored HTML dashboard
- **Branch review** — `--review main feature/x` lists only what the branch introduced or fixed, writes a PR comment, exits 1 on a new trust blocker, names product coverages no scenario selects any more; its rerun plan comes as one suite (`Rerun-<sha>`, changed rows only) and one command
- **Screens the suite opens** — wizards and screens per application, and the wizards no test opens
- **Product coverages the scenarios select** — per line of business, from the generated product model (`<Line>_coverage_structure.json`): which coverages a row an enabled scenario reaches names (its DataCombination row and what it references), their terms set, which options of each option term (limit, deductible) the scenarios use and every term value that is not an option in the model, those only in data rows no scenario reaches, and (Excel sheet "Product coverage") every coverage with its status
- **Which scenarios use a coverage** — `--uses "Liquor Liability Endorsement"` follows test data references to the DataCombination rows that use it and prints the tests and a suite that runs exactly them; repeat it (`--uses "Liquor Liability.*" --uses "TX|Texas"`) for the scenarios that use every value
- **Which tests touch a screen** — `--touches PolicyChangeWizard` (or `Page.getWidget`) lists the tests that reach a generated page or one widget, and a suite that runs them
- **Weekly** — `--weekly <projects...> --days 7` runs what landed in each suite through the branch review: verdict, new trust blockers, coverages lost, data rows changed, tests to rerun — one page
- **Since your last check** — every local run compares itself with the previous one (`healthcheck/last-run.json`): score, trust blockers, scenarios, coverages, findings added and fixed
- **JSON for other tools** — `--json` on any mode (health check, `--review`, `--uses`, `--touches`, `--weekly`, `--trend`, `--portfolio`) prints its result as one JSON document on stdout, progress on stderr, exit code kept; `--output json` writes the verdict, trust blockers at `path:line`, every rule's findings and the panels (`HealthCheck_*.json`, additive schema); `--review` writes its result as JSON beside the PR comment. For the CenterTest MCP server and CI to run this implementation instead of their own
- **Portfolio** — `--portfolio <projects...>` compares every client suite on one page, product coverage the scenarios select included
- **Health trend** — `--trend 6` charts score, trust blockers, test cases and product coverages selected month by month from git history
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
