---
name: timetravel-analyzer
description: Analyze CenterTest TimeTravelException log lines to extract date ranges, calculate the self-managed time travel target date, and determine which tests will be covered. Use when the user pastes TT exception logs, asks to analyze time travel failures, or wants to predict which tests a time travel cycle will target.
---

# Skill: TimeTravel Self-Managed Execution Analyzer

## Purpose

Parse CenterTest `TimeTravelException` log lines, extract the `highestExpectedDate` and `lowestExpectedDate` for each failed test, calculate the time travel target date (as `TimeTravelSelfManagedExecution` would), and show which tests will be re-executed vs which need additional TT cycles.

## When to Use

Trigger this skill when the user:
- Pastes log lines containing `Code TT-0XX` time travel exceptions
- Asks to analyze time travel failures or predict TT behavior
- Wants to know which tests will be covered by a time travel cycle
- Asks "what date will TT pick" or "which tests will be retried"

## How to Use

### Step 1: Collect log lines

The user will paste one or more log lines containing `Code TT-` messages. These come from `TimeTravelException` and follow these formats:

| Code | Method | Message Pattern |
|------|--------|----------------|
| TT-003 | `isOn` | `Expected date: {target}. The system date ({sys}) is not on {date}` |
| TT-004 | `isOnOrAfter` | `Expected date: {target}. The system date ({sys}) is not after or on {date}` |
| TT-005 | `isAfter` | `Expected date: {target}. The system date ({sys}) is not after {date}` |
| TT-006 | `isOnOrBefore` | `Expected date: {target}. The system date ({sys}) is not before or on {date}` |
| TT-007 | `isBefore` | `Expected date: {target}. The system date ({sys}) is not before {date}` |
| TT-008 | `isWithin` | `Expected date: {target}. The system date ({sys}) must be between {start} and {end} ({days} days)` |

### Step 2: Run the analyzer

Save the log lines to a temp file or pipe them directly:

```bash
echo "PASTE_LINES_HERE" | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyze_timetravel.py"
```

Or pass lines as arguments:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyze_timetravel.py" "line1" "line2"
```

### Step 3: Present the analysis

The script outputs:
1. **Parsed entries** — each test with its code, system date, lowest/highest expected dates
2. **Calculated TT date** — the date `TimeTravelSelfManagedExecution` would pick (lowest of all `highestExpectedDate` values)
3. **Targeted tests** — tests whose date range includes the TT date (will be re-executed)
4. **Not targeted tests** — tests that need a different date (would need additional TT cycles)
5. **Summary** — coverage stats and any additional TT dates needed

## Date Calculation Logic

This mirrors `TimeTravelSelfManagedExecution.getTimeTravelDate()`:

1. Each `TimeTravelException` stores a `TimeTravelInfo` with `highestExpectedDate` and `lowestExpectedDate`
2. The TT target date = `min(highestExpectedDate)` across all failed scenarios
3. A test is targeted if its range `[lowestExpectedDate .. highestExpectedDate]` contains the TT target date

### How dates map from each exception type:

| Method | `highestExpectedDate` | `lowestExpectedDate` |
|--------|----------------------|---------------------|
| `isOn(date)` | `date` | `date` |
| `isOnOrAfter(date)` | `renewalDate` | `date` |
| `isAfter(date)` | `renewalDate` | `date + 1` |
| `isOnOrBefore(date)` | `date` | `date - 30 years` |
| `isBefore(date)` | `date - 1` | `(date-1) - 30 years` |
| `isWithin(start, end)` | `end` | `start` |

## Script Details

- **Location**: `${CLAUDE_PLUGIN_ROOT}/scripts/analyze_timetravel.py`
- **Input**: log lines via stdin or command-line arguments
- **Output**: formatted analysis to stdout
- **Test name extraction**: attempts to parse test/scenario name from log line prefixes (brackets, `scenario=`, `test=`, or class name patterns)
