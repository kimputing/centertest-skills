# Calling the skills from other tools

The scripts in this repository are the current implementation of CenterTest's project checks. Other
tools — the CenterTest MCP server first, CI pipelines too — should run them instead of keeping their own
copies: clone or pull `kimputing/centertest-skills` (public) and call the scripts with `--json`. The
healthcheck, ddt-tools and cssid-finder documents carry `schema` (1 today); suite-builder and the
recording coverage print their plain result (a list or object) and recording-to-test's plan carries its
own `schemaVersion`. All changes are additive — new keys may appear, existing keys keep their meaning —
and `schema` bumps on a breaking change.

Python 3 with `openpyxl` and `javalang` (the healthcheck's Java parser). Run from anywhere; pass the
project with `--path` / `--project` / `CENTERTEST_PROJECT_DIR`. Progress goes to stderr, the JSON
document is the only thing on stdout.

| Question | Command | Exit code |
|---|---|---|
| Health check: trust verdict, findings at `path:line`, data/screens/product/jurisdiction panels | `plugins/centertest-healthcheck/scripts/eir_analyzer.py --path P --json [--cssids GEN_RESOURCES]` | 0 |
| Branch review: verdict, new/fixed findings, rerun plan and suite, run scope, coverage delta, attribution | `eir_analyzer.py --path P --review BASE [HEAD] --json` | 1 when the branch adds a trust blocker |
| Scenarios that use a data value (coverage, state, product) | `eir_analyzer.py --path P --uses "REGEX" [--uses "REGEX2" ...] --json` (rows using every value) | 0 |
| Fewest scenarios with the full run's breadth (every test method, coverage, line/jurisdiction) | `eir_analyzer.py --path P --cover [SUITE [--of SUITE2]] --json` (a suite: what it misses, what to add) | 0; 2 when a suite name is unknown |
| Everything one scenario enters (its row and every row it references, as a tree) | `eir_analyzer.py --path P --scenario TEST CODE --json` | 1 when there is no such row |
| Tests that reach a screen, widget getter or widget id | `eir_analyzer.py --path P --touches "PageRegex[.getX]" \| "Widget-Id" --json` | 0 |
| What landed in several suites | `eir_analyzer.py --weekly P1 P2 ... --days 7 --json` | 0 |
| Monthly trend | `eir_analyzer.py --path P --trend 6 --json` | 0 |
| Several suites side by side | `eir_analyzer.py --portfolio P1 P2 ... --json` | 0 |
| Broken data references | `plugins/ddt-tools/scripts/xlsx-validate-refs.py --json` (`CENTERTEST_PROJECT_DIR=P`) | 1 when any is broken |
| Unused reference codes | `plugins/ddt-tools/scripts/xlsx-cleanup-unused.py --json` | 0 |
| Cell-level workbook diff | `plugins/ddt-tools/scripts/xlsx-diff.py FILE [--ref REF] --json` or `OLD NEW --json` | 0 |
| Getter chain for a CSS id | `plugins/cssid-finder/scripts/find_getter.py APP "CSS_ID" --json` (`CENTERTEST_CSSIDS_DIR`) | 1 when nothing matches |
| Suites: list, resolve, pick, edit (dry run without `--write`) | `plugins/suite-builder/scripts/suite.py --project P --json <command> ...` | 0 |
| How much of a recording the project automates | `plugins/recording-to-test/scripts/ct.py coverage REC --cssids DIR --project P --json [--each]` | 0 |
| Recording → plan | `plugins/recording-to-test/scripts/ct.py parse REC --cssids DIR` | 0 |

Notes for callers:

- `--review`, `--weekly` and `--trend` cache each commit's analysis in `~/.centertest/cache/analysis/`,
  keyed by a hash of the scripts themselves: pulling a new version never reuses an old result.
- The healthcheck finds a project's generated cssids/product model from `--cssids`, then
  `<project>-generated` next to it, then the cssid-finder config only when it belongs to that project.
- Matching follows CenterTest itself: codes case-insensitively, Disabled values as `TRUEOPTIONS`
  (`true, t, yes, y, checked, 1`), suite entries as whole-name case-insensitive regexes, coverages by
  exact name on Guidewire 10.
