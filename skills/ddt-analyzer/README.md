# ddt-analyzer

Analyze CenterTest Data-Driven Testing structure and generate an Excel report.

## Latest Version

**GitHub**: [https://github.com/Kimputing/centertest-skills/tree/main/skills/ddt-analyzer](https://github.com/Kimputing/centertest-skills/tree/main/skills/ddt-analyzer)

To update to the latest version:

```bash
# If cloned
cd centertest-skills && git pull origin main

# Or download directly
curl -o ~/.claude/skills/ddt-analyzer/scripts/ddt-analyzer.py \
  https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-analyzer/scripts/ddt-analyzer.py
curl -o ~/.claude/skills/ddt-analyzer/SKILL.md \
  https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/ddt-analyzer/SKILL.md
```

## Prerequisites

- Python 3 (`python3` or `python`)
- `openpyxl` Python package (`pip install openpyxl`)

## Usage

```bash
# Analyze and generate report
python3 ddt-analyzer.py

# Exclude paths
python3 ddt-analyzer.py --exclude testdata/archive,testdata/old
```

## Report Sheets

| Sheet | Content |
|-------|---------|
| `DataCombination_References` | DC files vs referenced Data files |
| `ReferencedFiles_DataCombination` | Data files vs DC files that reference them |
| `Codes_Usage` | Code usage counts across all DC files |
| `Codes_Usage_Detail` | Per-DC-file code usage breakdown |
| `DataCombination_Tests` | Test classes mapped to datasources |

## Configuration

Uses the same project path as ddt-tools (`~/.centertest/ddt-tools.json`).
