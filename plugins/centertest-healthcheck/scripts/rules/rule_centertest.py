"""
Rules 9001, 9003, 9005, 9007, 9008: CenterTest framework compliance (beyond Eir).

9001 — Direct Selenium usage instead of CenterTest widgets
9003 — @DataDriven annotation patterns
9005 — CenterTest assertion framework usage
9007 — Thread.sleep anti-pattern detection
9008 — ImplicitSleep.sleep usage detection
"""

from __future__ import annotations

import os
import re
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
    "new Actions(",  # not "Actions(", which also matches e.g. clearActions()
    "new Select(",
]


def _scanned_classes(f):
    """
    Yield (display name, ClassEntry) for the main class and its inner classes.

    Tests often keep their flow steps in inner classes, so the rules must read
    those too. Inner classes are shown as Outer.Inner.
    """
    mc = f.main_class
    yield mc.class_name, mc
    for inner in f.inner_classes:
        yield f"{mc.class_name}.{inner.class_name}", inner


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
            for class_name, ce in _scanned_classes(f):
                for method in ce.methods:
                    if not method.body:
                        continue
                    for pattern in _SELENIUM_PATTERNS:
                        if pattern in method.body:
                            result.rows.append([class_name, method.name, pattern])
                            break  # one finding per method

    return result


# DDTHelper.getX(<arg>): with a ScenarioContext argument it reads the scenario's own data row,
# which only exists when the test is @DataDriven. getX("code") loads a row by code and needs nothing.
_DDT_GETTER_CALL = re.compile(r"DDTHelper\.get\w+\(\s*(\w+)\s*\)")
_CONTEXT_PARAM = re.compile(r"\bScenarioContext\s+(\w+)")


@rule(id="9003", description="Test reads scenario data without @DataDriven", category="CenterTest")
def data_driven_patterns(commits: CommitsDict, config) -> RuleResult:
    """
    Test classes that read the scenario's data row -- DDTHelper.getX(scenarioContext) or
    scenarioContext.getTestData() -- with no @DataDriven on the class or any method. The run has
    no data row, so the test cannot run.

    Loading a row by code (DDTHelper.getX("code")) is not reported: it needs no @DataDriven.
    """
    result = RuleResult(
        rule_id="9003",
        description="Test reads scenario data without @DataDriven",
        category="CenterTest",
        headers=["Class", "Method", "Issue"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in files:
            mc = f.main_class
            if mc is None or not f.is_test_class():
                continue

            methods = [m for _, ce in _scanned_classes(f) for m in ce.methods]
            has_data_driven = "DataDriven" in mc.annotations or any(
                "DataDriven" in m.annotations for m in methods)
            if has_data_driven:
                continue

            # Method bodies start at "{", so ScenarioContext parameter names come from the file.
            names = {"scenarioContext"}
            try:
                with open(f.key, encoding="utf-8", errors="replace") as fh:
                    names.update(_CONTEXT_PARAM.findall(fh.read()))
            except OSError:
                pass
            for m in methods:
                body = m.body or ""
                reads = [a for a in _DDT_GETTER_CALL.findall(body) if a in names]
                reads += [n for n in names if re.search(r"\b" + re.escape(n) + r"\.getTestData\(\)", body)]
                if reads:
                    result.rows.append([
                        mc.key,
                        m.name,
                        "Reads the scenario's data row but has no @DataDriven, so the run has no data",
                    ])
                    break

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
            for class_name, ce in _scanned_classes(f):
                for method in ce.methods:
                    if not method.body:
                        continue
                    if "Thread.sleep(" in method.body:
                        result.rows.append([class_name, method.name])

    return result


# JUnit raw assertion patterns (anti-pattern in CenterTest)
_JUNIT_ASSERT_PATTERNS = [
    "Assert.assertEquals(",
    "Assert.assertTrue(",
    "Assert.assertFalse(",
    "Assert.assertNull(",
    "Assert.assertNotNull(",
    "Assert.fail(",
    "org.junit.Assert",
]


@rule(id="9005", description="CenterTest assertion framework usage", category="CenterTest")
def assertion_framework_usage(commits: CommitsDict, config) -> RuleResult:
    """
    Find incorrect assertion patterns in CenterTest code.

    CORRECT patterns (widget-based assertions):
      - widget.assertEquals(value)
      - widget.assertContains(substring)
      - widget.assertNotEmpty()
      - widget.assertNotNull()
      - widget.assertEqualsNumeric(value)
      - CenterTestAssertion.withContext(...).assertThat(...)

    ANTI-PATTERNS (raw JUnit/Java assertions):
      - Assert.assertEquals(expected, actual)
      - Assert.assertTrue(condition)
      - assert keyword
      - Direct Assertions.assertThat() without CenterTestAssertion wrapper
    """
    result = RuleResult(
        rule_id="9005",
        description="CenterTest assertion framework usage",
        category="CenterTest",
        headers=["Class", "Method", "Issue", "Line"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            for class_name, ce in _scanned_classes(f):
                for method in ce.methods:
                    if not method.body:
                        continue
                    for line in method.body.splitlines():
                        stripped = line.strip()
                        if not stripped:
                            continue

                        # Check for raw JUnit Assert usage
                        for pattern in _JUNIT_ASSERT_PATTERNS:
                            if pattern in stripped:
                                result.rows.append([
                                    class_name,
                                    method.name,
                                    "Raw JUnit Assert — use widget.assertXxx() or CenterTestAssertion",
                                    stripped[:150],
                                ])
                                break

                        # Check for Assertions.assertThat without CenterTestAssertion wrapper
                        if "Assertions.assertThat(" in stripped and "CenterTestAssertion" not in method.body:
                            result.rows.append([
                                class_name,
                                method.name,
                                "Unwrapped AssertJ — wrap with CenterTestAssertion.withContext()",
                                stripped[:150],
                            ])

    return result


@rule(id="9008", description="ImplicitSleep.sleep usage", category="CenterTest")
def implicit_sleep_detection(commits: CommitsDict, config) -> RuleResult:
    """
    Find ImplicitSleep.sleep() calls in test code.

    ImplicitSleep adds fixed delays that slow down test execution.
    Consider using explicit waits or widget-level wait mechanisms instead.
    """
    result = RuleResult(
        rule_id="9008",
        description="ImplicitSleep.sleep usage",
        category="CenterTest",
        headers=["Class", "Method", "Line"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            for class_name, ce in _scanned_classes(f):
                for method in ce.methods:
                    if not method.body:
                        continue
                    for line in method.body.splitlines():
                        stripped = line.strip()
                        if "ImplicitSleep.sleep(" in stripped:
                            result.rows.append([
                                class_name,
                                method.name,
                                stripped[:150],
                            ])

    return result
