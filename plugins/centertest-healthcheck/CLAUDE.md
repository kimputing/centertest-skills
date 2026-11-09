# CLAUDE.md — centertest-healthcheck

## Architecture

```
scripts/
├── eir_analyzer.py      # CLI entry point, argparse, orchestration
├── eir_config.py        # Hierarchical config (CLI > env > ~/.centertest/centertest-healthcheck.json > defaults)
├── eir_parser.py        # Java parser: javalang + source-position slicing for method bodies
├── eir_git.py           # Non-destructive git (git show/ls-tree, no checkout)
├── eir_models.py        # Dataclasses: SourceCodeFile, ClassEntry, Method, Field, CommitInfo, RuleResult
├── eir_report.py        # HTML dashboard + Excel appendix + Markdown + terminal output
├── eir_portfolio.py     # --portfolio: several projects, read only, one comparison page in ~/.centertest/reports/
├── eir_trend.py         # --trend: month-end mainline commits via git archive -> score/blockers/tests chart page
├── eir_locate.py        # Adds Location (path:line) to rows with a Class column; HTML renders idea:// links
├── eir_fix.py           # --fix 15018: discarded .equals() -> widget assertEquals / Assertions.assertThat (same rule as the MCP fixer)
├── eir_impact.py        # Rerun plan for --review: per-method Java reach, changed DC rows, changed reference codes; rerun_suite() = the plan as suite entries (vendored suite.compact)
├── eir_data.py          # Test data panel: scenarios per full run, unread DCs, unused codes (= xlsx-cleanup-unused), broken refs live/dormant
├── eir_screens.py       # Screens/wizards the suite's own code opens (generated cssids/ -> page classes)
├── eir_products.py      # Product coverages (generated <Line>_coverage_structure.json) named in enabled testdata rows
├── eir_reach.py         # Forward reach from a test (per call: Facade.method, new Step, typed fields, superclasses); assertion vocabulary; rule 9010
├── eir_review.py        # --review: merge-base vs branch tip via git archive, findings diff, PR comment
├── eir_rules.py         # @rule decorator registry, auto-discovery, periodic vs snapshot execution
├── rule_core.py         # Shared utilities: get_test_list, divide_by_package, split_camel_case
└── rules/
    ├── __init__.py      # Auto-imports rule_*.py via pkgutil
    ├── rule_statistics.py   # 0001, 0002 (periodic=True)
    ├── rule_classnames.py   # 1001-1004 (1001 periodic=True)
    ├── rule_inheritance.py  # 2001, 2002
    ├── rule_selenium.py     # 3001
    ├── rule_methods.py      # 4001, 4002
    ├── rule_complexity.py   # 5001, 5002
    ├── rule_security.py     # 7001
    ├── rule_centertest.py   # 9001, 9003, 9005, 9007, 9008, 9010
    ├── rule_quality.py      # 15001, 15002, 15004, 15005, 15006, 15016, 15017, 15018
    ├── rule_suites.py       # 14005 via the vendored suite.py (suite-builder)
    └── rule_ddt.py          # 14002, 14003, 14004 (14003/14004 via the vendored ddt_refcheck.py)
```

## Adding a New Rule

1. Create or edit a `rules/rule_*.py` file
2. Decorate with `@rule(id="XXXX", description="...", category="...", periodic=False)`
3. Function signature: `def my_rule(commits: CommitsDict, config) -> RuleResult`
4. Add rule ID to rulesets in `eir_config.py` (`DEFAULT_RULESETS`)
5. That's it — `rules/__init__.py` auto-discovers it

**periodic=True**: rule gets all commits in monthly mode (for trend data like stats)
**periodic=False** (default): rule gets only the latest commit (avoids duplicate findings)

## Key Design Decisions

