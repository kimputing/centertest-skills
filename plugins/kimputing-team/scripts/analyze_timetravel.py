#!/usr/bin/env python3
"""
Analyze CenterTest TimeTravelException log lines.

Extracts highest/lowest expected dates from TT exception messages,
calculates the time travel target date, and determines which tests
would be covered by that date.

Usage:
    python3 analyze_timetravel.py < logfile.txt
    python3 analyze_timetravel.py "line1" "line2" ...
    echo "paste lines" | python3 analyze_timetravel.py

Log line format (from AnkrPtException):
    Code TT-003 - Expected date: 2025-06-15. The system date (2025-01-10) is not on 2025-06-15.
    Code TT-004 - Expected date: 2025-07-01. The system date (2025-01-10) is not after or on 2025-07-01
    Code TT-005 - Expected date: 2025-07-01.  The system date (2025-01-10) is not after 2025-07-01
    Code TT-006 - Expected date: 2025-03-15.  The system date (2025-04-01) is not before or on 2025-03-15
    Code TT-007 - Expected date: 2025-03-15. The system date (2025-04-01) is not before 2025-03-15
    Code TT-008 - Expected date: 2025-06-15.  The system date (2025-01-10) must be between 2025-03-01 and 2025-06-15 (106 days)

The "Expected date" is the highestExpectedDate (the TT target).
The lowestExpectedDate is derived from the exception type:
    TT-003 (isOn):          lowest = highest (exact date)
    TT-004 (isOnOrAfter):   lowest = comparison date
    TT-005 (isAfter):       lowest = comparison date + 1
    TT-006 (isOnOrBefore):  lowest = highest - 30 years
    TT-007 (isBefore):      lowest = highest - 30 years  (highest = comparison - 1)
    TT-008 (isWithin):      lowest = start date, highest = end date
"""

import re
import sys
from datetime import date, timedelta
from dataclasses import dataclass, field


@dataclass
class TimeTravelEntry:
    test_name: str
    code: str
    expected_date: date
    system_date: date
    highest_expected: date
    lowest_expected: date
    raw_line: str


# Patterns for each TT exception code
# All start with: Code TT-0XX - Expected date: YYYY-MM-DD
PATTERNS = {
    # TT-003: isOn - "Expected date: %s. The system date (%s) is not on %s."
    "003": re.compile(
        r"Code TT-003 - Expected date: (\d{4}-\d{2}-\d{2})\.\s+The system date \((\d{4}-\d{2}-\d{2})\) is not on (\d{4}-\d{2}-\d{2})"
    ),
    # TT-004: isOnOrAfter - "Expected date: %s. The system date (%s) is not after or on %s"
    "004": re.compile(
        r"Code TT-004 - Expected date: (\d{4}-\d{2}-\d{2})\.\s+The system date \((\d{4}-\d{2}-\d{2})\) is not after or on (\d{4}-\d{2}-\d{2})"
    ),
    # TT-005: isAfter - "Expected date: %s.  The system date (%s) is not after %s"
    "005": re.compile(
        r"Code TT-005 - Expected date: (\d{4}-\d{2}-\d{2})\.\s+The system date \((\d{4}-\d{2}-\d{2})\) is not after (\d{4}-\d{2}-\d{2})"
    ),
    # TT-006: isOnOrBefore - "Expected date: %s.  The system date (%s) is not before or on %s"
    "006": re.compile(
        r"Code TT-006 - Expected date: (\d{4}-\d{2}-\d{2})\.\s+The system date \((\d{4}-\d{2}-\d{2})\) is not before or on (\d{4}-\d{2}-\d{2})"
    ),
    # TT-007: isBefore - "Expected date: %s. The system date (%s) is not before %s"
    "007": re.compile(
        r"Code TT-007 - Expected date: (\d{4}-\d{2}-\d{2})\.\s+The system date \((\d{4}-\d{2}-\d{2})\) is not before (\d{4}-\d{2}-\d{2})"
    ),
    # TT-008: isWithin - "Expected date: %s.  The system date (%s) must be between %s and %s (%s days)"
    "008": re.compile(
        r"Code TT-008 - Expected date: (\d{4}-\d{2}-\d{2})\.\s+The system date \((\d{4}-\d{2}-\d{2})\) must be between (\d{4}-\d{2}-\d{2}) and (\d{4}-\d{2}-\d{2})"
    ),
}

