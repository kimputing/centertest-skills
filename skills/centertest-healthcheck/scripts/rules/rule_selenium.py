"""
Rule 3001: Selenium XPath analysis.

3001 — Find elements found by long XPaths
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, Section
from eir_rules import rule
from rule_core import get_implemented_classes


@rule(id="3001", description="Find elements by long XPaths", category="Selenium")
def long_xpath_detection(commits: CommitsDict, config) -> RuleResult:
    """
    Find methods using findElement(By.xpath or findElements(By.xpath.

    Uses full SHA in section headers (matching Eir).
    """
    result = RuleResult(
        rule_id="3001",
        description="Find elements by long XPaths",
        category="Selenium",
    )

    for commit_info, files in sorted(commits.items()):
        implemented = get_implemented_classes(files)
        findings = set()

        for f in implemented:
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                if "findElement(By.xpath" in method.body or "findElements(By.xpath" in method.body:
                    findings.add(f"{mc.class_name}:{method.name}")

        if findings:
            # Full SHA in headers (matching Eir)
            section = Section(
                title=f"Commit {commit_info.label}",
                items=sorted(findings),
            )
            result.sections.append(section)

    return result
