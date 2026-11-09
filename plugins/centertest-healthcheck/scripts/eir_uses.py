"""
--uses PATTERN: which scenarios exercise a coverage, a product, a state -- any test data value.

A row of any testdata sheet whose value cell matches PATTERN (whole cell, case-insensitive regex;
its Code included, reference columns not) is a hit. A row is a hit too when it references a hit row, followed until nothing new is found:
- a #Ref column (comma-separated codes of that sheet),
- a #A<>#B join cell ("a: b1, b2" lines: the B codes),
- an @Rel column (codes of the related DataCombination).
Scopes are the reference check's: a DC's #Ref resolves in its own reference workbooks
(ddt_refcheck.reference_codes_for), an @Rel through DataDrivenHierarchy.json's identifiers; a
reference sheet's #Ref resolves in its own workbook first. @Rel.#Ref hops are not followed. DataCombination hits are the
scenarios; each runs in the tests whose @DataDriven datasource is that workbook (disabled rows do
not run). The scenarios come back as suite entries (vendored suite-builder) and one command.
"""

from __future__ import annotations

import os
import re

import ddt_refcheck
from ddt_refcheck import format_value, load_workbook, _norm_sheet

DC_SHEET = "datacombination"


def _workbooks(repo_dir: str) -> list[str]:
    out = []
    for root, dirs, files in os.walk(os.path.join(repo_dir, "testdata")):
        dirs.sort()
        out += [os.path.join(root, f) for f in sorted(files) if f.endswith(".xlsx") and not f.startswith("~$")]
    return out


