# recording-to-test 2 — scenario wizard design

- **Issue:** kimputing/centertest-skills#41
- **Date:** 2026-11-03
- **Requirements:** `2026-11-03-scenario-wizard-requirements.md` (cited as R§n)
- **Status:** design and plans written (`docs/superpowers/plans/2026-11-03-wizard-{engine,skill,quality}.md`); implementation not started

## 1. Shape

Three parts, each shipped and tested on its own:

| Part | What | Plan |
|---|---|---|
| Engine | Python scripts: scan, parse, data/flow matching, narration, profile, gap report | `2026-11-03-wizard-engine.md` |
| Wizard | `SKILL.md` router + phase files + profile defaults | `2026-11-03-wizard-skill.md` |
| Quality | CI, eval harness, changelog / schema-version guard, recording scrubber | `2026-11-03-wizard-quality.md` |

The engine produces facts and candidates; it never decides. The wizard turns candidates into
questions at the gates (R§4). The existing split ("scripts gather facts, the model makes the
judgment calls") is kept.

## 2. Plugin layout

```
plugins/recording-to-test/
├── .claude-plugin/plugin.json
├── CHANGELOG.md                       # new (quality plan)
├── profile/
│   ├── defaults.md                    # Kimputing-wide switch defaults + universal facts
│   └── template.md                    # body of a new .claude/client-profile.md
├── scripts/
│   ├── ct.py                          # single entry point: ct.py <command> …
│   ├── schema.py                      # PLAN_SCHEMA_VERSION, PROJECT_SCHEMA_VERSION, PLAN_FIELDS
│   ├── parse_recording.py             # extended (schemaVersion, several recordings, narration hook)
│   ├── scan_project.py                # extended (dataWorkbooks, sharedValuesUsage, …)
│   ├── find_getter.py                 # vendored, unchanged
│   ├── xlsx_read.py                   # moved from the client wrapper, importable
│   ├── flow_match.py                  # facadeSequence, existingTests
│   ├── data_match.py                  # dcColumns, dataRowCandidates
│   ├── restart.py                     # restartCandidates, seedPointCandidates
│   ├── narration.py                   # transcripts / whisper → utterances per step
│   ├── profile.py                     # resolve / init client profiles
│   ├── gap_report.py                  # engine gap report for Kimputing
│   └── scrub_recording.py             # quality plan
├── skills/recording-to-test/
│   ├── SKILL.md                       # router, < 300 lines
│   └── phases/{understand,recording,reuse,code,data,restart,verify,profile}.md
├── evals/                             # quality plan: harness only, no client cases
└── tests/
```

### 2.1 Entry point and interpreter (R§5.4)

Every command goes through `ct.py`, so the skill has one launcher snippet:

```bash
PY=python3; "$PY" --version >/dev/null 2>&1 || PY=python
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/ct.py" <command> …
```

Commands: `scan`, `parse`, `xlsx`, `narrate`, `profile`, `tools`, `gap-report`. Each maps to a
module's `main(argv)`; the old `parse_recording.py` / `scan_project.py` command lines keep working.
External tools are found with `shutil.which`, never `command -v` (repo rule).

### 2.2 Sub-skills vs phase files (R§3, questionnaire I1)

**Decision: phase files, not separately triggered skills.** Each phase is
`skills/recording-to-test/phases/<phase>.md`, loaded by the router when that phase starts, so the
context holds one phase at a time (the goal of I1). Separate skills would each need a description
with trigger phrases, which reopens RT2 (several skills matching "create a test"). If a phase later
proves useful on its own (e.g. data), it can be promoted to a skill whose description says it runs
only inside the wizard. **Flagged for review.**

### 2.3 References with anchors (R§3, R§11)

Cross-references are `phases/<file>.md#<anchor>`. An anchor is a heading's GitHub slug or an
explicit `<a id="…"></a>`. `tests/test_skill_md.py` fails on a missing file or anchor, a `ct.py`
command or flag that doesn't exist, a `plan.<field>` not in `schema.PLAN_FIELDS`, a `$<digit>`,
or a `SKILL.md` over 300 lines.

## 3. Engine

### 3.1 Schema version (R§5.1)

`schema.py` holds `PLAN_SCHEMA_VERSION = 2`, `PROJECT_SCHEMA_VERSION = 2` (today's output is
version 1, unversioned) and `PLAN_FIELDS`, the top-level plan keys. Both JSON outputs carry
`"schemaVersion"`. The wizard refuses a plan whose major version it doesn't know and says to update
the plugin. Fields are only added; a removal or rename needs a version bump and a changelog entry.

### 3.2 Project scan additions

| Fact | Value | Used for |
|---|---|---|
| `dataWorkbooks` | `[{path, sheets: {name: {columns, codes, rows}}, usedBy: [test paths]}]` for every `*.xlsx` under `testdata/` | `dcColumns`, row rule 6.1.4 ("which tests a new row widens") |
| `sharedValuesUsage` | `{setCustom: n, dataKey: n, reservedKeyMisuse: [{path, key}]}` | default for `sharedValues`; reserved keys `PolicyExpirationDate`, `UserName`, `Password`, `Premium` |
| `negativeProtocol` | `{projectException: n, framework: n}` | default for `negativeProtocol` |
| `suites` | `{path, suites: {name: [entries]}}` from `CenterTestSuiteList.json` | suite registration options |
| `componentEffects` | `[{path, class, commits: [kind], afterCommit: bool}]` | re-run safety (R§7) |

`commits` kinds: `issue`, `bind`, `payment`, `cancel`, `reinstate`, `rewrite`, `submit`, found by
call/label patterns in the class. `afterCommit` is true when actions or checks follow the first
commit in the file: the payment example (paid, then a later step fails, a resume pays again).

### 3.3 Plan additions

| Field | Shape | Notes |
|---|---|---|
| `schemaVersion` | `2` | |
| `facadeSequence` | `[{seqs, pages, titles, candidates: [{facade, method, score, why}]}]` | segments by page (as the skill segments today); candidates only from `contextOnly` facades whose pages and titles overlap |
| `existingTests` | `[{path, folder, coveredSeqs, missingSeqs, score}]` | tests whose `flow` calls the candidate facades in order |
| `dcColumns` | `[{seq, label, value, workbook, sheet, column, why}]` | label tokens vs header tokens (camel split, `#`/`@` stripped, case-folded) |
| `dataRowCandidates` | `[{workbook, sheet, code, matched, total}]` | rows whose mapped cells equal recorded values; top 3 per workbook |
| `restartCandidates` | `[{afterSeq, kind, reason, rerunRisk, proposePolicy}]` | `kind`: `setup`, `centerSwitch`, `stateChanging`; `rerunRisk`: `safe` / `notResumable`; `proposePolicy`: `DISABLE_ON_FAILURE` or null |
| `seedPointCandidates` | `[{seq, seed, why}]` | `NEW_ACCOUNT`, `PRE_QUOTE`, `QUOTED`, `ISSUED_POLICY`, `CLAIM` |
| `narration` | `{source, segments, utterances: [{seq, t, text, asksCheck?, conditional?}], reason?, install?}` | `source`: `transcript` / `whisper` / `unavailable` / `none` |
| `parts`, `chain` | only when several recordings are given | see 3.5 |

Each utterance is also appended to `plan.notes` with `"source": "narration"`, so `noteChecks`
works on spoken notes without a second pipeline.

### 3.4 Narration (R§5.3)

1. `session.audio = [{f, t}]` (WebM/Opus, `t` ms since `startedAt`). None → `source: "none"`.
2. For each segment, a transcript next to the audio file wins:
   `audio/<stem>.transcript.json` = `{"segments": [{"start": ms, "end": ms, "text": "…"}]}`, times
   relative to the segment. **This is the contract proposed to `centertest-recorder`** (its issue
   is opened separately).
3. Otherwise `ffmpeg -i <seg>.webm -ar 16000 -ac 1 <seg>.wav` then
   `whisper-cli -m <model> -f <seg>.wav -oj -of <seg>`; read `transcription[].offsets.{from,to}`
   and `.text`. The model path: env `RECORDING_TO_TEST_WHISPER_MODEL` > `whisperModel` in
   `~/.centertest/recording-to-test.json` > none.
4. Any tool missing → `source: "unavailable"`, `reason`, and `install` steps per OS
   (`brew install ffmpeg whisper-cpp`; `winget install ffmpeg` + whisper.cpp release zip;
   `apt install ffmpeg` + build). The wizard then asks for the key points (R§5.3).
5. Utterance time = `seg.t + start`. Step time = `step.time − startedAt`. An utterance belongs to the
   last step whose time is ≤ the utterance's (the screen showing while it was said).

Audio is read through a byte reader (`file_bytes`, same lookup as `file_reader`), extracted to a temp
folder, and deleted afterwards. Nothing is uploaded.

### 3.5 Several recordings (R§2)

`ct.py parse a.zip b.zip …` builds one plan per recording, then
`{"schemaVersion": 2, "parts": [plan…], "chain": [{fromPart, toPart, endsOn, startsOn, startsLoggedIn}]}`.
A single recording keeps today's shape (plus the new fields). The wizard treats each part's start
like a recording that doesn't begin with a login, with "chain after part n" as the first option.

### 3.6 Client profile (R§10)

- `profile/defaults.md` and the repo's `.claude/client-profile.md` both start with a **flat**
  front-matter block (`key: value`, one per line, scalars only; stdlib has no YAML parser, so nested
  YAML is rejected with a message).
- `ct.py profile resolve --root <repo>` → `{path, exists, switches: {key: {value, source}},
  unknownKeys, staleFacts}`; `source` is `repo`, `defaults` or `scan` (a default of `auto` is filled
  from the scan: `sharedValues` from `sharedValuesUsage`, `negativeProtocol` from `negativeProtocol`,
  `comments` / `contextNaming` from the exemplar).
- `ct.py profile init --project project.json` → a draft `client-profile.md` (switches from the scan,
  body from `template.md` with the scan's layout, roles, build commands and guidance files, each fact
  dated today). The wizard shows it and writes it only after approval.
- Dated facts: a body line ending `(verified YYYY-MM-DD)`. `staleFacts` lists those older than 90 days.
- Switches and allowed values:

| Switch | Values | Default |
|---|---|---|
| `sharedValues` | `dataKey`, `setCustom`, `auto` | `auto` |
| `recordedValues` | `data`, `constants` | `data` |
| `comments` | `none`, `notes`, `javadoc`, `auto` | `auto` |
| `standardsSkill` | skill name or `none` | `none` |
| `negativeProtocol` | `framework`, `project`, `auto` | `auto` |
| `workbookWriter` | `openpyxl`, `excel`, `manual` | `openpyxl` |
| `gate` | `phases`, `plan`, `single` | `phases` |
| `defaultEnvironment` | name or empty | empty |
| `contextNaming` | `role`, `centerRoleContext`, `auto` | `auto` |
| `runCommand` | command template or empty | empty |

Machine config `~/.centertest/recording-to-test.json` (`whisperModel`, `quirks`) is personal and
never read into the shared profile (R§9).

### 3.7 Gap report (R§3)

`ct.py gap-report --plan plan.json --field <plan field> --expected … --got … --out-dir <dir>` writes
`<dir>/<date>-<field>.md`: recorder `toolVersion`, recording id, plan `schemaVersion`, field,
expected, got. No recorded values beyond what the user typed into `--expected` / `--got`. The
wizard puts it in `.claude/wizard/gaps/` and tells the user to send it to Kimputing.

## 4. Wizard

### 4.1 Phases and gates (R§4)

| Phase | File | Gate shows |
|---|---|---|
| Understand | `understand.md` | inputs read, center/LOB/transaction, start state, narration, missing facts |
| Reuse plan | `reuse.md` | ladder result per action, `existingTests`, variants, new components |
| Data | `data.md` | mechanism per value, rows/columns with sources, widened tests |
| Code plan | `code.md` + `restart.md` | files, overrides, restart points with re-run safety, tags, suite |
| Write | `code.md` | diff per file |
| Verify | `verify.md` | compile, runs, regressions, healthcheck, standards, run-vs-recording differences |

Recording-specific rules (today's §3–§9) move to `recording.md` with anchors; `understand.md`
and `reuse.md` link into it. Fixes made during the move: variants override `protected` hooks
(RW4); shared values per `sharedValues` (RW5); comments per `comments` (RW5); recorded values per
`recordedValues` (RW2).

### 4.2 Session state and plan file (R§4)

- State: `~/.centertest/recording-to-test/sessions/<repo-dir-name>-<scenario>.json` (phase reached,
  answers given, files written). "Resume <scenario>" reloads it.
- Plan: `.claude/wizard/<scenario>.plan.md` in the repo. On first use the wizard proposes adding
  `.claude/wizard/` to `.gitignore` (an approved edit).

### 4.3 Run vs recording comparison (R§9)

After a passing run, the wizard lists per recorded step: the recorded title vs the run's page
title from the narrative, and the recorded screenshot next to the run's screenshot for that step
(paths, for the user to open). Differences in title, order or missing screens go to the user; the
wizard does not decide them.

## 5. Quality

- **CI:** `.github/workflows/tests.yml`, matrix Ubuntu / macOS / Windows × Python 3.9 / 3.12, runs
  every `plugins/*/tests`.
- **Evals:** `evals/run_evals.py` runs engine-level cases (`ct.py scan` + `parse` against a project
  and recording, then checks expected plan values). **Cases live outside this public repo** (path
  from `--cases` or `CT_EVALS_DIR`), because client recordings and projects are private.
- **Changelog guard:** `CHANGELOG.md`; a test fails when `PLAN_SCHEMA_VERSION` or
  `PROJECT_SCHEMA_VERSION` isn't named in the top entry after a change.
- **Scrubber:** `scrub_recording.py` replaces hosts, names and typed values in a recording so it can
  be shared as a fixture (still kept private unless reviewed).

## 6. Decisions to confirm at review

1. **Phase files instead of separately triggered sub-skills** (2.2).
2. **Client recordings and eval cases in a private location** (5). R§11 asked for per-client
   fixtures in this repo; it is public, so only synthetic fixtures live here.
3. **`xlsx-read.ps1` is not carried over.** The wizard requires Python already; one reader is enough.
4. **Flat front matter** in profiles (3.6), no nested YAML.
5. **Transcript contract** for the Recorder: `audio/<stem>.transcript.json` (3.4).

## 7. Outside this repo

- `centertest-recorder`: transcript file per audio segment (3.4 contract).
- The client project with `new-scenario`: `client-profile.md` and retiring `new-scenario` (R§12).
