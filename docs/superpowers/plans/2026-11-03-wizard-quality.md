# Scenario Wizard — Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guard the wizard against silent breakage: CI on every PR, a changelog tied to the schema version, an eval harness whose client cases stay private, and a scrubber for sharing recordings as fixtures.

**Architecture:** One GitHub Actions workflow runs every plugin's `tests/` on three OSes; `evals/run_evals.py` runs engine-level cases from a folder outside this public repo; `scripts/scrub_recording.py` produces a `session.json`-only copy with hosts, typed values and dates replaced.

**Tech Stack:** GitHub Actions; Python 3.9+ standard library; `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-03-scenario-wizard-design.md` §5 and `…-requirements.md` R§11. Depends on the engine plan's `ct.py` and `schema.py`.

## Global Constraints

- CI matrix: `ubuntu-latest`, `macos-latest`, `windows-latest` × Python `3.9`, `3.12`; no `PYTHONUTF8` override (encoding bugs must show).
- No client cases, recordings, hosts or names in this repo; cases come from `--cases DIR` or `CT_EVALS_DIR`.
- `CHANGELOG.md` top entry names `plan schemaVersion N` and `project schemaVersion N` matching `schema.py`.
- Releases are git tags `recording-to-test-v<major>.<minor>.<patch>`; `plugin.json` keeps no `version` (repo convention).
- Commits `feat(recording-to-test): … (#41)` / `ci: … (#41)` ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A test that only passes with a UTF-8 console** (Windows default cp1252): the Windows job fails, which is the point. Covered by the matrix in Task 1.
2. **An eval case whose project path doesn't exist on this machine**: reported as `SKIP (project not found: …)`, other cases still run, exit code 0 if nothing failed. Test in Task 3.
3. **A typed value that also appears inside a note**: the scrubber replaces it in the note too and lists the note in its report for a manual look. Test in Task 4.
4. **The same value typed on two screens**: both get the same placeholder, so `dcColumns` / `dataRowCandidates` still match on a scrubbed fixture. Test in Task 4.
5. **Dates in a scrubbed recording**: all shifted by one fixed number of days, so `dateRelations` ("EffectiveDate + 1 day") stay the same. Test in Task 4.

---

### Task 1: CI workflow

**Files:**
- Create: `.github/workflows/tests.yml`

**Interfaces:**
- Runs on `pull_request` and `push` to `main`. One job, matrix per Global Constraints, `actions/checkout@v4`, `actions/setup-python@v5`. Step: for every `plugins/*/tests` directory, `python -m unittest discover -s <dir> -v`; fail the job if any run fails (bash loop with `shell: bash` on all OSes).

- [ ] **Step 1: Write** the workflow.
- [ ] **Step 2: Push** the branch and run `gh run watch` on the new run → all six jobs green. A red Windows job is a real bug: fix it in the engine code it names (not by changing the workflow).
- [ ] **Step 3: Commit** `ci: run plugin tests on Linux, macOS and Windows (#41)`.

---

### Task 2: Changelog and schema-version guard

**Files:**
- Create: `plugins/recording-to-test/CHANGELOG.md`
- Create: `plugins/recording-to-test/tests/test_changelog.py`
- Modify: `plugins/recording-to-test/CLAUDE.md` (a "Releasing" section)

**Interfaces:**
- Consumes: `schema.PLAN_SCHEMA_VERSION`, `schema.PROJECT_SCHEMA_VERSION`.
- `CHANGELOG.md` top entry: `## 2.0.0 — scenario wizard` with the lines `plan schemaVersion 2` and `project schemaVersion 2` and a list of added fields.
- "Releasing": add an entry, bump the version when a schema version changes, tag `recording-to-test-v2.0.0` on `main` after merge, push the tag.

