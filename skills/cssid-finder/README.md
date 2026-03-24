# cssid-finder

Find the Java getter chain (`hierarchyPath`) for a Guidewire UI CSS ID in CenterTest.

## Latest Version

**GitHub**: [https://github.com/Kimputing/centertest-skills/tree/main/skills/cssid-finder](https://github.com/Kimputing/centertest-skills/tree/main/skills/cssid-finder)

To update to the latest version:

```bash
# If cloned
cd centertest-skills && git pull origin main

# Or download directly
curl -o ~/.claude/skills/cssid-finder/scripts/find_getter.py \
  https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/cssid-finder/scripts/find_getter.py
curl -o ~/.claude/skills/cssid-finder/SKILL.md \
  https://raw.githubusercontent.com/Kimputing/centertest-skills/main/skills/cssid-finder/SKILL.md
```

## Usage

Trigger phrases:
- "find getter in PC for `SomePage-SomeElement`"
- "getter in BC for `BillingPage-Field`"
- "AB getter for `ABContactDetailPopup-Screen-Field`"

## Supported Layouts

The script auto-detects which layout is present:

| Layout | Structure | Format |
|--------|-----------|--------|
| **Properties** (new) | `cssids/<app>/<Page>.properties` | `cssId=getterChain` |
| **Legacy** | `<app>.cssids` | JSON-like `"cssId"` / `"hierarchyPath"` pairs |

## Prerequisites

- Python 3 (`python3` or `python`)

## Configuration

On first run, the script prompts for the path to the generated project's resources directory and saves it to `~/.centertest/cssid-finder.json`.

To override later:

```bash
python3 find_getter.py --set-path "/path/to/generated/src/main/resources"
```

The `CENTERTEST_CSSIDS_DIR` environment variable takes priority over saved config if set.

## Supported Apps

| App | Folder/File | Guidewire Product |
|-----|-------------|-------------------|
| pc  | pc/ or pc.cssids | PolicyCenter |
| cc  | cc/ or cc.cssids | ClaimCenter |
| bc  | bc/ or bc.cssids | BillingCenter |
| ab/cm | ab/ or ab.cssids | ContactManager / AgencyCenter |
