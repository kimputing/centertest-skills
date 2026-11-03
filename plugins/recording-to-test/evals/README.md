# Evals

`run_evals.py` runs `ct.py scan` and `ct.py parse` against a project and recordings described in case
folders, then checks expected values in the resulting plan and project JSON. Standard library only.

```
python3 plugins/recording-to-test/evals/run_evals.py --cases <dir>     # or: CT_EVALS_DIR=<dir>
```

Prints `PASS|FAIL|SKIP <name>` per case and a total. Exit 0 when nothing failed (skips are not failures),
1 when any case failed, 2 when no cases directory is given.

## Where cases live

Cases describe real client projects and recordings, so they are **never kept in this repository**. They live
in a private Kimputing repository, cloned locally; point `--cases` or `CT_EVALS_DIR` at the clone. Do not
commit a case, recording, host or client name here.

## Case format

`<cases>/<name>/case.json`:

```json
{
  "name": "pa-submission",
  "project": "${CT_PROJECT_ACME}",
  "recordings": ["recordings/submission"],
  "cssids": "${CT_CSSIDS}",
  "expect": [
    {"path": "plan.schemaVersion", "op": "equals", "value": 2},
    {"path": "plan.existingTests[0].path", "op": "contains", "value": "PA_Submission"},
    {"path": "plan.blockers", "op": "exists"},
    {"path": "plan.retired", "op": "absent"}
  ]
}
```

- `project`, `recordings` and `cssids` may use `${VAR}` (from the environment) and paths relative to the
  case folder. Several recordings give a plan shaped `{schemaVersion, parts, chain}`.
- `cssids` is optional: `parse` needs a cssids directory, taken from the scanned project's `cssids.value`
  when the scan finds it, else from this field. With neither, the case is SKIPped with a reason.
- A case is also SKIPped when the project or a recording is not on this machine, or a `${VAR}` is unset.
- `expect` paths are dotted with `[i]` indexes over `{"plan": ..., "project": ...}`. Ops: `equals`,
  `contains` (substring or list member), `exists`, `absent`. A failure names the path and the values.

## Adding a case from a wizard run

1. Run the wizard on the recording against the project; keep the recording folder.
2. In the private cases repository, create `<name>/case.json` with the recording (copy it into the case
   folder, or reference it by `${VAR}`) and the project path as a `${VAR}`.
3. Pick the values the run got right and that matter (test path, chosen facades, data rows, blockers) and
   write them as `expect` entries. Prefer a few stable facts over a full snapshot.
4. Run the harness; the case must PASS, and fail when you break the behaviour it guards.

## Skill-level evals

Whether the skill drives the wizard well (questions, ordering, the generated test) is evaluated manually,
per client, with the `skill-creator` skill's eval workflow. Keep those prompts and results in the same
private repository, not here.
