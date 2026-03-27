"""
Rules 15001, 15002, 15004, 15005: Common Java quality issues (beyond Eir).

15001 — Null pointer risk detection
15002 — Potential IndexOutOfBoundsException (.get(N) on lists)
15004 — String comparison issues (== instead of .equals())
15005 — Exception handling anti-patterns (empty catch blocks)
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_core import get_implemented_classes

# Pattern for chained method calls without null checks (4+ calls = higher risk)
_CHAIN_RE = re.compile(r"(\w+(?:\.\w+\([^)]*\)){4,})")

# Pattern for string == comparison
_STRING_EQ_RE = re.compile(r'(?:getString|getValue|getText|getName|toString)\s*\(\s*\)\s*==\s*"')
_STRING_EQ_RE2 = re.compile(r'"\s*==\s*\w+')

# Pattern for empty catch blocks
_EMPTY_CATCH_RE = re.compile(r"catch\s*\([^)]+\)\s*\{\s*\}", re.DOTALL)


@rule(id="15001", description="Potential null pointer risks", category="Quality")
def null_pointer_risks(commits: CommitsDict, config) -> RuleResult:
    """
    Find method call chains that risk NullPointerException.

    In CenterTest projects, most getter chains on page objects and widgets are
    generated and null-safe. This rule focuses on genuinely risky patterns:
    - JSON/Map access chains (e.g., body.get("key").getAsJsonObject().get(...))
    - External API response chains
    - Chains mixing data access with value comparison
    """
    result = RuleResult(
        rule_id="15001",
        description="Potential null pointer risks",
        category="Quality",
        headers=["Class", "Method", "Chain"],
    )

    # Genuinely risky patterns — JSON/Map/external API access
    # These return null from .get() and NPE on the next call
    risky_patterns = [
        ".getAsJsonObject()",   # Gson — NPE if parent .get() returned null
        ".getAsString()",       # Gson — NPE if parent .get() returned null
        ".getAsInt()",          # Gson — NPE if parent .get() returned null
    ]

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                for match in _CHAIN_RE.finditer(method.body):
                    chain = match.group(1)

                    # Only flag chains with genuinely risky JSON/Map patterns
                    if any(rp in chain for rp in risky_patterns):
                        result.rows.append([mc.class_name, method.name, chain[:150]])

    return result


# Pattern for .get(N) on lists — potential IndexOutOfBoundsException
# Matches: .get(0), .get(1), .get(2), etc. but NOT .get("string") or .get(variable)
_LIST_GET_RE = re.compile(r'\.get\(\s*(\d+)\s*\)')


@rule(id="15002", description="Potential IndexOutOfBoundsException", category="Quality")
def index_out_of_bounds_risks(commits: CommitsDict, config) -> RuleResult:
    """
    Find .get(N) calls on lists/collections using a hardcoded numeric index
    that are NOT guarded by a size check or isEmpty check.

    Patterns like getOptionList().get(1), getRows().get(0) risk
    IndexOutOfBoundsException if the list is smaller than expected.

    Skips calls where the method body contains .size() or .isEmpty() checks
    on the same collection variable, indicating the developer is aware of bounds.
    """
    result = RuleResult(
        rule_id="15002",
        description="Potential IndexOutOfBoundsException",
        category="Quality",
        headers=["Class", "Method", "Index", "Line"],
    )

    # Patterns that indicate a size guard exists in the method
    _GUARD_PATTERNS = [".size()", ".isEmpty()", "!isEmpty()", ".isPresent()"]

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue

                body = method.body

                for line in body.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    for m in _LIST_GET_RE.finditer(stripped):
                        index = int(m.group(1))

                        # Skip getFirstRow()-style patterns
                        context = stripped[:m.start()]
                        if "getFirstRow" in context:
                            continue

                        # Try to identify the collection variable/expression
                        # before .get(N) — e.g. "rows.get(0)" → "rows",
                        # "getOptionList().get(1)" → "getOptionList()"
                        prefix = stripped[:m.start()].rstrip(".")
                        # Extract the last token (variable or method call)
                        col_name = ""
                        for part in reversed(prefix.split(".")):
                            col_name = part.strip()
                            break

                        # Check if the method body contains a size/isEmpty
                        # guard on the same collection
                        guarded = False
                        if col_name:
                            for guard in _GUARD_PATTERNS:
                                if col_name + guard in body or col_name.rstrip(")") + guard in body:
                                    guarded = True
                                    break

                        if guarded:
                            continue

                        result.rows.append([
                            mc.class_name,
                            method.name,
                            index,
                            stripped[:150],
                        ])

    return result


@rule(id="15004", description="String comparison with == instead of .equals()", category="Quality")
def string_comparison_issues(commits: CommitsDict, config) -> RuleResult:
    """
    Find string comparisons using == instead of .equals().

    Detects patterns like: getValue() == "expected" or "expected" == variable
    """
    result = RuleResult(
        rule_id="15004",
        description="String comparison with == instead of .equals()",
        category="Quality",
        headers=["Class", "Method", "Line"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                for line in method.body.splitlines():
                    stripped = line.strip()
                    if _STRING_EQ_RE.search(stripped) or _STRING_EQ_RE2.search(stripped):
                        result.rows.append([
                            mc.class_name,
                            method.name,
                            stripped[:150],
                        ])

    return result


@rule(id="15005", description="Empty catch blocks", category="Quality")
def empty_catch_blocks(commits: CommitsDict, config) -> RuleResult:
    """
    Find empty catch blocks that silently swallow exceptions.

    Detects: catch (Exception e) { } with nothing inside.
    """
    result = RuleResult(
        rule_id="15005",
        description="Empty catch blocks",
        category="Quality",
        headers=["Class", "Method"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                if _EMPTY_CATCH_RE.search(method.body):
                    result.rows.append([mc.class_name, method.name])

    return result
