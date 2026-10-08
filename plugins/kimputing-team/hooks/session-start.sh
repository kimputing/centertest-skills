#!/usr/bin/env bash
# SessionStart hook: loads the Kimputing team rules (hooks/team-rules.md) into every session.
# A plugin cannot install a CLAUDE.md, so the rules arrive as additionalContext instead.
rules="${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}/hooks/team-rules.md"
[ -f "$rules" ] || exit 0
jq -Rs '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: .}}' < "$rules"
