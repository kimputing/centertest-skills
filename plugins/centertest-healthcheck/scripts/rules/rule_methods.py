"""
Rules 4001 and 4002: Method-level analysis.

4001 — Find possible variable substitutions
4002 — Find duplicate table row selections
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, Section
from eir_rules import rule
from rule_core import get_implemented_classes


# Lines starting with these prefixes are not replaceable (matching Eir)
_NOT_REPLACEABLE_PREFIXES = ("var ", "{", "}", "try", "throw", "logger", "new ")


def _parse_prefixes(method_body: str, mode: str = "overall") -> dict[str, int]:
    """
    Extract dot-chained prefixes from a method body.

    For each line, splits by '.', builds cumulative prefixes of length >= 2,
    then counts how many lines start with each prefix.

    mode="overall" (rule 4001): collects all prefixes of length >= 2
    mode="table" (rule 4002): only collects prefixes ending at .select()
    """
    # Use splitlines() instead of \r\n (fixes Eir's Linux/Mac bug)
    lines = method_body.splitlines()
    prefix_set = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "." not in line:
            continue
        # Check not-replaceable prefixes
        if any(line.startswith(p) for p in _NOT_REPLACEABLE_PREFIXES):
            continue

        # Split by '.' and build cumulative prefixes
        parts = line.split(".")
        prefix = ""
        for i, part in enumerate(parts):
            if i == 0:
                prefix = part
                continue  # First component alone is never a prefix
            prefix = prefix + "." + part

            if mode == "table":
                # Only collect prefixes ending at select()
                if part == "select()":
                    prefix_set.add(prefix)
            else:
                prefix_set.add(prefix)

    # Count how many lines start with each prefix
    prefix_counts = {}
    for prefix in prefix_set:
        count = sum(1 for line in lines if line.strip().startswith(prefix))
        if count > 0:
            prefix_counts[prefix] = count

    return prefix_counts


_KEYWORDS = {"if", "for", "while", "return", "else", "switch", "case", "catch", "do", "assert", "this", "super"}


def _is_extractable(prefix: str) -> bool:
    """Whether a repeated prefix could become a local variable: a complete expression (balanced,
    starts with a name, makes a call), not a statement or an action (ends with ';', runs
    .execute()), not the framework's restart-point idiom, not a stateful builder
    (CenterTestAssertion.withContext(...) must be built per assertion)."""
    p = prefix.strip()
    head = p.split(".", 1)[0].split("(", 1)[0].strip()
    return (p.count("(") == p.count(")") and "(" in p and not p.endswith(";")
            and head.isidentifier() and head not in _KEYWORDS
            and ".execute(" not in p and "restart" not in p.lower()
            and not p.startswith("CenterTestAssertion"))


def _longest(prefix_counts: dict[str, int]) -> dict[str, int]:
    """Drop a prefix when a longer one is repeated as often: the longer chain is the suggestion."""
    return {p: c for p, c in prefix_counts.items()
            if not any(q != p and q.startswith(p) and prefix_counts[q] == c for q in prefix_counts)}


@rule(id="4001", description="Find possible variable substitutions", category="Methods")
def variable_substitutions(commits: CommitsDict, config) -> RuleResult:
    """
    Find expressions repeated in a method that could be one local variable.

    Only complete, side-effect-free-looking expressions count (see _is_extractable), and only
    the longest of a chain's prefixes repeated equally often is suggested.
    Threshold configurable via eir.rule.4001.threshold (default: 2).
    """
    threshold = config.get_threshold("4001", 2)

    result = RuleResult(
        rule_id="4001",
        description="Find possible variable substitutions",
        category="Methods",
    )

    for commit_info, files in sorted(commits.items()):
        implemented = get_implemented_classes(files)
        commit_sections = []

        for f in implemented:
            mc = f.main_class
            if mc is None:
                continue

            for method in mc.methods:
                if not method.body:
                    continue

                prefix_counts = _parse_prefixes(method.body, mode="overall")

                # Filter to extractable expressions meeting threshold, longest chain only
                filtered = _longest({p: c for p, c in prefix_counts.items()
                                     if c >= threshold and _is_extractable(p)})
                if not filtered:
                    continue

                # Sort by count descending
                sorted_prefixes = sorted(filtered.items(), key=lambda x: -x[1])

                items = [f"{count}x — {prefix}" for prefix, count in sorted_prefixes]
                # Build method label: ClassName.methodName (or with inner class)
                method_label = f"{mc.class_name}.{method.name}"
                commit_sections.append(Section(title=method_label, items=items))

        if commit_sections:
            # Full SHA in headers (matching Eir)
            section = Section(
                title=f"Commit {commit_info.label}",
                subsections=commit_sections,
            )
            result.sections.append(section)

    return result


@rule(id="4002", description="Find duplicate table row selections", category="Methods")
def duplicate_table_row_selections(commits: CommitsDict, config) -> RuleResult:
    """
    Find repeated .select() call chains that could be extracted to a variable.

    Same algorithm as 4001 but only collects prefixes ending at .select().
    """
    threshold = config.get_threshold("4002", 2)

    result = RuleResult(
        rule_id="4002",
        description="Find duplicate table row selections",
        category="Methods",
    )

    for commit_info, files in sorted(commits.items()):
        implemented = get_implemented_classes(files)
        commit_sections = []

        for f in implemented:
            mc = f.main_class
            if mc is None:
                continue

            for method in mc.methods:
                if not method.body:
                    continue

                prefix_counts = _parse_prefixes(method.body, mode="table")

                filtered = {p: c for p, c in prefix_counts.items() if c >= threshold}
                if not filtered:
                    continue

                sorted_prefixes = sorted(filtered.items(), key=lambda x: -x[1])
                items = [f"{count}x — {prefix}" for prefix, count in sorted_prefixes]
                method_label = f"{mc.class_name}.{method.name}"
                commit_sections.append(Section(title=method_label, items=items))

        if commit_sections:
            section = Section(
                title=f"Commit {commit_info.label}",
                subsections=commit_sections,
            )
            result.sections.append(section)

    return result
