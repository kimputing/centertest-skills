---
name: cssid-finder
description: Find the Java getter chain (hierarchyPath) for a Guidewire UI CSS ID in CenterTest. Use when the user says "find getter", "what's the getter", or pastes a CSS ID and asks how to reference it in PC, CC, BC, or AB/CM. Triggers on phrases like "find getter in PC for", "getter in BC for", "AB getter for", or any CSS ID lookup request.
---

# Skill: CSS ID Getter Finder

## Purpose

Find the Java getter chain (`hierarchyPath`) for a CSS ID copied from the Guidewire UI during CenterTest development.

## When to Use

Trigger this skill when the user:
- Asks to find a getter for a CSS ID (e.g. "find getter for `AccountActivitiesPage-ActivitesLV-0-subject`")
- Wants to know the `hierarchyPath` for a UI element in PC, CC, BC, or AB/CM
- Pastes a CSS ID and asks how to reference it in a CenterTest scenario

## How to Use

### Step 1: Extract app and CSS ID

From the user's message, identify:
- **App**: pc, cc, bc, ab (or cm for ContactManager)
- **CSS ID**: the element identifier from the Guidewire UI

Examples:
- "find getter in PC for `AccountFile_Summary-AccountSummaryDashboard-AccountDetailsDetailViewTile-AccountDetailsDetailViewTile_DV-AccountHolder`" → app=pc
- "what's the getter in BC for `BillingCenterPage-SomeElement`" → app=bc
- "AB getter for `ABContactDetailPopup-ABContactDetailScreen-ABAddressDetailDV-AddressOwnerInputSet-Address_Description`" → app=ab

### Step 2: Run the script

Determine the Python command available on the system (`python3` or `python`) and use it:

```bash
PYTHON=$(command -v python3 || command -v python) && "$PYTHON" ~/.claude/skills/cssid-finder/scripts/find_getter.py <app> "<cssId>"
```

**First run**: the script will prompt for the path to the generated project's resources directory and save it to `~/.centertest/cssid-finder.json`.

**Override path**: if the user asks to change the path or you need to point to a different project:

```bash
"$PYTHON" ~/.claude/skills/cssid-finder/scripts/find_getter.py --set-path "/path/to/generated/src/main/resources"
```

**Show current path**:

```bash
"$PYTHON" ~/.claude/skills/cssid-finder/scripts/find_getter.py --show-path
```

### Step 3: Present result

Show the getter chain as a code snippet the developer can paste into their test:

```java
new AccountFile_SummaryPage(getContext()).getAccountHolder()
```

If not found, show the normalized form that was searched so the user can verify the CSS ID.

## Script Details

- **Script**: `scripts/find_getter.py`
- **Config**: `~/.centertest/cssid-finder.json` (created on first run)
- **Auto-detects** two layouts:
  1. **Properties** (new): `<resources>/cssids/<app>/<Page>.properties` — key=value format, one file per page
  2. **Legacy**: `<resources>/<app>.cssids` — single JSON-like file per app
- **Normalization**: numeric segments replaced with `[ROW]` (e.g. `LV-5-Name` → `LV-[ROW]-Name`), and trailing `_Input` suffix is stripped
- **Matching**: exact match first, then contains match for partial CSS IDs
- **Search**: uses `grep -F` for fast literal search

## Configuration

Path resolution order (first wins):
1. `CENTERTEST_CSSIDS_DIR` environment variable
2. Saved path in `~/.centertest/cssid-finder.json`
3. Interactive prompt (first run only, saves to config)
