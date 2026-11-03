# Reuse plan

Walk the reuse ladder for every action and decide what is reused, overridden or new. Nothing new is
drafted while the plan waits for approval.

## Ladder

The order is strict ([SKILL.md#hard-rules](../SKILL.md#hard-rules)); stop at the first rung that
holds, and say which one it was:

1. **An existing test** covers the scenario ([Existing tests](#existing-tests)).
2. **A data row** of an existing test fits the values
   ([phases/data.md#existing-row](data.md#existing-row)).
3. **An override column** on a row varies a reference
   ([phases/data.md#override-column](data.md#override-column)).
4. **A step override**: an existing component that almost fits, with its `protected` hooks
   overridden ([Variants](#variants)).
5. **New code**: a new step, facade call or test class, only for a gap that rungs 1-4 cannot close
   ([Bootstrap](#bootstrap)).

Each rung is checked by **reading the class**, never by its name: a match on a name is a candidate,
not proof. Open the component and compare what it does with what the scenario needs.

For every segment of `plan.facadeSequence` report one line that reflects behaviour, not only the
name: which rung, which class, what it drives, what state it leaves for later steps.

**A scenario that needs an extra step is a new test class.** An existing test that covers the flow
but lacks one more step (an `assertXYZ` after a submission) is never extended in place: the
scenario becomes its own new test class (`...XYZTest`) that reuses the same components
([phases/code.md#test-class](code.md#test-class)). Existing test classes stay as they are. The one
exception is making an existing test resumable: [phases/restart.md#resume-state](restart.md#resume-state)
and [phases/restart.md#implement](restart.md#implement).

**Gap: stop.** State exactly what has no component and ask before writing one. A recorded screen
with no matching component is a gap to propose, not a reason to replay its clicks, and a gap is
proposed one at a time.

## Existing tests

`plan.existingTests` lists tests whose `flow` already runs the recording's facade candidates in
order: `path`, `folder`, `coveredSeqs`, `missingSeqs` and `score`. The `score` is the covered
segments divided by **all** segments, so 1.0 means every segment is covered and a lower score
means the tests miss part of the scenario; `missingSeqs` names the recorded steps they do not run.

- The engine gives the list without knowing where the scenario belongs. **Rank it against the folder
  the user's scenario belongs to** (center, LOB, transaction): tests in that folder first, then the
  others by `score`. The same transaction in another LOB is the reference implementation: read it in
  full and list what is LOB-specific and what is not.
- Read the test. A flow match shows the facade calls ran, not that the data fits: compare the
  values the scenario needs with the test's data
  ([phases/data.md#existing-row](data.md#existing-row)).
- `score` 1.0 and the data fits: no new test; say so first. `missingSeqs` empty of anything the
  user cares about: same. Missing segments: the scenario is a new test class that reuses the
  covering test's components and adds the rest. Never an edit to the covering test.
- No candidates: say so, and go on with the facade check.

Also search the components for a class that already does the transaction but has no facade factory
or no caller: an unfinished component is a candidate (a reinstatement with a hard-coded reason).

## Facade check

For each segment, the candidates in `plan.facadeSequence` carry the facade, method, `step` (the
class the factory builds), `score` and `why`. A candidate is where the check starts
([phases/recording.md#facade-match](recording.md#facade-match)). For each one:

1. Open `step`. Does it drive the same pages and reach the same screen titles?
2. Does it rely on state this test does not create (a policy number read from the shared test data
   while the recording typed one)? Then it is not a match.
3. Does it take data objects the scenario has no row for? Then it resembles a facade rather than
   being one: say which, and let the ladder decide between a row for it and a new step.
4. Is it LOB-agnostic (a shared folder, a shared data type) or LOB-specific? Note it for
   [phases/code.md#placement](code.md#placement).
5. What does it set for later steps (job, policy, account numbers)? Note it: a later step that reads
   it needs this one to have run.
6. A **new value shared between steps** is shared per `sharedValues`
   ([phases/data.md#shared-values](data.md#shared-values)).
7. A **date- or rule-dispatched factory** (one that picks a subclass): never subclass the concrete
   class in a test. The difference is a hook on the abstract base ([Variants](#variants), rung 4).
8. A **hard-coded value** the scenario needs to vary moves to data: a `final` field set in the
   constructor and fed from a column, not a per-test override. An approved edit.

A facade call is a facade call only when all three conditions of
[phases/recording.md#facade-match](recording.md#facade-match) hold; otherwise the segment is a
variant or new.

## Variants

When an existing component almost fits, climb these rungs and stop at the first that works:

1. **Use it as is**, if its flow already fits.
2. **Override its protected hooks.** Read the base `execute()`. Skip a step with an **empty
   override**; change one with an override that calls `super` where it is still wanted. Extra work
   at the end is `super.execute()` followed by the extra step. Never a copy of the base sequence.
3. **A base step is private**: make it `protected`. An approved edit.
4. **No step exists at the point that differs**: add **one** generically named hook to the base,
   call it from the base `execute()`, and move the existing code into it. An approved edit; list
   **every other caller of the base** in the plan, each gets a regression run
   ([phases/verify.md#regression-runs](verify.md#regression-runs)).
5. **A new component** ([Bootstrap](#bootstrap)), only when none of the above fits.

The base owns the flow: a variant's `execute()` is `super.execute()` plus extras. Also:

- No per-variant method names, no copied base sequence, no static helper for logic a base class can
  own.
- Do not override to return a constant the base could hard-code: change the base (an approved
  edit).
- A subclass with no data for a step: the base step returns early on the null or empty value, with
  no empty override in the subclass for that.
- The same code in two or more tests belongs in the shared component.
- An inner subclass gets a descriptive name, is `private`, and moves to the components folder once
  a second test needs it.

**Allowed edits to existing code**, each shown in the plan with the files it touches and approved
one by one ([SKILL.md#hard-rules](../SKILL.md#hard-rules)):

| Edit | Plan lists |
|---|---|
| Make a private step `protected` | the class, the step, every subclass of the base |
| Add one generic hook to a base | the hook, the moved code, every other caller of the base (regression run) |
| Add a facade factory method | the facade file, the method, the step it builds |
| Move a hard-coded value to data | the value, the column, every caller (regression run) |
| Register the test in a suite | [phases/restart.md#suites](restart.md#suites) |

A smell found on the way is reported at the end, not fixed.

## Bootstrap

Use this for an approved gap, and for every screen group in a project that has no reusable
components yet. The rules for writing the step are in [phases/recording.md](recording.md#generate);
what is added here is the shape later scenarios can override:

- **A base with steps.** One class per transaction whose `execute()` is a flat list of `protected`
  step methods, one per wizard screen ([phases/code.md#step-shape](code.md#step-shape)). When the
  project already has an abstract base for the transaction, extend it and override only what
  differs. No long `execute()` of raw clicks.
- **Values come from data** when the project has a data layer
  ([phases/data.md#mechanisms](data.md#mechanisms)); with none,
  [phases/data.md#no-data-layer](data.md#no-data-layer).
- **Shared or LOB folder:** asked ([phases/code.md#placement](code.md#placement)).
- **One gap at a time.** Propose each new component with its steps, constructor, factory and the
  recorded seqs it replaces; wait for approval before the next.
- **A reusable step is written** so it can be reused:
  - the constructor only stores inputs (constructing a step already opens the center's browser, so a
    facade returns the step without running it, and a test constructs a step where it runs it);
  - action and verification are separate methods, and a check other flows may want is its own
    `Assert*` reusable ([phases/code.md#assertions](code.md#assertions));
  - `waitForPageTitle` at the start of each step method or right after the navigation that opens the
    screen, and at the end when the step leaves you on another screen; several possible landings are
    `waitForPageTitle("A", "B")` and then a branch on the page title;
  - seed points at logical step ends, `seed(GwSeedPoint.<value>)`
    ([phases/code.md#seed-points](code.md#seed-points));
  - an unexpected business state is a small data-aware exception whose message names the data, not a
    bare assertion failure.

## Gate

Show, for every segment: the rung it reached and why, with the class read and the plan field as
evidence (`plan.existingTests` ranked against the scenario's folder, `plan.facadeSequence`).

- Per segment: facade call, existing step, variant or new step, and why, as in the table in
  [phases/recording.md#gate](recording.md#gate); the base class and what it uses; retries
  collapsed; blocker screens and their helper; Quote and Issue through the base; navigation;
  helpers from another wizard (reuse or generalise).
- Existing tests with `score` and `missingSeqs`; which one the scenario reuses, or that it is a new
  test class.
- Each variant: base, hooks overridden (empty ones too), hooks made `protected` or added, the other
  callers that need a regression run.
- Each new component: steps, constructor, factory, seqs replaced.
- Allowed edits, each for a yes or no.

Up to 4 questions per batch, each with a recommendation and its evidence.
