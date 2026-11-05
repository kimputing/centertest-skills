# recording-to-test

A wizard that creates a CenterTest scenario in the shape the current project already uses, reusing
existing tests, data rows and facades before writing anything new. The input can be a CenterTest
Recorder recording (the `.zip` an analyst sends, its folder, or its `session.json`), several
recordings for one scenario, a plain-English request or user story, a Jira issue, or an existing
test (a new scenario next to it, a data row, or restart points). The result follows the project's own
structure: the test class in its `tests/<center>/<lob>/<txn>/` layout, the project's login facade,
new reusable step classes for the recorded screens, data rows, and the recorded checks as widget
assertions.

## Prerequisites

- Python 3 (no packages needed). CI tests on Python 3.14; older versions down to 3.9 may still work
  but aren't tested.
- A CenterTest project whose generated page objects are available: the `*-generated` dependency in
  the Gradle/Maven cache (it bundles `cssids/`), or a `*-generated` checkout next to the project.
- Optional, for recordings with voice narration: `ffmpeg`, `whisper.cpp` (`whisper-cli`) and a ggml
  model, set as `whisperModel` in `~/.centertest/recording-to-test.json`. Audio never leaves the
  machine. `ct.py tools` shows what is installed. Without them, narration is skipped, or use the
  transcript file the Recorder wrote next to the audio.
- Optional, for writing data rows: `openpyxl` (the default `workbookWriter`), or Excel / manual edits.
- Optional helper skills from this marketplace: `cssid-finder`, `ddt-tools`, `ddt-analyzer`,
  `centertest-healthcheck`.

## Use

In the project directory: "create a test from ~/Downloads/2026-10-01_174907_test1.zip", "add a test
for this story", "turn this Jira issue into a test", "make this test resumable" or "add a data row
for a scenario". The skill shows what it found and plans at the end of each phase and waits for your
approval before writing files. "Just run it" takes the recommended option at every gate, except for
the questions it never skips (start state, missing data, a row in an existing workbook, running
against an environment, git).

## Phases

| Phase | Result |
|---|---|
| Understand | inputs read, center / LOB / transaction, start state, narration, missing facts, profile problems |
| Reuse plan | existing test, data row, override column or step override found before any new code |
| Data | mechanism per value, rows and columns with their sources, the tests a new row would widen |
| Code plan | files, overrides, restart points with their re-run safety, flow tags, suite |
| Write | one diff per file |
| Verify | compile, runs, regressions, healthcheck, standards, run versus recording, git |

Hard rules: an existing test class is never changed (a scenario that needs an extra step becomes its
own class; "make this test resumable" edits restart points only); a row added to an existing DC
workbook is asked about every time; generated code is never hand-edited; no data value is invented.

## Client profiles

Where clients differ, a profile in the client's repo, `.claude/client-profile.md`, sets the switches
`sharedValues`, `recordedValues`, `comments`, `standardsSkill`, `negativeProtocol`, `workbookWriter`,
`gate`, `defaultEnvironment`, `contextNaming` and `runCommand`, plus dated facts (re-checked when
older than 90 days). Kimputing-wide defaults are in `profile/defaults.md`. On first use the skill
drafts a profile from the scan and writes it only after approval; after a run it offers updates as a
diff. Personal machine settings (`whisperModel`, `quirks`) stay in
`~/.centertest/recording-to-test.json`, never in the profile.

## Engine commands

The skill calls one script, `scripts/ct.py <command>`:

