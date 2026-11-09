# CenterTest Skills — Claude Code plugin marketplace

A Claude Code plugin marketplace distributing skills for CenterTest test automation development.

**GitHub**: `https://github.com/Kimputing/centertest-skills`

## Plugins

Six plugins, each installable on its own. You ask Claude Code in plain language; the matching skill runs.

| Plugin | In one line |
|--------|-------------|
| [centertest-healthcheck](plugins/centertest-healthcheck/) | Can these tests be trusted, what does the regression cover, and what does a branch introduce or drop |
| [suite-builder](plugins/suite-builder/) | Build and edit suites in `CenterTestSuiteList.json`, resolved exactly as CenterTest resolves them |
| [recording-to-test](plugins/recording-to-test/) | Turn a Recorder recording (or a request, story, Jira issue) into a test in the project's own structure |
| [ddt-tools](plugins/ddt-tools/) | Day-to-day test-data checks: broken references, cell-level diffs, unused codes |
| [ddt-analyzer](plugins/ddt-analyzer/) | The whole data-driven structure in one Excel report |
| [cssid-finder](plugins/cssid-finder/) | The Java getter chain for a Guidewire widget, from its CSS id or the words on screen |

## What the skills deliver

### centertest-healthcheck

**Can these tests be trusted?**
- A trust verdict first: checks that can never fail (a discarded `.equals()`), swallowed failures, tests that check nothing, data that cannot load, suite entries that run nothing — each at `path:line`, and the score capped at "At risk" until they are fixed
- What to fix first (must / should / suggestions), every finding at `path:line` with an IntelliJ link; `--fix 15018` rewrites the checks that can never fail
- Since your last check: score, blockers, scenarios, coverages, flows and jurisdictions before → after, and what left the run

**What does the regression cover?** (dashboard, Excel and JSON)
- Flows that run, scenario runs per full run, and what the regression covers at the top of the dashboard
- Product coverages the scenarios select, per line, from the generated product model — with the tests that select each
- Limit and deductible options the scenarios set, and data values that are not an option in the product
- The states or provinces each line's scenarios run in, and those the suite uses elsewhere but never on that line
- Screens and wizards the suite opens; test data at a glance (scenarios, unread workbooks, unused codes)
- How much of the full run each suite reaches (flows, coverages, jurisdictions) and what no suite reaches

**Questions about one value, screen or scenario**
- `--uses "Liquor Liability"` (repeat for "and"): the scenarios that use a coverage, state or any data value, as a suite
- `--touches PolicyInfoStep` or a widget id: the tests that reach a screen or one widget, as a suite
- `--scenario CA_RenewalTest AZ-Phoenix`: everything one scenario enters, as a tree, and what only it reaches

**Suites and releases**
- `--cover`: the smallest suite that keeps every flow, coverage and jurisdiction (`--deep`: every limit option too)
- `--cover Smoke [--of Regression]`: what a suite misses, and the fewest scenarios to add
- `--plan release.txt`: one rerun suite for a release's change list (coverages, values, screens, widgets)
- `--model-diff OLD [NEW]`: what a regenerated product model breaks — removed or renamed coverages and options, the scenarios that use them

**Branches, history and clients**
- `--review main feature/x`: a PR comment with a verdict, what the run loses (flows, coverages, options, jurisdictions), new trust blockers and who introduced them, data changes row by row, run scope, and one rerun suite
- `--trend 6`: score, blockers, tests, flows, coverages and jurisdictions month by month
- `--weekly`: what landed in every client suite, and what each run lost
- `--portfolio`: every client suite on one page
- `--statement`: a one-page coverage statement for a client, without code findings

### suite-builder
- List, show and resolve suites as CenterTest does (whole-name, case-insensitive regexes; nested suites)
- Create, add to, remove from, delete and rename suites — a dry run first, `--write` to apply, nothing else rewritten
- Pick tests by class, method, row code, description or row data (`--data "State=TX"`)
- An HTML picker to tick classes, methods and rows; it opens a suggested selection (`--from` a review, `--uses`, `--touches` or `--cover` result)
- Doctor: entries that run nothing, and a one-step fix

### recording-to-test
- A scenario wizard: from a Recorder recording, a request, a story, a Jira issue or an existing test to a test in the project's own layout, reusing its facades, steps and data
- Recorded checks become widget assertions; analyst notes become comments; a table of files to write before anything is written
- `ct.py coverage`: how much of a recorded flow the automation already performs (`--each` over a folder of recordings)

### ddt-tools
- Validate DataCombination references (relationship hops, scopes, overrides, case-insensitive as CenterTest reads them)
- A cell-level diff of a workbook against a git ref
- Codes nothing uses, and hardcoded codes in Java that do not exist
- `--json` on each, for CI and the MCP server

### ddt-analyzer
- A 28-sheet Excel report (17 without Data Studio): which tests use which data, code usage, orphaned and broken files, hierarchy checks, impact of changing a workbook

### cssid-finder
- The getter chain for a CSS id copied from the Guidewire UI (iterator and table rows included)
- `--words "effective date" --page PolicyInfo`: widgets by the words on screen
- `--json` for tools

Other tools (the CenterTest MCP server, CI) can run these implementations directly: every check has a `--json` mode — see [INTEGRATION.md](INTEGRATION.md).

## Installation

Inside Claude Code, add the marketplace and install the plugins you want:

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install centertest-healthcheck@centertest-skills
/plugin install cssid-finder@centertest-skills
/plugin install ddt-analyzer@centertest-skills
/plugin install ddt-tools@centertest-skills
/plugin install recording-to-test@centertest-skills
/plugin install suite-builder@centertest-skills
```

Each plugin is independent — install only the ones you need.

The healthcheck and DDT plugins need `openpyxl` (and `javalang` for the healthcheck). Where `pip install` is refused (Homebrew and other "externally managed" Pythons), create the shared environment once and every skill uses it:

```bash
python3 -m venv ~/.centertest/venv && ~/.centertest/venv/bin/python -m pip install openpyxl javalang
```

## Updating

```text
/plugin marketplace update centertest-skills
```

Every commit to `main` becomes a new version automatically (no `version` field is pinned in `plugin.json`).

## Structure

```
centertest-skills/                                  # marketplace repo
├── .claude-plugin/
│   └── marketplace.json                            # catalog of plugins
├── plugins/
│   └── <plugin-name>/
│       ├── .claude-plugin/plugin.json              # plugin manifest
│       ├── skills/<plugin-name>/SKILL.md           # skill definition
│       ├── scripts/                                # python scripts (resolved via ${CLAUDE_PLUGIN_ROOT})
│       ├── README.md                               # public docs
│       └── CLAUDE.md                               # dev context for Claude Code
└── README.md                                       # this file
```

## Contributing a new plugin

1. Create `plugins/<plugin-name>/` with `.claude-plugin/plugin.json`, `skills/<plugin-name>/SKILL.md`, and `scripts/`
2. In `SKILL.md`, reference scripts via `${CLAUDE_PLUGIN_ROOT}/scripts/<file>.py` so the path resolves to the plugin's install location
3. Add a new entry to `.claude-plugin/marketplace.json` under `plugins`
4. Update the table above
5. Run `claude plugin validate .` from the repo root to catch JSON / frontmatter errors

See the [Claude Code plugin marketplace docs](https://code.claude.com/docs/en/plugin-marketplaces) for the full schema.
