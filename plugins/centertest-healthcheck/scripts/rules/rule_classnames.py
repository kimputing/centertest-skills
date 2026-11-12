"""
Rules 1001-1004: Class naming analysis.

1001 — Test class naming convention statistics
1002 — Test classes with names longer than 120 characters
1003 — Test classes with package name in class name
1004 — Possible new packages within existing package
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, Section
from eir_rules import rule
from rule_core import get_test_list, divide_tests_by_package, split_camel_case


@rule(id="1001", description="Test class naming convention statistics", category="ClassNames", periodic=True)
def naming_convention_stats(commits: CommitsDict, config) -> RuleResult:
    """
    Per-commit stats: count of too-long names (>120) and missing suffixes.

    Missing suffix = @CenterTest class not ending with "Test" or
                     @ScenarioContainer class not ending with "ScenarioContainer".
    """
    result = RuleResult(
        rule_id="1001",
        description="Test class naming convention statistics",
        category="ClassNames",
        headers=["Commit", "Names > 120 chars", "Missing suffixes"],
    )

    # Also collect violating class names for detail reporting
    all_too_long = []
    all_missing_suffix = []

    # Known exceptions — classes that intentionally don't follow suffix convention
    suffix_exceptions = {"CheckEnvironmentAvailability"}

    for commit_info, files in sorted(commits.items()):
        test_list = get_test_list(files)
        too_long = 0
        missing_suffix = 0

        for f in test_list:
            mc = f.main_class
            if mc is None:
                continue
            if mc.class_name in suffix_exceptions:
                continue
            if len(mc.class_name) > 120:
                too_long += 1
                all_too_long.append(mc.key)
            if "CenterTest" in mc.annotations and not mc.class_name.endswith("Test"):
                missing_suffix += 1
                all_missing_suffix.append(f"{mc.key} (@CenterTest, missing 'Test' suffix)")
            if "ScenarioContainer" in mc.annotations and not mc.class_name.endswith("ScenarioContainer"):
                missing_suffix += 1
                all_missing_suffix.append(f"{mc.key} (@ScenarioContainer, missing 'ScenarioContainer' suffix)")

        result.rows.append([commit_info.label, too_long, missing_suffix])

    # Add detail sections listing the violating classes
    if all_too_long:
        result.sections.append(Section(
            title="Classes with names > 120 characters",
            items=all_too_long,
        ))
    if all_missing_suffix:
        result.sections.append(Section(
            title="Classes with missing naming suffix",
            items=all_missing_suffix,
        ))

    return result


@rule(id="1002", description="Test classes with names longer than 120 characters", category="ClassNames")
def long_class_names(commits: CommitsDict, config) -> RuleResult:
    """List test classes with names exceeding 120 characters."""
    result = RuleResult(
        rule_id="1002",
        description="Test classes with names longer than 120 characters",
        category="ClassNames",
    )

    for commit_info, files in sorted(commits.items()):
        test_list = get_test_list(files)
        violations = []
        for f in test_list:
            if f.main_class and len(f.main_class.class_name) > 120:
                violations.append(f.main_class.key)

        # Skip commits with no violations (matching Eir)
        if violations:
            section = Section(title=f"Commit {commit_info.label}", items=violations)
            result.sections.append(section)

    return result


@rule(id="1003", description="Test classes with package name in class name", category="ClassNames")
def package_name_in_class(commits: CommitsDict, config) -> RuleResult:
    """
    Find test classes where the immediate parent folder name appears in the filename.

    Uses path-based comparison (matching Eir): parent folder name vs filename, both lowercased.
    """
    result = RuleResult(
        rule_id="1003",
        description="Test classes with package name in class name",
        category="ClassNames",
    )

    for commit_info, files in sorted(commits.items()):
        test_list = get_test_list(files)
        # Group by parent folder name
        by_folder: dict[str, list[str]] = defaultdict(list)

        for f in test_list:
            # Use file path (key) to get parent folder name and filename
            path = f.key
            parent_folder = os.path.basename(os.path.dirname(path)).lower()
            file_name = os.path.basename(path).replace(".java", "").lower()

            # PA_SubmissionTest in .../submission/: a <LOB>_<Transaction>Test name repeats the folder on
            # purpose (the LOB prefix makes it unique across lines), so it is not a redundant package name.
            raw_name = os.path.basename(path).replace(".java", "")
            if re.match(r"[A-Za-z0-9]{1,8}_" + re.escape(parent_folder), raw_name, re.IGNORECASE):
                continue
            if parent_folder and parent_folder in file_name:
                by_folder[parent_folder].append(f.main_class.key if f.main_class else f.file_name)

        if by_folder:
            total = sum(len(v) for v in by_folder.values())
            section = Section(
                title=f"Commit {commit_info.label} — {total} possible removal(s)",
            )
            for folder_name, class_keys in sorted(by_folder.items()):
                sub = Section(title=folder_name, items=class_keys)
                section.subsections.append(sub)
            result.sections.append(section)

    return result


@rule(id="1004", description="Possible new packages within existing package", category="ClassNames")
def possible_new_packages(commits: CommitsDict, config) -> RuleResult:
    """
    Find common word prefixes in test class names within a package.

    For each package, splits test class names by CamelCase and suggests a sub-package for a
    word shared by at least 3 classes (and more than 30% of them) but not by all: a word every
    class carries is the package's theme, not a split. Connecting words and words that already
    name a segment of the package path are skipped.
    """
    result = RuleResult(
        rule_id="1004",
        description="Possible new packages within existing package",
        category="ClassNames",
    )

    skip_words = {"Test", "ScenarioContainer", "_", "", "In", "And", "Of", "For", "With", "To", "By",
                  "On", "The", "A", "An", "From", "Or", "At", "Is"}
    min_classes = 3

    for commit_info, files in sorted(commits.items()):
        by_package = divide_tests_by_package(files)
        commit_sections = []

        for pkg_name, pkg_files in sorted(by_package.items()):
            if len(pkg_files) <= 1:
                continue

            # Split all class names and count word frequencies
            word_counts: dict[str, int] = defaultdict(int)
            total_classes = len(pkg_files)

            for f in pkg_files:
                if f.main_class is None:
                    continue
                words = split_camel_case(f.main_class.class_name)
                seen = set()
                for w in words:
                    if w not in skip_words and w not in seen:
                        word_counts[w] += 1
                        seen.add(w)

            # A sub-package: enough classes share the word, but not all of them
            threshold = total_classes * 0.3
            segments = {seg.lower() for seg in pkg_name.split(".")}
            candidates = {w: c for w, c in word_counts.items()
                          if c > threshold and c >= min_classes and c < total_classes
                          and w.lower() not in segments}

            if candidates:
                items = []
                for word, count in sorted(candidates.items(), key=lambda x: (-x[1], x[0])):
                    pct = count * 100 / total_classes
                    items.append(f"{word}: {count}/{total_classes} ({pct:.0f}%)")
                commit_sections.append(Section(title=pkg_name, items=items))

        if commit_sections:
            section = Section(
                title=f"Commit {commit_info.label}",
                subsections=commit_sections,
            )
            result.sections.append(section)

    return result
