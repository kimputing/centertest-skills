"""
Rules 2001 and 2002: Inheritance analysis.

2001 — Method duplicates in child classes
2002 — Inner class duplicates
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, Section
from eir_rules import rule
from rule_core import get_test_list, get_implemented_classes


@rule(id="2001", description="Method duplicate in child class", category="Inheritance")
def method_duplicates_in_child(commits: CommitsDict, config) -> RuleResult:
    """
    Find inner classes that override parent methods with identical bodies.

    Algorithm (matching Eir):
    1. For each inner class with extensions
    2. Find parent class via import matching (endsWith)
    3. Find parent file via package matching (startsWith)
    4. Compare method bodies — if identical, mark as duplicate
    """
    result = RuleResult(
        rule_id="2001",
        description="Method duplicate in child class",
        category="Inheritance",
    )

    for commit_info, files in sorted(commits.items()):
        test_files = get_test_list(files)
        all_implemented = get_implemented_classes(files)

        # Build a lookup: full import path → SourceCodeFile
        duplicates: dict[str, list[str]] = defaultdict(list)  # inner_key → [method_names]

        for test_file in test_files:
            for inner_class in test_file.inner_classes:
                if not inner_class.extensions:
                    continue

                for parent_name in inner_class.extensions:
                    # Find matching import using endsWith (loose, matching Eir)
                    matching_import = None
                    for imp in test_file.imports:
                        if imp.endswith(parent_name):
                            matching_import = imp
                            break
                    if matching_import is None:
                        continue

                    # Find parent file using startsWith on package_name (loose, matching Eir)
                    parent_file = None
                    for f in all_implemented:
                        if f.main_class and matching_import.startswith(f.package_name) and f.main_class.class_name == parent_name:
                            parent_file = f
                            break
                    if parent_file is None or parent_file.main_class is None:
                        continue

                    # Compare method bodies
                    parent_methods = {m.name: m for m in parent_file.main_class.methods}
                    for child_method in inner_class.methods:
                        parent_method = parent_methods.get(child_method.name)
                        if parent_method and child_method.body == parent_method.body and child_method.body:
                            duplicates[inner_class.key].append(child_method.name)

        if duplicates:
            total = sum(len(v) for v in duplicates.values())
            section = Section(
                title=f"Commit {commit_info.label} — {total} method(s) marked for removal",
            )
            for inner_key, methods in sorted(duplicates.items()):
                sub = Section(title=inner_key, items=methods)
                section.subsections.append(sub)
            result.sections.append(section)

    return result


@rule(id="2002", description="Inner class duplicates", category="Inheritance")
def inner_class_duplicates(commits: CommitsDict, config) -> RuleResult:
    """
    Find structurally identical inner classes across different files.

    Uses ClassEntry equality (excludes class_name and key from comparison).
    Groups by structural identity, reports duplicates.
    """
    result = RuleResult(
        rule_id="2002",
        description="Inner class duplicates",
        category="Inheritance",
    )

    for commit_info, files in sorted(commits.items()):
        # Collect all inner classes
        all_inners = []
        for f in files:
            for inner in f.inner_classes:
                all_inners.append(inner)

        if not all_inners:
            continue

        # Group by structural equality
        groups: dict[int, list[str]] = defaultdict(list)  # hash → [keys]
        for inner in all_inners:
            groups[hash(inner)].append(inner.key)

        # Find duplicates (groups with >1 member)
        has_duplicates = False
        section = Section(title=f"Commit {commit_info.label}")

        # Sort by duplicate count ascending (matching Eir)
        for h, keys in sorted(groups.items(), key=lambda x: len(x[1])):
            if len(keys) <= 1:
                continue
            has_duplicates = True
            dup_count = len(keys) - 1
            plural = "s" if len(keys) > 2 else ""
            sub = Section(
                title=f"Inner classes duplicated {dup_count} time{plural}",
                items=keys,
            )
            section.subsections.append(sub)

        if has_duplicates:
            result.sections.append(section)

    return result
