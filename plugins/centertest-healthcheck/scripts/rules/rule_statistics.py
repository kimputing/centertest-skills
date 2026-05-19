"""
Rules 0001 and 0002: General test statistics.

0001 — General test statistics per commit
0002 — General test statistics by package
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, Section
from eir_rules import rule
from rule_core import (
    get_test_list, get_implemented_classes, divide_files_by_package,
    count_test_cases, count_commented_out_classes, safe_median, format_decimal,
)


@rule(id="0001", description="General test statistics", category="Statistics", periodic=True)
def general_test_statistics(commits: CommitsDict, config) -> RuleResult:
    """
    General test statistics per commit.

    Columns: Commit, Test Classes, Commented-Out Classes, Test Cases,
             Lines, LOC, Median LOC, Comment Lines, Comment %
    """
    result = RuleResult(
        rule_id="0001",
        description="General test statistics",
        category="Statistics",
        headers=["Commit", "Test Classes", "Commented-Out", "Test Cases",
                 "Lines", "LOC", "Median LOC", "Comment Lines", "Comment %"],
    )

    for commit_info, files in sorted(commits.items()):
        test_list = get_test_list(files)
        test_count = len(test_list)

        # Commented-out classes: files where all lines are comments
        commented_out = count_commented_out_classes(files)

        # Test cases counted from ALL files, not just test files (matching Eir)
        test_cases = count_test_cases(files)

        # Line metrics from test files only
        loc_sum = sum(f.lines_of_code for f in test_list)
        lines_sum = sum(f.lines for f in test_list)

        # Comment lines: from test list + fully-commented files in full commit
        comments_sum = sum(f.comment_lines for f in test_list)
        comments_sum += sum(f.comment_lines for f in files
                            if f.comment_lines > 0 and f.comment_lines == f.lines)

        # Median LOC from test files
        loc_values = [f.lines_of_code for f in test_list if f.lines_of_code > 0]
        median_loc = safe_median(loc_values)

        # Comment percentage
        comment_pct = (comments_sum * 100 / loc_sum) if loc_sum > 0 else 0

        result.rows.append([
            commit_info.label,
            test_count,
            commented_out,
            test_cases,
            lines_sum,
            loc_sum,
            format_decimal(median_loc),
            comments_sum,
            format_decimal(comment_pct),
        ])

    return result


@rule(id="0002", description="General test statistics by package", category="Statistics", periodic=True)
def general_test_statistics_by_package(commits: CommitsDict, config) -> RuleResult:
    """
    General test statistics grouped by package, per commit.

    Uses divideFilesByPackage (ALL files), then filters to tests per package.
    """
    result = RuleResult(
        rule_id="0002",
        description="General test statistics by package",
        category="Statistics",
    )

    for commit_info, files in sorted(commits.items()):
        section = Section(
            title=f"Commit {commit_info.label}",
            headers=["Package", "Test Classes", "Commented-Out", "Test Cases",
                     "Lines", "LOC", "Median LOC", "Comment Lines", "Comment %"],
        )

        # divideFilesByPackage groups ALL files (matching Eir)
        by_package = divide_files_by_package(files)

        for pkg_name, pkg_files in by_package.items():
            test_list = get_test_list(pkg_files)
            test_count = len(test_list)
            commented_out = count_commented_out_classes(pkg_files)
            test_cases = count_test_cases(pkg_files)

            loc_sum = sum(f.lines_of_code for f in test_list)
            lines_sum = sum(f.lines for f in test_list)
            comments_sum = sum(f.comment_lines for f in test_list)
            comments_sum += sum(f.comment_lines for f in pkg_files
                                if f.comment_lines > 0 and f.comment_lines == f.lines)

            # Median excludes LOC==0 files (matching Eir)
            loc_values = [f.lines_of_code for f in test_list if f.lines_of_code > 0]
            median_loc = safe_median(loc_values)

            comment_pct = (comments_sum * 100 / loc_sum) if loc_sum > 0 else 0

            section.rows.append([
                pkg_name,
                test_count,
                commented_out,
                test_cases,
                lines_sum,
                loc_sum,
                format_decimal(median_loc),
                comments_sum,
                f"{format_decimal(comment_pct)}%",
            ])

        result.sections.append(section)

    return result