def _tables(repo_dir: str) -> list[dict]:
    """[{rel, sheet (normalised), dc, headers, rows: [(code, cells)]}] for every sheet with a Code column."""
    tables = []
    for path in _workbooks(repo_dir):
        rel = os.path.relpath(path, repo_dir).replace("\\", "/")
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception:
            continue
        for ws in wb.worksheets:
            rows = [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
            if not rows:
                continue
            headers = [format_value(h).strip() for h in rows[0]]
            ci = next((i for i, h in enumerate(headers) if h.lower() == "code"), None)
            if ci is None:
                continue
            body = [(format_value(r[ci]).strip(), [format_value(c) for c in r]) for r in rows[1:]
                    if ci < len(r) and r[ci] not in (None, "")]
            tables.append({"rel": rel, "sheet": _norm_sheet(ws.title), "dc": ws.title.lower() == DC_SHEET,
                           "headers": headers, "rows": body})
        wb.close()
    return tables


def _codes(cell: str) -> list[str]:
    return [c.strip() for c in cell.split(",") if c.strip()]


_graph_cache: dict = {}


def _graph(repo_dir: str):
    """(tables, [(row key, [row keys it references])]) -- one reference graph per project."""
    if repo_dir in _graph_cache:
        return _graph_cache[repo_dir]
    from ddt_reference_scope import default_identifier_for, identifier_of, parse_relationships, strip_identifier
    tables = _tables(repo_dir)
    previous = os.getcwd()
    links = []  # (hit key of the row, [hit keys it points at])
    try:
        os.chdir(repo_dir)  # the engine resolves scopes from the project root
        ddt_refcheck.reset_caches()
        try:
            by_relationship, identifiers = parse_relationships(ddt_refcheck.load_hierarchy())
        except Exception:
            by_relationship, identifiers = {}, []
        sheets_of = {}
        for t in tables:
            if not t["dc"]:
                sheets_of.setdefault(t["sheet"], []).append(os.path.basename(t["rel"]).lower())
        for t in tables:
            base = os.path.basename(t["rel"]).lower()
            if t["dc"]:
                try:
                    scope = ddt_refcheck.reference_codes_for(t["rel"])
                    default_id = default_identifier_for(t["rel"], identifiers)
                except Exception:
                    scope, default_id = {}, ""
            for code, cells in t["rows"]:
                key = ("dc", t["rel"], code) if t["dc"] else ("row", base, t["sheet"], code)
                out = []
                for i, h in enumerate(t["headers"]):
                    cell = cells[i] if i < len(cells) else ""
                    if not cell or not h:
                        continue
                    if ddt_refcheck.JOIN_SEPARATOR in h:
                        target = h.split(ddt_refcheck.JOIN_SEPARATOR)[-1].strip()
                        refs = [(target[1:], c) for line in cell.splitlines()
                                for c in _codes(line.partition(":")[2])] if target.startswith("#") else []
                    elif h.startswith("#") and "." not in h:
                        refs = [(h[1:], c) for c in _codes(cell)]
                    elif h.startswith("@") and "." not in h and t["dc"]:
                        targets = by_relationship.get(h[1:].lower(), {})
                        for raw in _codes(cell):
                            target = targets.get(identifier_of(raw, default_id))
                            if target:
                                out.append(("dc", target.replace("\\", "/"), strip_identifier(raw)))
                        continue
                    else:
                        continue
                    for sheet, c in refs:
                        sk, c = _norm_sheet(sheet), ddt_refcheck.base_code(c)
                        if t["dc"]:
                            found = scope.get(sk, {}).get(c)
                            if found:
                                out.append(("row", found[0].lower(), sk, c))
                        else:  # a reference sheet: its own workbook first, else any with that sheet
                            books = [base] if base in sheets_of.get(sk, []) else sheets_of.get(sk, [])
                            out += [("row", b, sk, c) for b in books]
                links.append((key, out))
    finally:
        os.chdir(previous)
    _graph_cache[repo_dir] = (tables, links)
    return tables, links


def _key(t: dict, code: str) -> tuple:
    return ("dc", t["rel"], code) if t["dc"] else ("row", os.path.basename(t["rel"]).lower(), t["sheet"], code)


def _value_columns(t: dict) -> list[int]:
    """Columns that hold values; reference cells hold another sheet's codes."""
    return [i for i, h in enumerate(t["headers"]) if h and h[0] not in "#@" and ddt_refcheck.JOIN_SEPARATOR not in h]


_COVERAGE_WORDS = ("coverage", "bundle", "package", "endorsement")


def _coverage_table(t: dict) -> bool:
    """A sheet, or a table with a (non-reference) column, named for coverages, bundles, packages or
    endorsements: where coverage names live -- not a vehicle type or a prior-loss cause that happens to
    share a coverage's name."""
    return any(w in t["sheet"] for w in _COVERAGE_WORDS) or any(
        w in h.lower() for h in t["headers"] if h and h[0] not in "#@" for w in _COVERAGE_WORDS)


def reached_values(repo_dir: str, start: set | None = None, coverage_only: bool = False) -> set[str]:
    """Lower-cased value cells (codes included) of every row the start rows reach -- by default every
    enabled DataCombination row, or `start` (("dc", rel path, code) keys) --
    itself included, and the headers of its filled value columns (a term set as its own column):
    what the scenarios actually select, not what merely sits in a sheet."""
    tables, links = _graph(repo_dir)
    out_of = dict(links)
    if start is not None:
        start = set(start)
    else:
        start = set()
    for t in tables if not start else ():
        if not t["dc"]:
            continue
        di = next((i for i, h in enumerate(t["headers"]) if h.lower() == "disabled"), None)
        start |= {_key(t, code) for code, cells in t["rows"]
                  if di is None or di >= len(cells) or cells[di].strip().lower() not in ("true", "yes", "y", "x", "1")}
    reached, frontier = set(start), list(start)
    while frontier:
        for nxt in out_of.get(frontier.pop(), ()):
            if nxt not in reached:
                reached.add(nxt)
                frontier.append(nxt)
    values = set()
    for t in tables:
        if coverage_only and not _coverage_table(t):
            continue
        cols = _value_columns(t)
        for code, cells in t["rows"]:
            if _key(t, code) in reached:
                filled = [i for i in cols if i < len(cells) and cells[i].strip()]
                values |= {cells[i].strip().lower() for i in filled}
                values |= {t["headers"][i].lower() for i in filled}  # a term set as its own column
    return values


def rows_by_value(repo_dir: str, coverage_only: bool = False) -> dict[str, set]:
    """{lower-cased value: ("dc", rel path, code) keys of the enabled DataCombination rows that reach it}."""
    tables, links = _graph(repo_dir)
    out_of = dict(links)
    cells = {}
    for t in tables:
        if coverage_only and not _coverage_table(t):
            continue
        cols = _value_columns(t)
        for code, row in t["rows"]:
            filled = [i for i in cols if i < len(row) and row[i].strip()]
            cells[_key(t, code)] = [row[i].strip().lower() for i in filled] + [t["headers"][i].lower() for i in filled]
    result: dict[str, set] = {}
    for t in tables:
        if not t["dc"]:
            continue
        di = next((i for i, h in enumerate(t["headers"]) if h.lower() == "disabled"), None)
        for code, row in t["rows"]:
            if di is not None and di < len(row) and row[di].strip().lower() in ("true", "yes", "y", "x", "1"):
                continue
            start = _key(t, code)
            seen, frontier = {start}, [start]
            while frontier:
                for nxt in out_of.get(frontier.pop(), ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
            for key in seen:
                for value in cells.get(key, ()):
                    result.setdefault(value, set()).add(start)
    return result


def suite_rows(repo_dir: str, source_root: str) -> set | None:
    """("dc", datasource, code) keys of the DataCombination rows some suite runs; None without a suite file."""
    import suite as suites
    path = suites.find_suite_file(repo_dir)
    if not os.path.isfile(path):
        return None
    try:
        doc, _text = suites.load_suites(path)
    except (OSError, ValueError):
        return None
    tests = suites.scan(repo_dir, source_root)
    left = suites.uncovered(doc, tests)
    ds = {(t["class"], m["name"]): m["datasource"] for t in tests for m in t["methods"]}
    return {("dc", ds[(c, m)], code) for c, m, code in set(suites.scenarios_of(tests)) - left
            if code and ds.get((c, m))}


def scenarios_using(repo_dir: str, pattern: str) -> dict[str, set[str]]:
    """{DC rel path: codes of its DataCombination rows that use a value matching `pattern`}."""
    rx = re.compile(pattern, re.I)
    tables, links = _graph(repo_dir)
    hits = set()
    for t in tables:
        values = _value_columns(t)
        for code, cells in t["rows"]:
            if any(i < len(cells) and cells[i] and rx.fullmatch(cells[i].strip()) for i in values):
                hits.add(_key(t, code))
    changed = True
    while changed:
        changed = False
        for key, out in links:
            if key not in hits and any(o in hits for o in out):
                hits.add(key)
                changed = True
    result: dict[str, set[str]] = {}
    for h in hits:
        if h[0] == "dc":
            result.setdefault(h[1], set()).add(h[2])
    return result


def uses_report(repo_dir: str, source_root: str, pattern: str) -> dict:
    """The rows, the tests that run them, and suite entries for exactly those scenarios."""
    import suite as suites
    rows = scenarios_using(repo_dir, pattern)
    tests = suites.scan(repo_dir, source_root)
    runnable = set(suites.scenarios_of(tests))
    selected = set()
    per_dc = []
    for dc, codes in sorted(rows.items()):
        readers = sorted({t["class"] for t in tests for m in t["methods"] if m["datasource"] == dc})
        run = {(t["class"], m["name"], c) for t in tests for m in t["methods"] if m["datasource"] == dc
               for c in codes if (t["class"], m["name"], c) in runnable}
        selected |= run
        per_dc.append({"dc": dc, "codes": sorted(codes), "tests": readers,
                       "not_run": sorted(codes - {c for _cls, _m, c in run})})
    used = [t for t in tests if any(c == t["class"] for c, _m, _code in selected)]
    return {"pattern": pattern, "workbooks": per_dc, "scenarios": len(selected),
            "entries": suites.compact(selected, used)}


def suite_name(pattern: str) -> str:
    return "Uses-" + (re.sub(r"[^A-Za-z0-9]+", "", pattern.title()) or "Pattern")[:40]


def print_uses(report: dict, name: str, command: str | None) -> None:
    print(f"\n  SCENARIOS THAT USE /{report['pattern']}/")
    if not report["workbooks"]:
        print("  No test data row names it, directly or through a reference: no scenario exercises it.")
        return
    for w in report["workbooks"]:
        codes = ", ".join(w["codes"][:8]) + (f" +{len(w['codes']) - 8}" if len(w["codes"]) > 8 else "")
        tests = ", ".join(w["tests"]) or "no test reads this workbook"
        print(f"  {os.path.basename(w['dc'])}: {codes}  ->  {tests}")
        if w["not_run"] and w["tests"]:
            print(f"      not run (disabled): {', '.join(w['not_run'][:8])}")
    if not report["entries"]:
        print("\n  None of these rows runs (disabled, or no test reads the workbook).")
        return
    import json
    print(f"\n  {report['scenarios']} scenario(s) run it. As a suite for CenterTestSuiteList.json:\n")
    print("\n".join("    " + line for line in json.dumps({"Name": name, "List": report["entries"]}, indent=2).splitlines()))
    if command:
        print(f"\n  Then: {command}")


_PAGE_IMPORT = re.compile(r"^import\s+[\w.]+\.generated\.pages\.[\w.]*?\.?(\w+)\s*;", re.M)


_CHAIN_PAGE = re.compile(r"new\s+(\w+)\(getContext\(\)\)")
_CHAIN_GETTER = re.compile(r"\.(get\w+)\(")


def widget_targets(cssids_dir: str | None, widget_id: str) -> list[tuple[str, str, str]]:
    """[(page class, last getter, getter chain)] for a Guidewire widget id, looked up in the generated
    cssids the way cssid-finder does (vendored find_getter.py): an exact key first, then a partial one."""
    import find_getter
    if not cssids_dir:
        return []
    roots = [cssids_dir, os.path.dirname(os.path.abspath(cssids_dir))]
    found = []
    for app in ("pc", "bc", "cc", "ab"):
        layout, path = next((find_getter.detect_layout(r, app) for r in roots
                             if find_getter.detect_layout(r, app)[0] is not None), (None, None))
        if layout is None:
            continue
        forms = find_getter.normalize_css_id(widget_id)
        for exact in ([True, False] if layout == "properties" else [True]):
            hits = [g for form in forms for g in (find_getter.search_properties(path, form, exact_only=exact)
                                                    if layout == "properties" else find_getter.search_legacy(path, form))]
            if hits:
                found += hits
                break
    out = []
    for chain in dict.fromkeys(found):
        page = _CHAIN_PAGE.search(chain)
        getters = [g for g in _CHAIN_GETTER.findall(chain) if g != "getContext"]
        if page and getters:
            out.append((page.group(1), getters[-1], chain))
    return out


def touches_report(repo_dir: str, source_root: str, pattern: str, cssids_dir: str | None = None) -> dict:
    """Tests that reach a generated page (regex over the page classes the project imports) or one
    widget getter ("SubmissionWizardPage.getPolicyInfoStep"), and a suite that runs them whole.
    Reach is the --review rerun reach: per method, a static call must name its class."""
    import suite as suites
    from eir_impact import _java_sources, tests_reaching
    sources = _java_sources(repo_dir, source_root)
    if "-" in pattern and "." not in pattern:  # a Guidewire widget id
        targets = [(page, getter) for page, getter, _chain in widget_targets(cssids_dir, pattern)]
    else:
        page_rx, _, getter = pattern.partition(".")
        rx = re.compile(page_rx, re.I)
        targets = [(p, getter) for p in sorted({p for _path, text in sources.values()
                                                for p in _PAGE_IMPORT.findall(text) if rx.search(p)})]
    per_page, reached = [], set()
    for page, getter in dict.fromkeys(targets):
        tests = tests_reaching({page}, sources, {page: {getter}} if getter else None)
        per_page.append({"page": page + (f".{getter}" if getter else ""), "tests": sorted(tests)})
        reached |= set(tests)
    scanned = [t for t in suites.scan(repo_dir, source_root) if t["class"] in reached]
    selected = set(suites.scenarios_of(scanned))
    return {"pattern": pattern, "pages": per_page, "tests": sorted(reached), "scenarios": len(selected),
            "entries": suites.compact(selected, scanned)}


def print_touches(report: dict, name: str, command: str | None) -> None:
    print(f"\n  TESTS THAT TOUCH /{report['pattern']}/")
    if not report["pages"]:
        print("  No generated page the project imports matches it (a widget id needs the generated cssids: --cssids).")
        return
    for p in report["pages"]:
        names = ", ".join(p["tests"][:8]) + (f" +{len(p['tests']) - 8}" if len(p["tests"]) > 8 else "")
        print(f"  {p['page']}: {len(p['tests'])} test(s)" + (f"  ->  {names}" if names else ""))
    if not report["entries"]:
        print("\n  No test reaches it (or its tests have no enabled rows).")
        return
    import json
    print(f"\n  {len(report['tests'])} test(s), {report['scenarios']} scenario(s). As a suite for CenterTestSuiteList.json:\n")
    print("\n".join("    " + line for line in json.dumps({"Name": name, "List": report["entries"]}, indent=2).splitlines()))
    if command:
        print(f"\n  Then: {command}")
