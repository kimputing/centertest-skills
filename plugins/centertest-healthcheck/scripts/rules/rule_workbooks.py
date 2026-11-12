"""
Rules 27001-27004: consistency defects in the DataCombination and reference workbooks under testdata/.

27001  the same header spelled with different casing across workbooks
27002  two rows with the same Code in one sheet
27003  a reference whose code matches its target row only case-insensitively
27004  whitespace defects in cells (padding, tabs, non-breaking spaces, empty list items)

How CenterTest reads a workbook (centertest-platform, centertest-core, read for these rules):
- ExcelDataReader.getDataRow trims every cell (String.trim: characters up to U+0020 -- spaces, tabs,
  line breaks; NOT the non-breaking space U+00A0) and keys it by the lower-cased header;
  normalizeHeader lower-cases headers, so header casing never changes what a test reads.
- ExcelDataReader.parseSheet keys each row by code.toLowerCase().trim() in a map: of two rows with the
  same code (any casing) only the LAST is kept -- the DataCombination sheet included, disabled rows
  included (they are put first and filtered later).
- ReferenceGraphLoader.resolve / AbstractTestData.referenceTokens lower-case a reference cell, split it
  on ",", trim each token and skip empty ones; codes are therefore matched case-insensitively and a
  dangling ", " is ignored.

Workbooks are read through the vendored ddt_refcheck (each file read once per process, shared with
rules 14003/14004); lock files (~$*.xlsx) are skipped. References are resolved exactly as ddt_refcheck
resolves them (the DC's References sheet or $references scope, $relationships for @ columns, the related
DC's scope for @Rel.#Ref), so 27003 only names real targets.
"""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_helpers import file_location

CATEGORY = "Workbooks"
_ROW_HEADERS = ["File", "Sheet", "Row", "Column", "Value", "Issue", "Runs in", "Location"]
_JAVA_TRIM = "".join(chr(c) for c in range(0x21))          # what String.trim() removes
_UNTRIMMED_SPACES = "\u00a0\u2007\u202f\u200b\ufeff"        # look like (or are) nothing, survive trim()


def _result(rule_id: str, description: str, headers: list[str]) -> RuleResult:
    return RuleResult(rule_id=rule_id, description=description, category=CATEGORY, headers=headers)


def _no_openpyxl(result: RuleResult) -> bool:
    try:
        import ddt_refcheck  # noqa: F401  (imports openpyxl)
        return False
    except ImportError:
        result.error = "openpyxl required to read the workbooks"
        return True


def _java_trim(value: str) -> str:
    return value.strip(_JAVA_TRIM)


def _norm_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


class _Sheet:
    def __init__(self, title: str, header_row: int, headers: list[str], rows: list[tuple[int, list]]):
        self.title, self.header_row, self.headers, self.rows = title, header_row, headers, rows

    def column(self, name: str):
        """Index of the column whose header normalises to `name` ("code", "description"), else None."""
        return next((i for i, h in enumerate(self.headers) if _norm_header(h) == name), None)


def _workbooks(repo: str) -> list[tuple[str, list[_Sheet]]]:
    """[(path relative to the project, sheets)] for testdata/**/*.xlsx, sorted, each read once.
    A sheet's header row is its first non-empty row; rows keep their Excel row numbers and raw values."""
    from ddt_refcheck import format_value, load_workbook
    out = []
    base = os.path.join(repo, "testdata")
    for path in sorted(set(glob.glob(os.path.join(base, "**", "*.xlsx"), recursive=True))):
        if os.path.basename(path).startswith("~$"):
            continue
        try:
            book = load_workbook(path, read_only=True, data_only=True)
        except Exception:
            continue  # unreadable workbooks are reported by 14002/14003
        sheets = []
        for ws in book.worksheets:
            header_row, headers, rows = 0, None, []
            for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if headers is None:
                    if all(c in (None, "") for c in row):
                        continue
                    header_row, headers = idx, [format_value(c).strip() for c in row]
                    continue
                if any(c not in (None, "") for c in row):
                    rows.append((idx, list(row)))
            if headers is not None:
                sheets.append(_Sheet(ws.title, header_row, headers, rows))
        out.append((os.path.relpath(path, repo).replace(os.sep, "/"), sheets))
    return out


