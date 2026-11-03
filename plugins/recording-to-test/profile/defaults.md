---
sharedValues: auto
recordedValues: data
comments: auto
standardsSkill: none
negativeProtocol: auto
workbookWriter: openpyxl
gate: phases
defaultEnvironment:
contextNaming: auto
runCommand:
---
# Kimputing-wide defaults

A client repo overrides any of the switches above in `.claude/client-profile.md`. The facts below hold
for every CenterTest project.

- The DataKey keys PolicyExpirationDate, UserName, Password and Premium are reserved by the framework. Never reuse them as a shared-value key.
- Never run `upgradePages` or `rebuildCode`.
- Generated code (the `generated` pages package) is never edited by hand.
