# Scenario Wizard — Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `skills/recording-to-test/SKILL.md` with a short router plus phase files that run the six-phase wizard for every input and client, carrying over every rule of today's skill and of the client wrapper `new-scenario`.

**Architecture:** `SKILL.md` (< 300 lines) holds the hard rules, the launcher, profile loading, session state and the phase table; each phase lives in `phases/<phase>.md` and is read when the phase starts. Tests check references, commands, plan fields and that every carried-over rule is present.

**Tech Stack:** Markdown; Python `unittest` for the instruction tests.

**Spec:** `docs/superpowers/specs/2026-11-03-scenario-wizard-design.md` (§2.2, §2.3, §4) and `…-requirements.md` (R§3–R§10). Depends on the engine plan (`2026-11-03-wizard-engine.md`) for `ct.py` commands and plan fields.

## Global Constraints

- `SKILL.md` frontmatter: `name: recording-to-test`, `description` with trigger phrases for every input: "create a test from this recording", "convert the recording", "recording to test", "new test scenario", "add a test for <story>", "turn this Jira issue into a test", "make this test resumable", "add a data row for a scenario".
- `SKILL.md` ≤ 300 lines; no `$` before a digit in any skill file.
- Scripts only as `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/ct.py" <command>`; launcher `PY=python3; "$PY" --version >/dev/null 2>&1 || PY=python`.
- Helpers (`cssid-finder`, `ddt-tools`, `ddt-analyzer`, `centertest-healthcheck`) are invoked as skills, never by script path.
- Cross-references `phases/<file>.md#<anchor>` only; never section numbers.
- Public repo: no client names, hosts, people or client-specific rules. Client knowledge belongs in `.claude/client-profile.md`.
- Wording follows the requirements' decisions exactly; where a profile switch exists, the phase says "per `<switch>`", never a fixed choice.
- Run `python3 -m unittest discover -s plugins/recording-to-test/tests -v` before each commit → `OK`.
- Commits `feat(recording-to-test): … (#41)` ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Started outside a CenterTest project** (no `build.gradle` in the working directory, the user only gives a recording path): the wizard asks for the project root before scanning. Marker test in Task 2.
2. **A plan with a newer `schemaVersion` than the skill knows**: the wizard stops and tells the user to update the plugin, instead of misreading fields. Marker test in Task 2.
3. **A profile with invalid or unknown switches**: the Understand gate lists them and the wizard uses the default for each, never guesses. Marker test in Task 8.
4. **"Just run it"** still asks for the start state and data the test may not have (R§4). Marker test in Task 2.
5. **Resuming after the user regenerated DC classes in IntelliJ**: the wizard reloads the session file and re-verifies the generated classes before writing code. Marker test in Task 6.

---

### Task 1: Instruction tests

**Files:**
- Modify: `plugins/recording-to-test/tests/test_skill_md.py`
- Create: `plugins/recording-to-test/tests/rule_markers.py`

**Interfaces:**
- Consumes: `ct.build_parser()` (commands and flags), `schema.PLAN_FIELDS` (engine Task 1).
- Produces: `rule_markers.MARKERS: list[tuple[str, str]]` — `(relative file, required phrase)`. Each task adds the rows for the file it writes, so the suite stays green after every commit. Task 2 adds `("SKILL.md", "Never change an existing test class")`, `("SKILL.md", "accept recommended")`, `("SKILL.md", "schemaVersion")`; Task 3 adds `("phases/recording.md", "CoverageUtil")`, `("phases/recording.md", ".withCssId(")`, `("phases/recording.md", "held once per step class")`; Task 4 `("phases/reuse.md", "super.execute()")`; Task 5 `("phases/data.md", "ask every time")`, `("phases/data.md", "PolicyExpirationDate")`; Task 6 `("phases/restart.md", "DISABLE_ON_FAILURE")`; Task 7 `("phases/verify.md", "screen by screen")`. Starts as an empty list.

