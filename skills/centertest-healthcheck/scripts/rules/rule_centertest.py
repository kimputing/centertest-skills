"""
Rules 9001, 9003, 9007: CenterTest framework compliance (beyond Eir).

9001 — Direct Selenium usage instead of CenterTest widgets
9003 — @DataDriven annotation patterns
9007 — Thread.sleep anti-pattern detection
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_core import get_implemented_classes

# Direct Selenium patterns that should use CenterTest widgets instead
_SELENIUM_PATTERNS = [
    "WebDriver",
    "WebElement",
    "findElement(",
    "findElements(",
    "driver.get(",
    "driver.navigate(",
    ".sendKeys(",
    "Actions(",
    "new Select(",
]


@rule(id="9001", description="Direct Selenium usage instead of CenterTest widgets", category="CenterTest")
def direct_selenium_usage(commits: CommitsDict, config) -> RuleResult:
    """
    Find methods using Selenium WebDriver/WebElement directly.

    CenterTest provides widget abstractions; direct Selenium usage
    bypasses the framework's wait mechanisms and page object model.
    """
    result = RuleResult(
        rule_id="9001",
        description="Direct Selenium usage instead of CenterTest widgets",
        category="CenterTest",
        headers=["Class", "Method", "Pattern Found"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                for pattern in _SELENIUM_PATTERNS:
                    if pattern in method.body:
                        result.rows.append([mc.class_name, method.name, pattern])
                        break  # one finding per method

    return result


@rule(id="9003", description="@DataDriven annotation patterns", category="CenterTest")
def data_driven_patterns(commits: CommitsDict, config) -> RuleResult:
    """
    Analyze @DataDriven usage patterns.

    Reports only test classes that use DDTHelper but are missing @DataDriven
    annotation, since that indicates a potential misconfiguration.
    """
    result = RuleResult(
        rule_id="9003",
        description="Test classes using DDTHelper without @DataDriven",
        category="CenterTest",
        headers=["Class", "Issue"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in files:
            mc = f.main_class
            if mc is None:
                continue

            # Only check test classes
            if not f.is_test_class():
                continue

            # Check @DataDriven on class OR any method (it's typically on methods)
            has_data_driven = "DataDriven" in mc.annotations
            if not has_data_driven:
                for method in mc.methods:
                    if "DataDriven" in method.annotations:
                        has_data_driven = True
                        break

            # Check for DDTHelper usage in method bodies
            has_ddt_helper = False
            for method in mc.methods:
                if method.body and "DDTHelper" in method.body:
                    has_ddt_helper = True
                    break

            # Report test classes that use DDTHelper but lack @DataDriven
            if has_ddt_helper and not has_data_driven:
                result.rows.append([
                    mc.key,
                    "Uses DDTHelper but missing @DataDriven annotation",
                ])

    return result


@rule(id="9007", description="Thread.sleep anti-pattern detection", category="CenterTest")
def thread_sleep_detection(commits: CommitsDict, config) -> RuleResult:
    """
    Find Thread.sleep() calls in test code.

    CenterTest provides explicit wait mechanisms through its widget framework.
    Thread.sleep() is an anti-pattern that makes tests slow and flaky.
    """
    result = RuleResult(
        rule_id="9007",
        description="Thread.sleep anti-pattern detection",
        category="CenterTest",
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
                if "Thread.sleep(" in method.body:
                    result.rows.append([mc.class_name, method.name])

    return result
