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
    from ddt_refcheck import load_workbook
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


# --- Which tests run each workbook ------------------------------------------------

# A DDTHelper getter embeds its workbook: getWorkerscompWC_SubmissionDC(String code) {... "testdata/....xlsx" ...}
_GETTER_RE = re.compile(r'public\s+static\s+[\w.]+\s+(get\w+)\s*\([^)]*\)\s*\{[^\n]*?"(testdata/[^"]+\.xlsx)"')
_TRUTHY = {"true", "t", "yes", "y", "checked", "1"}  # CenterTest's TRUEOPTIONS (BaseTestData.isDisabled)

NOT_RUN_UNUSED = "not run: no test reads this workbook"
NOT_RUN_DISABLED = "not run: row disabled"


def _workbook_users(repo_dir: str, source_root: str) -> dict:
    """{workbook rel path: sorted class names that read it}.

    A class reads a workbook through @DataDriven(datasource=...), a DDTHelper getter for it, or
    its generated DC class name. Generated code (any 'datadriven' folder) is not a reader. A DC
    reached through an @Rel column of a read DC is read by the same classes.
    """
    src = os.path.join(repo_dir, source_root)
    getters: dict[str, str] = {}
    readers: list[tuple[str, str]] = []  # (class name, code)
    for root, _dirs, files in os.walk(src):
        generated = "datadriven" in root.replace("\\", "/").split("/")
        for name in files:
            if not name.endswith(".java"):
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            if generated:
                if name == "DDTHelper.java":
                    for m in _GETTER_RE.finditer(text):
                        getters[m.group(1)] = m.group(2)
            else:
                readers.append((name[:-5], text))
    workbooks = {}
    testdata = os.path.join(repo_dir, "testdata")
    for root, _dirs, files in os.walk(testdata):
        for name in files:
            if name.endswith(".xlsx") and not name.startswith("~$"):
                rel = os.path.relpath(os.path.join(root, name), repo_dir).replace("\\", "/")
                workbooks.setdefault(name[:-5], rel)  # DC class name == workbook stem
    users: dict[str, set] = {}
    dc_stems = {stem: path for stem, path in workbooks.items() if stem.endswith("DC")}
    for cls, text in readers:
        for path in _DATASOURCE_RE.findall(text):
            users.setdefault(path, set()).add(cls)
        for getter, path in getters.items():
            if getter in text:
                users.setdefault(path, set()).add(cls)
        words = set(re.findall(r"\w+", text))  # a DC class name is a whole word: one set beats a regex per stem
        for stem in words & dc_stems.keys():
            users.setdefault(dc_stems[stem], set()).add(cls)
    _follow_relationships(repo_dir, users)
    return {path: sorted(classes) for path, classes in users.items()}


def _workbook_tokens(repo_dir: str, source_root: str) -> dict:
    """{workbook rel path: names a class uses to read it}: its datasource path, the DDTHelper getters
    for it and its DC class name, plus those of every DC that reaches it through an @Rel column.
    The same names _workbook_users looks for, so a reader's methods that use them can be found."""
    src = os.path.join(repo_dir, source_root)
    tokens: dict[str, set] = {}
    for root, _dirs, files in os.walk(src):
        if "datadriven" not in root.replace("\\", "/").split("/") or "DDTHelper.java" not in files:
            continue
        try:
            with open(os.path.join(root, "DDTHelper.java"), encoding="utf-8", errors="replace") as fh:
                for m in _GETTER_RE.finditer(fh.read()):
                    tokens.setdefault(m.group(2), set()).add(m.group(1))
        except OSError:
            continue
    for root, _dirs, files in os.walk(os.path.join(repo_dir, "testdata")):
        for name in files:
            if name.endswith(".xlsx") and not name.startswith("~$"):
                rel = os.path.relpath(os.path.join(root, name), repo_dir).replace("\\", "/")
                tokens.setdefault(rel, set()).add(rel)
                if name[:-5].endswith("DC"):
                    tokens[rel].add(name[:-5])
    _follow_relationships(repo_dir, tokens)
    return tokens


