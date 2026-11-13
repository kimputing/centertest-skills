"""
Rule 0003: Java files the analyzer could not parse.

javalang reads Java up to 8. Newer syntax inside method bodies (switch expressions, yield,
instanceof patterns, text blocks) and records are handled by parsing a lowered copy
(eir_parser._lower_for_javalang), so those files are read in full. What is left -- Java 14+ syntax
outside a body (a switch expression in a field initializer, sealed/permits), or a real syntax
error -- falls back to a regex parse that finds the class and slices method bodies, but inner
classes, fields and annotation arguments are lost there. The rule lists those files so a reader
knows which findings may be missing, instead of the files dropping out silently.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_helpers import latest_files, location


@rule(id="0003", description="Java files the analyzer could not fully parse", category="Statistics")
def unparsed_files(commits: CommitsDict, config) -> RuleResult:
    result = RuleResult(
        rule_id="0003",
        description="Java files the analyzer could not fully parse",
        category="Statistics",
        headers=["File", "Reason", "Methods still checked", "Location"],
    )
    for f in latest_files(commits):
        if not f.cannot_compile:
            continue
        methods = len(f.main_class.methods) if f.main_class else 0
        line = 1
        if "at line " in f.parse_error:
            try:
                line = int(f.parse_error.split("at line ", 1)[1].split()[0])
            except ValueError:
                pass
        result.rows.append([f.file_name, f.parse_error or "unreadable", methods, location(f, line, config)])
    if result.rows:
        result.summary = (f"{len(result.rows)} file(s) use syntax the parser does not read (Java 14+ outside a "
                          "method body, or a syntax error); their method "
                          "bodies are still checked, but inner classes, fields and annotation arguments are not")
    return result
