---
name: centertest-healthcheck
description: Run a health check on CenterTest Java projects — analyze code quality, test automation patterns, and framework compliance. Generates Excel reports with configurable rules. Use when the user says "health check", "run healthcheck", "code quality report", "check CenterTest compliance", "find code smells", "analyze test classes", "code statistics", "test quality report", "CenterTest code review", "review this branch", "review the PR", "what did this branch introduce", "is this branch safe to merge", "what should I rerun for this branch", "which tests does this PR affect", "which screens do we test", "which tests use this coverage", "what exercises <coverage/product/state>", "the product changed <coverage>, what do I rerun", "which tests touch this screen", "the <screen> changed, what do I rerun", "how many scenarios do we run", "compare my clients", "what landed this week", "weekly report across clients", "what changed in my suites", "all my suites", "portfolio", "what is not covered", "health trend", "is the suite getting better", "fix the silent assertions", "fix checks that cannot fail", "monthly quality report", or wants code metrics, naming conventions, duplicate detection, XPath usage, variable substitutions, cyclomatic complexity, or security analysis.
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

Analyze the current project with every rule (`CenterTestFull`, the default — the trust verdict needs
the trust rules; a smaller ruleset reports them as "not checked"):

```bash
PYTHON=$(for c in "$HOME/.centertest/venv/bin/python" "$HOME/.centertest/venv/Scripts/python.exe" python3 python; do "$c" -c "import openpyxl, javalang" >/dev/null 2>&1 && { echo "$c"; break; }; done)
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/centertest/project"
```

### Reporting to the user

The terminal summary ends with the trust blockers, the test data, the screens and the product coverages. Reply in this order:

0. **Since your last check** (when the terminal prints it): score and trust blockers before → after, and the
   findings added (trust ones first, with `path:line`) and fixed since the previous run in this project,
   and what **left the run** (a flow that no longer runs, a line no longer run in a jurisdiction) with the
   flows and jurisdictions before → after.
1. **Can these tests be trusted?** Each trust blocker group with its count and `path:line` locations —
   these are the things to fix first. Say plainly when there are none.
2. **What to fix first**: the tiers (must fix, should fix, suggestions) as counts with their top rules;
   do not list suggestions one by one.
3. **Test data and suites**: scenario runs, unread workbooks, unused codes, scenarios no suite runs.
   **What the suite exercises**: wizards no test opens, and per line of business how many of the
   product's coverages the test data names (lowest first; name the coverages a well-covered line misses),
   how many of their option terms' options (limits, deductibles) the scenarios use, and every **term value
   that is not an option in the product model** (`Coverage / Term = value (options: ...)`) — the dropdown
   offers no such value, so say which data row to correct. Then the **jurisdictions** (states or provinces)
   each line's scenarios run in, and for a line with few, the ones the suite uses on other lines but never
   on it (`not here, on other lines`) — state-specific rules and forms of that line nobody exercises.
   Then **how much of the full run each suite reaches** (flows, coverages, line/jurisdictions as a share):
   name the suite that is the real regression, a "regression" or "smoke" suite that reaches little, and
   the suites that run nothing, and what **no suite** reaches (flows, coverages, line/jurisdictions that
   run only when everything runs); offer `--cover SUITE` for what one misses.
4. **Offer the next step that fits** (and run it only when asked):
   discarded `.equals()` → `--fix 15018` (diff first); suite entries that run nothing → the
   `suite-builder` skill's `doctor`; unused codes → `ddt-tools` cleanup report; a branch to merge →
   `--review main <branch>`; a status report → `--trend 6`.
5. Point to the HTML report for the details and the Excel (its Verdict sheet) for sharing.

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
- **Suite changes**: when the branch edits `CenterTestSuiteList.json`, each changed suite's scenarios
  before → after with what it now runs or no longer runs, new entries that add nothing (the suite already
  runs them) and new entries that match no test.
- **Data changes**: every workbook the branch changed, per sheet, by Code — rows added, removed, and
  changed column by column (old → new, cut to where the cell differs). Read it like a code diff.
- **Rerun to verify**: the comment also lists the tests the branch reaches — through changed Java
  (followed per method, so a facade like `BC` only passes on the methods that use the change), changed
  DataCombination rows (with their codes) and changed reference-data codes (through the DC rows that
  use them) — and the `bootRun` commands to run them when the project's `build.gradle` forwards
  `-PcenterTest` and `-Pfilter` (a `Code=^(...)$` row filter). Offer to run them against the user's
  environment; never run them unasked.
