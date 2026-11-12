"""
Rule 14005: suite entries that run nothing.

CenterTestSuiteList.json entries are read the way CenterTest reads them -- each part a
case-insensitive regex on the whole class, method or code -- by suite.py, a vendored copy of
plugins/suite-builder/scripts/suite.py. An entry that matches no test is reported by CenterTest
as a failed scenario, and the suite silently stops running what it lists; a composite suite that
names a missing suite loses that part, and a package pattern that matches no test class runs nothing.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule


def _line_of(text: str, after: int, value: str) -> int:
    """1-based line of the JSON string `value` at or after offset `after` (0 when not found)."""
    i = text.find(json.dumps(value, ensure_ascii=False), after)
    return text.count("\n", 0, i) + 1 if i >= 0 else 0


@rule(id="14005", description="Suite entries that run nothing", category="CenterTest")
def suite_entries_that_run_nothing(commits: CommitsDict, config) -> RuleResult:
    import suite as suites
    result = RuleResult(
        rule_id="14005",
        description="Suite entries that run nothing",
        category="CenterTest",
        headers=["Suite", "Entry", "Issue", "Location"],
    )
    repo = config.repository_dir
    path = suites.find_suite_file(repo)
    if not os.path.isfile(path):
        return result
    try:
        doc, text = suites.load_suites(path)
    except (OSError, ValueError) as e:
        result.error = f"Cannot read {os.path.relpath(path, repo)}: {e}"
        return result
    tests = suites.scan(repo, getattr(config, "source_root", "src/main/java"))
    scenarios = suites.scenarios_of(tests)
    rel = os.path.relpath(path, repo).replace("\\", "/")
    # CenterTest finds a child suite by exact name (TestDataProvider.readFilterList: filter.contains(name)),
    # so "regression" does not reach the suite "Regression".
    exact = {str(s.get("Name", "")) for s in doc["CenterTestSuites"]}
    folded = {n.lower(): n for n in exact}
    for s in doc["CenterTestSuites"]:
        name = str(s.get("Name", ""))
        start = text.find(json.dumps(name, ensure_ascii=False))
        for entry in s.get("List", []) or []:
            if not suites.resolve_entry(entry, scenarios):
                result.rows.append([name, entry, suites.why_nothing(entry, tests),
                                    f"{rel}:{_line_of(text, max(start, 0), entry)}"])
        by_class = {t["class"]: t["package"] for t in tests}
        for pattern in s.get("Packages", []) or []:
            if not any(suites._full(pattern, pkg) or suites._full(pattern, f"{pkg}.{cls}") for cls, pkg in by_class.items()):
                result.rows.append([name, pattern, "package pattern matches no test class",
                                    f"{rel}:{_line_of(text, max(start, 0), pattern)}"])
        for child in s.get("Suites", []) or []:
            if str(child) not in exact:
                near = folded.get(str(child).lower())
                issue = (f"names suite '{child}', but the suite is '{near}': CenterTest matches suite names exactly, "
                         "so this part runs nothing") if near else "names a suite that does not exist"
                result.rows.append([name, child, issue, f"{rel}:{_line_of(text, max(start, 0), child)}"])
    return result


@rule(id="9011", description="Data-driven tests with no enabled rows", category="CenterTest")
def tests_with_no_enabled_rows(commits: CommitsDict, config) -> RuleResult:
    """@DataDriven test methods whose DataCombination rows are all disabled (or that have none):
    they run no scenario, yet the class exists and suites may list it. Parked on purpose or
    forgotten -- either way the suite does less than it says."""
    import suite as suites
    result = RuleResult(
        rule_id="9011",
        description="Data-driven tests with no enabled rows",
        category="CenterTest",
        headers=["Class", "Method", "Issue"],
    )
    tests = suites.scan(config.repository_dir, getattr(config, "source_root", "src/main/java"))
    for (cls, method), workbook in sorted(suites.switched_off(tests).items()):
        result.rows.append([cls, method, f"every row of {os.path.basename(workbook)} is disabled: the test runs nothing"])
    return result
