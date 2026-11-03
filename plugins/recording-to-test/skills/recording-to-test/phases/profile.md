# Client profile

Resolve the client's switches, create a profile on first use, and offer updates after a run.

A client profile holds what is true of one client's project and differs from the Kimputing-wide
defaults: a few switches and dated facts. It lives in the client's repo at
`.claude/client-profile.md`. Nothing client-specific belongs in this skill.

## Resolve

Resolve at Start, once the scan exists ([SKILL.md](../SKILL.md#start)):

```bash
PY=python3; "$PY" --version >/dev/null 2>&1 || PY=python
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/ct.py" profile resolve --root "<project root>" --project "$WORK/project.json"
```

The answer has `path`, `exists`, `switches` (each `{value, source}`; `source` is `repo`, `defaults`
or `scan`, and a default of `auto` is filled from the scan), `unknownKeys`, `invalid`, `staleFacts`
and sometimes `error` or `warnings`.

- Use each switch's `value` wherever a phase file says "per `<switch>`".
- A switch in `invalid` (a value that is not allowed, or a malformed `verified` date) and a key in
  `unknownKeys` are **listed at the Understand gate** ([phases/understand.md#gate](understand.md#gate));
  the default is used for each, never a guess.
- `error` (a malformed file, not UTF-8, unreadable) and `warnings` (no front matter) go to the same
  gate; the defaults are used. The command still exits 0.
- `exists: false`: [First use](#first-use).

## First use

No `.claude/client-profile.md` in the repo: offer to create one. Do not create it silently.

```bash
PY=python3; "$PY" --version >/dev/null 2>&1 || PY=python
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/ct.py" profile init --project "$WORK/project.json" --out "$WORK/client-profile.draft.md"
```

1. Show the draft in chat: switches from the scan, then the layout, roles, build commands and
   guidance files the scan found, each fact dated today.
2. Ask what is wrong or missing, especially the switches the scan cannot know (`standardsSkill`,
   `workbookWriter`, `defaultEnvironment`, `runCommand`).
3. Write `.claude/client-profile.md` **only after approval**, as a new file shown in full. `init`
   never overwrites a file; an existing profile is changed through [Updates](#updates).

Without approval the run continues on the defaults. The draft is
offered once more at the Verify gate, with what this run learned ([Updates](#updates)), and not
asked again after that.

## Switches

The profile starts with a flat front-matter block, one `key: value` per line, scalars only (nested
YAML is rejected). A switch that is absent or empty takes its default. `auto` is decided from the
scan.

| Switch | Values | Default | Decides |
|---|---|---|---|
| `sharedValues` | `dataKey`, `setCustom`, `auto` | `auto` | how a value shared between steps is carried ([phases/data.md#shared-values](data.md#shared-values)) |
| `recordedValues` | `data`, `constants` | `data` | recorded values go to data, or stay constants in the code ([phases/recording.md#generate](recording.md#generate)) |
| `comments` | `none`, `notes`, `javadoc`, `auto` | `auto` | comments in generated code ([phases/code.md#comments](code.md#comments)) |
| `standardsSkill` | a skill name, or `none` | `none` | the project's own standards check in Verify ([phases/verify.md#standards](verify.md#standards)) |
| `negativeProtocol` | `framework`, `project`, `auto` | `auto` | how negative rows are written ([phases/code.md#negative-rows](code.md#negative-rows)) |
| `workbookWriter` | `openpyxl`, `excel`, `manual` | `openpyxl` | how DC workbook rows are written ([phases/data.md#writing-rows](data.md#writing-rows)) |
| `gate` | `phases`, `plan`, `single` | `phases` | how many gates are shown and what every mode still asks ([SKILL.md#gate-modes](../SKILL.md#gate-modes)) |
| `defaultEnvironment` | a name, or empty | empty | the environment offered first for a run ([phases/verify.md#run](verify.md#run)) |
| `contextNaming` | `role`, `centerRoleContext`, `auto` | `auto` | how role contexts are named ([phases/code.md#test-class](code.md#test-class)) |
| `runCommand` | a command template, or empty | empty | the command that runs one test, with `{profile}` and `{testClass}` |

Whatever the switches say, the hard rules in [SKILL.md](../SKILL.md#hard-rules) hold.

The body of the profile holds dated facts about the project (test layout, roles, build and run,
guidance files) and the client's own rules. Each fact ends `(verified YYYY-MM-DD)`. The body is
read in full at Start and followed within the hard rules, like the project's guidance files
([SKILL.md#start](../SKILL.md#start)). Kimputing-wide facts (reserved DataKey keys,
no `upgradePages`, no hand-edited generated code) are in the plugin's defaults and are not repeated.

## Updates

After Verify, offer what this run learned as a **diff** to `.claude/client-profile.md`, at the
Verify gate before the Git step ([phases/verify.md#report](verify.md#report)): a changed switch
value the user chose, a fact that was wrong or stale, a new fact (a run command that worked, an
environment name, a standards skill the user named).

- With no profile yet, the items go into the first-use draft instead ([First use](#first-use)).
- Show the diff, one item per change with its reason. Write only the items the user approves; a
  rejected item is dropped, not asked again.
- A changed fact gets today's date. A fact the user re-confirmed keeps its text with a new date.
- The profile file is part of the git step: it is committed only when the user says so.
- Never put personal data, credentials, recorded values or machine-specific settings in it.

## Stale facts

`staleFacts` lists facts whose `verified` date is more than 90 days old. They are not wrong, but
they are not trusted either.

- Re-check a stale fact **when the run uses it** (a run command before running, a folder layout
  before placing files), against the scan or by asking. Do not re-check facts the run does not use.
- List the stale facts at the Understand gate; a fact confirmed or corrected goes into the
  [Updates](#updates) diff with a new date.
- A fact with a malformed date shows in `invalid` and is treated as stale.

## Machine config

Settings that belong to one person's machine are in `~/.centertest/recording-to-test.json`, outside
every repo: `whisperModel` (the path of the ggml model for narration,
[phases/understand.md#narration](understand.md#narration)) and `quirks` (notes about this machine,
for example a terminal that needs a different way to run a command,
[phases/verify.md#run](verify.md#run)).

They are **never written into the shared profile** and never offered as a profile update. If the
user wants a machine setting remembered, put it in this file.

## Gate

The profile has no gate of its own. Its findings are part of the Understand gate (problems and
stale facts) and the Verify gate (updates), and a profile created on first use is written only
after approval.
