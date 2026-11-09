#!/usr/bin/env python3
"""Validate that DC DataCombination sheets only reference codes that exist in their reference data sheets,
and that reference sheets' own #-columns (reference-to-reference edges) also point to valid codes.

Usage:
    xlsx-validate-refs.py                          # validate all DC files
    xlsx-validate-refs.py testdata/WorkersCompDC.xlsx  # validate specific DC file
    xlsx-validate-refs.py --json                   # one JSON document on stdout (for the MCP server, CI)

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/ddt-tools/scripts/xlsx-validate-refs.py
"""

import os
import sys

# Add script directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddt_config import get_project_dir, run_with_pr_review_report

try:
    import openpyxl  # noqa: F401  (the engine needs it; fail here with a clear message)
except ImportError:
    print(f"ERROR: openpyxl is not installed for {sys.executable}.\n"
          f"  Install it for this Python: \"{sys.executable}\" -m pip install openpyxl\n"
          "  If pip refuses (Homebrew and other externally managed Pythons), create the CenterTest\n"
          "  environment once; the skills use it automatically:\n"
          "    python3 -m venv ~/.centertest/venv && ~/.centertest/venv/bin/python -m pip install openpyxl javalang",
          file=sys.stderr)
    sys.exit(1)

from ddt_refcheck import validate_dc, validate_all_reference_sheets, find_all_dc_files


def main():
    project_dir = get_project_dir()
    os.chdir(project_dir)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        dc_files = args
    else:
        dc_files = find_all_dc_files()

    # (file, kind, row, column, code, sheet, message) for every broken reference
    findings = []
    for dc_path in dc_files:
        try:
            errors = validate_dc(dc_path)
        except Exception as e:
            findings.append((dc_path, "dc", 0, "", "", "", f"failed to validate — {e}"))
            continue
        findings += [(dc_path, "dc", *e) for e in errors]
    # reference sheets' own #-columns: once per unique reference file
    for ref_path, errors in sorted(validate_all_reference_sheets(dc_files).items()):
        findings += [(ref_path, "reference sheet", *e) for e in errors]

    if "--json" in sys.argv[1:]:
        import json
        print(json.dumps({"schema": 1, "tool": "xlsx-validate-refs", "broken": len(findings),
                          "findings": [dict(zip(("file", "kind", "row", "column", "code", "sheet", "message"), f))
                                       for f in findings]}, ensure_ascii=False, default=str))
        sys.exit(1 if findings else 0)
    current = None
    for path, kind, row_idx, col, code, sheet, message in findings:
        if path != current:
            current = path
            print(f"\n  {path}" + (" [reference sheet]" if kind == "reference sheet" else ""))
        if not col and not code:
            print(f"    ERROR: {message}")
        else:
            print(f"    [Row {row_idx}] {col} -> '{code}' : {message} (sheet: {sheet})")
    if not findings:
        print("  All DC references are valid.")
    else:
        print(f"\n  Found {len(findings)} broken reference(s) in {len({f[0] for f in findings})} file(s).")
        sys.exit(1)


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__.strip())  # usage only: no check, no pr-review report
        sys.exit(0)
    if "--json" in sys.argv[1:]:
        main()  # stdout is the JSON document alone: no pr-review report tee
    else:
        run_with_pr_review_report("xlsx-validate-refs", main)
