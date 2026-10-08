# kimputing-team

The shared Kimputing Claude Code setup in one install. For Kimputing staff, not for clients.

## Install

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install kimputing-team@centertest-skills
```

Restart Claude Code after installing. To update later: `/plugin marketplace update centertest-skills`.

## What you get

| Piece | What it does | Needs |
|---|---|---|
| Team rules (SessionStart hook) | Every session starts with the working principles and the GitHub issue conventions (Type, labels, Priority, project CT, linked branches). Source: [`hooks/team-rules.md`](hooks/team-rules.md). | `jq` |
| CT hook (PostToolUse on Bash) | When Claude creates an issue in a `kimputing/*` repo, it is added to org project **CT** (#2) and Claude is told so. | `jq`, `gh` signed in with the `project` scope |
| `heimdall-report` skill | "Heimdall report for <Client>": CenterTest usage report from the Heimdall database, via AWS SSM. | A checkout of `kimputing/centertest-heimdall`; `aws` CLI with `ssm:SendCommand` |
| `postgresql-query` skill | "query the database": read-only SQL against a CenterTest results database. | `psql`; `PG*` variables, or the local dev defaults |
| `reportportal-api` skill | ReportPortal API knowledge: launches, test items, logs, analytics. | Your own ReportPortal API token |
| `timetravel-analyzer` skill | Analyses CenterTest `TimeTravelException` log lines. | `python3` |

## Check it works

- Start a session and ask: *"Which team rules are loaded?"* Claude should name the working
  principles and the issue conventions.
- Run `gh auth status`; the token scopes must include `project`, or the CT hook reports
  *FAILED to add to CT project*. Fix with `gh auth refresh -s project`.

## Changing the rules

Edit `hooks/team-rules.md` and merge to `main`. Everyone gets the change on their next
`/plugin marketplace update centertest-skills`.
