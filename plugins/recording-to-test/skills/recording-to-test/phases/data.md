# Data

Decide where every value the test needs comes from, and write or validate the data rows. Never
invent a data value: `#` reference codes, coded values and relationship codes must exist in the
workbooks ([SKILL.md#rule-no-invented-data](../SKILL.md#rule-no-invented-data)).

## Mechanisms

Per value, pick the cheapest mechanism that fits, in this order:

1. [An existing row](#existing-row) fits.
2. [An override column](#override-column) on a row varies an existing reference.
3. [A new row](#new-row) in an existing workbook.
4. [A new workbook, column or relationship](#new-workbook) (regeneration).
5. [Constants](#no-data-layer), only when the project has no data layer yet.

Per `recordedValues` ([phases/profile.md#switches](profile.md#switches)): `data` sends recorded
values through this order (a new row also carries the values the test later asserts on, read back
from the same row: [phases/recording.md#generate](recording.md#generate)); `constants` keeps them as
constants in the step.

What the engine gives you:

- `plan.dcColumns`: for each recorded value, up to three workbook columns that could hold it,
  ranked. Candidates, not decisions.
- `plan.dataRowCandidates`: rows whose cells equal the recorded values (Excel date serials and
  formatted numbers are already compared by value).
- `project.dataWorkbooks`: `workbooks` (each with `path`, `sheets` of `columns`, `codes` and
  `rows`, and `usedBy`, the tests that read it) and `skipped` (workbooks the scan could not read).
  Say so for any skipped workbook that might matter.

Read a workbook before proposing a value (no Excel needed):

```bash
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/ct.py" xlsx <workbook>.xlsx --max-rows 30 [--sheet '^Cancellation$']
```

It prints sheets, headers and rows. The project's guidance and profile describe its workbook shape
(DC, generated class, `DDTHelper` getter, `@DataDriven` path, reference workbooks, `#` reference
columns, `@` relationship columns, date formats, blank markers); read that first.

## Existing row

A row whose cells equal the recorded values (`plan.dataRowCandidates`), or that the user names,
fits: point `@DataDriven` at its workbook and select the row by `Code`. Check each recorded value
against the row, column by column, and show the matches and the gaps.

A workbook read by `@DataDriven` without a row filter runs **every** row, so a row added later
widens each test in its `usedBy`. Pointing at an existing row adds none; say which tests already
read the workbook.

## Override column

A variation of an existing reference (a different city, a different effective date) is an
**override column** on the row, before a new reference row.

- Every hop carries its marker: `#Address.City`, `#Address.WestCoast.City`,
  `@Submission.#Policy.EffectiveDate`. A markerless `Address.City` fails with `TD-034`.
- A comma list maps positionally onto a multi-row reference.
- `<blank>` clears a value the reference would otherwise supply.
- A reference row can itself carry overrides that every DC using it inherits (framework 6.12), and
  an `Override` cell holds one row's overrides as lines (6.16). Use these only when the project's
  workbooks already do.
- In code, only for a true one-off: `dataDC.withX("code")`, `replaceReference(...)`, or a field
  `setValue(...)` in the test's `initializeData(...)`. Show it at the gate as an exception.

**Which row carries the overrides.** By default a **new row**, so the [New row](#new-row)
checkpoints apply (ask every time, `usedBy`, full preview). Writing override values into an
**existing** row silently changes every test that uses it, so do that only when the user picks that
row at the gate after seeing its `usedBy` tests.

**A header not in the workbook yet** (e.g. `#Address.City`) is a new column: say so at the gate and
follow [New workbook](#new-workbook), regeneration and its verification included, unless the
CenterTest docs ("Data overrides") say override columns need no regeneration. Check the docs or
ask; never assume. Then write through [Writing rows](#writing-rows).

## New row

A new row in an existing workbook: **ask every time. Never assume.** It widens every test that
reads the workbook without a row filter. (An existing row needs no such question:
[Existing row](#existing-row); the question is asked only here.) Two checkpoints:

1. **Checkpoint 1: target and alternative.** Show the workbook and its DC, the tests in its `usedBy` that the row
   widens (each is one more scenario on every run), and the alternative: a new workbook for a new
   test ([new workbook](#new-workbook)). Wait for the choice.
2. Read headers and existing `Code`s with `ct.py` `xlsx`; confirm no existing row already fits.
3. Fill every column from a source you can name: reference codes from the referenced sheet, values
   already present in that column, relationship codes that exist in the target DC, a new `Code`
   unique and following the file's pattern. Recorded dates follow
   [phases/recording.md#dates](recording.md#dates).
4. **Checkpoint 2: preview.** Every column, its value and where it came from. Wait for an explicit yes on the
   whole row.

Adding rows needs no regeneration; adding columns or files does ([Regeneration](#regeneration)).

## New workbook

A new DC workbook, a new column or a new relationship is a generation-level change. Propose: the
workbook path and its columns (mirror the closest existing DC; a plain file copy keeps the header
row exact, then replace its rows through [Writing rows](#writing-rows)), any hierarchy-file edit
(an allowed edit to existing code: [SKILL.md#allowed-edits](../SKILL.md#allowed-edits)), and the
generated class it should produce. Then [Regeneration](#regeneration).

## No data layer

When the project has no DC workbooks and no `@DataDriven` tests, offer:

1. **Constants** (the default when there is no data layer): recorded values as
   `private static final` constants in the new step, named from the field label. Fastest; flag it as a data-layer TODO in the report.
2. **First DC workbook**: one workbook for this transaction with the recorded values as its first
   row, plus the hierarchy and generator setup the framework needs (a [new workbook](#new-workbook)
   with [Regeneration](#regeneration)). Slower now, reusable later.

Offer both with a recommendation: 2 when the user expects more scenarios of this transaction, 1 for
a one-off. Ask ([phases/recording.md#generate](recording.md#generate)).

## Writing rows

Per `workbookWriter` ([phases/profile.md#switches](profile.md#switches)):

- `openpyxl`: write with the library, on any OS (`python3 -c "import openpyxl"` to check it).
- `excel`: Excel automation, on Windows.
- `manual`: give the user the exact cells (workbook, sheet, row `Code`, header, value) to type.

Always: locate cells by the row `Code` and the header text, never by position; never raw XML (no
editing the zip); no backup copies, since git has the original. Show the written cells (or the
diff) after the write, then [validate](#validate).

## Regeneration

Done **by the user**, in the IDE, following the profile's steps if it has them. The wizard never
runs a generator that deletes sources. Offer to pause here
([SKILL.md#session-state-and-plan-file](../SKILL.md#session-state-and-plan-file)). When the user
says it is done, verify before writing any code that calls the new getters:

1. The generated class exists with the expected getters.
2. The `DDTHelper` overloads exist.
3. `git status` shows additions only under the generated package. Anything else (a deleted or
   modified source) is reported and nothing proceeds until the user decides.

## Generated values

Tokens need **framework 6.16 and later**. Confirm the project's CenterTest version first
(`project.build`, or `centertest.version` in `gradle.properties`); on an older version use the
project's own generator instead. For names and contact data that must be fresh on every run, put
tokens in the cell of a **new** row:
`{firstname}`, `{lastname}`, `{companyname}`, `{email}`, `{phone}`, `Adult-{testcode}`, rather than
writing name-randomising code. They are restored after a restart, so an account created before the
restart still matches. A project value generator can add its own keys: check the project's
guidance for them. Existing rows are not converted.

## Shared values

A value one step produces and a later step reads is shared per `sharedValues`
([phases/profile.md#switches](profile.md#switches)):

- `dataKey`: typed, generated accessors on the data class.
- `setCustom` (allowed): `Helper.getData(getContext()).setCustom(<KEY>, value)` and
  `getCustom(<KEY>)` later.

The only prohibited keys are the **reserved built-in keys** the generator owns: `PolicyExpirationDate`,
`UserName`, `Password`, `Premium`. When `sharedValues` comes from the scan (`source: scan`) or is
still `auto`, look at `project.sharedValuesUsage`: both counts non-zero → ask (the scan took the
majority); both zero → ask; otherwise use the value.

## Validate

After writing:

1. Re-read the workbook with `ct.py` `xlsx` (above): cells aligned to their headers, `Code`
   unique, other rows unchanged.
2. Invoke the `ddt-tools` skill (as a skill, never by script path): reference validation and a diff
   of the workbook against git.

Report any broken reference before going on; do not edit around it silently.

## Gate

**Pre-write gate.** Show per value: the mechanism and its source (row `Code`, override column, new
row, new workbook); the existing-state reference check (every `#` code, coded value and
relationship code found in the workbooks); for a new row, the full preview and the widened tests
(`usedBy`) beside the new-workbook alternative, asked every time; override columns with their
markers and the row that carries them; generated-value tokens; shared values and their
`sharedValues` mode; the recording decisions routed here
([phases/recording.md#gate](recording.md#gate)): date relations (one batch,
[phases/recording.md#dates](recording.md#dates)), identity values and their generators
([phases/recording.md#identity-values](recording.md#identity-values)), picks and row filters that
depend on existing data ([phases/recording.md#row-filters](recording.md#row-filters)); what the
user must do (regeneration, manual cells). Wait for approval before anything is written.

**Report after writing (the post-write report):** the cells written, the re-read result, and the `ddt-tools`
validation and diff ([Validate](#validate)).
