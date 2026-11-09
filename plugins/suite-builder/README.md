# suite-builder

Build and edit CenterTest suites (`CenterTestSuiteList.json`) from the project's own tests: pick
classes, methods and DataCombination rows, add them to or remove them from existing suites, delete or
rename suites, and see what every suite really runs — including entries that match nothing, which
CenterTest reports as failed scenarios.

## Install

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install suite-builder@centertest-skills
```

## Use

In a CenterTest project: "which suites do we have?", "create a Smoke suite with the login tests and
the Texas submission rows", "remove the disabled vehicle types from Regression1", "delete the Old
suite". The skill shows the selection and a dry-run diff before it writes anything.

Engine: `scripts/suite.py` (`list`, `show`, `scan`, `pick`, `create`, `add`, `remove`, `delete`,
`rename`, `set`); see `skills/suite-builder/SKILL.md`.

## Prerequisites

- Python 3 — no packages (workbooks are read with the standard library).