| Command | Does |
|---|---|
| `scan` | project facts: layout, roles, bases, facades, tests, data layer, build and run commands |
| `parse` | the plan for one or several recordings, narration included |
| `xlsx` | sheet names, headers and rows of a workbook |
| `narrate` | transcript of a recording's audio mapped to steps |
| `tools` | whether ffmpeg and whisper are installed |
| `profile resolve` / `profile init` | resolved switches / a draft client profile |
| `gap-report` | a report of an engine gap, for Kimputing |
| `scrub` | a `session.json` copy with typed and posted values, `--also` words, hosts, long numbers, issue keys, meta ids and dates replaced in every non-structural string (`scrub <recording> --out DIR [--day-shift N] [--also WORD]`); narration transcripts (`audio/<stem>.transcript.json`) are written scrubbed, audio files never copied, so a recording without a transcript loses its narration; displayed text may remain and anything original still found is listed in `needsReview.leftovers`, so review `needsReview` and the files before storing them, and keep fixtures in a private repo |

## Checks → assertions

The Recorder names each check (`isEqualTo`, `optionsContains`, …); the generated test calls the
matching widget assertion. A soft check (*Continue the test if this fails*) uses the `…Soft` variant,
which records the failure and lets the test go on.

| Recorder check | Generated call |
|---|---|
| `isEqualTo` / `isNotEqualTo` | `assertEquals` / `assertNotEquals` |
| `isEqualToNumeric` / `isNotEqualToNumeric` | `assertEqualsNumeric` / `assertNotEqualsNumeric` |
| `contains` / `notContains` | `assertContains` / `assertNotContains` |
| `isIn` | `assertIsIn` |
| `isEmpty` / `isNotEmpty` | `assertEmpty` / `assertNotEmpty` |
| `isChecked` / `isVisible` / `isRequired` | `assertChecked` / `assertVisible` / `assertRequired` (`true` or `false`) |
| `optionsContains` / `optionsEquals` / `optionsNotContains` | `assertOptionsContain` / `assertOptionsEqual` / `assertOptionsNotContain` |
| `isEnabled` / `isDisabled` | `assertEnabled` / `assertDisabled` |
| `isEditable` / `isReadonly` | `assertEditable` / `assertReadOnly` |
| `isLabelEqualTo` | `assertLabel` |
| Message shown: exact / contains | `MessagesUtil.assertMessageWith` / `assertMessageContaining` |
| No errors | `MessagesUtil.getErrorMessages` is empty, in `CenterTestAssertion` |

`MessagesUtil` has no soft form, so a soft message check is wrapped in
`CenterTestAssertion…softAssertThat(() -> …)`.

## Coverages and wizards

Every coverage goes through `CoverageUtil`, which finds a coverage and its term by their screen
labels. A generated coverage getter is never used, because it depends on the coverage's place in
the iterator.

| Recorded on a coverage | Generated call |
|---|---|
| tick / untick the coverage | `coverageUtil.setSelected("GL Deductible", true)` |
| set a term | `coverageUtil.setCoverage("General Liability", "Occurrence Limit", "500,000")` |
| `isEqualTo` / `isEditable` / `isReadonly` / `isNotEmpty` on a term | `assertEquals` / `assertEditable` / `assertReadOnly` / `assertNotNull` |

When the recording has no coverage title (a single-term coverage), the label is used as the
coverage and its first term is set. That line is on the review list.

A date picked with the calendar is recorded as clicks only. Its value is taken from the form the
step sent to the server, and that line is on the review list.

A step creates its wizard page once, in a field set in its constructor, or uses the field of a
reusable base step that already holds the wizard. It never writes `new SubmissionWizardPage(getContext())`
in each method. `coverageUtil` is held the same way.

## What it proposes at the gates

- **Where the test starts**, when the recording doesn't begin with a login: the setup the other
  tests in the same `tests/<center>/<lob>/<txn>/` folder use (login, account, submission, policy
  search, restart point) and a data row that fits.
- **Retries collapsed**: a value corrected after Next is set once, a refused Next / Issue becomes the
  fix then one click, and a validation loop (errors at
  Issue → Clear / Edit Policy Transaction → fix → Quote again) becomes the fix before the first Quote.
- **Project helpers for blocker screens** ("Issues that block Issuance", "Risk Approval Details"):
  the project's methods that wait for that screen or open its page, instead of raw clicks.
  Rows picked by recorded values (a vehicle, a date) are flagged like other picks of existing data.