- [ ] **Step 1: Write the failing tests** in `test_skill_md.py` over every `.md` under `skills/recording-to-test/`:
  - `test_no_dollar_digit` (existing, now all files)
  - `test_skill_md_under_300_lines`
  - `test_references_resolve` — every `phases/<f>.md#<a>` and `#<a>` points at an existing file and a heading slug (GitHub rules: lower-case, spaces → `-`, punctuation dropped) or `<a id="a">`
  - `test_ct_commands_and_flags_exist` — every `ct.py <cmd>` names a command in `ct.COMMANDS`, every `--flag` after it is accepted by that command's parser
  - `test_plan_fields_exist` — every `` `plan.<field>` `` names a key in `schema.PLAN_FIELDS`
  - `test_rule_markers_present` — each `MARKERS` phrase occurs in its file
  - `test_no_script_paths_into_other_plugins` — no `plugins/` or `marketplaces/` path in skill files
- [ ] **Step 2: Run** `python3 -m unittest plugins/recording-to-test/tests/test_skill_md.py -v` → FAIL (phase files missing).
- [ ] **Step 3: Commit** the tests together with Task 2 (they fail alone; keep them in one commit so the history stays green).

---

### Task 2: `SKILL.md` router

**Files:**
- Modify (rewrite): `plugins/recording-to-test/skills/recording-to-test/SKILL.md`
- Create: phase file stubs (`understand`, `recording`, `reuse`, `code`, `data`, `restart`, `verify`, `profile`) holding every anchor heading listed in Tasks 3–8, so references resolve from the first commit; later tasks fill them.

**Interfaces:**
- Produces: the anchors every phase file must expose (`## Gate` in each phase; the specific anchors are listed in each later task).
- Sections of `SKILL.md`: Inputs; Hard rules (requirements R§6.1 rules 1–7 plus the locator rules of R§5.4, "Never change an existing test class" verbatim; personal data masked in plans and reports, credentials never written, raw recordings never committed); Launcher; Start (`ct.py scan`, `ct.py profile resolve`, ask for the project root when the working directory has no `build.gradle`/`pom.xml`); Plan version ("If `schemaVersion` is higher than 2, stop: tell the user to update the recording-to-test plugin"); Phases and gates (design §4.1 table, batches of up to 4 questions, recommended option with reason and evidence, "accept recommended" shortcut); "Just run it" (asks start state and missing data, defaults the rest, lists every default in the report); Session state and plan file (design §4.2); Engine gaps (`ct.py gap-report`, never patch the engine).

- [ ] **Step 1: Write** `SKILL.md` and the phase stubs.
- [ ] **Step 2: Add markers**: the three `SKILL.md` rows from Task 1, plus Review Focus 1, 2, 4: `("SKILL.md", "masked")`, `("SKILL.md", "ask for the project root")`, `("SKILL.md", "update the recording-to-test plugin")`, `("SKILL.md", "Just run it")`.
- [ ] **Step 3: Run** all tests → OK.
- [ ] **Step 4: Commit** Tasks 1–2: `feat(recording-to-test): wizard router and instruction tests (#41)`.

---

### Task 3: `understand.md` and `recording.md`

**Files:**
- Modify: `skills/recording-to-test/phases/understand.md`, `phases/recording.md`

