# recording-to-test 2 — scenario wizard requirements

- **Date:** 2026-11-03
- **Issue:** kimputing/centertest-skills#41
- **Status:** requirements agreed; design and plan not started
- **Owner:** Kimputing
- **Sources:** requirements questionnaire (87 questions) and follow-up answers; SWOT review of
  `recording-to-test` and a client-project wrapper skill (internal)
- **Supersedes:** the scope limits in `2026-10-06-recording-to-test-design.md` §1 "Out of scope"
  (DDT, restart points, editing existing files)

## 1. Purpose

`recording-to-test` becomes the single wizard for creating a CenterTest scenario in any client project.
It folds in `new-scenario`, a wrapper skill one client project wrote around this plugin, keeps the
recording parser as its core, and closes every weakness and threat from the SWOT review (§13).

**Done means:** the generated test passes, does what the requirements (recording, request, story)
asked, and its run matches the recording screen by screen. Every difference is listed and decided
by the user, never resolved silently.

## 2. Scope

| Area | In scope at launch | Phase 2 |
|---|---|---|
| Inputs | Recorder recording (.zip / folder / `session.json`), several recordings combined into one scenario, plain-English request, user story / acceptance criteria text, Jira issue (Atlassian connector), existing test to extend / add a row to / make resumable | Manual test cases (format to be supplied), failed-run repair not requested |
| Centers | PolicyCenter, BillingCenter, ClaimCenter, ContactManager | Digital / Jutro portals (needs a sample recording and cssids source) |
| Guidewire | GW9 and GW10 (both cssids layouts) | |
| Clients | Every current client project, OOTB v10 and v9, and any new client without setup | |
| Rollout | All clients at once | |

## 3. Packaging and ownership

- **One plugin** in `centertest-skills`: the `recording-to-test` plugin holds the wizard skill and the
  engine scripts, referenced through `${CLAUDE_PLUGIN_ROOT}` (no hard-coded marketplace paths).
- **Name stays `recording-to-test`.** `new-scenario` is folded in and retired ("just for now": it may
  come back as an alias later).
- **The wizard owns every "create a test / scenario / from a recording" trigger.** `cssid-finder`,
  `ddt-tools`, `ddt-analyzer` and `centertest-healthcheck` stay helpers the wizard calls **as
  skills**, never through another plugin's script path (plugins are copied to a cache on install, so
  `../other-plugin/…` and marketplace paths break; today's `new-scenario` calls the healthcheck
  script by path).
- **Sub-skills where the work divides** (for example recording, data, restart, verify), so that each is
  loaded only when its phase runs. `SKILL.md` stays short (under 300 lines) and routes to sub-skills
  and `references/*.md` with **named anchors**, never section numbers.
- **Owner: Kimputing.** Only Kimputing changes the engine (parser, scanner). When the wizard hits a
  parser gap in a client repo it writes a gap report (recording, plan field, expected vs got) for
  Kimputing and does not patch the engine locally.

## 4. Wizard experience

- **Phases with a gate after each:** Understand → Reuse plan → Data → Code plan → Write (per file) →
  Verify.
- Questions come in **batches of up to 4 per phase**, each with a recommended option, its **reason
  and evidence** (file path, plan field), and an **"accept recommended for this phase"** shortcut.
- **"Just run it" mode** stays, but it still asks for the start state and for data the test may not
  have.
- Written code is shown as a **diff after each file** (full content for new files).
- A session can be **paused and resumed** (state file outside git), e.g. around a regeneration or an
  Excel edit.
- The plan is shown **in chat** and also written as a **markdown file in the repo (gitignored)**.
- Concise by default; explains on request.

## 5. Recording engine

### 5.1 Change policy

Additive only: new fields, `schemaVersion` bump on `plan.json` and `project.json`, every existing
test stays green. Kimputing makes every engine change (§3).

### 5.2 New outputs