- **Who introduced each trust blocker**: a `path:line` finding is blamed on the tip (author, date, commit); a
  line written before the range says so (something it relies on changed); a workbook row gets the range's last
  commit to that workbook. The weekly page sums them per author. Report facts, not blame.
- **Run scope**: scenarios a full run executes, merge-base → tip, with those **removed** (test or row gone)
  and **switched off** (row disabled) named — say these: they shrink the run without failing anything.
  **Flows that no longer run** (a test method that ran scenarios and runs none on the tip: every row
  switched off, or the test gone - deleted or renamed) come first: a whole flow leaves regression silently.
- **Product coverage**: when the branch changes test data and the generated product model is found
  (`--cssids` or `<project>-generated`), the coverages scenarios no longer select (say these first: a
  reviewer should confirm each was meant) and those newly selected, per line of business, and the **term
  values the branch introduces that are not an option in the product model** (a limit or deductible the
  dropdown does not offer): name each with its options, so the author corrects the row before the run.
- **Jurisdictions**: the states or provinces a line's scenarios no longer run in on the branch (say these:
  a row removed, switched off or re-addressed silently drops a state's rules from regression) and those
  newly run in.
- **All of it in one run**: from two tests up, the comment carries a suite `Rerun-<sha>` whose entries
  run exactly the plan's scenarios (a whole test, or `Class method (codeA|codeB)` for changed rows) and
  the one command to start it. Offer to add it with the `suite-builder` skill (`create Rerun-<sha>
  --entry "…"` per entry: dry run, then `--write` on approval), and to remove it after the run. To trim it
  first, save the `--json` result and open `suite.py picker --from <file>`: the plan comes pre-ticked.

### A coverage statement for the client

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --statement
```

Writes `healthcheck/Coverage_Statement_<timestamp>.html`, a one-page, client-facing summary without the code
findings: flows run in a full regression, distinct scenarios, product coverages and limit/deductible options
the scenarios select (per line), jurisdictions per line, the suites that run most of it, and known gaps
(coverages not selected, values that are not an option, flows in no suite). Use it for a client review or a
release sign-off; it needs the generated product model for coverages and jurisdictions.

### The smallest suite with the full run's breadth

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --cover
```

Picks the fewest scenarios that still run every test method once, select every product coverage the
full run selects and run every line in every jurisdiction it runs in (greedy set cover over the
scenarios a test runs; ties in name order). Prints "N of M scenarios", the first picks with what each
adds, and a suite `Cover-Breadth` with its command. Use it for a smoke or pre-release run, or after an
environment refresh. `--cover SUITE` says what an existing suite misses (test methods, coverages,
line/jurisdiction pairs, named) and the fewest scenarios to add; `--of REGRESSION` measures it against
another suite (a PolicyCenter smoke suite against the PolicyCenter regression) instead of everything
that runs. A suite's own scenarios count even when the reference suite does not contain them. `--deep`
also keeps every limit and deductible option the full run sets (a release suite; Portage: 64 instead of
61 scenarios for 34 options). Say what it does not keep: repeated scenarios of one flow with other data (without `--deep`, limits and
options too), which find data-specific defects. Offer the suite through `suite-builder` (or `picker --from`
the `--json` result to trim it), as for `--uses`.

### Everything one scenario enters

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --scenario CA_RenewalTest AZ-Phoenix
```

TEST is a test class or a DataCombination workbook (stem or path), CODE the row code (any case). Prints
whether the row runs (Disabled), the test methods that run it, the suites that include it, and the row
with every row it reaches as a tree: `#Ref`, join and `@Rel` columns lead to the referenced workbook /
sheet / code with its filled values; a row reached twice says "(shown above)"; a code with no row says
"(no such row)". It also says what **only this scenario reaches** (test methods, product coverages,
line/jurisdiction pairs no other scenario reaches) — what leaves the regression if the row is disabled
or deleted; "nothing" means it is redundant for breadth (still maybe not for its data). Use it when a scenario fails ("what did it enter?"), to explain a scenario to a client,
or before changing a shared row. Unknown code: exit 1 and the workbook's codes. `--json` for tools.

