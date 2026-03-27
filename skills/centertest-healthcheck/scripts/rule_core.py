#!/usr/bin/env python3
"""
Shared rule utilities for eir-analyzer.

Mirrors Eir's RuleCore base class: filtering, grouping, and helper methods
used by multiple rules.

Placed at scripts/ level (not inside rules/) to keep dependency direction clean.

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/eir-analyzer/scripts/rule_core.py
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict

from eir_models import SourceCodeFile


def get_test_list(files: list[SourceCodeFile]) -> list[SourceCodeFile]:
    """
    Filter to test classes: files whose main class has @CenterTest or @ScenarioContainer.

    Matches Eir's getTestList().
    """
    return [f for f in files if f.is_test_class()]


def get_implemented_classes(files: list[SourceCodeFile]) -> list[SourceCodeFile]:
    """
    Filter to files with a non-null main class.

    Matches Eir's getImplementedClasses().
    """
    return [f for f in files if f.main_class is not None]


def divide_files_by_package(files: list[SourceCodeFile]) -> dict[str, list[SourceCodeFile]]:
    """
    Group ALL files by package_name.

    Matches Eir's divideFilesByPackage() — groups all files, not just tests.
    Rule 0002 uses this to get per-package stats.
    """
    by_pkg: dict[str, list[SourceCodeFile]] = defaultdict(list)
    for f in files:
        by_pkg[f.package_name].append(f)
    return dict(sorted(by_pkg.items()))


def divide_tests_by_package(files: list[SourceCodeFile]) -> dict[str, list[SourceCodeFile]]:
    """
    Group test classes by package_name.

    Matches Eir's divideTestsByPackage().
    """
    by_pkg: dict[str, list[SourceCodeFile]] = defaultdict(list)
    for f in files:
        if f.is_test_class():
            by_pkg[f.package_name].append(f)
    return dict(sorted(by_pkg.items()))


def safe_median(values: list[int | float]) -> float:
    """Compute median, returning 0 for empty lists."""
    if not values:
        return 0.0
    return statistics.median(values)


def split_camel_case(name: str) -> list[str]:
    """
    Split a string by CamelCase boundaries.

    Approximates Apache Commons StringUtils.splitByCharacterTypeCamelCase:
    - Splits at lowercase→uppercase transitions
    - Splits at uppercase→lowercase when preceded by uppercase run
    - Splits at letter→digit and digit→letter transitions
    - Splits on non-alphanumeric characters
    """
    # Insert spaces at transitions
    result = name
    # Uppercase run followed by uppercase+lowercase (e.g., XMLParser → XML Parser)
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", result)
    # Lowercase/digit followed by uppercase (e.g., testClass → test Class)
    result = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", result)
    # Letter→digit (e.g., Test3 → Test 3)
    result = re.sub(r"([A-Za-z])(\d)", r"\1 \2", result)
    # Digit→letter (e.g., 3D → 3 D)
    result = re.sub(r"(\d)([A-Za-z])", r"\1 \2", result)
    # Split on spaces and non-alphanumeric
    tokens = re.split(r"[\s_]+", result)
    return [t for t in tokens if t]


def count_test_cases(files: list[SourceCodeFile]) -> int:
    """
    Count test case methods across ALL files (not just test files).

    Matches Eir rule 0001: counts methods with @CenterTestCase or @Scenario
    from all files where main_class is not None and method_count > 0.
    """
    count = 0
    for f in files:
        if f.main_class is not None and f.main_class.method_count > 0:
            for method in f.main_class.methods:
                if "CenterTestCase" in method.annotations or "Scenario" in method.annotations:
                    count += 1
    return count


def count_commented_out_classes(files: list[SourceCodeFile]) -> int:
    """Count files where all lines are comments (fully commented-out files)."""
    return sum(1 for f in files if f.comment_lines > 0 and f.comment_lines == f.lines)


def format_decimal(value: float) -> str:
    """Format a float to match Java DecimalFormat('#.##')."""
    if value == int(value):
        return str(int(value))
    formatted = f"{value:.2f}"
    # Strip trailing zeros after decimal
    formatted = formatted.rstrip("0").rstrip(".")
    return formatted if formatted else "0"