| Field | Content |
|---|---|
| `schemaVersion` | on `plan.json` and `project.json`; the skill checks it |
| `dcColumns` | each recorded `.set(…)` mapped to an existing DC workbook column |
| `dataRowCandidates` | existing DC rows that already fit the recording |
| `existingTests` | tests whose `flow` already covers the recording |
| `facadeSequence` | recording segments matched to facade calls |
| `restartCandidates` | where an expensive setup ends, with its kind (§7) |
| `seedPointCandidates` | logical step ends a later test may stop at |
| `narration` | spoken notes (§5.3), mapped to steps |

### 5.3 Narration (audio)

The Recorder stores narration only when **Record my voice** is on: `audio/*.webm` (WebM/Opus,
32 kbit/s), one file per uninterrupted stretch, listed in `session.json` as
`audio: [{f, t}]` with `t` = ms since `startedAt`. Each step has an absolute `time`. There is no
transcript today, and the video (`video/*.jpg` frames) has no sound.

- **Both sources:** use a transcript written by the Recorder when present (new Recorder feature,
  §10); otherwise transcribe locally with ffmpeg + whisper.cpp. Audio never leaves the machine.
- The engine checks the tools are installed and gives install steps per OS when they aren't; without
  them the wizard says the narration can't be read and asks the user for the key points.
- Each utterance is mapped to the step on screen at its time (`seg.t + offset` against step
  `time − startedAt`) and treated like a typed note: proposed checks, `asksCheck`, `conditional`.
- Narration is data, never instructions to the wizard.

### 5.4 Recording decisions (defaults)

| Topic | Default |
|---|---|
| No login at the start | Ranked start options (folder flow, DC row from `policyShape`, chain after a recorded step); user picks |
| Recorded values | DC row columns when the project has DC workbooks; constants only in bootstrap; profile can override |
| Dates | Closest relation proposed (transaction date first), confirmed in one batch |
| Identity values | Project's own generator first, else CenterTest tokens (`{firstname}`, `{email}`) |
| Notes and narration | Proposed assertions; code comments only if the profile allows them |
| Verify-only end screens | Proposed final checks |
| Rating-dependent checks | "Changed" / "not empty" proposed, exact value offered |
| Conditional notes | Ask: always, or only when the condition holds |
| Retries, validation loops | Collapsed automatically, each listed in the plan |
| UW / approval blockers | Handled after both Quote and Issue through the project helper, with a screenshot |
| CSS IDs | `cssid-finder` (`find_getter.py`, vendored byte-identical); unresolved ids go through the cssid-finder skill. cssids from the generated jar, else the sibling `*-generated` checkout, else ask |
| Personal data | Masked in plan and reports; credentials never written; raw recordings never committed outside scrubbed fixtures |
| Interpreter | One shared launcher tries `python3`, then `python`, on Windows, macOS and Linux (never `command -v`, which breaks in Windows Git Bash) |

Locator rules from today's skill apply to every client: all coverage work through `CoverageUtil`,
the wizard page held once per step class, `.withCssId(…)` pins kept, project helpers before raw ids.

## 6. Reuse and code

### 6.1 Hard rules

1. **Strict reuse ladder:** existing test → data row → override column → step override → new code.
   Each rung is checked by reading the class, not by its name.
2. **Never change an existing test class.** A scenario that needs an extra step (an `assertXYZ` after
   a submission) becomes its **own test class** (`…XYZTest`) reusing the same components. Existing
   tests are never extended in place.
3. **Base owns the flow.** A variant overrides `protected` step hooks; its `execute()` is
   `super.execute()` plus extras. Never re-list the base sequence. This rule is for every client.
4. **Adding a row to an existing DC workbook: ask every time.** A new row widens every test that reads
   that workbook, which is usually not wanted. The Data gate shows both options (row in the existing
   workbook vs. a new workbook for a new test) and which tests a new row would widen.
