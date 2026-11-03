# Scenario Wizard — Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the recording-to-test scripts with the facts and candidates the wizard needs (schema version, data/flow matching, restart and seed candidates, narration, several recordings, client profiles, gap reports) without changing any existing output.

**Architecture:** New focused modules beside `parse_recording.py` / `scan_project.py`, each called from `scan()` or `analyse()` and exposed through one dispatcher, `ct.py`. Every new field is additive; the 164 existing tests stay green.

**Tech Stack:** Python 3.9+ standard library only; `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-03-scenario-wizard-design.md` (design, §3) and `docs/superpowers/specs/2026-11-03-scenario-wizard-requirements.md`.

## Global Constraints

- Python 3.9+, **standard library only** in `scripts/` (no openpyxl, no PyYAML).
- JSON written with `ensure_ascii=True`; stdout reconfigured to UTF-8 (as the existing `main()`s do).
- External tools via `shutil.which`; never `command -v`.
- No imports from other plugins; `find_getter.py` stays byte-identical to cssid-finder's.
- Additive only: no existing plan or project key changes shape; `PLAN_SCHEMA_VERSION = 2`, `PROJECT_SCHEMA_VERSION = 2`.
- Public repo: no client names, hosts or people in code, tests, fixtures or commit messages. Use `com.acme` as in the existing tests.
- Run all tests before each commit: `python3 -m unittest discover -s plugins/recording-to-test/tests -v` → `OK`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; prefix `feat(recording-to-test):` and reference `#41`.

## Review Focus

