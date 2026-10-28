# CLAUDE.md — recording-to-test

## What It Does

Recorder recording → CenterTest test in the target project's structure. Design:
`docs/superpowers/specs/2026-10-06-recording-to-test-design.md` (repo root).

## Architecture

- `scripts/parse_recording.py` — `session.json` → plan JSON: getter per widget, Java fragment per
  action/check, `review` list, `retries`, framework `imports`.
- `scripts/scan_project.py` — project → facts (package, layout, roles, step bases and their
  `@FlowTags`, facades, exemplars, tests and steps per folder, `Abstract*` bases and which methods
  read each constructor arg, screen helpers by title/page, the project's CLAUDE.md/AGENTS.md files,
  cssids source, build commands). Read-only.
- `scripts/find_getter.py` — **vendored, byte-identical** copy of `plugins/cssid-finder/scripts/find_getter.py`.
  Never edit it here; change cssid-finder, then `cp` it over. `tests/test_vendored_sync.py` fails when they differ.
- `skills/recording-to-test/SKILL.md` — the judgment steps (segments, facade matches, names,
  confirmation gate, generation, compile).

## Tests

    python3 -m unittest discover -s plugins/recording-to-test/tests -v

There is no CI in this repo; run them before every commit.

## Gotchas

- A step's `actions` led **to** that step's screen; its checks verify that screen. Segment by the
  widget's page, not by `step.screen`.
- About a third of real widget ids are not in cssids (wizard buttons, tab bar, list-row columns,
  coverage terms in iterators). `resolve_fallback()` builds them in the project's idioms; the
  `raw` rule writes `Widget<Type>.get(id, getContext())`.
- Coverage widgets (`…CoverageInputSet-CovPatternInputGroup…`) never reach `resolve()`: the
  `coverage` rule in `translate()` turns them into `coverageUtil.setSelected/setCoverage/assert…`
  from the recorded `label` (term) and `context[-1]` (coverage). This is a team rule: all coverage
  work goes through `CoverageUtil`. Only an item with no coverage title or no `CoverageUtil` call is reviewed.
- A date picked from the calendar fires no `change` event: the recorder logs only clicks on the
  field and its `<id>_dateIcon`. The value is in the step's posted form (`requests[].fields`).
  `with_picked_dates()` turns the first such click into that change (`source: "request"`, reviewed)
  and folds the field's other calendar clicks into it. `postedDates` holds the other dates in the same
  post, e.g. the policy period's `PolicyPeriodEffDateID_Arg`.
- Recorded booleans come only from checkboxes. `WidgetCheckBoxInput` has only `set(String)`, so
  they are written `.set("true")`. A row cell's live id ends in `_Cell`; its generated getter doesn't.
- The run command comes from the `-P` properties the `bootRun` block reads (`-Pprofile`,
  `-PcenterTest`). With no `centerTest` there it is `null` and the skill asks; the
  `--spring.profiles.active` form is used only for a `bootRun` that reads no properties.
- `find_getter()` prints and exits — call the module's lookup functions, not it.
- OOTB writes `@FlowTags` in two forms (`("…")` and `({"…"})`); the scan reports the annotation as written.
- cssids from the generated jar (`cssids/` in GW10, `<app>.cssids` at the root in GW9) are extracted
  once per jar into `<system temp>/recording-to-test-cssids/<hash>` and reused.
- The generator writes a conditional toolbar segment into the getter itself:
  `….get[DriverLV_tb]AddDriver()`. `unbracket()` rewrites it to `getAddDriver()` and, when that call
  ends the chain, adds `.withCssId("<live id>")`. Every lookup result goes through it.
- A menu item reached through its button (`<button getter>.get("Label")`, rule `menuItem`) opens the
  menu itself, so the click that opened it is dropped (`fold_menu_openers`). A raw
  `WidgetMenuItem.get(id)` only moves to its element, so its opener stays.
- A form input's `name` is its widget id in Guidewire, so it's never used as a label. A list cell
  with no label gets its column header from the step's DOM snapshot (`dom/NNNN.html`, read via
  `file_reader()`).
- `retries()` runs on the finished plan: `corrected` (same widget, new value at a later step) and
  `validationLoop` (Clear / Edit Policy Transaction after errors, the fixes, and the resume click).
- `scan_project.py` reads Java with regexes (`methods_of()` matches brace-balanced bodies of methods
  with an access modifier). Package-private methods are not indexed in `screenHelpers` /
  `transactionBases`.
- Fixture recordings under `tests/fixtures/recordings/real-*` are trimmed copies of real
  recordings; check new ones for sensitive data before committing.
