#!/bin/bash
# PostToolUse(Bash) hook: whenever a command creates an issue in a kimputing/* repo, add it to
# the kimputing org project "CT" (ProjectV2 #2). Covers `gh issue create`, GraphQL `createIssue`,
# and REST `gh api .../issues` POSTs. Read-only commands are ignored so listings never get added.
input=$(cat)
cmd=$(jq -r '.tool_input.command // ""' <<<"$input")

creates=0
grep -q 'gh issue create' <<<"$cmd" && creates=1
grep -q 'createIssue' <<<"$cmd" && creates=1
if grep -qE 'gh api[^|;&]*repos/[^ ]+/issues([ "'\'']|$)' <<<"$cmd" \
   && grep -qE -- '(-X|--method)[ =]?POST|(^| )-[fF] |--raw-field|--field|--input' <<<"$cmd"; then
  creates=1
fi
[ $creates -eq 0 ] && exit 0

urls=$(jq -r '.tool_response | tostring' <<<"$input" \
  | grep -oE 'https://github\.com/kimputing/[A-Za-z0-9._-]+/issues/[0-9]+' | sort -u)
[ -z "$urls" ] && exit 0

added=(); failed=()
while read -r url; do
  if gh project item-add 2 --owner kimputing --url "$url" >/dev/null 2>&1; then
    added+=("$url")
  else
    failed+=("$url")
  fi
done <<<"$urls"

msg=""
[ ${#added[@]} -gt 0 ] && msg="Added to CT project: ${added[*]}."
[ ${#failed[@]} -gt 0 ] && msg="$msg FAILED to add to CT project (add manually): ${failed[*]}."
jq -n --arg m "$msg" '{systemMessage: $m, hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $m}}'
