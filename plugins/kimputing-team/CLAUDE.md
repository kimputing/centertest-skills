# CLAUDE.md — kimputing-team

## What It Is

The Kimputing team bundle: two hooks and four skills. Unlike the other plugins here it holds
several skills, because it is the team's setup rather than one tool.

## Layout

- `hooks/hooks.json` — SessionStart → `session-start.sh`; PostToolUse(Bash) → `add-issue-to-ct.sh`.
- `hooks/team-rules.md` — the team rules. `session-start.sh` sends this file as `additionalContext`,
  because a plugin cannot install a `CLAUDE.md`.
- `hooks/add-issue-to-ct.sh` — reads the hook JSON on stdin; only acts when the command created an
  issue (`gh issue create`, GraphQL `createIssue`, REST POST to `…/issues`) and the output holds a
  `github.com/kimputing/<repo>/issues/<n>` URL. Then `gh project item-add 2 --owner kimputing`.
- `skills/<name>/SKILL.md` — one folder per skill; scripts in `scripts/`, referenced as
  `${CLAUDE_PLUGIN_ROOT}/scripts/<file>`.

## Rules for this plugin

- No credentials and no personal paths (`/Users/<name>/…`) in any file. Skills read secrets from
  the user's environment or their own config.
- `heimdall-report` calls the script in the user's `centertest-heimdall` checkout; keep its
  defaults (instance, RDS host) in the script, not here.

## Testing the hooks

```bash
CLAUDE_PLUGIN_ROOT=$PWD/plugins/kimputing-team bash plugins/kimputing-team/hooks/session-start.sh | jq .
echo '{"tool_input":{"command":"ls"},"tool_response":{}}' | bash plugins/kimputing-team/hooks/add-issue-to-ct.sh  # no output
```
