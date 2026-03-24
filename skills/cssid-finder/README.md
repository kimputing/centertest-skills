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

## Configuration

Set the `CENTERTEST_CSSIDS_DIR` environment variable to point to your resources directory:

```bash
export CENTERTEST_CSSIDS_DIR="/path/to/generated/src/main/resources"
```

## Supported Apps

| App | Folder/File | Guidewire Product |
|-----|-------------|-------------------|
| pc  | pc/ or pc.cssids | PolicyCenter |
| cc  | cc/ or cc.cssids | ClaimCenter |
| bc  | bc/ or bc.cssids | BillingCenter |
| ab/cm | ab/ or ab.cssids | ContactManager / AgencyCenter |