1. **Narration on a machine without ffmpeg/whisper/model** (the usual Windows case): `narration.source == "unavailable"` with a `reason` and per-OS `install`, never an exception. Test in Task 9.
2. **A broken or locked workbook in `testdata/`** (Excel's `~$*.xlsx` lock file, a non-zip `.xlsx`): skipped with `skipped: [{path, reason}]`, scan completes. Test in Task 3.
3. **Recorder timestamps with offsets and fractions** (`2026-10-01T18:04:18.123456+02:00`, `Z`): step offsets computed in ms correctly on Python 3.9 (`fromisoformat` there rejects `Z`). Test in Task 9.
4. **A plan built without `--project`**: every new field present and empty (`[]`), no `KeyError`. Test in Tasks 6–8.
5. **Several recordings where a later one doesn't start with a login**: `chain[i].startsLoggedIn` is `false` and `startsOn` is that part's first title. Test in Task 10.

---

### Task 1: Schema version and the `ct.py` dispatcher

**Files:**
- Create: `plugins/recording-to-test/scripts/schema.py`, `plugins/recording-to-test/scripts/ct.py`
- Modify: `scripts/parse_recording.py` (`build_plan`), `scripts/scan_project.py` (`scan`)
- Test: `plugins/recording-to-test/tests/test_ct.py`

**Interfaces:**
- Produces: `schema.PLAN_SCHEMA_VERSION: int = 2`, `schema.PROJECT_SCHEMA_VERSION: int = 2`, `schema.PLAN_FIELDS: frozenset[str]` (every top-level plan key, including the ones later tasks add: `facadeSequence`, `existingTests`, `dcColumns`, `dataRowCandidates`, `restartCandidates`, `seedPointCandidates`, `narration`, `parts`, `chain`, `schemaVersion`).
- Produces: `ct.COMMANDS: dict[str, str]` (command → module name), `ct.build_parser() -> argparse.ArgumentParser`, `ct.main(argv: list[str]) -> int`. Commands: `scan`→`scan_project`, `parse`→`parse_recording`, `xlsx`→`xlsx_read`, `narrate`→`narration`, `profile`→`profile`, `tools`→`narration` (`tools` subcommand), `gap-report`→`gap_report`. `ct.main([cmd, *rest])` imports the module and returns `module.main(rest)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_plan_carries_schema_version(self):
    plan = pr.build_plan(load("synthetic"), CSSIDS)
    self.assertEqual(plan["schemaVersion"], schema.PLAN_SCHEMA_VERSION)

def test_project_carries_schema_version(self):  # temp project as in test_scan_project
    self.assertEqual(sp.scan(root)["schemaVersion"], schema.PROJECT_SCHEMA_VERSION)

def test_plan_keys_are_declared(self):
    plan = pr.build_plan(load("real-180418"), CSSIDS, pr.file_reader(...), None)
    self.assertLessEqual(set(plan), schema.PLAN_FIELDS)

def test_ct_parse_matches_parse_recording(self):
    # run both via subprocess with --out to temp files; json.load both; assertEqual

def test_ct_unknown_command_exits_2(self):
    self.assertEqual(ct.main(["nope"]), 2)
```

- [ ] **Step 2: Run** `python3 -m unittest plugins/recording-to-test/tests/test_ct.py -v` → FAIL (`No module named 'schema'`).
- [ ] **Step 3: Implement** `schema.py`, `ct.py`; add `"schemaVersion": PLAN_SCHEMA_VERSION` first in the `plan` dict in `build_plan`, and `"schemaVersion": PROJECT_SCHEMA_VERSION` first in `scan()`'s result. `ct.py` puts its own folder on `sys.path` and prints the command list on `-h`.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): schemaVersion and ct.py entry point (#41)`.

---

### Task 2: Workbook reader in the engine

**Files:**
- Create: `scripts/xlsx_read.py` (port of the client wrapper's stdlib reader, generic)
- Test: `tests/test_xlsx_read.py`, helper `tests/xlsx_fixture.py`

**Interfaces:**
- Produces: `xlsx_read.read_workbook(path: str, sheet: str = ".*", max_rows: int | None = None) -> dict[str, list[dict[str, str]]]` — per sheet name, data rows (header row excluded) as `{header: value}`; empty cells omitted. Raises `xlsx_read.WorkbookError` on a non-zip or missing workbook part.
- Produces: `xlsx_read.headers(path: str, sheet: str = ".*") -> dict[str, list[str]]`.
- Produces: `xlsx_fixture.make_xlsx(path: str, sheets: dict[str, list[list[str]]]) -> None` (writes a minimal valid xlsx with shared strings, for tests).
- CLI `main(argv)`: `<path> [--max-rows N] [--sheet REGEX]`, same printed format as the original (`--- [Sheet]  data rows: N`, then `   A=Code | B=…`).

- [ ] **Step 1: Write the failing tests** — `test_rows_keyed_by_header` (`{"Code": "Default", "#Person": "Adult"}`), `test_inline_and_shared_strings`, `test_blank_cells_omitted`, `test_sheet_filter`, `test_not_a_zip_raises_workbook_error`, `test_cli_prints_header_and_counts`.
- [ ] **Step 2: Run** → FAIL (no module).
- [ ] **Step 3: Implement** with `zipfile` + `xml.etree.ElementTree`, column letters from the cell `r` attribute, header from the first row.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): stdlib workbook reader (#41)`.

---

### Task 3: Scan — `dataWorkbooks`

**Files:**
- Modify: `scripts/scan_project.py` (new `data_workbooks(root, tests)`, called from `scan`)
- Test: `tests/test_scan_project.py` (new class `DataWorkbooksTest`)

**Interfaces:**
- Consumes: `xlsx_read.headers`, `xlsx_read.read_workbook`.
- Produces: `project["dataWorkbooks"] = fact({"workbooks": [{"path": "testdata/personalauto/PA_SubmissionDC.xlsx", "sheets": {"DataCombination": {"columns": [...], "codes": [...], "rows": n}}, "usedBy": ["src/main/java/.../PA_SubmissionTest.java"]}], "skipped": [{"path", "reason"}]}, evidence)` or `missing("no .xlsx under testdata")`. `usedBy` from each test's `@DataDriven(datasource = "…")`. Files named `~$*` are skipped silently; unreadable ones go to `skipped`.

- [ ] **Step 1: Write the failing tests** — `test_lists_columns_codes_and_rows`, `test_used_by_from_data_driven` (TEST_A's `PA_SubmissionDC.xlsx` → its path), `test_corrupt_workbook_is_skipped_with_reason` (write `b"not a zip"` to `bad.xlsx`; scan succeeds; `skipped[0]["path"]` ends with `bad.xlsx`), `test_excel_lock_file_ignored` (`~$PA_SubmissionDC.xlsx` absent from both lists), `test_no_testdata_is_missing`.
- [ ] **Step 2: Run** → FAIL (`KeyError: 'dataWorkbooks'`).
- [ ] **Step 3: Implement** `data_workbooks`; walk `testdata/` with `SKIP_DIRS`; codes = values of the `Code` column.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): scan DC workbooks (#41)`.

---

### Task 4: Scan — `sharedValuesUsage`, `negativeProtocol`, `suites`

**Files:**
- Modify: `scripts/scan_project.py` (`shared_values_usage(root, java)`, `negative_protocol(java)`, `suites(root)`)
- Test: `tests/test_scan_project.py` (class `ConventionsTest`)

**Interfaces:**
- Produces: `project["sharedValuesUsage"] = fact({"setCustom": int, "dataKey": int, "reservedKeyMisuse": [{"path", "key"}]})` — `setCustom(` call count; `DataKey.` reference count; misuse = `setCustom("<key>"` where key ∈ `RESERVED_KEYS = ("PolicyExpirationDate", "UserName", "Password", "Premium")` (exported constant).
- Produces: `project["negativeProtocol"] = fact({"projectException": int, "framework": int})` — counts of `NegativeTestException` and `passTestWhen` in tests.
- Produces: `project["suites"] = fact({"path": "src/main/resources/CenterTestSuiteList.json", "suites": {name: [entries]}})` or `missing(...)`. Accept both the `List` and `Packages` shapes; unknown shapes kept as raw.

- [ ] **Step 1: Write the failing tests** — `test_counts_setcustom_and_datakey`, `test_reserved_key_with_setcustom_is_flagged` (`setCustom("Premium", x)` → `{"key": "Premium"}`), `test_other_setcustom_keys_not_flagged`, `test_negative_protocol_counts`, `test_suites_listed`, `test_no_suite_file_is_missing`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the three functions with regexes over the indexed Java and `json.load` for the suite file.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): scan shared-value, negative-test and suite conventions (#41)`.

---

### Task 5: Scan — `componentEffects`

**Files:**
- Modify: `scripts/scan_project.py` (`component_effects(root, steps)`)
- Test: `tests/test_scan_project.py` (class `ComponentEffectsTest`)

**Interfaces:**
- Produces: `project["componentEffects"] = fact([{"path", "class", "commits": [kind], "afterCommit": bool}])`, only classes with at least one commit. `COMMIT_PATTERNS: dict[str, re.Pattern]` with kinds `issue` (`getIssuePolicy|getIssueNow`), `bind` (`getBindOnly|BindPolicyChange|getBind\w*`), `payment` (`Payment|getPay\w*|MakePayment`), `cancel` (`getCancelNow|CancelPolicy`), `reinstate`, `rewrite`, `submit` (`getSubmit\w*`). `afterCommit`: text after the first commit match contains `assert`, `waitForPageTitle`, or `.set(`.

- [ ] **Step 1: Write the failing tests** — `test_payment_then_assert_is_after_commit` (class clicking `getMakePayment()` then `assertEquals` → `{"commits": ["payment"], "afterCommit": True}`), `test_issue_last_is_not_after_commit`, `test_class_without_commit_absent`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): scan components that commit back-end state (#41)`.

---

### Task 6: Plan — `facadeSequence` and `existingTests`

**Files:**
- Create: `scripts/flow_match.py`
- Modify: `scripts/parse_recording.py` (`analyse` calls it; `build_plan` initialises both keys to `[]`)
- Test: `tests/test_flow_match.py`

**Interfaces:**
- Consumes: `plan["steps"][i]["pages"]`, `["waitTitle"]`, `["seq"]`, `["login"]` (set in `analyse`); `project["facades"]["value"]` (`[{facade, method, contextOnly, pages, titles, step}]`); `project["folders"]["value"]["tests"]`.
- Produces: `flow_match.segments(plan: dict) -> list[dict]` (`{seqs, pages, titles}`; consecutive steps sharing a page; a `…Popup` page joins the open segment; a `login` step alone).
- Produces: `flow_match.facade_sequence(plan: dict, facades: list) -> list[dict]` — per segment `candidates: [{facade, method, score, why}]`, only `contextOnly`, score = share of the segment's pages and titles the method lists, sorted desc, max 3. Facade `pages` are generated class names (`SubmissionWizardPage`); plan pages are id prefixes (`SubmissionWizard`): compare with the `Page` suffix removed, as `analyse` already does for `wizardFields`.
- Produces: `flow_match.existing_tests(sequence: list, folders: dict, folder: str | None) -> list[dict]` — `{path, folder, coveredSeqs, missingSeqs, score}` for tests whose `flow` contains top candidates in order; folder tests first; max 5.

- [ ] **Step 1: Write the failing tests** — `test_popup_joins_segment`, `test_login_alone`, `test_candidate_needs_context_only`, `test_candidates_ranked_by_overlap`, `test_existing_test_covering_all_segments_scores_1`, `test_no_project_gives_empty_lists` (`build_plan(..., project=None)` → both `[]`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; `analyse` sets `plan["facadeSequence"]` and `plan["existingTests"]` when `project.get("facades", {}).get("value")`.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): facade sequence and existing tests covering a recording (#41)`.

---

### Task 7: Plan — `dcColumns` and `dataRowCandidates`

**Files:**
- Create: `scripts/data_match.py`
- Modify: `scripts/parse_recording.py` (`analyse`; keys initialised to `[]`)
- Test: `tests/test_data_match.py`

**Interfaces:**
- Consumes: plan actions with `type == "change"` (`label`, `value`, `seq`; skip `REDACTED`); `project["dataWorkbooks"]["value"]["workbooks"]`; `project["root"]`; `xlsx_read.read_workbook`.
- Produces: `data_match.tokens(text: str) -> set[str]` (camel-case split, `#`/`@`/`.` separators, lower-case, stopwords `{"the","of","a"}` removed).
- Produces: `data_match.dc_columns(plan: dict, workbooks: list) -> list[dict]` — `{seq, label, value, workbook, sheet, column, why}` where the label's tokens ⊆ the header's tokens or the reverse; one best column per action per workbook.
- Produces: `data_match.data_row_candidates(columns: list, root: str, read=xlsx_read.read_workbook) -> list[dict]` — `{workbook, sheet, code, matched, total}`; a cell matches when trimmed, case-folded values are equal, or both parse as the same date (`MM/DD/YYYY`, `YYYY-MM-DD`); top 3 per workbook with `matched > 0`.

- [ ] **Step 1: Write the failing tests** — `test_tokens_split_camel_and_markers` (`"#Person.FirstName"` → `{"person","first","name"}`), `test_label_maps_to_column` (`"First name"` → `#Person.FirstName`), `test_redacted_values_skipped`, `test_rows_ranked_by_matches`, `test_dates_match_across_formats` (`10/01/2026` = `2026-10-01`), `test_no_workbooks_gives_empty_lists`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; workbooks read once per run (dict cache).
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): map recorded values to DC columns and rows (#41)`.

---

### Task 8: Plan — `restartCandidates` and `seedPointCandidates`

**Files:**
- Create: `scripts/restart.py`
- Modify: `scripts/parse_recording.py` (`analyse`; keys initialised to `[]`)
- Test: `tests/test_restart.py`

**Interfaces:**
- Consumes: `flow_match.segments`, `plan["facadeSequence"]`, step `appSwitch`, action labels; `project["componentEffects"]["value"]`.
- Produces: `restart.restart_candidates(plan: dict, sequence: list, effects: list) -> list[dict]` — `{afterSeq, kind, reason, rerunRisk, proposePolicy}`:
  - `setup`: end of the last segment whose top candidate method name starts with `create` (account, submission, policy) and is followed by more segments.
  - `centerSwitch`: before a step with `appSwitch: true`.
  - `stateChanging`: a segment containing an Issue/Bind/Pay/Cancel/Reinstate/Rewrite action (or whose top candidate's component is in `effects` with `afterCommit: true`) followed by further actions or checks → `rerunRisk: "notResumable"`, `proposePolicy: "DISABLE_ON_FAILURE"`, `reason` naming the commit kind and the later seqs.
  - otherwise `rerunRisk: "safe"`, `proposePolicy: None`.
- Produces: `restart.seed_points(plan: dict) -> list[dict]` — `{seq, seed, why}`: `NEW_ACCOUNT` (title starts "Account Summary" after a create-account segment), `PRE_QUOTE` (title "Pre-Quote Issues"), `QUOTED` (title "Quote"), `ISSUED_POLICY` (title starts "Submission Bound"/"Policy Change Bound"/"Job Complete"), `CLAIM` (title starts "Claim" in `cc`).

- [ ] **Step 1: Write the failing tests** — `test_payment_followed_by_checks_is_not_resumable` (synthetic plan: payment segment then an amount check → `rerunRisk == "notResumable"`, `proposePolicy == "DISABLE_ON_FAILURE"`), `test_component_after_commit_marks_state_changing`, `test_setup_after_create_submission`, `test_center_switch_candidate`, `test_seed_points_from_titles`, `test_no_project_gives_empty_lists`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): restart and seed point candidates with re-run safety (#41)`.

---

### Task 9: Narration

**Files:**
- Create: `scripts/narration.py`
- Modify: `scripts/parse_recording.py` (`file_bytes(path)`; `build_plan(..., read_bytes=None, tools=None)` sets `plan["narration"]` and appends utterances to `plan["notes"]` with `"source": "narration"`; `main` passes `file_bytes(args.recording)`)
- Create fixture: `tests/fixtures/recordings/narrated/` (synthetic `session.json` with `audio: [{"f": "audio/0001.webm", "t": 4000}]`, a dummy `audio/0001.webm`, and `audio/0001.transcript.json`)
- Test: `tests/test_narration.py`

**Interfaces:**
- Produces: `parse_recording.file_bytes(path: str) -> Callable[[str], bytes | None]` (same lookup and path checks as `file_reader`).
- Produces: `narration.to_ms(iso: str) -> int` handling `Z`, offsets and up to 9 fractional digits on Python 3.9.
- Produces: `narration.find_tools(env: Mapping = os.environ, config_path: str = "~/.centertest/recording-to-test.json") -> dict` → `{"ffmpeg": path|None, "whisper": path|None, "model": path|None}`; model from `RECORDING_TO_TEST_WHISPER_MODEL` > config `whisperModel`.
- Produces: `narration.narrate(session: dict, read_bytes, tools: dict, workdir: str) -> dict` → `{"source": "none"|"transcript"|"whisper"|"unavailable", "segments": [...], "utterances": [{"seq", "t", "text", "asksCheck"?, "conditional"?}], "reason"?, "install"?}`. Transcript file `audio/<stem>.transcript.json` = `{"segments": [{"start", "end", "text"}]}` (ms from the segment start). Whisper: `ffmpeg -y -i <in> -ar 16000 -ac 1 <wav>`; `whisper-cli -m <model> -f <wav> -oj -of <base>`; read `transcription[].offsets.from` and `.text`. `install` = `{"macos": "brew install ffmpeg whisper-cpp", "windows": "winget install Gyan.FFmpeg, then whisper.cpp release zip (whisper-cli.exe) on PATH", "linux": "apt install ffmpeg; build whisper.cpp"}` plus "download a ggml model and set whisperModel".
- Produces: `narration.assign_steps(utterances: list, steps: list, started_at: str) -> list` — each utterance gets the `seq` of the last step whose offset ≤ its time (first step if earlier).
- Produces: CLI `main(argv)`: `narrate <recording> [--out]` and `tools` (prints `find_tools()` JSON).
- Note flags reuse `parse_recording.note_entry` (import it lazily to avoid a cycle, or move `ASKS_CHECK`/`CONDITIONAL` use into a shared helper).

- [ ] **Step 1: Write the failing tests** — `test_to_ms_handles_z_offset_and_fraction` (`"2026-10-01T18:04:18.123456+02:00"` and `"…Z"`), `test_transcript_file_wins` (fixture → `source == "transcript"`, utterance `t == 4000 + start`), `test_utterance_mapped_to_step_on_screen`, `test_whisper_path_with_fake_tools` (temp dir with fake `ffmpeg` / `whisper-cli` Python scripts writing the expected files; `tools` pointing at them; `source == "whisper"`), `test_missing_tools_unavailable_with_install` (`tools = {"ffmpeg": None, …}` → `source == "unavailable"`, `"windows" in install`), `test_no_audio_is_none`, `test_utterances_join_notes_with_source` (`plan["notes"]` has `{"source": "narration"}` entries; `asksCheck` set for "verify the premium"), `test_existing_fixtures_unchanged` (real-180418 plan has `narration == {"source": "none", "segments": [], "utterances": []}` and the same `notes` as before).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; temp files under `tempfile.TemporaryDirectory()`, removed after.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): narration from transcripts or local whisper (#41)`.

---

### Task 10: Several recordings

**Files:**
- Modify: `scripts/parse_recording.py` (`combine(plans: list) -> dict`; `main` takes `recording` with `nargs="+"`)
- Test: `tests/test_parse_recording.py` (class `CombineTest`)

**Interfaces:**
- Produces: `parse_recording.combine(plans: list[dict]) -> dict` = `{"schemaVersion": 2, "parts": plans, "chain": [{"fromPart": i, "toPart": i+1, "endsOn": last step waitTitle of part i, "startsOn": first step waitTitle of part i+1, "startsLoggedIn": part i+1's first step login}]}`. With one recording `main` writes the plan itself (unchanged shape).

- [ ] **Step 1: Write the failing tests** — `test_single_recording_shape_unchanged`, `test_two_recordings_chain` (real-180418 + real-174907 → 2 parts, 1 chain entry), `test_second_part_without_login` (`startsLoggedIn is False`, `startsOn` = its first title), `test_cli_accepts_several_paths`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): combine several recordings into one plan (#41)`.

---

### Task 11: Client profiles

**Files:**
- Create: `scripts/profile.py`, `plugins/recording-to-test/profile/defaults.md`, `plugins/recording-to-test/profile/template.md`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `profile.SWITCHES: dict[str, tuple[str, ...] | None]` — allowed values per switch (design §3.6 table; `None` = free text: `standardsSkill`, `defaultEnvironment`, `runCommand`).
- Produces: `profile.parse_front_matter(text: str) -> tuple[dict[str, str], str]`; raises `profile.ProfileError("nested YAML is not supported: line N")` for indented or list lines.
- Produces: `profile.resolve(root: str, project: dict | None, defaults_path: str, today: datetime.date) -> dict` = `{"path", "exists", "switches": {k: {"value", "source": "repo"|"defaults"|"scan"}}, "unknownKeys": [...], "invalid": [{"key","value","allowed"}], "staleFacts": [{"line","verified"}]}`. `auto` resolved from the scan: `sharedValues` = `dataKey` if `dataKey > setCustom` else `setCustom`; `negativeProtocol` = `project` if `projectException > framework` else `framework`; `comments`/`contextNaming` stay `auto` (the wizard reads the exemplar).
- Produces: `profile.init_profile(project: dict, today: datetime.date, template_path: str) -> str` — front matter with resolved switches + `template.md` body filled with LOB prefixes (`testLayout`), roles (`testStyle`), build commands (`build`), guidance files, each fact line ending `(verified YYYY-MM-DD)`.
- Produces: CLI `profile resolve --root R [--project P]` and `profile init --project P [--out F]` (prints to stdout by default; never overwrites an existing file).
- `profile/defaults.md` front matter = the design §3.6 defaults; body = universal facts only (reserved DataKey keys; never run `upgradePages`/`rebuildCode`; generated code is never hand-edited). No client names.

- [ ] **Step 1: Write the failing tests** — `test_flat_front_matter`, `test_nested_yaml_rejected`, `test_repo_overrides_defaults`, `test_auto_shared_values_from_scan`, `test_unknown_key_reported`, `test_invalid_value_reported`, `test_stale_fact_after_90_days` (verified 2026-07-01, today 2026-11-03 → listed; 2026-10-01 → not), `test_init_contains_layout_and_dates`, `test_init_refuses_existing_file`, `test_missing_profile_resolves_to_defaults` (`exists is False`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run all tests** → OK.
- [ ] **Step 5: Commit** `feat(recording-to-test): client profile resolve and init (#41)`.

---

### Task 12: Gap report

**Files:**
- Create: `scripts/gap_report.py`
- Test: `tests/test_gap_report.py`

**Interfaces:**
- Produces: `gap_report.write(plan: dict, field: str, expected: str, got: str, out_dir: str, today: datetime.date) -> str` (path). File `<out_dir>/<YYYY-MM-DD>-<field-slug>.md` with sections: Recording (`recording.id`, `recording.toolVersion`), Plan (`schemaVersion`), Field, Expected, Got, "Send this file to Kimputing (recording-to-test engine)". A second report on the same day and field gets `-2`, `-3`.
- Produces: CLI `gap-report --plan P --field F --expected E --got G [--out-dir D]` (default `.claude/wizard/gaps`).

- [ ] **Step 1: Write the failing tests** — `test_report_written_with_versions`, `test_same_day_same_field_numbered`, `test_no_recorded_values_copied` (plan with a recorded value `"Jane Doe"` → not in the file).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run all tests** → OK; also `python3 plugins/recording-to-test/scripts/ct.py -h` lists all seven commands.
- [ ] **Step 5: Commit** `feat(recording-to-test): engine gap report (#41)`; update the design doc status line to "engine done".
