# cssid-finder

Find the Java getter chain (`hierarchyPath`) for a Guidewire UI CSS ID in CenterTest.

## Install

```text
/plugin marketplace add Kimputing/centertest-skills
/plugin install cssid-finder@centertest-skills
```

To update later: `/plugin marketplace update centertest-skills`.

## Trigger phrases

- "find getter in PC for `SomePage-SomeElement`"
- "getter in BC for `BillingPage-Field`"
- "AB getter for `ABContactDetailPopup-Screen-Field`"

See [`skills/cssid-finder/SKILL.md`](skills/cssid-finder/SKILL.md) for the full skill definition.

## Supported layouts

The script auto-detects which layout is present:

| Layout | Structure | Format |
|--------|-----------|--------|
| **Properties** (new) | `cssids/<app>/<Page>.properties` | `cssId=getterChain` |
| **Legacy** | `<app>.cssids` | JSON-like `"cssId"` / `"hierarchyPath"` pairs |

## Supported apps

| App | Folder/File | Guidewire Product |
|-----|-------------|-------------------|
| pc  | pc/ or pc.cssids | PolicyCenter |
| cc  | cc/ or cc.cssids | ClaimCenter |
| bc  | bc/ or bc.cssids | BillingCenter |
| ab/cm | ab/ or ab.cssids | ContactManager / AgencyCenter |

## Prerequisites

- Python 3 (`python3` or `python`)

## Configuration

On first run, the script prompts for the path to the generated project's `src/main/resources` directory and saves it to `~/.centertest/cssid-finder.json`. The `CENTERTEST_CSSIDS_DIR` environment variable overrides saved config if set.
