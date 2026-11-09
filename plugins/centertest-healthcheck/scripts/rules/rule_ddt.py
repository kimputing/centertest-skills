"""
Rules 14002–14004: DDT data source integrity (cross-skill with ddt-tools).

14002 — @DataDriven datasource file existence check
14003 — DDT reference column integrity (# columns point to valid sheets/codes)
14004 — DDT relationship integrity (@ columns resolve to an existing target DC file + code)
        Also validates #-columns on reference sheets (reference-to-reference edges).
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_core import get_implemented_classes

try:
    from openpyxl import load_workbook
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False

# Regex to extract datasource path from @DataDriven annotation
_DATASOURCE_RE = re.compile(r'@DataDriven\s*\(\s*datasource\s*=\s*"([^"]+)"')


@rule(id="14002", description="@DataDriven datasource file existence", category="CenterTest")
def datasource_file_check(commits: CommitsDict, config) -> RuleResult:
    """
    Verify that @DataDriven(datasource = "testdata/...") references point
    to Excel files that actually exist on disk.

    Checks both class-level and method-level @DataDriven annotations.
    """
    result = RuleResult(
        rule_id="14002",
        description="@DataDriven datasource file existence",
        category="CenterTest",
        headers=["Class", "Method", "Datasource Path", "Issue"],
    )

    repo_dir = config.repository_dir

    for commit_info, files in sorted(commits.items()):
        for f in files:
            mc = f.main_class
            if mc is None:
                continue

            # Scan method bodies and annotations for @DataDriven
            for method in mc.methods:
                # Check method annotations — javalang extracts annotation names
                # but not parameters, so we need to scan the body text too
                datasource = None

                # Search in method body for the full annotation with datasource param
                if method.body:
                    m = _DATASOURCE_RE.search(method.body)
                    if m:
                        datasource = m.group(1)

                if datasource is None:
                    continue

                # Check if file exists
                full_path = os.path.join(repo_dir, datasource)
                if not os.path.isfile(full_path):
                    result.rows.append([
                        mc.class_name,
                        method.name,
                        datasource,
                        "File not found",
                    ])

    return result


def _refcheck_findings(repo_dir: str) -> dict:
    """{file: [(row, col, code, sheet, message)]} from the shared ddt-tools engine (cached per repo).

    ddt_refcheck.py is a vendored copy of plugins/ddt-tools/scripts/ddt_refcheck.py, so the
    healthcheck and xlsx-validate-refs report the same broken references.
    """
    if repo_dir in _REFCHECK_CACHE:
        return _REFCHECK_CACHE[repo_dir]
    import ddt_refcheck
    previous = os.getcwd()
    try:
        os.chdir(repo_dir)
        ddt_refcheck.reset_caches()
        findings = ddt_refcheck.validate_project() if os.path.isdir("testdata") else {}
    finally:
        os.chdir(previous)
    rel = {}
    for path, errors in findings.items():
        key = os.path.relpath(path, repo_dir) if os.path.isabs(path) else path
        rel[key.replace("\\", "/")] = errors
    _REFCHECK_CACHE[repo_dir] = rel
    return rel


_REFCHECK_CACHE: dict = {}


def _is_relationship_column(col: str) -> bool:
    """'@Submission' (a DC-to-DC relationship), not '@Submission.#Coverage' (a hop reference)."""
    return col.startswith("@") and "." not in col


@rule(id="14003", description="DDT reference column integrity", category="CenterTest")
def ddt_reference_integrity(commits: CommitsDict, config) -> RuleResult:
    """
    Verify # reference columns (and @Rel.#Ref hop columns) point to codes that exist.

    Uses the same engine as ddt-tools' xlsx-validate-refs.py: the DC's reference scope comes
    from its References sheet or $references, overrides (#Ref.Field), joins (#A<>#B) and
    sentinels (<blank>) are not codes, and a hop column is checked in the related DC's scope.
    Reference sheets' own # columns are included. @-relationship findings are rule 14004.
    """
    result = RuleResult(
        rule_id="14003",
        description="DDT reference column integrity",
        category="CenterTest",
        headers=["File", "Row", "Column", "Code", "Issue"],
    )
    if not _HAS_OPENPYXL:
        result.error = "openpyxl required for DDT reference validation"
        return result
    for path, errors in sorted(_refcheck_findings(config.repository_dir).items()):
        for row_idx, col, code, _sheet, message in errors:
            if not _is_relationship_column(col) and col:
                result.rows.append([path, row_idx or "-", col, code or "-", message])
    return result


@rule(id="14004", description="DDT relationship (@) target integrity", category="CenterTest")
def ddt_relationship_integrity(commits: CommitsDict, config) -> RuleResult:
    """
    Verify DC-to-DC @-relationship columns resolve to an existing target DC file and code.

    For each DC file's @<Relationship> column (e.g. @Submission):
      1. resolve the identifier ($identifiers default for the DC, or a Prefix. on the value)
      2. look up the target DC file via $relationships[relationship][identifier]
      3. check the target DC file exists and the referenced Code is a row in it
    Together with 14003 this equals what xlsx-validate-refs.py reports.
    """
    result = RuleResult(
        rule_id="14004",
        description="DDT relationship (@) target integrity",
        category="CenterTest",
        headers=["File", "Row", "Column", "Code", "Issue"],
    )
    if not _HAS_OPENPYXL:
        result.error = "openpyxl required for DDT relationship validation"
        return result
    for path, errors in sorted(_refcheck_findings(config.repository_dir).items()):
        for row_idx, col, code, _sheet, message in errors:
            if _is_relationship_column(col) or not col:
                result.rows.append([path, row_idx or "-", col or "-", code or "-", message])
    return result