### Which scenarios use a coverage (or any data value)

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --uses "Liquor Liability Endorsement"
```

Finds every test data row whose value cell matches the pattern (whole cell, case-insensitive regex:
`"Hired Auto.*|HiredAuto"`; repeat `--uses` for the rows that use every value — "GL in Texas with Liquor
Liability" is `--uses "Liquor Liability.*" --uses "TX|Texas"`), follows references to it (`#Ref`, `#A<>#B` joins, `@Rel` — scoped as the
reference check scopes them) and prints per DC workbook the rows, the tests that run them, rows that are
disabled, which suites run how many of them (and how many no suite runs — say that first: regression never
exercises those), and a suite `Uses-<Pattern>` that runs exactly those scenarios plus its command. Use it when a
product change (a coverage, a form, a state) needs a targeted rerun. "No scenario exercises it" is an
answer too: say so and point at the product coverage panel. Offer to add the suite with the
`suite-builder` skill (`create … --entry`, dry run first).

### Which tests touch a screen (or one widget)

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --touches "PolicyChangeWizard"
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --touches "SubmissionWizardPage.getOfferingStep"
```

A regex over the generated page classes the project imports, `Page.getWidget` for one widget, or a
Guidewire widget id from the app or a log (`SubmissionWizard-…-OrganizationType`, resolved through the
generated cssids like cssid-finder does). Prints per
page the tests that reach it (the review's reach: per method, through facades, steps and fields inherited
from a base class) and a `Touches-<Pattern>` suite with its command. Use it when a Guidewire screen (PCF)
changes or an upgrade touches a wizard. Offer the suite through `suite-builder`, as for `--uses`.

### Weekly (what landed in every client suite)

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --weekly /path/to/suiteA /path/to/suiteB --days 7
```

Per suite: the mainline commit `--days` ago against HEAD through the branch review — commits landed,
verdict, new trust blockers by kind, findings added/fixed, **what the run lost** (flows that no longer
run, product coverages no scenario selects any more, jurisdictions a line no longer runs in, term values
that are not an option), data rows changed and tests to rerun; quiet suites say so. One `--cssids` goes
only to the project it was generated for; the others use their own `<project>-generated`. Reads the
projects only; page in `~/.centertest/reports/Weekly_<timestamp>.html`. Report the suites with new trust
blockers or anything lost first; offer `--review <sha> HEAD` on one suite for its full PR-style comment.

### Portfolio (every client suite on one page)

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --portfolio /path/to/client-a /path/to/client-b ...
```

Runs `CenterTestFull` on each project's working tree — read only, nothing is written into them — and
writes `~/.centertest/reports/Portfolio_<timestamp>.html`: per suite the score, trust blockers by kind,
scenarios per full run, broken data that tests run, unread workbooks, wizards opened per application,
product coverages the scenarios select (overall and the four biggest lines), jurisdictions the scenarios
run in (the widest lines), the widest suite with its share of flows and coverages and the flows no suite
runs (a client whose widest suite reaches little has no real regression suite: say so), and the last commit date. About 4 s per suite. Ask the user which projects to include.

### Health trend (for a status report)

How the suite moved month by month — health score, trust blockers, test classes and cases, flows that
run, product coverages selected and jurisdictions (with the generated product model), findings —
from the last mainline commit of each month (exported with `git archive`, same rules as a normal run):

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --ruleset CenterTestFull --trend 6
```

Writes `healthcheck/Trend_<timestamp>.html` (one chart per measure plus the table) and prints the table.
About 3 s per month. Use `CenterTestFull` so blockers are complete; the page names trust rules a smaller
ruleset left out. Lead the summary with the direction of trust blockers and test cases, then breadth
(flows, coverages, jurisdictions): a month where one drops is worth naming.

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
| **Full** | 0001-4002 (11 rules) | The original Eir core set (no trust rules) |
| **Statistics** | 0001, 1001 | General code and naming statistics |
| **PackageStatistics** | 0002 | Package-level metrics |
| **FixSet** | 1002-2002 | Code improvement suggestions |
| **XPath** | 3001 | Selenium XPath optimization |
| **Methods** | 4001, 4002 | Method-level analysis |
| **CenterTest** | 9001, 9003, 9007, 3001 | CenterTest framework compliance |
| **Quality** | 5001, 5002, 15001, 15004, 15017, 15018, 7001 | Code quality and security |
| **Security** | 7001 | Hardcoded credentials detection |
| **CenterTestFull** | Every rule | **Default.** Complete health check, trust verdict included |

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
| 9005 | CenterTest | Assertions that bypass the framework: raw JUnit `Assert`, raw AssertJ (`org.assertj`; the CenterTest `Assertions` has the same API plus DataField-aware comparisons). The CenterTest `Assertions` without `CenterTestAssertion` is a supported approach and is not reported |
| 9007 | CenterTest | Thread.sleep anti-pattern detection |
| 9011 | CenterTest | Data-driven tests whose DataCombination rows are all disabled — they run nothing (parked or forgotten) |
| 9010 | CenterTest | Tests that open screens but reach no assertion (followed per call through facades, steps, superclasses and field-held helpers); tools that open no screen are not reported |
| 14002 | CenterTest | @DataDriven datasource file existence |
| 14003 | CenterTest | DDT reference (`#`) column integrity — sheets/codes exist |
| 14005 | CenterTest | Suite entries in CenterTestSuiteList.json that match no test (CenterTest reports each as a failed scenario) and composite suites naming a missing suite |
| 14004 | CenterTest | DDT relationship (`@`) target integrity — target DC file + `Code` exist |
| 15001 | Quality | Potential null pointer risks (a loud failure with a poor message: should fix) |
| 15002 | Quality | Hardcoded `.get(N)` with no size check — in a test it fails loudly but says "Index N out of bounds" instead of what was missing; assert the size first (should fix) |
| 15004 | Quality | String comparison with == |
| 15005 | Quality | Empty catch blocks |
| 15017 | Quality | Unbounded busy-waits and recursion (no deadline / no iteration cap) |
| 15018 | Quality | Discarded .equals() return value (silent assertion bug — likely meant .assertEquals()) |