# Pattern to extract test name from log line prefix (common log formats)
TEST_NAME_PATTERNS = [
    # Format: FQCN before ": Code TT-" (e.g. "com.copperpoint.tests.misc.TimeTravelExampleTest: Code TT-")
    re.compile(r"((?:[a-z][a-zA-Z0-9_]*\.)+[A-Z][A-Za-z0-9_]+):\s*Code TT-"),
    # Format: [TestClassName.methodName] or [TestClassName#methodName]
    re.compile(r"\[([A-Za-z0-9_]+(?:[.#][A-Za-z0-9_]+)*)\]"),
    # Format: scenario=TestName or test=TestName
    re.compile(r"(?:scenario|test)\s*=\s*([A-Za-z0-9_.#]+)", re.IGNORECASE),
    # Format: class.method or just ClassName at start of line
    re.compile(r"^\s*([A-Z][A-Za-z0-9_]+(?:\.[a-z][A-Za-z0-9_]*)?)\s"),
]

# Pattern for TT codes that are info/error messages without date ranges (e.g. TT-001, TT-002)
SKIPPED_TT_PATTERN = re.compile(r"Code TT-(\d{3})")


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def extract_test_name(line: str) -> str:
    for pattern in TEST_NAME_PATTERNS:
        m = pattern.search(line)
        if m:
            return m.group(1)
    return "Unknown"


def parse_line(line: str) -> TimeTravelEntry | None:
    """Parse a single log line for TT exception info."""
    line = line.strip()
    if not line or "Code TT-" not in line:
        return None

    test_name = extract_test_name(line)

    for code, pattern in PATTERNS.items():
        m = pattern.search(line)
        if not m:
            continue

        if code == "003":
            # isOn: highest = lowest = exact date
            expected = parse_date(m.group(1))
            system = parse_date(m.group(2))
            return TimeTravelEntry(test_name, code, expected, system, expected, expected, line)

        elif code == "004":
            # isOnOrAfter: highest = renewalDate (expected), lowest = comparison date
            expected = parse_date(m.group(1))
            system = parse_date(m.group(2))
            comparison = parse_date(m.group(3))
            return TimeTravelEntry(test_name, code, expected, system, expected, comparison, line)

        elif code == "005":
            # isAfter: highest = renewalDate (expected), lowest = comparison + 1
            expected = parse_date(m.group(1))
            system = parse_date(m.group(2))
            comparison = parse_date(m.group(3))
            return TimeTravelEntry(test_name, code, expected, system, expected, comparison + timedelta(days=1), line)

        elif code == "006":
            # isOnOrBefore: highest = date, lowest = date - 30 years
            expected = parse_date(m.group(1))
            system = parse_date(m.group(2))
            return TimeTravelEntry(test_name, code, expected, system, expected, expected.replace(year=expected.year - 30), line)

        elif code == "007":
            # isBefore: highest = comparison - 1, lowest = (comparison-1) - 30 years
            expected = parse_date(m.group(1))
            system = parse_date(m.group(2))
            comparison = parse_date(m.group(3))
            highest = comparison - timedelta(days=1)
            return TimeTravelEntry(test_name, code, expected, system, highest, highest.replace(year=highest.year - 30), line)

        elif code == "008":
            # isWithin: dates in log may be swapped (isWithin(int offset) passes
            # renewalDate+offset as startDate, renewalDate as endDate).
            # The Java code stores TimeTravelInfo(endDate, startDate) as-is,
            # so highestExpectedDate can end up < lowestExpectedDate.
            # We normalize here: highest = max(both dates), lowest = min(both dates)
            expected = parse_date(m.group(1))
            system = parse_date(m.group(2))
            date_a = parse_date(m.group(3))
            date_b = parse_date(m.group(4))
            highest = max(date_a, date_b)
            lowest = min(date_a, date_b)
            return TimeTravelEntry(test_name, code, expected, system, highest, lowest, line)

    # Check if it's a non-date TT code (TT-001 format error, TT-002 missing data)
    m = SKIPPED_TT_PATTERN.search(line)
    if m:
        return None  # valid TT line but not a date-range exception

    return None


def calculate_tt_date(entries: list[TimeTravelEntry]) -> date:
    """
    Replicate TimeTravelSelfManagedExecution.getTimeTravelDate():
    Collect highestExpectedDate from each entry, return the lowest (earliest).
    """
    dates = [e.highest_expected for e in entries]
    return min(dates)


def find_targeted_tests(entries: list[TimeTravelEntry], tt_date: date) -> tuple[list[TimeTravelEntry], list[TimeTravelEntry]]:
    """
    Replicate getBatchJobsToExecute() filter logic:
    A test is targeted if its date range contains tt_date:
        (lowest < tt_date < highest) OR tt_date == highest OR tt_date == lowest
    """
    targeted = []
    not_targeted = []
    for e in entries:
        if ((e.lowest_expected < tt_date and e.highest_expected > tt_date)
                or tt_date == e.highest_expected
                or tt_date == e.lowest_expected):
            targeted.append(e)
        else:
            not_targeted.append(e)
    return targeted, not_targeted