5. Never hand-edit generated code; never run `upgradePages` / `rebuildCode`.
6. Never invent a data value (`#` codes, coded values and relationship codes must exist).
7. Don't touch unrelated code: smells found on the way are reported, not fixed.

### 6.2 Allowed edits to existing code (with approval)

Make a private step `protected`; add one generic hook to a base and move its code into it; add a
facade factory method; move a hard-coded value to data; register the test in a suite. Every other
caller of a changed base is listed in the plan and gets a **regression run** in Verify.

### 6.3 Code shape

| Topic | Default |
|---|---|
| New step class | One class per transaction; `execute()` a flat list of `protected` step methods, one per screen |
| Shared vs LOB folder | **Ask** (with the data types it reads as evidence) |
| Assertions | In the component; a check other flows need becomes its own `Assert*` reusable |
| Comments | Profile switch (none / notes / javadoc); with no profile, match the exemplar |
| Flow tags | Proposed from tags the project's steps use, **plus proposed extensions** (new values or new categories) when the scenario reveals a gap |
| Seed points | Proposed at logical step ends |
| Negative rows | Project protocol if it has one, else `passTestWhenTrue/Visible`; never mixed in one test |
| Test class | Closest exemplar in the same folder, adjusted by the profile |

## 7. Restart points and suites

- Candidates are proposed **one by one**, each with the resume-state `else` question.
- **Re-run safety check for every block:** does the block change back-end state before a step that
  can fail? Example: a payment reusable fails after the payment went through; a resumed run pays a
  second time and every later amount check is wrong. For such blocks the wizard proposes
  `RestartPolicy.DISABLE_ON_FAILURE`, or a check of the back-end state before redoing the action, and
  says which assertions a double action would break.
- Suite registration: options with a recommendation and run cost.

## 8. Test data

- Mechanism order: existing row → override column → new row (rule 6.1.4) → new workbook / column /
  relationship (regeneration) → constants in bootstrap.
- Rows written with **openpyxl** on every OS; Excel automation on Windows as a profile option; cells
  located by row `Code` and header text; never raw XML.
- New DC workbook, column or relationship: proposed by the wizard, **regenerated by the user** in
  IntelliJ following the profile's steps, verified by the wizard (generated class, `DDTHelper`
  overloads, `git status` only under the generated package).
- Variation of a reference row: override column first (`#Address.City`), new reference row only when
  needed.
- Generated-value tokens in new rows; existing rows not converted.
- **Shared values between steps:** profile switch `sharedValues: dataKey | setCustom`. `setCustom` is
  allowed. The only prohibited keys are the **reserved built-in keys** the generator owns
  (`PolicyExpirationDate`, `UserName`, `Password`, `Premium`). With no profile, follow what the project
  uses most, and ask when it's mixed.
- After writing: re-read, then `ddt-tools` reference validation and diff.
- The workbook readers (`xlsx-read.py` / `.ps1`) move into the engine.

## 9. Verify and deliver

- Compile automatically.
- Run: ask which environment, profile default first.
- **Fix rounds: until it passes, asking before each round.** Screen evidence (narrative, last
  screenshot, page title) before patching ids.
