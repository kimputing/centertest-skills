#!/usr/bin/env python3
"""Report unused codes in DDT reference data files.

Usage:
    xlsx-cleanup-unused.py              # report unused codes across all Data files
    xlsx-cleanup-unused.py --json       # one JSON document on stdout (for the MCP server, CI)

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/ddt-tools/scripts/xlsx-cleanup-unused.py
"""

import glob
import os
import sys
from datetime import datetime

# Add script directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddt_config import get_project_dir, run_with_pr_review_report

try:
    from openpyxl import load_workbook
except ImportError:
    print(f"ERROR: openpyxl is not installed for {sys.executable}.\n"
          f"  Install it for this Python: \"{sys.executable}\" -m pip install openpyxl\n"
          "  If pip refuses (Homebrew and other externally managed Pythons), create the CenterTest\n"
          "  environment once; the skills use it automatically:\n"
          "    python3 -m venv ~/.centertest/venv && ~/.centertest/venv/bin/python -m pip install openpyxl javalang",
          file=sys.stderr)
    sys.exit(1)

from ddt_refcheck import _norm_sheet, used_codes


def format_value(val):
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val)


def read_codes_from_sheet(wb, sheet_name):
    """Read all Code values from a sheet. Returns {code: row_index}."""
    ws = wb[sheet_name]
    headers = None
    codes = {}
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        values = [format_value(c) for c in row]
        if all(v == "" for v in values):
            continue
        if headers is None:
            headers = [v.lower() for v in values]
            continue
        row_dict = dict(zip(headers, values))
        code = row_dict.get("code", "")
        if code:
            codes[code] = row_idx
    return codes


def collect_all_data_codes():
    """Scan all Data files and collect every code per file/sheet."""
    data_files = glob.glob("testdata/*Data.xlsx") + glob.glob("testdata/*Data.xlsx")
    data_files = sorted(set(f for f in data_files if not os.path.basename(f).startswith("~$")))

    result = {}
    for path in data_files:
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception:
            continue
        file_data = {}
        for sheet_name in wb.sheetnames:
            codes = read_codes_from_sheet(wb, sheet_name)
            if codes:
                file_data[sheet_name] = codes
        wb.close()
        result[path] = file_data

    return result


def main():
    project_dir = get_project_dir()
    os.chdir(project_dir)

    as_json = "--json" in sys.argv[1:]
    if not as_json:
        print("Scanning DC files, reference sheets and Java for code usages...")
    used = used_codes()
    ways = {}
    for codes in used.values():
        for hows in codes.values():
            for how in hows:
                ways[how] = ways.get(how, 0) + 1

    if not as_json:
        print("Scanning all Data files for codes...")
    data_codes = collect_all_data_codes()

    total_unused = 0
    findings = []

    for filepath, sheets in sorted(data_codes.items()):
        for sheet_name, codes in sorted(sheets.items()):
            in_use = used.get(_norm_sheet(sheet_name), {})
            unused = {c for c in codes if c not in in_use}
            if unused:
                findings.append((filepath, sheet_name, unused, codes))
                total_unused += len(unused)

    if as_json:
        import json
        print(json.dumps({"schema": 1, "tool": "xlsx-cleanup-unused", "unused": total_unused, "ways": ways,
                          "sheets": [{"file": f, "sheet": s, "codes": len(c), "unused": sorted(u)}
                                     for f, s, u, c in findings]}, ensure_ascii=False))
        return
    if ways:
        print("Codes counted as used: " + ", ".join(f"{n} via {how}" for how, n in sorted(ways.items())))

    if not findings:
        print("\nNo unused codes found.")
        return

    print(f"\nFound {total_unused} unused code(s):\n")
    for filepath, sheet_name, unused, codes in findings:
        used_count = len(codes) - len(unused)
        basename = os.path.basename(filepath)
        if len(unused) == len(codes):
            tag = "ENTIRE SHEET UNUSED"
        else:
            tag = f"{used_count} used, {len(unused)} unused"
        print(f"  {basename} / {sheet_name} ({tag})")
        for code in sorted(unused):
            print(f"    - {code}")


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__.strip())  # usage only: no check, no pr-review report
        sys.exit(0)
    if "--json" in sys.argv[1:]:
        main()  # stdout is the JSON document alone: no pr-review report tee
    else:
        run_with_pr_review_report("xlsx-cleanup-unused", main)
