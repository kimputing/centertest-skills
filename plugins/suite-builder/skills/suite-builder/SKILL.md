---
name: suite-builder
description: Build and edit CenterTest test suites in CenterTestSuiteList.json — create a suite, add or remove tests, methods or DataCombination (DDT) rows, delete or rename suites, see what a suite really runs and which entries match nothing. Use when the user says "create a suite", "build a suite", "add these tests to the smoke suite", "remove the Texas rows from Regression", "delete the suite", "what does the Sanity suite run", "which suites are broken", "let me pick the tests", "open the suite picker", "suite for all WC submissions", or works with CenterTestSuiteList.json.
---

# suite-builder

Suites live in the project's `CenterTestSuiteList.json` (usually `src/main/resources/`). An entry in a
suite's `List` is `<class> [<method> [<code>]]`, and CenterTest reads **each part as a
case-insensitive regular expression matched against the whole name** — so `PA_SubmissionTest run tx_.*`
runs every `tx_…` row. A suite can also have `Packages` (package regexes) and `Suites` (other suites by
name). An entry that matches nothing is reported by CenterTest as a failed scenario.

The engine reads that file and the project's tests the same way: test classes (`@CenterTest`), their
`@CenterTestCase` methods, and the codes of each method's `@DataDriven` DataCombination workbook
(disabled rows excluded unless asked). It needs Python only — no packages.

```bash
PYTHON=$(python3 --version >/dev/null 2>&1 && echo python3 || echo python)
"$PYTHON" "${CLAUDE_PLUGIN_ROOT}/scripts/suite.py" --project "<project>" <command> ...
```

Run it from the project or pass `--project`. `--suites <file>` points at another suite file.

## Commands

| Command | Does |
|---|---|
| `list` | every suite, its kind (List / Packages / Suites), the scenarios it runs, entries that match nothing |
| `show NAME` | the suite as written, every scenario it runs, entries that match nothing, missing child suites |
| `scan` | test classes → methods → row counts (`--json` for the full tree with codes and descriptions) |
| `pick [selectors]` | the scenarios a selection matches and the entries it would become — writes nothing |
| `create NAME [selectors]` | a new List suite |
| `add NAME [selectors]` | append entries for what the suite does not run yet |
| `remove NAME [selectors]` | take the selection out (an entry partly inside is rewritten to what it keeps) |
| `delete NAME` | delete the suite (warns when a composite suite names it) |
| `rename OLD NEW` | rename; composite suites that name it follow |
| `set NAME --entries-file F` | replace the List with the lines of F (`-` = stdin) |
| `picker [--suite NAME] [--open]` | a page to tick classes, methods and rows, showing the suite before → after; it produces the `suite.py` command that applies the change |

**Selectors** — case-insensitive regexes, *searched* in the name, all must match: `--class`, `--method`,
`--code`, `--desc` (the row's Description), `--package`. Or `--entry "Class method code"`, read exactly as
CenterTest reads an entry (repeatable). `--include-disabled` also selects rows marked Disabled.

`create`, `add`, `remove`, `delete`, `rename` and `set` **print the change and write nothing** unless
`--write` is given. Writing keeps the file's indentation and line endings. Entries the tool did not
touch stay exactly as written (patterns stay patterns). Entries it writes are compact: `Class` for a
whole class, `Class method` for a whole method, `Class method (a|b)` for some rows (codes escaped so
they match only themselves).

## Picking visually

When the user wants to browse and tick rather than describe, run
`suite.py --project <project> picker --suite <NAME> --open` (omit `--suite` for a new one). The page lists
package → class → method → DataCombination rows with checkboxes and a filter; the right side shows the
scenarios the suite runs before → after and its entries marked + / −. **Copy command for Claude** copies the
`suite.py set` (or `create`) command; when the user pastes it, run it **without** `--write` first, show the
diff, then run it with `--write` after they confirm. The page is written to
`~/.centertest/reports/suite-picker_<project>.html`; re-run `picker` after the suites change.

## How to work with the user

1. **Start with `list`** (and `show NAME` for the suite in question) so the user sees what exists and
   what each suite really runs. Point out entries that match nothing — CenterTest fails on them — and,
   for a code that no longer exists, offer the closest codes from `scan --json`.
2. **Turn the user's words into selectors** ("all workers comp submissions in Texas" →
   `--class "WC_.*Submission" --code "TX|Texas"` or `--desc Texas`), run **`pick`** and show the
   scenarios. Adjust until the user agrees. For many separate picks, collect `--entry` lines.
3. **Dry run** the edit (`create` / `add` / `remove` …) and show the printed diff: entries added and
   removed, and scenarios before → after.
4. **Write only after the user approves** (`--write`). For `delete`, always ask first and mention any
   composite suite that names it. Never edit `CenterTestSuiteList.json` by hand when the engine can
   do it.
5. To run a suite, give the command and do not run it unasked: set `CENTERTESTFILTERCENTERTESTSUITE=<suite>`
   (or `-PsuiteFilter=<suite>` when the project's `build.gradle` forwards it) before `./gradlew bootRun`.

## Notes

- A selection is matched against runnable scenarios: a method without data is one scenario (code `""`);
  a data-driven method has one per enabled row.
- `Packages` and `Suites` parts of a suite are kept as they are; `add`/`remove` change only `List`.
- A test class name that exists in two packages matches in both, as it does in CenterTest.
