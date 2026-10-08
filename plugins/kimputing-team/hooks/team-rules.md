# Kimputing team rules (from the kimputing-team plugin)

## Working Principles

These govern all Kimputing work.

1. **Ask, don't assume.** If anything about intent, architecture, or requirements is
   unclear, ask before writing a line. No silent guesses.
2. **Simplest solution first.** Implement the minimum thing that works; no abstractions
   that weren't requested. Future-useful ideas → raise as suggestions, don't build them.
3. **Don't touch unrelated code.** If a file isn't part of the current task, leave it.
4. **Flag uncertainty explicitly.** If you're not confident, say so before proceeding —
   admitting a gap beats confidence without certainty.

---

## GitHub Issue Conventions

These govern every `kimputing/*` repository.

### Every issue carries three things

1. **Type** — `Bug`, `Feature` or `Task`. `gh issue edit <n> --type <Type>`.
2. **Labels** — which must **never restate the type**. A `bug` label on an issue typed `Bug`
   is noise; so is `critical` on an issue that has a Priority. Labels carry what the type
   cannot: the **area** of the system (`area:grid`, `area:codegen`, `area:security`, …), who
   asked (`customer-request`), and whether a design question is still open
   (`needs-decision`). Multiple area labels on one issue are correct — a single generic label
   hides that an issue spans two subsystems.
3. **Priority** — `Urgent` / `High` / `Medium` / `Low`, chosen from **that issue's own
   description**, not an impression of it. Reserve `Urgent` for data loss/corruption or an
   unusable app.
4. **Project** — every issue in a `kimputing/*` repo goes on the org project **CT** (#2).
   The kimputing-team plugin's `add-issue-to-ct` PostToolUse hook does this automatically for
   `gh issue create`, GraphQL `createIssue` and REST `gh api …/issues` POSTs and reports it;
   for any other creation path, run `gh project item-add 2 --owner kimputing --url <url>`.

### Priority is an Issue Field, not a project field

This is the part that wastes time if forgotten. `Priority` (and `Effort`) live on GitHub's
**Issue Fields** API and are defined **org-wide** — the same field IDs work across every repo
in the org. They also *project* into a ProjectV2 board as a read-only shell whose `options`
reads `[]` and which rejects all writes with `UNPROCESSABLE: Only custom fields can be
updated…`. That shell is a dead end: don't try to fix it, and don't ask the user to add
options by hand. Use:

```bash
# definitions + option IDs
gh api graphql -f query='{repository(owner:"<org>",name:"<repo>"){
  issueFields(first:20){nodes{... on IssueFieldSingleSelect {id name options{id name}}}}}}'
```
```graphql
mutation { setIssueFieldValue(input:{ issueId:"<issue node id>", issueFields:[
  {fieldId:"<IFSS_…>", singleSelectOptionId:"<IFSSO_…>", rationale:"why this level"} ]}){clientMutationId} }
```

Read values back via `issueFieldValues` → `IssueFieldSingleSelectValue.value` (there is no
`option` subfield). Always pass `rationale` (max 280 chars) so the call is auditable.
`suggest:true` stores a value as a pending suggestion instead of applying it.

### Every piece of work links back to its issue

- **Branch** — `gh issue develop <n> --base main --name <branch> --checkout`. A branch merely
  *named* after an issue is not linked.
- **PR** — `Closes #<n>` in the body; verify with `closingIssuesReferences`, not the text.
  Closing keywords do **not** work across repositories — cross-repo references are links only.
- Expect `linkedBranches` to read empty once a PR exists; GitHub swaps the branch entry for
  the PR entry. The `ConnectedEvent` in the issue timeline is the durable proof.

### Gotchas

- `gh issue edit` needs each label as its own `--add-label` argument. Build them in a bash
  array; a space-joined string fails with `invalid issue format` while a surrounding `echo`
  still prints success.
- `gh label create` has no `--repo` flag — set `GH_REPO` instead.
- Deleting a label strips it from **closed** issues too. Preserve the information (usually by
  setting the type) before deleting.
- An org-level ProjectV2 can hold items from many repos; link with
  `linkProjectV2ToRepository`, add with `gh project item-add <n> --owner <org> --url <url>`.
