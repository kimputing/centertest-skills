# ddt-tools

Data-Driven Testing tools for CenterTest — validate DC references, diff xlsx test data, report unused codes, and convert xlsx for git.

## Latest Version

**GitHub**: [https://github.com/Kimputing/centertest-skills/tree/main/skills/ddt-tools](https://github.com/Kimputing/centertest-skills/tree/main/skills/ddt-tools)

To update to the latest version:

```bash
# If cloned
cd centertest-skills && git pull origin main

# Or download directly
SKILL_DIR=~/.claude/skills/ddt-tools/scripts
curl -o $SKILL_DIR/xlsx-validate-refs.py https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-tools/scripts/xlsx-validate-refs.py
curl -o $SKILL_DIR/xlsx-diff.py https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-tools/scripts/xlsx-diff.py
curl -o $SKILL_DIR/xlsx-cleanup-unused.py https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-tools/scripts/xlsx-cleanup-unused.py
curl -o $SKILL_DIR/ddt-check-code-usages.py https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-tools/scripts/ddt-check-code-usages.py
curl -o $SKILL_DIR/xlsx-textconv.py https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-tools/scripts/xlsx-textconv.py
curl -o $SKILL_DIR/ddt_config.py https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-tools/scripts/ddt_config.py
curl -o ~/.claude/skills/ddt-tools/SKILL.md https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-tools/SKILL.md
```

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

On first run, any tool will prompt for the CenterTest project path and save it to `~/.centertest/ddt-tools.json`.

To override later:

```bash
python3 ddt_config.py --set-path "/path/to/centertest-project"
```

The `CENTERTEST_PROJECT_DIR` environment variable takes priority over saved config if set.

## Usage Examples

```bash
# Validate all DC references
python3 xlsx-validate-refs.py

# Validate a specific DC file
python3 xlsx-validate-refs.py testdata/WorkersCompDC.xlsx

# Diff testdata vs origin/main
python3 xlsx-diff.py testdata/WorkersCompDC.xlsx

# Report unused codes
python3 xlsx-cleanup-unused.py

# Validate hardcoded DDTHelper string codes in Java source
python3 ddt-check-code-usages.py
```