- [ ] **Step 1: Write the failing test** `test_top_entry_names_current_schema_versions` (reads the first `## ` section; asserts both `f"plan schemaVersion {PLAN_SCHEMA_VERSION}"` and `f"project schemaVersion {PROJECT_SCHEMA_VERSION}"` occur in it).
- [ ] **Step 2: Run** → FAIL (no file).
- [ ] **Step 3: Write** `CHANGELOG.md` and the CLAUDE.md section.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): changelog tied to schema versions (#41)`.

---

### Task 3: Eval harness

**Files:**
- Create: `plugins/recording-to-test/evals/run_evals.py`, `plugins/recording-to-test/evals/README.md`
- Test: `plugins/recording-to-test/tests/test_run_evals.py`

**Interfaces:**
- Case file `<cases>/<name>/case.json`: `{"name": str, "project": str, "recordings": [str], "expect": [{"path": str, "op": "equals"|"contains"|"exists"|"absent", "value"?: any}]}`. `project` and `recordings` may use `${VAR}` (expanded from the environment) and paths relative to the case folder.
- `run_evals.get_path(doc: dict, path: str)` — dotted path with `[i]` indexes over `{"plan": …, "project": …}`, e.g. `plan.existingTests[0].path`; raises `KeyError` with the failing segment.
- `run_evals.run_case(case_dir: str, ct: str) -> dict` → `{"name", "status": "PASS"|"FAIL"|"SKIP", "failures": [str], "reason"?}`; runs `ct.py scan` and `ct.py parse` (with `--project`) into a temp dir.
- `run_evals.main(argv) -> int` — `--cases DIR` (else `CT_EVALS_DIR`; neither → exit 2 with a message); prints one line per case and a total; exit 1 if any `FAIL`.
- README: case format, where client cases live (a private Kimputing repository, cloned locally; never this repo), how to add a case from a wizard run, and skill-level evals through the `skill-creator` skill (manual, per client).

- [ ] **Step 1: Write the failing tests** — `test_get_path_with_indexes`, `test_passing_case` (temp case using the `com.acme` test project from `test_scan_project` and the `synthetic` recording; expect `plan.schemaVersion equals 2`), `test_failing_expectation_reported`, `test_missing_project_is_skip`, `test_env_var_expanded`, `test_no_cases_dir_exits_2`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** and write the README.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): eval harness with private cases (#41)`.

---

### Task 4: Recording scrubber

**Files:**
- Create: `plugins/recording-to-test/scripts/scrub_recording.py`; register `scrub` in `ct.COMMANDS`
- Test: `plugins/recording-to-test/tests/test_scrub_recording.py`

**Interfaces:**
- Produces: `scrub_recording.scrub(session: dict, day_shift: int = 100) -> tuple[dict, dict]` → `(scrubbed session, report)`. Rules:
  - every URL host (`startUrl`, step `url`, request URLs) → `gw.example.test`;
  - every typed value (`actions[].value` of `type == "change"`, not `[redacted]`, not a date, not a pure number) → `V<n>` per distinct value (same value, same placeholder), also replaced inside notes, messages and `meta` text;
  - every `MM/DD/YYYY` / `YYYY-MM-DD` date and every step `time` / `startedAt` shifted by `day_shift` days;
  - `dom`, `net`, `screenshot`, `before`, `full`, `video`, `audio` references removed (only `session.json` is written);
  - report = `{"hosts": [...], "values": n, "notesChanged": [seq], "datesShifted": n}`.
- CLI `ct.py scrub <recording> --out DIR [--day-shift N]` writes `DIR/session.json` and prints the report.

- [ ] **Step 1: Write the failing tests** — `test_hosts_replaced`, `test_same_value_same_placeholder`, `test_value_inside_note_replaced_and_reported`, `test_dates_shifted_and_relations_kept` (plan of the scrubbed fixture has the same `dateRelations[*].text` as the original), `test_redacted_and_numbers_kept`, `test_media_references_removed`, `test_scrubbed_plan_still_builds` (`pr.build_plan` on the output).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): recording scrubber for private fixtures (#41)`; update the design doc status line.
