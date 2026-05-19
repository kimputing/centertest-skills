"""
Rules 5001 and 5002: Code complexity analysis (beyond Eir).

5001 — Cyclomatic complexity analysis
5002 — Method length analysis
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, Section
from eir_rules import rule
from rule_core import get_implemented_classes

# Patterns that increase cyclomatic complexity
_COMPLEXITY_PATTERNS = [
    re.compile(r"\bif\s*\("),
    re.compile(r"\belse\s+if\s*\("),
    re.compile(r"\bfor\s*\("),
    re.compile(r"\bwhile\s*\("),
    re.compile(r"\bcase\s+"),
    re.compile(r"\bcatch\s*\("),
    re.compile(r"&&"),
    re.compile(r"\|\|"),
    re.compile(r"\?"),  # ternary operator
]


def _cyclomatic_complexity(body: str) -> int:
    """Estimate cyclomatic complexity from method body text."""
    if not body:
        return 1
    complexity = 1  # base complexity
    for pattern in _COMPLEXITY_PATTERNS:
        complexity += len(pattern.findall(body))
    return complexity


@rule(id="5001", description="Methods with high cyclomatic complexity", category="Complexity")
def high_complexity_methods(commits: CommitsDict, config) -> RuleResult:
    """
    Find methods exceeding the cyclomatic complexity threshold.

    Threshold configurable via eir.rule.5001.threshold (default: 10).
    """
    threshold = config.get_threshold("5001", 10)

    result = RuleResult(
        rule_id="5001",
        description="Methods with high cyclomatic complexity",
        category="Complexity",
        headers=["Class", "Method", "Complexity"],
    )

    for commit_info, files in sorted(commits.items()):
        implemented = get_implemented_classes(files)

        for f in implemented:
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                cc = _cyclomatic_complexity(method.body)
                if cc > threshold:
                    result.rows.append([
                        mc.class_name,
                        method.name,
                        cc,
                    ])

    return result


@rule(id="5002", description="Methods exceeding recommended length", category="Complexity")
def long_methods(commits: CommitsDict, config) -> RuleResult:
    """
    Find methods exceeding the line count threshold.

    Threshold configurable via eir.rule.5002.threshold (default: 50).
    """
    threshold = config.get_threshold("5002", 50)

    result = RuleResult(
        rule_id="5002",
        description="Methods exceeding recommended length",
        category="Complexity",
        headers=["Class", "Method", "Lines"],
    )

    for commit_info, files in sorted(commits.items()):
        implemented = get_implemented_classes(files)

        for f in implemented:
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                line_count = len(method.body.splitlines())
                if line_count > threshold:
                    result.rows.append([
                        mc.class_name,
                        method.name,
                        line_count,
                    ])

    return result
