# Restart points and suites

Propose restart points one by one with their re-run safety, and the suite registration. Part of the
Code plan phase; the result is shown at the Code plan gate ([phases/restart.md#gate](#gate)).

A restart run skips the blocks an earlier run completed, so a long flow resumes where it failed
instead of starting over. **Mandatory** for a test with time travel or a manual step; optional
otherwise.

## Candidates

Read `plan.restartCandidates`: `{afterSeq, kind, reason, rerunRisk, proposePolicy}`. A candidate
exists even without a project (then there is no `project.componentEffects`). Show them in order and
**ask per candidate**, never a blanket yes.

| `kind` | Meaning |
|---|---|
| `setup` | The expensive setup that produces what the scenario acts on (account or policy before a cancellation, change, renewal, rewrite or reinstatement). Strong. `afterSeq` is the end of the setup segment. |
| `centerSwitch` | A switch between centers. Strong. `afterSeq` is the step before the app switch. |
| `stateChanging` | Any work follows a commit (issue, bind, payment, cancel, reinstate, rewrite) anywhere later; `afterSeq` is the commit's step. |

Where no kind fits but a slow step is followed by more work, offer it as a heuristic candidate and
say so; the user decides. A flow of a login plus one or two calls has none: say "no restart point"
and move on. For each candidate show: after which step, the reason, `rerunRisk`, and the policy
proposed.

**Name the restart point for what it represents** (`ACCOUNT`, `POLICY`, `CANCELLATION`), not for
where it sits.

## Rerun safety

A resumed run repeats the block that failed. Decide, per candidate, whether repeating it is safe.

The user's example: a payment goes through, a later step in the same block fails, and the resumed
run pays again, so every later amount check is wrong. The same holds for any commit: issuing twice,
binding twice, cancelling or reinstating twice.

- Read `rerunRisk`. `safe`: the block can run again from the top. `notResumable`: it changes
  back-end state and cannot be resumed half-done.
- Cross-check `project.componentEffects` (`{path, class, commits, afterCommit}`) for every component
  inside the block: a block that holds a commit and also later steps is not safe, whatever the
  engine says about its neighbours. List the components and their commits in the proposal.
- For a `stateChanging` candidate there are two remedies. **Recommended when the scenario allows
  it:** a restart point right after the commit, so a resume never repeats it. Otherwise
  `scenarioContext.restart(X, RestartPolicy.DISABLE_ON_FAILURE)` (`proposePolicy`) on the block
  containing the commit: a failure inside it reruns the test cleanly with new data instead of resuming
  on a broken policy forever. Propose it for every cancellation, reversal, payment or other
  back-end state change.
- Alternative when the block should stay resumable: a back-end state check before redoing the
  commit (is the payment already there?), written as a condition inside the block. It is new logic,
  so it needs its own approval, and it is for new test classes only: not available when making an
  existing test resumable; use `DISABLE_ON_FAILURE` or a new test class.
- Say plainly in the proposal what a resume would do: "resumes after the policy is issued; the
  payment block is not resumable".

## Resume state

A restart restores the values the scenario saved with `Helper.getData(...)`, **not the screen**. Per
restart point, answer: what is the first step after the block, and what does it need open?

- It needs a screen the block left open: add an `else` branch that navigates there (for example a
  policy search). The `else` only re-navigates to the screen the next step needs; no assertions, no
  data changes.
- It re-opens what it needs from the saved values: no `else`.

Say which, and why, for every point. This is the resumed-state check; an `else` is part of the
approved change, not an afterthought.

**Making an existing test resumable** ("make this test resumable") is the single allowed edit to an
existing test class ([SKILL.md#hard-rules](../SKILL.md#hard-rules)). Only restart points change: the
`RestartPoints` enum, the `restart()` / `restartComplete()` blocks and their `else` branches. No new
steps, assertions or data changes. Show it as a diff, get explicit approval at the Code plan gate,
then run a regression run of that test, all its rows
([phases/verify.md#regression-runs](verify.md#regression-runs)). If the test needs anything more,
that part is a new test class.

## Implement

- A `RestartPoints` enum next to the test (or the folder's existing one), one constant per point.
- Around each block:
  `if (scenarioContext.restart(RestartPoints.X)) { … scenarioContext.restartComplete(RestartPoints.X); }`
  plus the agreed `else`. With a policy: `scenarioContext.restart(RestartPoints.X, RestartPolicy.DISABLE_ON_FAILURE)`.
- Follow the folder's tests for the data source and where the point sits
  ([phases/recording.md#generate](recording.md#generate)).
- **String restart points** for multi-center flows or points decided at run time:
  `scenarioContext.appendRestartPointsList("BILLING_REVIEW", …)`, called once before the first
  `restart()`.
- `scenarioContext.getCurrentRestartPointName()` tells which point a run resumes from. Never read
  `getCustom("Restart")` (`DH-003`).
- After the wizard session itself is resumed (not the test), re-verify the generated classes and
  the edited files named in the session state before writing more code: a regeneration or an edit
  outside the chat may have changed them.

## Suites

Read `project.suites`: `{path, suites: {Name: {List|Suites|Packages}}}` (`List`: test entries;
`Suites`: other suites listed by name; `Packages`: package regexes); when the file could not be
parsed it is `{path, suites: {}, raw}`, so show the raw text and ask. Suites group by transaction.

Offer the options with a recommendation and each one's **run cost** (how many scenarios the suite
runs, whether it includes slow flows):

1. an existing suite for this transaction;
2. a new suite listing every test of that transaction;
3. none.

Entry rules:
- Entries are regular expressions per part: `Class`, `Class method`, `Class run (code1|code2)`.
- An entry that matches nothing is reported as a failed scenario, so a typo shows up on the first run.
- `Packages` entries take package regexes.
- Registering a test in a suite is an edit to existing code: approval, shown as a diff
  ([SKILL.md#hard-rules](../SKILL.md#hard-rules)).

## Gate

Part of the Code plan gate ([phases/code.md#gate](code.md#gate)). Show:

- per restart point: name, after which step, kind and reason, `rerunRisk`, policy
  (`DISABLE_ON_FAILURE` or none), the `else` decision with its reason, string or enum;
- components with commits inside a block, from `project.componentEffects`;
- for an existing test: the diff of restart points only, and the regression run of all its rows;
- the suite option recommended, its run cost, and the entries as written.

Wait for an explicit answer per restart point and for the suite.