## Trust verdict

Every report opens with **"Can these tests be trusted?"**: findings that mean a test can pass while
the application is broken, or cannot run its data at all — checks that can never fail (15018),
swallowed failures (15005), tests that open screens but check nothing (9010), tests that read data they never load (9003), missing datasources (14002), suite entries that run nothing (14005), missing data codes (14003) and missing
related rows (14004). A data finding is a blocker only when a test runs it: rules 14003/14004 add a
**Runs in** column naming the classes that read the workbook (through `@DataDriven`, a `DDTHelper`
getter, the DC class, or an `@Rel` relationship from a DC they read); findings in workbooks no test
reads, or in rows marked `Disabled`, are listed as cleanup, not blockers. Any blocker caps the health
score at 59 ("At risk"). Trust rules that were not
part of the run are listed as *not checked*, never as passed — use `CenterTestFull` for a complete
verdict. When reporting results to the user, lead with these blockers.

## Test data

The dashboard's **Test data** panel gives the scenarios a full run executes (enabled DataCombination
rows of each `@DataDriven` test, times a row's `Multiplier`, plus one run per non-data-driven test),
the DC workbooks no test reads, the reference codes nothing uses (the same count as
`xlsx-cleanup-unused`), broken references split into data tests run and data no test runs ("not checked" when rules 14003/14004
were not part of the run), and the distinct scenarios no suite in `CenterTestSuiteList.json` runs.

## Screens the suite opens

The dashboard shows, per application, how many wizards (business transactions) and screens the
suite's own code opens, and lists the wizards no test opens — the gaps to plan against. It reads the
generated project's cssids — Guidewire 10's `cssids/<app>/` or Guidewire 9's `<app>.cssids` (found as
`<project>-generated` next to the project, else the cssid-finder config, else pass
`--cssids <generated src/main/resources>`). A screen counts when the suite's code builds or holds its
page object (`new X(`, `X page =`), not when its name merely appears. Screens opened only inside
framework-provided steps are not seen, so the numbers are floors; say so when quoting them.

## Fixing checks that can never fail

```bash
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --rules 15018 --fix 15018          # diff only
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/eir_analyzer.py" --path "/path/to/project" --rules 15018 --fix 15018 --write  # apply
```

Rewrites each discarded `x.equals(y);` as the assertion it was meant to be: a widget getter gets the
widget's own `assertEquals(y)`; a value gets `Assertions.assertThat(x).isEqualTo(y)` with the
framework's `Assertions` (imported, or fully qualified beside a raw AssertJ import). Show the diff, write
only after the user agrees, and tell them to compile and run the affected tests — a check that never
failed may start failing, which is the point.

## Finding locations

Every finding that names a class carries a **Location** (`src/.../X.java:42`): the flagged line when
the rule reports a snippet, else the method declaration, else the class. Quote it as `path:line` when
reporting — it is clickable in the terminal. In the HTML report locations open the file in IntelliJ
(`idea://` links). Branch reviews include them in the PR comment.

## Report Output

Reports are saved to `{project}/results/`:
- **Excel**: `HealthCheck_YYYYMMDD_HHMMSS.xlsx` — a Verdict sheet first (score, every trust blocker with its location, what to fix first, test data and suites), then the Summary sheet and one sheet per rule
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