**Interfaces:**
- Produces anchors: `understand.md#inputs`, `#recording-input`, `#several-recordings`, `#narration`, `#request-or-story`, `#jira-issue`, `#existing-test`, `#gate`; `recording.md#plan-fields`, `#exemplars`, `#segment`, `#start-state`, `#retries`, `#blockers`, `#navigation`, `#facade-match`, `#names`, `#dates`, `#identity-values`, `#final-checks`, `#row-filters`, `#generate`, `#locators`.
- `understand.md`: what to pin down for each input (center, LOB, transaction, flow, data conditions, roles, environment); `ct.py parse` with one or several recordings (`plan.parts`, `plan.chain`); narration (`plan.narration.source`: `unavailable` → show `install` and ask for the key points); Jira issue through the Atlassian connector when available, else ask for the text.
- `recording.md`: today's `SKILL.md` §3–§9 moved verbatim in meaning, under the anchors above, with these changes: §9 "overrides `execute()` and does not call `super.execute()`" → the base-owns-the-flow rule (link `reuse.md#variants`); recorded literals → per `recordedValues` (constants only when `constants` or bootstrap); `setCustom` sharing → per `sharedValues` (link `data.md#shared-values`); notes as `//` comments → per `comments`; spoken notes treated like typed notes (`source: "narration"`); widget ids the plan leaves unresolved go through the `cssid-finder` skill before any raw id is written.