- **`@dataclass(eq=False)`** on Method, ClassEntry, Field — custom equality for rules 2001/2002 (structural comparison). Breaking this silently produces wrong results.
- **Package from directory path**, not `package` statement — matches original Eir behavior
- **`.*datadriven.*`** excluded by default — generated code, not actionable
- **Method body extraction** via brace-balanced source-position slicing from javalang's `position.line` — javalang doesn't store method body text
- **Runs in** (rule_ddt `_workbook_users`): a workbook's readers are non-generated classes with its `@DataDriven` path, a `DDTHelper` getter whose body names it, or its DC class name; DCs reached by `@Rel` columns inherit them. Findings in unread workbooks or `Disabled` rows are dormant (`eir_report.is_dormant`): listed, never blockers, and `--review` does not count them.
- **Location** is added after the rules run (local mode and `--review`), not by each rule: a new rule with `Class`/`Method` (and optionally `Line`/`Snippet` code) columns gets it for free. `--review` ignores it when matching findings.
- **Severity** is per category (`_SEVERITY`) with per-rule overrides (`_RULE_SEVERITY`: 15001/15002 medium — a loud failure with an unhelpful message, 15006 low — clutter); `severity_of()` feeds both the score and the fix order.
- **`health_score()`** in `eir_report.py` is the only score formula; the dashboard and `--trend` both call it.
- **Trust blockers** (`TRUST_RULES` in `eir_report.py`: 15018, 15005, 14002-14005, 9003, 9010) are listed first in HTML, Markdown and terminal and cap the score at `TRUST_SCORE_CAP` (59). Only add a rule there when a finding means a test can pass while the app is broken, or cannot run.
- **Score calculation** uses severity weights (Security/Quality=3x, CenterTest=2x, ClassNames=1x) with proportional penalty (few findings in big project = partial credit)

## Running

```bash
# Full healthcheck (CenterTestFull, every rule, is the default ruleset: the trust verdict needs the trust rules)
python3 scripts/eir_analyzer.py --path /path/to/project

# Single rule
python3 scripts/eir_analyzer.py --path /path/to/project --rules "15002"

# Monthly trend (full history, no dates needed)
python3 scripts/eir_analyzer.py --path /path/to/project --monthly

# List rules
python3 scripts/eir_analyzer.py --list-rules
```

Output goes to `{project}/healthcheck/` — HTML (primary) + Excel (appendix).

## Rule ID Ranges

| Range | Category | Examples |
|-------|----------|---------|
| 0001-0002 | Statistics | Test counts, LOC, median |
| 1001-1004 | ClassNames | Naming conventions |
| 2001-2002 | Inheritance | Method/inner class duplicates |
| 3001 | Selenium | XPath detection |
| 4001-4002 | Methods | Variable substitution, row selection |
| 5001-5002 | Complexity | Cyclomatic complexity, method length |
| 7001 | Security | Hardcoded credentials |
| 9001-9008 | CenterTest | Widget compliance, assertions, sleep |
| 14002-14003 | DDT | Datasource existence, reference integrity |
| 15001-15018 | Quality | NPE, IndexOOB, catch, unused vars, logging, unbounded loops/recursion, discarded .equals() |

## Gotchas

- `--review` keys findings without position columns (`Row`) and with digits in grouped items replaced by `#`, so a moved row or a count going from 2x to 3x is not "new". Rules that error on either side are listed as not compared; an uncompared trust rule makes the verdict "Not verified" (exit 1).
- `eir_analyzer.py` name is historical — the skill is centertest-healthcheck
- Rule 9005 checks method-level `@DataDriven` (not just class-level)
- Rules 9001, 9003, 9005, 9007 and 9008 scan the main class **and its inner classes** (tests often keep flow steps there). Inner-class findings are labelled `Outer.Inner`. The parser only collects direct inner classes, so a class nested inside an inner class is still not scanned.
- Rule 1001 has `suffix_exceptions` set for `CheckEnvironmentAvailability`
- Rule 15001 is very targeted — only Gson JSON patterns, not page object chains
- Rule 15017 only inspects `while` loops and direct self-recursion. `for`, foreach, and `do/while` are out of scope by design to avoid false positives. The loop is exempt if the body contains `break`, `return`, `throw`, a `System.currentTimeMillis`/`Instant.now`/`nanoTime` deadline, or a counter mutation (`++`/`--`/`+=`/`-=`). Recursion is exempt if the body contains any of `max|attempt|depth|limit|count|tries|retries|retry`, or every self-call passes a literal `false` (a flag switched off). String literals are stripped first; a loop whose condition has a counter or reads until `null`/`-1` (`while ((x = next()) != null)`) is exempt too.
- Rule 15018 flags `expr.equals(args);` (and `.equalsIgnoreCase`, `.contentEquals`) only when the call is the outermost expression of a standalone statement — i.e., the line ends `);` immediately after the matched closing paren. Skipped when the line starts with control keywords (`if`, `while`, `return`, `assert`, `throw`, `for`, `else`, `case`), when an `=`/`&&`/`||`/`!`/`?` appears before `.equals(`, or when the call is nested (a `)` precedes the trailing `;`).
- `scripts/ddt_refcheck.py` and `scripts/ddt_reference_scope.py` are vendored copies of the ddt-tools files: never edit them here. 14003 + 14004 together equal what `xlsx-validate-refs.py` reports.
- HTML report score uses weighted formula, not simple pass/fail count
