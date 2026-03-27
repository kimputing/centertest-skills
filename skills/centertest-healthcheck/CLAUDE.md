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
    ├── rule_centertest.py   # 9001, 9003, 9005, 9007, 9008
    ├── rule_quality.py      # 15001, 15002, 15004, 15005, 15006, 15016
    └── rule_ddt.py          # 14002, 14003
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
- **Score calculation** uses severity weights (Security/Quality=3x, CenterTest=2x, ClassNames=1x) with proportional penalty (few findings in big project = partial credit)

## Running

```bash
# Full healthcheck
python3 scripts/eir_analyzer.py --path /path/to/project --ruleset CenterTestFull

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
| 15001-15016 | Quality | NPE, IndexOOB, catch, unused vars, logging |

## Gotchas

- `eir_analyzer.py` name is historical — the skill is centertest-healthcheck
- Rule 9005 checks method-level `@DataDriven` (not just class-level)
- Rule 1001 has `suffix_exceptions` set for `CheckEnvironmentAvailability`
- Rule 15001 is very targeted — only Gson JSON patterns, not page object chains
- HTML report score uses weighted formula, not simple pass/fail count
