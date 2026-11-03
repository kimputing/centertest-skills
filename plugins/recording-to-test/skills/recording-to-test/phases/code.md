# Code plan and write

Plan the files, step shape, assertions, tags and test class, then write them one file at a time.

## Step shape

- **One class per transaction.** `execute()` is a flat list of `protected` step methods, one per
  screen (`policyInfoStep(); vehiclesStep(); quoteStep(); issueStep();`). No long `execute()` of
  raw clicks.
- A variant of an existing base overrides its hooks and its `execute()` is `super.execute()` plus
  extras ([phases/reuse.md#variants](reuse.md#variants)).
- The wizard page and `coverageUtil` are held once per class
  ([phases/recording.md#locators](recording.md#locators)).
- The constructor only stores inputs. The step's name and path are shown at the gate; copy the shape
  of the exemplar step ([phases/recording.md#exemplars](recording.md#exemplars)).

## Placement

The shared folder or the LOB folder is **asked**, never decided on your own. Show the evidence: the
data types the step reads (a shared data type means LOB-agnostic, a LOB-specific type means the LOB
folder), where the facade methods it replaces live, and where the exemplar sits. Recommend one, with
that reason.

A step that works across all LOBs gets no LOB tag
([Flow tags](#flow-tags)).

## Assertions

- Assertions live **in the component**, written in the style of the neighbouring component.
- A check other flows need becomes its own `Assert*` reusable, not bolted onto the action step; the
  action and the verification are separate methods.
- Widget assertions (`assertEquals`, `assertVisible`, ...) for one field;
  `CenterTestAssertion.withContext(context).withDescription("...")` for a business rule, and `softAssertThat` to collect several checks before failing.
- Proposed final checks come from [phases/recording.md#final-checks](recording.md#final-checks);
  the user approves or edits them at this gate.
- Tests never touch widgets.

## Comments

Per `comments` ([phases/profile.md#switches](profile.md#switches)): `none` copies no notes (their checks stay), `notes`
puts a note as a `//` comment at its line, `javadoc` puts it in the step method's Javadoc, and
`auto` matches the exemplar. Page messages are not copied. Class Javadoc follows the same switch
([phases/recording.md#generate](recording.md#generate)).

## Flow tags

Propose tags for each new step class from the tags the project's steps already use
(`steps.bases[].flowTags`, and the tags on the exemplar and on the neighbouring steps): application
and transaction, not an unrelated transaction's tag. Describe what the component does, not the test.

When the scenario reveals a gap, also propose **new values or categories**: a transaction or process
the existing category enums have no value for, or a dimension they do not cover at all. Show each as
an addition to the category's file, with the reason, and approve it like any other edit. Never invent
a tag silently.

A run-time tag in a test is proposed only when the data takes a distinguishable path, and then as a
constant, not a string.

## Seed points

`plan.seedPointCandidates` lists logical step ends (`seq`, `seed`, `why`) where a later test may
want to start. Propose one call at the end of each logical step a later test may want to stop at:
`seed(GwSeedPoint.<value>)` with the candidate's `seed` value (`NEW_ACCOUNT`, `PRE_QUOTE`, `QUOTED`,
`ISSUED_POLICY`, `CLAIM`), or the project's own `SeedPoint` enum when its steps use one. The call is
a no-op unless `centertest.runtime.seed` is set, so the same flow can seed environments without code
changes. Each is a proposal: the user keeps or drops it, and it is not placed
where the step has not yet reached that state.

## Negative rows

A row that expects a failure follows `negativeProtocol`: the project's own protocol when it has one
(`project`), else the framework's `passTestWhenTrue` / `passTestWhenFalse` / `passTestWhenVisible` at the point the error is
proven (`framework`), no try/catch. Never both in one test.

## Test class

Copy the closest exemplar test in the same folder, adjusted by the profile. `@CenterTest`, a `final`
class, one `@CenterTestCase` method, the roles as the project gets them, each facade call ending
in `.execute()`.

- One test case is the method `run`; several in one class (only when they differ by a single value)
  are named for the difference (`runCancellationNow`).
- Context variables are declared at the top of the method, then a blank line, named per
  `contextNaming`: `role` (`producerContext`) or `centerRoleContext` (`pcProducerContext`), `auto`
  as the exemplar.
- Descriptive local names.
- A scenario that extends an existing test is a **new test class**, not an edit
  ([phases/reuse.md#ladder](reuse.md#ladder)).
- Restart points and suite registration: [phases/restart.md#implement](restart.md#implement),
  [phases/restart.md#suites](restart.md#suites).

## Write

After the Code plan gate is approved, in this order, **one file at a time**: data (the Data phase),
component and facade, test class, suite registration.

- After each file show the diff, or the full content for a new file, and wait for a go before the
  next. Update the session state ([SKILL.md#session-state-and-plan-file](../SKILL.md#session-state-and-plan-file)).
- Write what [phases/recording.md#generate](recording.md#generate) describes, as approved.
- Never hand-edit generated code; never invent a data value; no backup copies.
- A problem found in unrelated code is reported, not fixed.

## Gate

Show: files in order (new, edited) and for each edit the reason and approval; names and paths;
placement answer; the wizard page field (inherited or own); hooks overridden; pinned ids; ids found
with `cssid-finder`; radios in rows; rows read by id on a bound job; final checks; conditions in notes; comments; flow tags (existing, proposed new values or categories);
seed points kept; negative-row protocol; test class and context naming; facade factory methods.
The restart points and suite are part of this gate ([phases/restart.md#gate](restart.md#gate)).
