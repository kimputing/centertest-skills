# recording-to-test

Turns a CenterTest Recorder recording (the `.zip` an analyst sends, its folder, or its `session.json`) into a CenterTest
test that follows the project's own structure: the test class in its `tests/<center>/<lob>/<txn>/`
layout, the project's login facade, new reusable step classes for the recorded screens, and the
recorded checks as widget assertions.

## Prerequisites

- Python 3.9+ (no packages needed)
- A CenterTest project whose generated page objects are available: the `*-generated` dependency in
  the Gradle/Maven cache (it bundles `cssids/`), or a `*-generated` checkout next to the project.

## Use

In the project directory: "create a test from ~/Downloads/2026-10-01_174907_test1.zip".
The skill shows a table of what it will generate and waits for your approval before writing files.

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

## What it proposes at the confirmation table

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
for the same list in another wizard (e.g. a submission's `addLossClaim`) are offered for reuse. Quote / Issue in a wizard's
toolbar become `getWizardButtons().getQuote()` / `getIssuePolicy()`, or the transaction base's own
quote and issue methods.

## Project guidance

If the project has `CLAUDE.md` / `AGENTS.md` files, the skill follows them. When they ask for an
edit to an existing file (for example a facade factory method for every new step), it makes that
edit and lists it. Otherwise it only creates new files.

## What it does not do (yet)

DDT data sheets, ReportPortal configuration.
