"""
Rule 7001: Security analysis (beyond Eir).

7001 — Hardcoded credentials detection
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_core import get_implemented_classes

# Patterns suggesting hardcoded credentials in string assignments
_CREDENTIAL_KEYWORDS = [
    "password", "passwd", "secret", "api_key", "apikey",
    "access_key", "accesskey", "token", "private_key", "privatekey",
]

# Regex: variable assignment with credential keyword and a string literal
_CREDENTIAL_RE = re.compile(
    r'(?:String|var)\s+\w*(?:' + '|'.join(_CREDENTIAL_KEYWORDS) + r')\w*\s*=\s*"[^"]{3,}"',
    re.IGNORECASE,
)

# Also detect in method calls: setPassword("literal")
_SETTER_RE = re.compile(
    r'(?:set|with)(?:' + '|'.join(k.capitalize() for k in _CREDENTIAL_KEYWORDS) + r')\s*\(\s*"[^"]{3,}"',
    re.IGNORECASE,
)


@rule(id="7001", description="Potential hardcoded credentials", category="Security")
def hardcoded_credentials(commits: CommitsDict, config) -> RuleResult:
    """
    Find potential hardcoded passwords, API keys, and tokens.

    Scans string assignments and setter calls for credential keywords
    with string literal values. Lower confidence — may flag false positives
    like algorithm names.
    """
    result = RuleResult(
        rule_id="7001",
        description="Potential hardcoded credentials",
        category="Security",
        headers=["Class", "Method", "Finding"],
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
                    match = _CREDENTIAL_RE.search(stripped) or _SETTER_RE.search(stripped)
                    if match:
                        result.rows.append([
                            mc.class_name,
                            method.name,
                            stripped[:150],
                        ])

    return result
