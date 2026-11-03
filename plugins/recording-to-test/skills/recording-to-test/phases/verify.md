# Verify and deliver

Compile, run, regression runs, healthcheck, standards, compare with the recording, report, git.

**One order, used everywhere:** compile, run, regression runs, healthcheck, standards, compare
with recording, report, git. Fix rounds happen inside the run (and any regression run) until it
passes. One exception: if this run's changes are not committed when the healthcheck runs and the
user commits at the Git step, the healthcheck runs once more as the very last action and its
findings are appended to the report.

Be honest about verification: say what compiled, what ran, which rows passed and what was not run.
Try the commands yourself first. If one fails for an environment reason (a build that cannot run
from this shell, missing credentials), hand the user the exact command to run in their own
terminal, then read the result. Machine quirks of that kind belong in the personal config, never
the shared profile ([phases/profile.md#machine-config](profile.md#machine-config)). Missing
credentials (`CENTERTEST_TOKEN`, repository keys) are reported, never worked around.

Mask token-like and personal values when quoting a log, a narrative or a screenshot.

## Compile

Compile automatically; no question needed. Use `project.build.compile`, from the project root.
Read the output for `BUILD SUCCESSFUL`, `BUILD FAILED`, `error:` and `cannot find symbol`.

On errors, fix **only files this run created or edited**, show each change, and recompile. After 3
rounds stop and report what is left. A compile error in a file the run did not touch is reported,
not fixed ([SKILL.md#rule-unrelated-code](../SKILL.md#rule-unrelated-code)).

After a DC regeneration, verify the generated classes first
([phases/data.md#regeneration](data.md#regeneration)).

## Run

Never run against an environment without the user's yes. Ask:

1. **Run now?** If not, the report says the test was compiled but not run.
2. **Which environment?** Per `defaultEnvironment`, the profile's default comes first as the
   recommended option. Offer **"no profile (default environment)"** first when the profile names
   none: a plain run with the environment from the project's `customer.centertest.properties`,
   the usual case. Then offer each of `project.build.profiles`.

Run only the new test (or the new rows of it): the command is `project.build.run`, or the one per
`runCommand` when the profile sets it; fill in `{profile}` and `{testClass}`; with no profile,
leave the profile argument (`-Pprofile={profile}`) out. When `project.build.run` is `null`, the
project's `bootRun` reads `-P` properties (`project.build.bootRunProperties`) but none that
selects a test:
ask how this project runs a single test (often `-Pprofile=… -Pfilter=…` or a suite file); don't
guess.

Before reading the result, check that the **scenarios scheduled equal the rows selected**. A
different number means the row filter or the suite entry is wrong
([phases/data.md#validate](data.md#validate)).

Read the result: status per scenario and the error code from the runner output, and, for what data
was really used, the per-row narrative and last screenshot (see Fix rounds). Look an error code up
in the CenterTest documentation (the `centertest-mcp` `search_documentation` or
`analyze_stacktrace` tools when connected, otherwise the docs portal; never sign in for the user)
before debugging it. Say whether the failure is in the changed code's path (the stack trace passes
through methods this run wrote or edited) or after it.

When the run fails: [Fix rounds](#fix-rounds). When it passes: [Regression runs](#regression-runs),
then [Healthcheck](#healthcheck), [Standards](#standards), [Compare with
recording](#compare-with-recording), [Report](#report) and [Git](#git), in that order.

## Fix rounds

**Until it passes, asking before each round**: show what the evidence says and what the next fix
would be, and wait for the user's yes before editing and rerunning. The user may stop at any
round; the report then says what still fails. In "Just run it" mode: up to 3 rounds without
asking, then stop and report ([SKILL.md#just-run-it](../SKILL.md#just-run-it)).

**Read the run's evidence first.** It is in `results/<timestamp>/<test>/TestRecord/`:
- the `*_Narrative.html`: each step, the failing widget and the error, and the page title per step;
- `Screenshots/`: one image per step, the last one is where the run stopped;
- `logs/` has the runner log but no page detail; use it for the stack trace only.

Then:
1. **Screen first.** When a widget is not found (`WI-005`) or a click times out,
   check the screen before the id: look at the last screenshot and the page title the narrative
   shows first. If the page is not where the step expected (still blocked by underwriting
   issues, a validation error, a warning to accept, another wizard step), the missing widget is
   a symptom: handle that
   screen (the project's blocker helper, the missing required field, the accepted warning)
   instead of patching the id.
2. Only when the right page is shown, fix the getter. If it ends in `.withCssId(…)` or is raw,
   check the recorded id against the page; an id that cannot be resolved goes through the
   `cssid-finder` skill ([phases/recording.md#locators](recording.md#locators)).
3. Data problems (a code no sheet knows, an empty required cell) go back to
   [phases/data.md#validate](data.md#validate); never invent a value.

**Fix only files this run created or edited**, plus the edits the project's guidance asked for.
A cause in code the run did not touch is reported to the user, who decides. Show each change and
rerun only after the user's yes.

When the cause is the engine (the plan said one thing, the recording shows another), do not work
around it silently and never patch the engine: [Engine gaps](#engine-gaps).

## Regression runs

Run every caller listed at the Code gate ([phases/code.md#gate](code.md#gate)) after the new test
passes, each with the same environment answer:
- every other caller of a base that was edited: the variants and the tests that use it;
- every row of an existing test made resumable
  ([phases/restart.md#resume-state](restart.md#resume-state)).

Ask once for the list ("these N callers, this environment"), then run them. A regression that
fails is reported with its evidence; whether the changed base or the test is at fault is the
user's decision, and the fix follows [Fix rounds](#fix-rounds), asking before each.

## Healthcheck

Invoke the `centertest-healthcheck` skill (as a skill, never by script path). It analyses the
**last commit**, not uncommitted files; say so. If this run's changes are not committed yet, say in
the healthcheck result that it saw none of them; the one re-run after a commit at
[Git](#git) is the exception in the order at the top of this file.

Report findings **in the files this run changed only**, grouped by file. Findings elsewhere are
not listed. Delete the report folder the skill wrote when it is done. Fix nothing until the user
picks.

## Standards

After the healthcheck, before the comparison and report. Per `standardsSkill`:
- a skill is named: run it in its pre-PR mode over this run's diff;
- none: the built-in checklist over the diff (SKILL.md hard rules and allowed edits,
  [SKILL.md#hard-rules](../SKILL.md#hard-rules)):
  1. reuse first: nothing rebuilt that a test, row, override column or step already gives;
  2. no existing test class changed (except restart points) and the edits made are on the allowed
     list, each approved;
  3. the base owns the flow: variants override `protected` hooks, `execute()` is `super.execute()`
     plus extras, no re-listed sequence, no per-variant method names, no new static helper for
     logic a base could own;
  4. no copied code, no generated code edited, no value invented;
  5. shared values per `sharedValues` ([phases/data.md#shared-values](data.md#shared-values));
     never a reserved built-in key (`PolicyExpirationDate`, `UserName`, `Password`, `Premium`); null
     and empty guards sit in the base, not in empty subclass overrides;
  6. nothing unrelated touched.

**Report only; fix nothing until the user picks** which findings to fix.

## Compare with recording

Only when the input was a recording and the run passed (otherwise n/a). Compare the run's screens
with the recording's **screen by screen**, per recorded step of the plan (`plan.steps`, skipping
those the plan dropped as navigation, retries or verify-only):

| `seq` | Recorded title | Run's title (narrative) | Recorded screenshot | Run's screenshot |
|---|---|---|---|---|

- **Recorded title:** the plan step's `title` (and `waitTitle`) for that `seq`.
- **Run's title:** the page title in the `*_Narrative.html`. Match a narrative entry to a `seq` by
  the order of the screens in the narrative, and confirm each by its title; where the order and
  the title disagree, that is a difference to list, not a match to force.
- **Recorded screenshot:** read `steps[].screenshot` (`shots/NNNN.jpg`; also `before` / `full` when
  useful) from the recording's `session.json`, matched by `seq`. The path is relative to the
  recording folder; for a zip, extract it to the session's work folder (`$WORK`) first so the user
  can open the file.
- **Run's screenshot:** the matching file in the run's `Screenshots/`.
- The screenshot columns are **paths** for the user to open. Do not describe the images.
- List every difference: a different title, steps in another order, a recorded screen the run
  never showed, a run screen the recording never had. Mark steps that match as `same`.

**Several recordings:** compare each part with its own `session.json` and its own steps
(`plan.parts`), rows named `part:seq`; the seams (`plan.chain`: a dropped login, a step between the
parts) are listed like any other difference.

**Every difference goes to the user; the wizard does not decide** whether it is acceptable,
a generated simplification (a collapsed retry, navigation replacing a Next click) or a defect. Say
which of the plan's recorded decisions could explain it (`plan.retries`, `plan.blockers`,
`plan.navigation`), and leave the call to the user. If the user says the run is wrong, that is a
new [Fix round](#fix-rounds).

With no differences, say so in one line.

## Report

A summary in chat and a **PR description draft** (the same facts, written for a reviewer).

Report plainly: compiled or not, ran or not (which environment), which rows passed, what was not
run. Then:

- files created; existing files edited, each with its reason and the approval; facades and helpers
  reused; helpers from another wizard reused or generalised;
- every `rule`, `raw` or `partial` getter and whether it compiled; untranslated items; `key` and
  `dialog` items mentioned;
- retries and validation loops collapsed (which recorded steps became which lines); Next clicks
  replaced by navigation; blocker screens and the helper used for each; Quote / Issue routed
  through the base; verify-only screens dropped or turned into final checks; final checks added;
- the start chain chosen and any return helper in between;
- dates (typed or calendar-picked, the relations chosen); generated identity values; picks that
  depend on existing data; radios in rows (clicked and checked); rows read by id on a bound job;
  pinned ids (`withCssId`) and why; values derived from data and what they were compared with;
  notes with a condition and what was chosen;
- data: rows or columns added, the workbook, tests widened, TODOs for the data layer
  ([phases/data.md#gate](data.md#gate)); restart points added and suite entries, or the suite
  file and the class to add when the guidance does not say to edit it;
- regression results, healthcheck findings in changed files (state that it saw the last commit),
  standards findings, and run-vs-recording differences with the user's decisions;
- **every default taken without asking** when the user said to just run it
  ([SKILL.md#just-run-it](../SKILL.md#just-run-it));
- engine gap reports written, with their paths.

Personal data in the PR draft is masked, and recorded values do not appear in it.

Offer the profile updates this run found here, before Git, as a diff for approval
([phases/profile.md#updates](profile.md#updates)).

## Git

Asked at the end, never earlier, and never done without the user's yes. Offer **any of**: branch,
commit, PR; the user picks which. The repo is on GitHub or Azure DevOps: read the remote and use
`gh` or `az repos` accordingly; if the tool is missing, give the command to run.

- **Branch:** linked to its issue or work item (the Jira key, GitHub issue number or Azure DevOps
  work item id from the input, else ask), named after the project's convention.
- **Commit:** only this run's files; recorded files, `project.json`, `plan.json` and
  `.claude/wizard/` are never committed ([SKILL.md#session-state-and-plan-file](../SKILL.md#session-state-and-plan-file)).
  The message follows the project's convention and references the issue or work item.
- **PR:** the PR description draft from [Report](#report), the issue or work item linked.

If the user commits and the healthcheck ran before the commit, run it once more now as the very last
action and append its findings to the report (the order at the top).

## Engine gaps

When a problem is in the engine (a plan field wrong or missing for what the recording shows, a
scan fact that is false), work around it with the user and write a gap report with `ct.py gap-report`; never patch the
engine:

```bash
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/ct.py" gap-report --plan "$WORK/plan.json" --field "<plan field>" \
  --expected "<what it should be>" --got "<what it is>" --out-dir ".claude/wizard/gaps"
```

`--expected` and `--got` are copied verbatim into the report: **describe the gap
without recorded values** (`a date field`, `a policy number`, not the value). Tell the user to send the printed
file to Kimputing, and list it in the report. See also [SKILL.md#engine-gaps](../SKILL.md#engine-gaps).

## Gate

Show:
- compile result and the rounds it took;
- run: environment, scenarios scheduled vs rows selected, status per row, fix rounds taken;
- regression runs: callers run and their results;
- healthcheck findings in changed files (last commit only) and standards findings, to be picked;
- run vs recording: the table and every difference, awaiting the user's decision (n/a when the
  test was not run or did not pass);
- the report and PR description draft;
- the profile updates this run found, as a diff;
- the git options (branch, commit, PR) for the user to pick.

Wait for an explicit answer on each difference, each finding, each profile update and each git
option. A post-commit healthcheck re-run, if any, is the last action.
