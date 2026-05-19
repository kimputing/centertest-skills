#!/usr/bin/env python3
"""
Suppression system for centertest-healthcheck.

Allows marking specific findings as "not an issue" so they don't appear
in subsequent reports. Suppressions are stored in the evaluated project's
healthcheck/suppressions.json file.

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/centertest-healthcheck/scripts/eir_suppressions.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date

from eir_models import Suppression, RuleResult, Section


SUPPRESSIONS_FILE = "suppressions.json"


def load_suppressions(output_dir: str) -> list[Suppression]:
    """Load suppressions from {output_dir}/suppressions.json. Returns [] if not found."""
    path = os.path.join(output_dir, SUPPRESSIONS_FILE)
    if not os.path.isfile(path):
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: Could not load suppressions: {e}", file=sys.stderr)
        return []

    suppressions = []
    for entry in data.get("suppressions", []):
        suppressions.append(Suppression(
            rule_id=entry.get("rule_id", ""),
            class_name=entry.get("class", "*"),
            method=entry.get("method", "*"),
            match=entry.get("match", ""),
            reason=entry.get("reason", ""),
            added=entry.get("added", ""),
        ))
    return suppressions


def save_suppressions(output_dir: str, suppressions: list[Suppression]):
    """Save suppressions to {output_dir}/suppressions.json."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, SUPPRESSIONS_FILE)

    data = {
        "version": 1,
        "suppressions": [
            {
                "rule_id": s.rule_id,
                "class": s.class_name,
                "method": s.method,
                **({"match": s.match} if s.match else {}),
                "reason": s.reason,
                "added": s.added or str(date.today()),
            }
            for s in suppressions
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"  Suppressions saved to {path}")


def _matches_field(pattern: str, value: str) -> bool:
    """Check if a pattern matches a value. '*' matches anything."""
    if pattern == "*" or pattern == "":
        return True
    return pattern == value


def _matches_substring(match_str: str, row: list) -> bool:
    """Check if match_str is a substring of any column in the row."""
    if not match_str:
        return True  # no match constraint
    for val in row:
        if match_str in str(val):
            return True
    return False


def matches_suppression(rule_id: str, row: list, suppression: Suppression) -> bool:
    """
    Check if a finding row matches a suppression entry.

    All non-wildcard fields must match:
    - rule_id: exact match (required)
    - class_name: matches row[0], '*' = any
    - method: matches row[1], '*' = any
    - match: substring match against any column in the row
    """
    if suppression.rule_id != rule_id:
        return False
    if len(row) >= 1 and not _matches_field(suppression.class_name, str(row[0])):
        return False
    if len(row) >= 2 and not _matches_field(suppression.method, str(row[1])):
        return False
    if not _matches_substring(suppression.match, row):
        return False
    return True


def _matches_section_item(rule_id: str, item: str, suppression: Suppression) -> bool:
    """Check if a section item (string) matches a suppression."""
    if suppression.rule_id != rule_id:
        return False
    # For section items, match against the full string
    if suppression.class_name != "*" and suppression.class_name not in item:
        return False
    if suppression.method != "*" and suppression.method not in item:
        return False
    if suppression.match and suppression.match not in item:
        return False
    return True


def apply_suppressions(results: list[RuleResult], suppressions: list[Suppression]) -> tuple[list[RuleResult], int]:
    """
    Filter suppressed findings from results.

    Returns (filtered_results, total_suppressed_count).
    Modifies results in-place for efficiency.
    """
    if not suppressions:
        return results, 0

    total_suppressed = 0

    for result in results:
        rule_sups = [s for s in suppressions if s.rule_id == result.rule_id]
        if not rule_sups:
            continue

        # Filter flat rows
        if result.rows:
            original_count = len(result.rows)
            result.rows = [
                row for row in result.rows
                if not any(matches_suppression(result.rule_id, row, s) for s in rule_sups)
            ]
            total_suppressed += original_count - len(result.rows)

        # Filter section items
        for section in result.sections:
            if section.items:
                original_count = len(section.items)
                section.items = [
                    item for item in section.items
                    if not any(_matches_section_item(result.rule_id, item, s) for s in rule_sups)
                ]
                total_suppressed += original_count - len(section.items)

            for sub in section.subsections:
                if sub.items:
                    original_count = len(sub.items)
                    sub.items = [
                        item for item in sub.items
                        if not any(_matches_section_item(result.rule_id, item, s) for s in rule_sups)
                    ]
                    total_suppressed += original_count - len(sub.items)

    return results, total_suppressed


def show_suppressions(output_dir: str):
    """Print current suppressions to terminal."""
    suppressions = load_suppressions(output_dir)
    if not suppressions:
        print("No suppressions configured.")
        print(f"  File: {os.path.join(output_dir, SUPPRESSIONS_FILE)}")
        return

    print(f"\nSuppressions ({len(suppressions)}):\n")
    print(f"  {'Rule':<8} {'Class':<35} {'Method':<25} {'Reason'}")
    print(f"  {'—'*6:<8} {'—'*33:<35} {'—'*23:<25} {'—'*30}")
    for s in suppressions:
        print(f"  {s.rule_id:<8} {s.class_name:<35} {s.method:<25} {s.reason}")
        if s.match:
            print(f"  {'':8} match: {s.match}")
    print(f"\n  File: {os.path.join(output_dir, SUPPRESSIONS_FILE)}")