def _runs_in(config, path: str, row) -> str:
    """Where a finding bites (the reading tests, "reference data", or why it never runs) -- as 14003."""
    try:
        from rules.rule_ddt import _runs_in as runs_in
        return runs_in(config.repository_dir, getattr(config, "source_root", "src/main/java") or "src/main/java", path, row)
    except Exception:
        return ""


def _visible(value: str, limit: int = 80) -> str:
    """The cell as written, with invisible characters shown (tab as \\t, nbsp as \\u00a0)."""
    shown = value.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    for ch in _UNTRIMMED_SPACES:
        shown = shown.replace(ch, "\\u%04x" % ord(ch))
    shown = f"'{shown}'"
    return shown if len(shown) <= limit else shown[: limit - 2] + "…'"


# ---------------------------------------------------------------------------
# 27001
# ---------------------------------------------------------------------------

@rule(id="27001", description="Header casing drifts across workbooks", category=CATEGORY)
def header_casing_drift(commits: CommitsDict, config) -> RuleResult:
    """One header written with different casing across the DC and reference workbooks: Disabled vs
    disabled, TestCaseId vs TestCaseID, #Misc.ReformGRID vs #Misc.ReformGrid.

    Headers are compared after trimming, case-insensitively and nothing else (Composite Rating vs
    CompositeRating is not a casing drift). CenterTest lower-cases headers, so tests read the column
    either way: a low-severity consistency finding -- search, diff and copy-paste between workbooks see
    two names. One row per header, spellings most used first; Location is the first sheet using the
    least-used spelling.
    """
    result = _result("27001", "Header casing drifts across workbooks", ["Header", "Spellings", "Where", "Issue", "Location"])
    if _no_openpyxl(result):
        return result
    uses: dict[str, dict[str, list[tuple[str, str, int]]]] = {}
    for path, sheets in _workbooks(config.repository_dir):
        for sh in sheets:
            for h in sh.headers:
                if h:
                    places = uses.setdefault(h.lower(), {}).setdefault(h, [])
                    if not places or places[-1][:2] != (path, sh.title):
                        places.append((path, sh.title, sh.header_row))
    for key in sorted(uses):
        spellings = uses[key]
        if len(spellings) < 2:
            continue
        ranked = sorted(spellings.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        counts = ", ".join(f"'{s}' ({len(p)} sheet{'s' if len(p) != 1 else ''})" for s, p in ranked)
        where = "; ".join(
            f"'{s}': " + ", ".join(f"{os.path.basename(p)}[{t}]" for p, t, _r in places[:4])
            + (f" +{len(places) - 4} more" if len(places) > 4 else "")
            for s, places in ranked)
        rare_path, _t, rare_row = ranked[-1][1][0]
        result.rows.append([
            ranked[0][0], counts, where,
            "one column, several spellings: CenterTest reads headers case-insensitively, so tests are not "
            "affected, but search, diff and reviewers see different names for the same column",
            file_location(rare_path, rare_row, config),
        ])
    return result


# ---------------------------------------------------------------------------
# 27002
# ---------------------------------------------------------------------------

@rule(id="27002", description="Duplicate code in a sheet", category=CATEGORY)
def duplicate_code_in_sheet(commits: CommitsDict, config) -> RuleResult:
    """Two rows of one sheet with the same Code (trimmed, case-insensitive -- how CenterTest keys rows).

    CenterTest keeps rows in a map by code, so only the last row survives: a reference to the code gets
    that row, and in a DataCombination sheet the earlier row never runs (even when the later one is
    disabled). Instance codes are distinct rows: "Coupe(2)" is its own key, not a copy of "Coupe" (the
    "(n)" suffix only means an instance in a reference cell). One row per duplicated code, at the first
    (silently ignored) row; sheets without a Code column are skipped.
    """
    result = _result("27002", "Duplicate code in a sheet", _ROW_HEADERS)
    if _no_openpyxl(result):
        return result
    from ddt_refcheck import format_value
    for path, sheets in _workbooks(config.repository_dir):
        for sh in sheets:
            ci = sh.column("code")
            if ci is None:
                continue
            seen: dict[str, list[tuple[int, str]]] = {}
            for idx, row in sh.rows:
                code = _java_trim(format_value(row[ci])) if ci < len(row) else ""
                if code:
                    seen.setdefault(code.lower(), []).append((idx, code))
            for key, hits in seen.items():
                if len(hits) < 2:
                    continue
                (first, code), last = hits[0], hits[-1][0]
                spellings = sorted({c for _i, c in hits})
                ignored = [str(i) for i, _c in hits[:-1]]
                case_note = f" (spelled {', '.join(repr(s) for s in spellings)}; codes match case-insensitively)" if len(spellings) > 1 else ""
                result.rows.append([
                    path, sh.title, first, sh.headers[ci], code,
                    f"code on rows {', '.join(str(i) for i, _c in hits)}{case_note}: CenterTest keeps only the last "
                    f"(row {last}), so row{'s' if len(ignored) > 1 else ''} {', '.join(ignored)} "
                    f"{'are' if len(ignored) > 1 else 'is'} silently ignored",
                    _runs_in(config, path, first), file_location(path, first, config),
                ])
    return result


# ---------------------------------------------------------------------------
# 27003
# ---------------------------------------------------------------------------

def _case_only(token: str, available) -> str | None:
    """The target spelling when `token` names a row of `available` only case-insensitively; None when
    it matches exactly (or as an instance copy), is a sentinel, or names no row at all (14003's)."""
    import ddt_refcheck as rc
    token = token.strip()
    if not token or rc.SENTINEL_RE.fullmatch(token):
        return None
    exact = {str(c).strip(): c for c in available}
    base = rc.base_code(token)
    if token in exact or base in exact:
        return None
    lower = {k.lower(): k for k in exact}
    return lower.get(token.lower()) or lower.get(base.lower())


def _case_only_references(repo: str) -> list[tuple[str, str, int, str, str, str, str]]:
    """[(file, sheet, row, column, token, target spelling, where the target is)] -- resolved as
    ddt_refcheck.validate_dc and validate_all_reference_sheets resolve references."""
    import ddt_refcheck as rc
    from ddt_reference_scope import default_identifier_for, identifier_of, parse_relationships, strip_identifier
    found = []
    previous = os.getcwd()
    try:
        os.chdir(repo)
        rc.reset_caches()
        if not os.path.isdir("testdata"):
            return []
        dc_files = rc.find_all_dc_files()
        by_relationship, identifiers = parse_relationships(rc.load_hierarchy())

        def where_of(available, target):
            hit = available.get(target) if isinstance(available, dict) else None
            return f"{hit[0]} row {hit[1]}" if hit else ""

        for dc in dc_files:
            try:
                wb = rc.load_workbook(dc, read_only=True, data_only=True)
            except Exception:
                continue
            sheet = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
            if sheet is None:
                continue
            headers, rows = None, []
            for idx, row in enumerate(wb[sheet].iter_rows(values_only=True), start=1):
                values = [rc.format_value(c) for c in row]
                if all(v == "" for v in values):
                    continue
                if headers is None:
                    headers = values
                else:
                    rows.append((idx, dict(zip(headers, values))))
            if not headers:
                continue
            refs, rels, hops = rc.classify_headers(headers)
            if refs:
                scope = rc.reference_codes_for(dc)
                for idx, data in rows:
                    for col in refs:
                        available = scope.get(rc._norm_sheet(col[1:]))
                        if not available:
                            continue
                        for token in (data.get(col, "") or "").split(","):
                            target = _case_only(token, available)
                            if target:
                                found.append((dc, sheet, idx, col, token.strip(), target, where_of(available, target)))
            if not (rels or hops):
                continue
            try:
                default_id = default_identifier_for(dc.replace("\\", "/"), identifiers)
            except ValueError:
                continue  # 14004 reports it
            for idx, data in rows:
                for col in rels:
                    targets = by_relationship.get(col[1:].lower(), {})
                    for raw in (data.get(col, "") or "").split(","):
                        raw = raw.strip()
                        if not raw or rc.SENTINEL_RE.fullmatch(raw):
                            continue
                        target_file = targets.get(identifier_of(raw, default_id))
                        if not target_file or not os.path.isfile(target_file):
                            continue
                        target = _case_only(strip_identifier(raw), rc.load_dc_codes(target_file))
                        if target:
                            found.append((dc, sheet, idx, col, raw, target, os.path.basename(target_file)))
                for col, relationship, sheet_key in hops:
                    cell = data.get(col, "")
                    if not cell:
                        continue
                    rel_targets = by_relationship.get(relationship.lower(), {})
                    related = []
                    for raw in (data.get("@" + relationship, "") or "").split(","):
                        raw = raw.strip()
                        if raw and not rc.SENTINEL_RE.fullmatch(raw):
                            t = rel_targets.get(identifier_of(raw, default_id))
                            if t and t not in related:
                                related.append(t)
                    if not related:
                        related = sorted(set(rel_targets.values()))
                    available = {}
                    for t in related:
                        if os.path.isfile(t):
                            available.update(rc.reference_codes_for(t).get(sheet_key, {}))
                    for token in cell.split(","):
                        target = _case_only(token, available) if available else None
                        if target:
                            found.append((dc, sheet, idx, col, token.strip(), target, where_of(available, target)))

        # "#Ref" columns on reference sheets, against every reference file in scope (as 14004 checks them)
        ref_paths = set()
        for dc in dc_files:
            ref_paths.update(rc._collect_ref_file_locations(dc))
        scope = rc._build_global_ref_codes(ref_paths)
        for ref_path in sorted(ref_paths):
            try:
                wb = rc.load_workbook(ref_path, read_only=True, data_only=True)
            except Exception:
                continue
            rel = os.path.relpath(ref_path, repo)
            for name in wb.sheetnames:
                if name.lower() in ("datacombination", "references"):
                    continue
                headers = None
                for idx, row in enumerate(wb[name].iter_rows(values_only=True), start=1):
                    values = [rc.format_value(c) for c in row]
                    if all(v == "" for v in values):
                        continue
                    if headers is None:
                        headers = values
                        cols = [(i, h, rc._norm_sheet(h[1:])) for i, h in enumerate(headers)
                                if h.startswith("#") and "." not in h and rc.JOIN_SEPARATOR not in h]
                        continue
                    for i, h, key in cols:
                        available = scope.get(key)
                        if not available or i >= len(values):
                            continue
                        for token in values[i].split(","):
                            target = _case_only(token, available)
                            if target:
                                found.append((rel, name, idx, h, token.strip(), target, where_of(available, target)))
    finally:
        os.chdir(previous)
    return [(p.replace("\\", "/"), *rest) for p, *rest in found]


@rule(id="27003", description="Reference differs from its target only by case", category=CATEGORY)
def reference_differs_only_by_case(commits: CommitsDict, config) -> RuleResult:
    """A reference cell whose code matches its target row only case-insensitively (NS_Johnteen ->
    NS_JohnTeen) -- in #Ref and @Rel.#Ref columns of DataCombination sheets, @Rel columns (against the
    related DC's codes) and #Ref columns of reference sheets, each resolved in the scope ddt_refcheck
    (rules 14003/14004) uses. A code with no target at all is 14003/14004's, not this rule's.

    CenterTest lower-cases reference cells and row codes, so the reference resolves: this is a low
    severity consistency finding, not a broken reference.
    """
    result = _result("27003", "Reference differs from its target only by case", _ROW_HEADERS)
    if _no_openpyxl(result):
        return result
    for path, sheet, row, col, token, target, where in sorted(_case_only_references(config.repository_dir),
                                                              key=lambda f: (f[0], f[1], f[2], f[3], f[4])):
        result.rows.append([
            path, sheet, row, col, token,
            f"names row '{target}'{f' ({where})' if where else ''} with different casing: CenterTest matches codes "
            "case-insensitively, so it resolves, but search, diff and reviewers see two spellings of one code",
            _runs_in(config, path, row), file_location(path, row, config),
        ])
    return result


# ---------------------------------------------------------------------------
# 27004
# ---------------------------------------------------------------------------

def _reference_column(header: str) -> bool:
    """#Ref, @Rel and @Rel.#Ref columns hold comma-separated codes (overrides and joins do not)."""
    if not header or "<>" in header:
        return False
    if header[0] in "#@" and "." not in header:
        return True
    return re.fullmatch(r"@\w+\.#\w+", header) is not None


def _padding(chunk: str) -> str:
    if "\t" in chunk:
        return "tab"
    if chunk.strip(" "):
        return "line break" if chunk.strip(" \t") and not chunk.strip(" \t\r\n") else "whitespace"
    return "space" if len(chunk) == 1 else f"{len(chunk)} spaces"


def _whitespace_issues(value: str, is_code_list: bool) -> list[str]:
    issues = []
    odd = sorted({ch for ch in value if ch in _UNTRIMMED_SPACES})
    if odd:
        names = ", ".join("U+%04X" % ord(ch) for ch in odd)
        issues.append(f"contains an invisible space ({names}) that CenterTest does not trim: the value sent to the "
                      "application, or the code looked up, differs from what the cell shows")
    trimmed = _java_trim(value)
    if "\t" in trimmed:
        issues.append("contains a tab inside the value: CenterTest trims only the ends, so the tab reaches the application")
    dangling = False
    if is_code_list and trimmed:
        items = [x.strip(_JAVA_TRIM) for x in trimmed.split(",")]
        dangling = len(items) > 1 and any(not x for x in items)
    lead, trail = len(value) - len(value.lstrip(_JAVA_TRIM)), len(value) - len(value.rstrip(_JAVA_TRIM))
    if dangling:  # 'NS_JohnAdult, ': the padding is part of the dangling separator, said once below
        lead, trail = (0 if trimmed.startswith(",") else lead), (0 if trimmed.endswith(",") else trail)
    if trimmed and (lead or trail):
        parts = [f"{side} {_padding(chunk)}" for side, chunk in
                 (("leading", value[:lead]), ("trailing", value[len(value) - trail:])) if chunk]
        issues.append(" and ".join(parts) + ": CenterTest trims cells, so tests read the trimmed value, but search, "
                      "diff and anyone copying the value see a different one")
    if dangling:
        issues.append("has an empty item in its code list (a dangling ','): CenterTest skips empty items, so it "
                      "resolves the same, but it reads like a code is missing")
    return issues


@rule(id="27004", description="Whitespace defects in cells", category=CATEGORY)
def whitespace_defects_in_cells(commits: CommitsDict, config) -> RuleResult:
    """Leading/trailing padding, tabs, invisible (non-breaking, zero-width) spaces and dangling list
    separators in codes, reference cells and values of the testdata workbooks.

    What each costs (CenterTest trims every cell with String.trim and skips empty reference tokens):
    - padding at either end and a dangling ", " in a reference list: no runtime effect -- a
      consistency finding (search/diff/copy-paste see another value);
    - a tab inside the trimmed value or a non-breaking/zero-width space anywhere: reaches the
      application or the code lookup unchanged -- a real mismatch.
    Guards: header rows, Description columns (free text), join columns (#A<>#B, aligned on purpose) are
    skipped; the empty-item check runs only on reference columns and the Code column -- override columns
    (#Vehicle.CostNew = ",,,,,,70000") use empty positions on purpose. Runs of spaces inside a value are
    not reported: fixed-width texts (MVR records) and application names may contain them on purpose.
    """
    result = _result("27004", "Whitespace defects in cells", _ROW_HEADERS)
    if _no_openpyxl(result):
        return result
    for path, sheets in _workbooks(config.repository_dir):
        for sh in sheets:
            skip = {i for i, h in enumerate(sh.headers) if _norm_header(h) == "description" or "<>" in h}
            code_cols = {i for i, h in enumerate(sh.headers) if _reference_column(h) or _norm_header(h) == "code"}
            for idx, row in sh.rows:
                for i, value in enumerate(row):
                    if i in skip or i >= len(sh.headers) or not sh.headers[i] or not isinstance(value, str):
                        continue
                    issues = _whitespace_issues(value, i in code_cols)
                    if issues:
                        result.rows.append([path, sh.title, idx, sh.headers[i], _visible(value), "; ".join(issues),
                                            _runs_in(config, path, idx), file_location(path, idx, config)])
    return result
