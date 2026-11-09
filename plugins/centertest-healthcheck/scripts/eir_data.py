"""
The suite's test data at a glance: how many scenarios a full run executes, which workbooks no
test reads, how many reference codes nothing uses, and how many broken references would bite.

Scenarios: every enabled DataCombination row of a @DataDriven test's datasource is one run of
that test (a row's Multiplier repeats it); tests that are not data-driven run once.
"""

from __future__ import annotations

import glob
import os

_TRUTHY = {"true", "t", "yes", "y", "checked", "1"}  # CenterTest's TRUEOPTIONS (BaseTestData.isDisabled)


def _dc_row_counts(path: str) -> tuple[int, int]:
    """(scenarios, disabled rows) of one DataCombination sheet, Multiplier applied."""
    from ddt_refcheck import load_workbook
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return 0, 0
    sheet = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
    rows = [r for r in wb[sheet].iter_rows(values_only=True) if any(c not in (None, "") for c in r)] if sheet else []
    wb.close()
    if not rows:
        return 0, 0
    headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    di = headers.index("disabled") if "disabled" in headers else None
    mi = headers.index("multiplier") if "multiplier" in headers else None
    runs = disabled = 0
    for r in rows[1:]:
        if di is not None and di < len(r) and str(r[di] if r[di] is not None else "").strip().lower() in _TRUTHY:
            disabled += 1
            continue
        times = 1
        if mi is not None and mi < len(r) and r[mi] not in (None, ""):
            try:
                times = max(1, int(float(r[mi])))
            except ValueError:
                times = 1
        runs += times
    return runs, disabled


def data_overview(repo_dir: str, source_root: str, results=None) -> dict | None:
    """Numbers for the "Test data" panel, or None when the project has no testdata/."""
    if not os.path.isdir(os.path.join(repo_dir, "testdata")):
        return None
    import ddt_refcheck
    from rules.rule_ddt import _DATASOURCE_RE, workbook_users

    users = workbook_users(repo_dir, source_root)
    previous = os.getcwd()
    try:
        os.chdir(repo_dir)
        ddt_refcheck.reset_caches()
        dcs = ddt_refcheck.find_all_dc_files()
        used = ddt_refcheck.used_codes(dcs, source_root)
        # The same Data files xlsx-cleanup-unused reports on, so the two counts agree.
        data_files = sorted(f for f in glob.glob("testdata/*Data.xlsx") if not os.path.basename(f).startswith("~$"))
        total_codes = unused_codes = 0
        for path in data_files:
            for sheet, (_headers, codes) in _codes_by_sheet(path).items():
                in_use = used.get(ddt_refcheck._norm_sheet(sheet), {})
                total_codes += len(codes)
                unused_codes += sum(1 for c in codes if c not in in_use)
    finally:
        os.chdir(previous)

    tests_by_source: dict[str, list[str]] = {}
    test_classes = 0
    for root, _dirs, files in os.walk(os.path.join(repo_dir, source_root)):
        if "datadriven" in root.replace("\\", "/").split("/"):
            continue
        for name in files:
            if not name.endswith(".java"):
                continue
            with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if "@CenterTest" not in text:
                continue
            test_classes += 1
            for source in set(_DATASOURCE_RE.findall(text)):
                tests_by_source.setdefault(source, []).append(name[:-5])
    data_driven = {t for tests in tests_by_source.values() for t in tests}
    scenarios, disabled = test_classes - len(data_driven), 0
    for source, tests in tests_by_source.items():
        runs, off = _dc_row_counts(os.path.join(repo_dir, source))
        scenarios += runs * len(tests)
        disabled += off * len(tests)

    # Scenarios no suite runs (suite.py is the vendored suite-builder engine).
    in_no_suite = None
    import suite as suites
    suite_file = suites.find_suite_file(repo_dir)
    if os.path.isfile(suite_file):
        try:
            doc, _text = suites.load_suites(suite_file)
            s_tests = suites.scan(repo_dir, source_root)
            left = suites.uncovered(doc, s_tests)
            in_no_suite = {"count": len(left), "of": len(suites.scenarios_of(s_tests)),
                           "classes": sorted({c for c, _m, _k in left} -
                                             {c for c, _m, _k in set(suites.scenarios_of(s_tests)) - left})}
        except (OSError, ValueError):
            in_no_suite = None

    checked = any(r.rule_id in ("14003", "14004") and not r.error for r in results or [])
    live = dormant = 0
    for r in results or []:
        if r.rule_id in ("14003", "14004") and "Runs in" in r.headers:
            i = r.headers.index("Runs in")
            for row in r.rows:
                if str(row[i]).startswith("not run"):
                    dormant += 1
                else:
                    live += 1
    return {
        "scenarios": scenarios, "disabled": disabled, "test_classes": test_classes,
        "data_driven": len(data_driven),
        "dc_files": len(dcs), "unread": sorted(d for d in dcs if not users.get(d)),
        "codes": total_codes, "unused_codes": unused_codes,
        "broken_live": live if checked else None, "broken_dormant": dormant if checked else None,
        "in_no_suite": in_no_suite,
    }


def ddt_format(value) -> str:
    from ddt_refcheck import format_value
    return format_value(value).strip()


def _codes_by_sheet(path: str) -> dict:
    """{sheet: (headers, [codes])} for sheets with a Code column."""
    from ddt_refcheck import load_workbook
    out = {}
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return out
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
        if not rows:
            continue
        headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
        if "code" in headers:
            ci = headers.index("code")
            # distinct codes, as xlsx-cleanup-unused counts them
            out[ws.title] = (headers, sorted({ddt_format(r[ci]) for r in rows[1:] if ci < len(r) and r[ci] not in (None, "")}))
    wb.close()
    return out


def print_data(d: dict) -> None:
    print("  TEST DATA")
    print(f"  A full run executes {d['scenarios']} scenario runs ({d['data_driven']} data-driven of "
          f"{d['test_classes']} test classes; Multiplier repeats included; {d['disabled']} rows disabled)")
    print(f"  {d['dc_files']} DC workbooks, {len(d['unread'])} read by no test"
          + (": " + ", ".join(os.path.basename(u) for u in d["unread"][:5]) if d["unread"] else ""))
    broken = ("not checked (rules 14003/14004 were not run)" if d["broken_live"] is None else
              f"{d['broken_live']} in data tests run, {d['broken_dormant']} in data no test runs")
    print(f"  {d['unused_codes']} of {d['codes']} reference codes unused; broken references: {broken}")
    if d.get("in_no_suite"):
        n = d["in_no_suite"]
        print(f"  {n['count']} of {n['of']} distinct scenarios are in no suite; classes no suite runs: "
              + (", ".join(n["classes"][:6]) + (" ..." if len(n["classes"]) > 6 else "") if n["classes"] else "none"))