- **Exemplars by relevance**: a step from the same center/LOB/transaction folder, preferring one
  that was itself generated from a recording.
- **Dates and identity values**: typed and calendar-picked dates as relative dates, and generators
  for names, licence numbers, VINs and SSNs that would collide on reruns.
- **Final checks** from the analyst's notes and the expected outcome. When a note asks to verify,
  confirm or ensure something ("rating territory codes are updated"), the fields matching its words
  are listed with the values the recording shows for them, before and after (Stat. Territory
  `102` → `105`), and an assertion is proposed from them.
- **Stronger checks**: a recorded "is visible" check on a field that shows a value gets a value check
  instead (contains the address just entered).
- **Dates against the transaction**: every date is related to the transaction's own dates first
  (a conviction picked after a policy change is "change date + 1 day"), also when the analyst kept
  the default change date, then to the other posted dates and to the recording day.
- **Notes about coverages and amounts**: coverage fields are checked through `CoverageUtil` with their
  coverage title, and the note's screen is summarised (does it show "surcharge" at all? what did the
  premium do?) so a "no surcharge" note becomes a clear question.
- **Where the test starts**: when the recording continues where one of the folder's recorded steps
  ends (same coverages), "chain after that step" is offered, with the base's return helper when that
  step ends elsewhere.
- **Expected outcome against the recording**: two binds described, one recorded, is a question.
- **The policy's data**: how many vehicles, drivers and unassigned contacts the opened policy has,
  first and last, so the start option can name a data row that fits.
- **Verify-only screens** at the end of a recording (reopening the bound job to look) are marked, and
  proposed as final checks rather than replayed.
- **Conditional notes** ("If there's an error…, override") are listed so you choose: always, or only
  when the condition holds.
- **Navigation**: Next clicks that pass screens without changing anything can become the project's
  own way of moving between wizard screens (e.g. the left-hand menu).
- Picks that depend on the account's existing data (row 0 of a contact list) are flagged.

- **Pinned ids**: when the getter found for a widget would look for a different id at runtime
  (a bracketed toolbar segment, an iterator, a partial match), the recorded id is pinned with
  `.withCssId(…)`.
- **UW blocks** are handled through the project's helper after both Quote and Issue, with a
  screenshot of the blocking issues for the report.

Menu items are picked by their label on the menu button (`getAddDriver().get("New Person")`), and a
click that only opened the menu is dropped. A picker's menu (its menu icon, then an item such as
"New Location") becomes `WidgetMenuItem.get("<…MenuIcon>", getContext()).get("New Location")`. A radio
button is set on its widget's getter (`…_IC`, not the option's `…_IC_0`); a radio in a list row is
clicked on the recorded option and then checked, because the row cell's `set()` doesn't take. A row of
a table the recording added to is its last row (`getLastRow()`), not existing data. Helpers written
for the same list in another wizard (e.g. a submission's `addLossClaim`) are offered for reuse.
An entry picked from a menu by its position (a driver, an existing contact) is picked by its recorded
name instead (`getAddDriver().get("Existing Driver").get("John Smith")`), and only menus of the
policy's own records count as data. Next buttons and coverage amounts follow the project
(`getNextV9()`, `2000000`), and helpers are ranked so a UW popup's `…SpecialApproval` methods come first. Quote / Issue in a wizard's
toolbar become `getWizardButtons().getQuote()` / `getIssuePolicy()`, or the transaction base's own
quote and issue methods.

## Project guidance

If the project has `CLAUDE.md` / `AGENTS.md` files, the skill follows them. When they ask for an
edit to an existing file (for example a facade factory method for every new step), it makes that
edit and lists it. Otherwise it creates new files, and edits existing code only in the few ways the
skill allows (`SKILL.md`, "Edits to existing code"), each shown as a diff and approved first.

## What it does not do (yet)

ReportPortal configuration.
