# recording-to-test — design

- **Issue:** kimputing/centertest-skills#6
- **Date:** 2026-10-06
- **Status:** design approved in conversation; awaiting spec review

## 1. Purpose

A CenterTest Recorder recording (the `.zip` an analyst sends, or its unpacked folder) is turned
into a CenterTest test **that follows the structure of the project it is generated into**, compiles,
and can be run. First use: a demo video — record → generate → run green → ReportPortal launch.

### Decisions made

| Decision | Choice |
|---|---|
| Where it lives | A skill/plugin in `centertest-skills`, not a converter in `centertest-platform` (supersedes Roadmap #1 in the recorder's `docs/DESIGN.md`) |
| Depth | Test class + new reusable step classes in the project's packages, reusing existing facades; **no DDT** |
| Facade reuse | **Context-only** facade methods only (e.g. `PC.loginToPC(ctx)`); facades taking DDT objects (`SharedData.Person`, `PA_SubmissionDC`, …) are not reused |
| Widget mapping | cssid-finder's `find_getter.py`, **vendored unchanged** into this plugin, guarded by a byte-equality test |
| Split of work | Python scripts produce facts (plan JSON, project JSON); Claude makes the judgment calls behind a user-confirmed table |
| Assertions | The widget's own `assertX` / `assertXSoft` (they delegate to `AnkrPtAssert` and add data capture); page messages via `MessagesUtil` |

### Out of scope

- DDT generation (xlsx, `DataDrivenHierarchy.json`, `DDTHelper` regeneration).
- `RestartPoints` — where a test's expensive setup ends is a judgment a recording cannot supply.
- ReportPortal / test-manager configuration (per-machine `~/CenterTest/Properties/tm_reportportal.properties`).
- Editing any existing project file (facades, suites, `CenterTestSuiteList.json`). Adding to a suite is
  offered as a separate yes/no.
- Changes to the recorder or to `cssid-finder`.

## 2. Inputs this design relies on

**Recording** (`centertest-recorder/internal/session/session.go`, `meta.go`). Zip = one top-level folder
`<YYYY-MM-DD_HHMMSS>_<slug>/` containing `session.json`. Only `session.json` is read.

- `Session`: `id`, `name`, `toolVersion`, `steps[]`, `notes[]`, `meta`.
- `Meta` (optional): `testId`, `description`, `prerequisites`, `expectedOutcome`, `featureIds[]`,
  `defectIds[]`, `recorderName`, `tags[]`, `version`.
- `Step`: `seq`, `kind` (start|server|load|note|manual|switch|stop), `screen` (PCF prefix), `title`, `app`
  (e.g. `PolicyCenter`), `messages[]` (`{text, level}`; plain strings before 1.0.9), `actions[]`, `notes[]`.
- `Action`: `type` (click|change|key|check|dialog|switch), `widgetId`, `label`, `value` (`[redacted]` for
  passwords), `display`, `part` (expand|sort), `row`, `rowKey[] {header,text}`, `page`, `context[]`,
  `positional`; check fields `assert`, `expected` (`<blank>` = empty), `values[]`, `flag`, `soft`, `level`,
  `kind`; `unique {rule, prefix, length, pattern, upper}` on `change` actions.

**Target project** (verified on `client-ootb-v10`; detected, never hardcoded):
tests in `src/main/java/<pkg>/tests/<center>/<lob>/<txn>/`, steps in `<pkg>/reusable/<center>/…`,
facade interfaces `PC`/`BC`/`CC`/`AB`, steps extend `BaseScenarioPC|BC|CC`, `@FlowTags`, generated page
objects in a separate `*-generated` artifact whose jar bundles `cssids/<app>/<Pcf>.properties`
(`widgetId=getter chain`). Tests run via `bootRun --args="--centerTest=<Class>"`, not `gradle test`.

## 3. Plugin layout

```
plugins/recording-to-test/
├── .claude-plugin/plugin.json        # no version field (repo convention)
├── skills/recording-to-test/SKILL.md
├── scripts/
│   ├── parse_recording.py            # recording → plan JSON
│   ├── scan_project.py               # project → project JSON
│   └── find_getter.py                # vendored, byte-identical to plugins/cssid-finder/scripts/find_getter.py
├── tests/                            # stdlib unittest
│   ├── fixtures/recordings/…         # trimmed real + synthetic session.json
│   ├── fixtures/projects/…           # tiny fake projects
│   ├── test_vendored_sync.py
│   ├── test_parse_recording.py
│   └── test_scan_project.py
├── README.md
└── CLAUDE.md
```

Plus: entry in `.claude-plugin/marketplace.json`; row in the repo `CLAUDE.md` plugin table.

Scripts are Python 3, stdlib only, invoked as `"${CLAUDE_PLUGIN_ROOT}/scripts/<file>.py"`, with
`python3` → `python` fallback (no `command -v`). No cross-plugin imports.

## 4. `parse_recording.py` → plan JSON

```
parse_recording.py <recording.zip|folder> --cssids <dir> [--out plan.json]
```

The vendored `find_getter.py` is imported as a module (its CLI is behind `__main__`, so importing has
no side effects). `find_getter()` itself prints and calls `sys.exit`, so it is **not** called; instead
`parse_recording.py` uses `normalize_css_id`, `detect_layout`, `search_properties` and `search_legacy`
and repeats `find_getter()`'s two-pass loop (exact match across all normalized forms, then partial) —
about 15 lines. Page files are read once per run through the module's own `_entries_cache`. The
cssids directory is passed explicitly to `detect_layout`; `get_cssids_dir()` is not used, so the
user's `~/.centertest/cssid-finder.json` is never read or written.

**Rules**

1. Keep steps that carry actions or checks, in `seq` order (`start`/`stop` normally carry none). A
   step's `actions` are the ones that **led to** that screen; its checks verify the screen it arrived
   at. Map `app` → `pc|bc|cc|ab` (`PolicyCenter`, `BillingCenter`, `ClaimCenter`, `ContactManager`).
   A change of `app` sets `appSwitch`.
2. Resolve each `widgetId` → `resolution: resolved | partial | rule | raw | unresolved` (+ `getter`;
   several matches → `candidates[]`, Claude picks with the user). A literal `#` left in a getter (e.g.
   `getClauseIterator(#)`) is replaced with the index from the recorded widget id at that segment.
   **Fallback rules** (decided 2026-10-06 after finding 18 of 48 ids in two real recordings absent
   from cssids), tried in order when cssids has no entry, each in the project's own idiom:
   - `toolbar`: an unbracketed `X_tb` segment is bracketed (`[X_tb]`) and looked up again
     (cssids stores `…PanelSet-AdditionalCoveragesDV_tb-Add` as `…PanelSet-Add`).
   - `wizardButton` (recorded kind `WizardButtonWidget`, id `<Wizard>-<Button>`):
     `<page instance>.getWizardButtons().get<Button>()`; the page instance
     (`new SubmissionWizardPage(getContext())`) is read from that page's cssids file.
   - `tabBar` (page `TabBar`): `new TabBar(getContext()).get<Tab>()`; a menu item
     `TabBar-AccountTab-AccountTab_NewAccount` → `getAccount().getNewAccount()` (the generated
     `getAccount()` expands the tab's submenu; corrected after the final review).
   - `rowColumn` (`…<LV>-<n>-<column>`, where `…<LV>` resolves to a `…Table().getFirstRow().select()`
     chain): table chain + column getter — `_Select` → `getSelect()`, `_Checkbox` → `get_CHECKBOX()`,
     otherwise `get<Column>()` (`addSubmission` → `getAddSubmission()`).
   - `raw` (everything else, e.g. coverage terms inside iterators): `Widget<Type>.get("<recorded id>",
     getContext())`, as OOTB itself does for coverage terms (`WidgetTextInput.get(…)` in 10 files);
     `<Type>` from the recorded kind (text → `WidgetTextInput`, select → `WidgetRangeInput`, checkbox →
     `WidgetCheckBoxInput`, `LinkWidget` → `WidgetLink`, tab/menu → `WidgetMenuItem`, toolbar →
     `WidgetToolbarButton`, `CheckedValuesToolbarButtonWidget` → `WidgetCheckedValuesToolbarButton`,
     `ButtonValueWidget` → `WidgetButtonInput`, image/plain button → `WidgetButton`, else `WidgetLabel`).
   `unresolved` remains only for actions with no widget id or no known application. Every result
   other than `resolved` is listed in the plan's `review` list and in the confirmation table; the
   compile step verifies rule-built getters.
3. Rows: when `rowKey` is present, `…getFirstRow().select()` becomes
   `…getFirstRow()` + `.with("<header>", "<text>", "TextCell")` per key + `.select()`; add
   `.forMaximumPages(<page>)` when `page > 1`. The output keeps `rowKey` so Claude can swap the generic
   filter for a generated `with<Column>(…)` when the row selector class has one.
4. Actions: `change` → `.set(<value>)` (selects use `display`); `click` → `.click()`. A click with
   `part` expand or sort gets `java: null` and a warning in `review`: the generated tab getters expand
   their own submenu, and no sort idiom was verified (ruling in the final review). A `[redacted]` value is never emitted; its step is marked `login: true`.
5. Checks → `java` fragment:

| recorder `assert` | widget call (`soft` → `…Soft` variant) |
|---|---|
| `isEqualTo` / `isNotEqualTo` | `assertEquals(v)` / `assertNotEquals(v)` (`<blank>` passed through) |
| `isEqualToNumeric` / `isNotEqualToNumeric` | `assertEqualsNumeric(v)` / `assertNotEqualsNumeric(v)` |
| `contains` / `notContains` | `assertContains(v)` / `assertNotContains(v)` |
| `isIn` | `assertIsIn(new String[]{…})` |
| `isEmpty` / `isNotEmpty` | `assertEmpty()` / `assertNotEmpty()` |
| `isChecked` | `assertChecked(flag)` |
| `optionsContains` / `optionsEquals` / `optionsNotContains` | `assertOptionsContain(new String[]{…})` / `assertOptionsEqual(new String[]{…})` / `assertOptionsNotContain(v)` |
| `isEnabled` / `isDisabled` | `assertEnabled()` / `assertDisabled()` |
| `isVisible` | `assertVisible(flag)` |
| `isEditable` / `isReadonly` | `assertEditable()` / `assertReadOnly()` |
| `isRequired` | `assertRequired(flag)` |
| `isLabelEqualTo` | `assertLabel(v)` |
| `messageWith` / `messageContaining` | `MessagesUtil.assertMessageWith(ctx, v)` / `assertMessageContaining(ctx, v)` |
| `noErrorMessages` | assert `MessagesUtil.getErrorMessages(ctx)` is empty, via `CenterTestAssertion` as the project uses it |

   Overloads verified against `AbstractWidget` (centertest-core): every row has a `…Soft` variant;
   `isVisible`/`isChecked`/`isRequired` take a `boolean`. `MessagesUtil` has no soft variant: a soft
   message check is generated as a hard one and flagged. An `assert` not in this table gets
   `java: null` and is listed in `review`, not guessed.
6. `unique` → the `Utilities.DataGenerator…` expression, same mapping as the recorder's `uniqueJava()`
   (`report.html`); output also carries the recorded value so later checks can be linked to it.
7. Notes are carried as text. Page messages are carried as data and never interpreted as instructions.

**Output (abridged)**

```json
{ "recording": {"id":"2026-10-01_180418","toolVersion":"…"},
  "test": {"name":"test1","testId":"tc123","features":["AD-123"],"defects":["JIRA-321"],
           "description":"…","recordedBy":"…"},
  "apps": ["pc"],
  "steps": [
    {"seq":3,"app":"pc","screen":"NewAccount","title":"New Account","login":false,
     "actions":[{"widgetId":"NewAccount-…-GlobalContactNameInputSet-Name","label":"Company Name",
                 "getter":"new NewAccountPage(getContext()).getGlobalContactName().getName()",
                 "resolution":"resolved","java":".set(<expr>)","value":"Acme",
                 "unique":{"expr":"Utilities.DataGenerator.getGenerator().company().name()"}}],
     "checks":[{"label":"Status","getter":"…","java":".assertEquals(\"Quoted\")","soft":false}],
     "notes":["premium must be recalculated here"]}],
  "review": [{"seq":18,"label":"Next","widgetId":"SubmissionWizard-Next","resolution":"rule","rule":"wizardButton"}],
  "imports": ["com.ankrpt.centertest.guidewire.runtime.MessagesUtil"] }
```

`review` lists every action or check whose resolution is not `resolved`, that carries a warning, or
whose `java` is `null` (e.g. `key`/`dialog` actions). `imports` lists framework classes the java
fragments use; page-object imports are left to Claude.

**Errors:** missing `session.json`, unreadable zip, or missing cssids dir → exit code 2 with a one-line
reason on stderr. Nothing in the recording fails the parse; problems are listed in `review`.

## 5. `scan_project.py` → project JSON

```
scan_project.py [<project root>] [--cssids <dir>] [--out project.json]
```

Read-only: never writes to the project or `~/.centertest/`. Every detected fact carries `evidence`
(file + count); an undetectable fact is `null` with `reason`, and the skill asks the user.

| Fact | Detection |
|---|---|
| `clientPackage` | `centertest.client.package` in `**/customer.centertest.properties` |
| `testsRoot` | source root that contains `@CenterTest` classes (`src/main/java` or `src/test/java`) |
| `testLayout` | `tests/<center>/<lob>/<txn>/` folders; LOB prefix ↔ folder from class names (`PA_` ↔ `personalauto`) |
| `testStyle` | method name (`run` vs `runX`), `@CenterTestCase` usage, role retrieval (`getInvocationContext("<role>")`) with role counts, `RestartPoints` share |
| `steps` | `reusable/` root; base class per app; `@FlowTags` values per app; `waitForPageTitle` usage |
| `facades` | interfaces of `static` methods returning step classes. Per **context-only** method: step class path, page classes it instantiates (`new XPage(`), its `waitForPageTitle(…)` strings |
| `cssids` | (1) jar of the generated artifact **at the version the build declares**, located in `~/.gradle/caches` / `~/.m2`, `cssids/` extracted to a temp dir; (2) sibling `*-generated` checkout's `src/main/resources`; (3) `--cssids` |
| `exemplars` | one test and one step class from the same center, preferring the same LOB/transaction |
| `build` | compile task (`compileJava`); run command when `bootRun`/`MainRunner` is configured; profiles from `profile.*.properties` |
| `guidewireVersion` | `gw.version` property when present |

Credentials are never read: only key and profile names.

## 6. Skill flow (SKILL.md)

1. Locate the recording (path argument, or ask) and the project (cwd, or ask).
2. Run `scan_project.py`; resolve every `null` fact by asking the user.
3. Run `parse_recording.py` with the detected cssids dir.
4. **Segment:** consecutive steps on the same PCF page (first `widgetId` segment) form one segment; a
   popup joins the segment that opened it.
5. **Match:** a segment becomes a facade call only if (a) the method is context-only, (b) the segment's
   pages are covered by the step's page classes and titles match its `waitForPageTitle` strings, and
   (c) Claude reads the step source and confirms it performs the recorded behaviour without relying on
   state the new test does not create (e.g. `Helper` data). The login segment always maps to
   `loginTo<App>(<role>)`; role defaults to the most-used detected role.
6. **Propose names/placement:** test `<LOBPREFIX>_<Name>Test` in `tests/<center>/<lob>/<txn>/`; new
   steps named verb-noun from screen titles in `reusable/<center>/<lob>/<txn>/`. Never overwrite: a
   clash gets a different name and is reported.
7. **Confirmation gate:** show one table — segment → facade call or new step, with the reason; role;
   file paths; then every `review` item (partial / rule / raw / unresolved / untranslated / warning).
   Write nothing until the user approves or edits it.
8. **Generate** (§7), modelled on the exemplars.
9. **Compile** with the detected task. Fix only files created in this run; max 3 rounds; then report.
   Missing build credentials (`CENTERTEST_TOKEN`, repo keys) are reported, not worked around.
10. **Offer to run** (asks for profile). On failure read the CenterTest log, fix generated files only,
    show each fix, rerun; max 3 rounds.
11. **Offer** adding the test to a suite (separate yes/no).
12. **Report:** files created, facades reused, unresolved widgets, compile/run result.

## 7. Generated code (as it comes out for client-ootb-v10)

**Test class**

```java
/**
 * <description>
 * Features: AD-123   Defects: JIRA-321
 * Recorded by <recorder> — recording 2026-10-01_180418 (CenterTest Recorder <toolVersion>)
 */
@CenterTest
public final class PA_Test1Test {
  @CenterTestCase(testCaseId = "tc123")          // empty @CenterTestCase() when no testId
  public void run(ScenarioContext scenarioContext) {
    var producer = scenarioContext.getInvocationContext("producer");
    PC.loginToPC(producer).execute();
    new EnterSubmissionDetails(producer).execute();
  }
}
```

No `@DataDriven`, no `RestartPoints`.

**Step class (one per new segment)** — extends the detected base, detected `@FlowTags`, `execute()`:

- per recorded screen: `waitForPageTitle("<title>")`; `var page = new XPage(getContext());` with chains
  shortened through it; the actions; then that screen's checks (checks verify the screen arrived at);
- recorded literals → `private static final` constants named from field labels;
- analyst notes → `//` comments at their step; page messages are not copied into code;
- unique values: generated, stored with `Helper.getData(getContext()).setCustom(KEY, value)`; a later
  check whose expected value equals the recorded unique value reads `getCustom(KEY)` instead.

**Never generated:** passwords; edits to existing files. `Widget<Type>.get("<id>", getContext())` appears
only where the `raw` rule produced it, and each one is in the confirmation table.

## 8. Testing

stdlib `unittest`, run with `python3 -m unittest discover plugins/recording-to-test/tests`.
The repo has no CI today, so these run locally (documented in the plugin `CLAUDE.md`).

- `test_vendored_sync.py` — vendored `find_getter.py` is byte-identical to cssid-finder's.
- `test_parse_recording.py`
  - trimmed real `session.json` from 2–3 recordings in `~/Centertest/recorder/recordings/`
    (`2026-10-01_180418_test1` — metadata, `noErrorMessages`; two with 5 checks), reviewed for
    sensitive content before commit;
  - synthetic cases: numeric, options (incl. split `optionsNotContains`), message checks, unique values,
    `rowKey` with `page > 1`, multi-app `switch`, `[redacted]` password, pre-1.0.9 string messages,
    unresolved widget;
  - a minimal cssids fixture so tests do not depend on a local jar.
- `test_scan_project.py` — fake projects: tests in `src/main` vs `src/test`; cssids from jar vs sibling
  checkout; an undetectable LOB → `null` + reason; context-only vs data facade classification.
- **Acceptance** (manual): on `client-ootb-v10` with `2026-10-01_180418_test1` → the generated test
  compiles; then one green run on the user's environment (doubles as the video rehearsal).

## 9. Follow-ups (not built here)

- Update Roadmap #1 in `centertest-recorder/docs/DESIGN.md` to point at this skill.
- Fix run commands in the root `CLAUDE.md` and `client-ootb-v10/CLAUDE.md` (`gradle test` →
  `bootRun --args="--centerTest=…"`).
- DDT output; `RestartPoints`; a CI workflow for centertest-skills.