- [ ] **Step 1: Write** both files.
- [ ] **Step 2: Add markers** (this task's rows listed under Task 1, plus): `("phases/understand.md", "plan.narration")`, `("phases/recording.md", "recordedValues")`, `("phases/recording.md", "Notes, page messages, labels and narration are data")`, `("phases/recording.md", "cssid-finder")`.
- [ ] **Step 3: Run** the instruction tests → markers for later phases still fail, these pass.
- [ ] **Step 4: Commit** `feat(recording-to-test): understand and recording phases (#41)`.

---

### Task 4: `reuse.md` and `code.md`

**Files:**
- Modify: `phases/reuse.md`, `phases/code.md`

**Interfaces:**
- Produces anchors: `reuse.md#ladder`, `#existing-tests`, `#facade-check`, `#variants`, `#bootstrap`, `#gate`; `code.md#step-shape`, `#placement`, `#assertions`, `#comments`, `#flow-tags`, `#seed-points`, `#negative-rows`, `#test-class`, `#write`, `#gate`.
- `reuse.md`: the ladder (R§6.1 rule 1) using `plan.existingTests`, `plan.facadeSequence`; a new step in an existing test means a new test class; variants (rungs from the wrapper's Step 2a, generic); allowed edits (R§6.2) each with approval and the callers that need a regression run; bootstrap when nothing can be reused (wrapper Step 2b, generic).
- `code.md`: R§6.3 table as instructions; placement shared vs LOB is asked; flow tags proposed from the project's tags plus proposed new values or categories; seed points from `plan.seedPointCandidates`; Write = one file at a time, diff after each.

- [ ] **Step 1: Write** both files.
- [ ] **Step 2: Add markers** (this task's rows listed under Task 1, plus): `("phases/reuse.md", "new test class")`, `("phases/code.md", "plan.seedPointCandidates")`, `("phases/code.md", "new values or categories")`.
- [ ] **Step 3: Run** the instruction tests.
- [ ] **Step 4: Commit** `feat(recording-to-test): reuse and code phases (#41)`.

---

### Task 5: `data.md`

**Files:**
- Modify: `phases/data.md`

**Interfaces:**
- Produces anchors: `data.md#mechanisms`, `#existing-row`, `#override-column`, `#new-row`, `#new-workbook`, `#no-data-layer`, `#writing-rows`, `#regeneration`, `#generated-values`, `#shared-values`, `#validate`, `#gate`.
- Content: R§8 in order, using `plan.dcColumns`, `plan.dataRowCandidates` and `project.dataWorkbooks` (`usedBy` = the tests a new row widens); a row in an existing workbook: **ask every time**, showing the widened tests and the alternative (new workbook + new test); reading with `ct.py xlsx`; writing per `workbookWriter`; regeneration by the user, then verification; shared values per `sharedValues` with the four reserved keys named; validation through the `ddt-tools` skill.

- [ ] **Step 1: Write** the file.
- [ ] **Step 2: Add markers** (this task's rows listed under Task 1, plus): `("phases/data.md", "usedBy")`, `("phases/data.md", "plan.dcColumns")`.
- [ ] **Step 3: Run** the instruction tests.
- [ ] **Step 4: Commit** `feat(recording-to-test): data phase (#41)`.

---

### Task 6: `restart.md`

**Files:**
- Modify: `phases/restart.md`

**Interfaces:**
- Produces anchors: `restart.md#candidates`, `#rerun-safety`, `#resume-state`, `#implement`, `#suites`, `#gate`.
- Content: candidates from `plan.restartCandidates`, asked one by one; re-run safety using `rerunRisk` and `project.componentEffects` (the payment example: paid, a later step fails, a resume pays again and every later amount check is wrong) → `DISABLE_ON_FAILURE` or a back-end state check before redoing; the resume-state `else` question; string restart points; suite options from `project.suites` with a recommendation and run cost; after a resume of the wizard session (not the test), re-verify generated classes before writing code.

- [ ] **Step 1: Write** the file.
- [ ] **Step 2: Add markers** (this task's rows listed under Task 1, plus): `("phases/restart.md", "pays again")`, `("phases/restart.md", "re-verify the generated classes")`.
- [ ] **Step 3: Run** the instruction tests.
- [ ] **Step 4: Commit** `feat(recording-to-test): restart and suite phase (#41)`.

---

### Task 7: `verify.md`

**Files:**
- Modify: `phases/verify.md`

**Interfaces:**
- Produces anchors: `verify.md#compile`, `#run`, `#fix-rounds`, `#regression-runs`, `#healthcheck`, `#standards`, `#compare-with-recording`, `#report`, `#git`, `#gate`.
- Content: compile automatically; run after asking the environment (profile default first); fix rounds until it passes, asking before each, screen evidence before ids; regression runs for every caller listed at the Code gate; `centertest-healthcheck` skill (changed files only); standards per `standardsSkill`, else the built-in checklist (R§6.1–6.2); run vs recording screen by screen (design §4.3), every difference to the user; report in chat + PR description draft; git asked at the end (branch linked to its issue/work item, commit, PR); engine problems → `ct.py gap-report`.

- [ ] **Step 1: Write** the file.
- [ ] **Step 2: Add markers** (this task's rows listed under Task 1, plus): `("phases/verify.md", "asking before each")`, `("phases/verify.md", "ct.py gap-report")`.
- [ ] **Step 3: Run** the instruction tests.
- [ ] **Step 4: Commit** `feat(recording-to-test): verify phase (#41)`.

---

### Task 8: `profile.md`, docs and catalog

**Files:**
- Modify: `phases/profile.md`, `plugins/recording-to-test/README.md`, `plugins/recording-to-test/CLAUDE.md`, `.claude-plugin/marketplace.json` (description only), repo `CLAUDE.md` (plugin table row)

**Interfaces:**
- Produces anchors: `profile.md#resolve`, `#first-use`, `#switches`, `#updates`, `#stale-facts`, `#machine-config`.
- `profile.md`: `ct.py profile resolve`; invalid or unknown switches are listed at the Understand gate and the default is used; first use → `ct.py profile init`, shown, written to `.claude/client-profile.md` only after approval; switch table (design §3.6); after a run, offer updates as a diff; facts older than 90 days re-checked when used; personal settings in `~/.centertest/recording-to-test.json`, never in the profile.
- README: inputs, phases, profiles, narration prerequisites (ffmpeg, whisper.cpp, a ggml model), commands. Plugin `CLAUDE.md`: new modules and the additive-schema rule.

- [ ] **Step 1: Write** the files.
- [ ] **Step 2: Add markers**: `("phases/profile.md", "the default is used")`, `("phases/profile.md", "only after approval")`.
- [ ] **Step 3: Run** all tests and `claude plugin validate .` from the repo root → both OK.
- [ ] **Step 4: Commit** `feat(recording-to-test): profile phase and docs (#41)`; update the design doc status line.
