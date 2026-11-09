#!/usr/bin/env python3
"""Validate that DC DataCombination sheets only reference codes that exist in their reference data sheets,
and that reference sheets' own #-columns (reference-to-reference edges) also point to valid codes.

Usage:
    xlsx-validate-refs.py                          # validate all DC files
    xlsx-validate-refs.py testdata/WorkersCompDC.xlsx  # validate specific DC file

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

    total_errors = 0
    files_with_errors = 0

    # --- Per-DC DataCombination #-column validation (unchanged) ---
    for dc_path in dc_files:
        try:
            errors = validate_dc(dc_path)
        except Exception as e:
            print(f"\n  {dc_path}")
            print(f"    ERROR: failed to validate — {e}")
            files_with_errors += 1
            total_errors += 1
            continue
        if errors:
            files_with_errors += 1
            print(f"\n  {dc_path}")
            for row_idx, col, code, sheet, message in errors:
                total_errors += 1
                print(f"    [Row {row_idx}] {col} -> '{code}' : {message} (sheet: {sheet})")

    # --- Reference-sheet #-column validation: once per unique reference file ---
    ref_sheet_findings = validate_all_reference_sheets(dc_files)
    for ref_path, errors in sorted(ref_sheet_findings.items()):
        files_with_errors += 1
        print(f"\n  {ref_path} [reference sheet]")
        for row_idx, col, code, sheet, message in errors:
            total_errors += 1
            print(f"    [Row {row_idx}] {col} -> '{code}' : {message} (sheet: {sheet})")

    if total_errors == 0:
        print("  All DC references are valid.")
    else:
        print(f"\n  Found {total_errors} broken reference(s) in {files_with_errors} file(s).")
        sys.exit(1)


if __name__ == "__main__":
    run_with_pr_review_report("xlsx-validate-refs", main)