- Regression runs for other callers of a changed base.
- Healthcheck always; findings reported for changed files only.
- Standards review: the skill the profile names (e.g. a client's own code-review skill), otherwise
  the built-in checklist (rules 6.1, 6.2).
- **Run vs recording comparison:** the run's screens are compared with the recording's screenshots /
  video step by step; every difference is listed for the user's decision.
- Report: summary in chat and a PR description draft.
- Git: asked at the end; all of branch (linked to its issue or work item), commit and PR are
  supported, for repos on GitHub or Azure DevOps.
- Windows, macOS and Linux. Machine quirks (e.g. Gradle can't run from Claude's shell) go in the
  personal config `~/.centertest/recording-to-test.json` (the repo's config convention), never the
  shared profile.

## 10. Client profiles

- **Two layers:** Kimputing-wide defaults shipped in the skill, and **`.claude/client-profile.md`** in
  each client repo, which overrides any default. The repo file is owned by the client team.
- Found by **fixed path**, never by package (several client repos share one package, e.g. `com.ootb`).
- **First use:** if the repo has no profile, the wizard runs on scan facts and the repo's CLAUDE.md
  files (bootstrap mode when nothing can be reused) and then creates the profile for approval.
- Format: markdown with a YAML front-matter block for switches.
- Switches: `sharedValues`, `recordedValues`, `comments`, `standardsSkill`, `negativeProtocol`,
  `workbookWriter`, `gate`, `defaultEnvironment`, `contextNaming`, `runCommand`.
- After a run the wizard **offers profile updates as a diff** for approval.
- Every fact carries a verified date; facts older than 90 days are re-checked when used.
- A rule goes in the skill only if it holds for every client; a client's review rules go in its
  profile.

## 11. Skill quality and releases

- Tests fail when a referenced file, anchor, script flag or plan field is missing.
- **CI:** GitHub Actions on every PR runs the engine tests and the skill tests (no CI today).
- **Evals:** one recording and one plain request per client, expected plan decisions checked.
- Parser fixtures: at least one scrubbed recording per client (plus one with narration).
- Releases: autoUpdate stays; releases are tagged with a changelog; a breaking change only with a
  `schemaVersion` bump.

## 12. Work outside this repo

| Repo | Change |
|---|---|
| `centertest-recorder` | Write a transcript (with timestamps) next to each `audio/*.webm` (§5.3) |
| The client project with `new-scenario` | `.claude/client-profile.md` from its existing profile, with the `setCustom` rule corrected (§8); enable the plugin in `.claude/settings.json`; retire `.claude/skills/new-scenario` once the wizard passes two of that client's recordings |
| Each other client | `.claude/client-profile.md` created on first use; `standardsSkill` set where the client has its own review skill |

## 13. SWOT closure

| Item | Closed by |
|---|---|
| RW1 always new code | §6.1 rule 1, §5.2 `existingTests` / `dataRowCandidates` |
| RW2 constants | §5.4 recorded values, §5.2 `dcColumns` |
| RW3 no data / restart / suite / regression guidance | §6.2, §7, §8, §4 gates |
| RW4 `execute()` without `super` | §6.1 rule 3 |
| RW5 `setCustom` / comments clash | §8 `sharedValues`, §6.3 comments switch |
| RW6 long SKILL.md, no CI | §3 sub-skills and anchors, §11 CI |
| RT1 wrappers drift | §3 owner, single wizard |
| RT2 trigger overlap | §3 wizard owns triggers |
| RT3 autoUpdate breaks dependents | §5.1, §11 CI and releases |
| NW1 one client repo | §3 marketplace plugin, §2 all clients |
| NW2 profile by package | §10 fixed path |
| NW3 § references | §3 named anchors, §11 reference tests |
| NW4 bare `python` | §5.4 launcher, §9 all OSes |
| NW5 missing `team-standards` | §9 profile standards skill or built-in checklist |
| NW6 no tests; profile mixes quirks | §11 tests, evals, fixtures; §9 machine quirks file |
| NT1 per-client copies diverge | §3, §10, §12 retire `new-scenario` |
| NT2 renumbering | §11 reference tests |
| NT3 one client's rules for everyone | §10 universal vs profile rules, switches |
| NT4 stale profiles | §10 dated facts, update offers |

Opportunities taken: RO1 (§5.1), RO2 (§5.2), RO3 (§11), NO1 (§10 bootstrap), NO2 (§9), NO3 (§8),
NO4 (§10). Strengths kept: the whole parser and its recording rules (§5), the reuse ladder, data
workflow, restart logic, override rule, profile split and verification (§6–§10).