def _follow_relationships(repo_dir: str, users: dict) -> None:
    """Give each DC reached through an @Rel column the readers of the DC that reaches it.

    A relationship names one target per identifier ($relationships: {Submission: {WC: ..., CA: ...}}):
    a DC reaches the target of its own identifier (its path's $identifiers match) and of any
    `IDENT.code` written in the column -- not every target of the relationship. With no identifier
    at all, every target is kept."""
    import ddt_refcheck
    from ddt_reference_scope import default_identifier_for, identifier_of, parse_relationships
    previous = os.getcwd()
    try:
        os.chdir(repo_dir)
        ddt_refcheck.reset_caches()
        by_relationship, identifiers = parse_relationships(ddt_refcheck.load_hierarchy())
        if not by_relationship:
            return
        pending = list(users)
        while pending:
            path = pending.pop()
            if not os.path.isfile(path):
                continue
            try:
                wb = load_workbook(path, read_only=True, data_only=True)
                sheet = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
                rows = list(wb[sheet].iter_rows(values_only=True)) if sheet else []
                wb.close()
            except Exception:
                continue
            header = [ddt_refcheck.format_value(h) for h in rows[0]] if rows else []
            _refs, rels, hops = ddt_refcheck.classify_headers(header)
            try:
                default_id = default_identifier_for(path.replace("\\", "/"), identifiers)
            except ValueError:
                default_id = ""
            wanted: dict[str, set] = {}
            for col in rels:  # @Rel cells may name another identifier: IDENT.code
                i = header.index(col)
                ids = {identifier_of(c.strip(), default_id) for r in rows[1:] if i < len(r) and r[i] not in (None, "")
                       for c in ddt_refcheck.format_value(r[i]).split(",") if c.strip()}
                wanted.setdefault(col[1:].lower(), set()).update(ids or {default_id.upper()})
            for _c, rel, _s in hops:
                wanted.setdefault(rel.lower(), set()).add(default_id.upper())
            for rel, ids in wanted.items():
                targets = by_relationship.get(rel, {})
                chosen = [targets[i] for i in ids if i in targets] if ids - {""} else []
                for target in chosen or targets.values():
                    before = len(users.get(target, ()))
                    users.setdefault(target, set()).update(users[path])
                    if len(users[target]) != before:
                        pending.append(target)
    finally:
        os.chdir(previous)


def _disabled_rows(repo_dir: str, path: str) -> set:
    """Excel row numbers of DataCombination rows switched off in a 'Disabled' column."""
    try:
        wb = load_workbook(os.path.join(repo_dir, path), read_only=True, data_only=True)
    except Exception:
        return set()
    sheet = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
    disabled = set()
    if sheet:
        col = None
        for idx, row in enumerate(wb[sheet].iter_rows(values_only=True), start=1):
            if col is None:
                lowered = [str(h).strip().lower() if h is not None else "" for h in row]
                if "disabled" not in lowered:
                    break
                col = lowered.index("disabled")
                continue
            if col < len(row) and str(row[col] if row[col] is not None else "").strip().lower() in _TRUTHY:
                disabled.add(idx)
    wb.close()
    return disabled


def workbook_users(repo_dir: str, source_root: str) -> dict:
    """_workbook_users, computed once per project and run (the rules and the data panel share it)."""
    key = (repo_dir, source_root)
    if key not in _USERS_CACHE:
        _USERS_CACHE[key] = _workbook_users(repo_dir, source_root)
    return _USERS_CACHE[key]


def _runs_in(repo_dir: str, source_root: str, path: str, row) -> str:
    """Where a finding bites: the reading classes, or why it never runs."""
    users = workbook_users(repo_dir, source_root)
    if not path.endswith("DC.xlsx"):
        return "reference data"
    readers = users.get(path, [])
    if not readers:
        return NOT_RUN_UNUSED
    if isinstance(row, int) and row in _disabled_rows(repo_dir, path):
        return NOT_RUN_DISABLED
    tests = [c for c in readers if c.endswith("Test")] or readers
    more = len(readers) - 2
    return ", ".join(tests[:2]) + (f" +{more}" if more > 0 else "")


_USERS_CACHE: dict = {}


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
        headers=["File", "Row", "Column", "Code", "Issue", "Runs in"],
    )
    if not _HAS_OPENPYXL:
        result.error = "openpyxl required for DDT reference validation"
        return result
    for path, errors in sorted(_refcheck_findings(config.repository_dir).items()):
        for row_idx, col, code, _sheet, message in errors:
            if not _is_relationship_column(col) and col:
                result.rows.append([path, row_idx or "-", col, code or "-", message,
                                    _runs_in(config.repository_dir, config.source_root, path, row_idx)])
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
        headers=["File", "Row", "Column", "Code", "Issue", "Runs in"],
    )
    if not _HAS_OPENPYXL:
        result.error = "openpyxl required for DDT relationship validation"
        return result
    for path, errors in sorted(_refcheck_findings(config.repository_dir).items()):
        for row_idx, col, code, _sheet, message in errors:
            if _is_relationship_column(col) or not col:
                result.rows.append([path, row_idx or "-", col or "-", code or "-", message,
                                    _runs_in(config.repository_dir, config.source_root, path, row_idx)])
    return result