CODE_NAMES = {
    "003": "isOn",
    "004": "isOnOrAfter",
    "005": "isAfter",
    "006": "isOnOrBefore",
    "007": "isBefore",
    "008": "isWithin",
}


def format_output(entries: list[TimeTravelEntry], skipped: list[str] | None = None) -> str:
    if not entries:
        return "No TimeTravelException entries found in input."

    lines = []
    lines.append("=" * 80)
    lines.append("TIMETRAVEL SELF-MANAGED EXECUTION ANALYSIS")
    lines.append("=" * 80)

    # Show parsed entries
    lines.append(f"\nParsed {len(entries)} TimeTravelException(s):\n")
    lines.append(f"  {'#':<4} {'Test':<40} {'Code':<14} {'System Date':<14} {'Lowest':<14} {'Highest':<14}")
    lines.append(f"  {'─'*4} {'─'*40} {'─'*14} {'─'*14} {'─'*14} {'─'*14}")
    for i, e in enumerate(entries, 1):
        code_label = f"TT-{e.code} ({CODE_NAMES.get(e.code, '?')})"
        lines.append(f"  {i:<4} {e.test_name:<40} {code_label:<14} {e.system_date!s:<14} {e.lowest_expected!s:<14} {e.highest_expected!s:<14}")

    # Calculate TT date
    tt_date = calculate_tt_date(entries)
    lines.append(f"\n{'─' * 80}")
    lines.append(f"CALCULATED TIME TRAVEL DATE: {tt_date}")
    lines.append(f"  (lowest of all highestExpectedDates)")
    lines.append(f"{'─' * 80}")

    # Show which tests are targeted
    targeted, not_targeted = find_targeted_tests(entries, tt_date)

    lines.append(f"\nTARGETED TESTS ({len(targeted)} of {len(entries)}):")
    lines.append(f"  These tests will be re-executed after time travel to {tt_date}:\n")
    if targeted:
        for e in targeted:
            lines.append(f"  [OK] {e.test_name:<40} range: [{e.lowest_expected} .. {e.highest_expected}]")
    else:
        lines.append("  (none)")

    if not_targeted:
        lines.append(f"\nNOT TARGETED ({len(not_targeted)}):")
        lines.append(f"  These tests need a DIFFERENT date and will NOT be covered:\n")
        for e in not_targeted:
            lines.append(f"  [!!] {e.test_name:<40} range: [{e.lowest_expected} .. {e.highest_expected}]")
            if e.lowest_expected > tt_date:
                lines.append(f"       └─ needs at least {e.lowest_expected} (TT date is {(e.lowest_expected - tt_date).days} days too early)")
            elif e.highest_expected < tt_date:
                lines.append(f"       └─ needs at most {e.highest_expected} (TT date is {(tt_date - e.highest_expected).days} days too late)")

    # Skipped lines
    if skipped:
        lines.append(f"\nSKIPPED ({len(skipped)} lines — no date range to extract):")
        for s in skipped:
            # Extract just the TT code part
            m = SKIPPED_TT_PATTERN.search(s)
            code = m.group(1) if m else "???"
            test = extract_test_name(s)
            lines.append(f"  [--] TT-{code}  {test}")

    # Summary
    lines.append(f"\n{'=' * 80}")
    lines.append("SUMMARY")
    lines.append(f"{'=' * 80}")
    system_dates = set(e.system_date for e in entries)
    lines.append(f"  Current system date(s): {', '.join(str(d) for d in sorted(system_dates))}")
    lines.append(f"  Time travel target:     {tt_date}")
    lines.append(f"  Tests covered:          {len(targeted)}/{len(entries)}")
    if not_targeted:
        lines.append(f"  Tests NOT covered:      {len(not_targeted)} (would need additional TT cycles)")
        # Suggest what additional dates would be needed
        remaining_dates = sorted(set(e.highest_expected for e in not_targeted))
        lines.append(f"  Additional TT dates needed: {', '.join(str(d) for d in remaining_dates)}")
    if skipped:
        lines.append(f"  Skipped (no date range): {len(skipped)}")
    lines.append("")

    return "\n".join(lines)


def main():
    input_lines = []

    if len(sys.argv) > 1:
        # Arguments passed directly
        input_lines = sys.argv[1:]
    else:
        # Read from stdin
        input_lines = sys.stdin.read().splitlines()

    entries = []
    skipped = []
    for line in input_lines:
        stripped = line.strip()
        if not stripped or "Code TT-" not in stripped:
            continue
        entry = parse_line(stripped)
        if entry:
            entries.append(entry)
        else:
            skipped.append(stripped)

    print(format_output(entries, skipped))


if __name__ == "__main__":
    main()
