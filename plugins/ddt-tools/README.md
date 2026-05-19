# ddt-tools

Data-Driven Testing tools for CenterTest — validate DC references, diff xlsx test data, report unused codes, and convert xlsx for git.

## Install

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install ddt-tools@centertest-skills
```

To update later: `/plugin marketplace update centertest-skills`.

See [`skills/ddt-tools/SKILL.md`](skills/ddt-tools/SKILL.md) for trigger phrases and the full skill definition.

## Prerequisites

- Python 3 (`python3` or `python`)
- `openpyxl` Python package (`pip install openpyxl`)
- Git (for diff and textconv tools)

## Tools

| Script | Purpose |
|--------|---------|
| `xlsx-validate-refs.py` | Validate DC reference integrity |
| `xlsx-diff.py` | Cell-level diff of xlsx files vs git |
| `xlsx-cleanup-unused.py` | Report unused codes in Data files |
| `ddt-check-code-usages.py` | Validate hardcoded DDTHelper string codes in Java source |
| `xlsx-textconv.py` | Convert xlsx to text for git diff |
| `ddt_config.py` | Shared config (project path management) |

## Configuration

On first run, any tool will prompt for the CenterTest project path and save it to `~/.centertest/ddt-tools.json`. The `CENTERTEST_PROJECT_DIR` environment variable overrides saved config.
