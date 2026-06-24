#!/usr/bin/env python3
"""Validate that DC DataCombination sheets only reference codes that exist in their reference data sheets,
and that reference sheets' own #-columns (reference-to-reference edges) also point to valid codes.

Usage:
    xlsx-validate-refs.py                          # validate all DC files
    xlsx-validate-refs.py testdata/WorkersCompDC.xlsx  # validate specific DC file

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/ddt-tools/scripts/xlsx-validate-refs.py
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add script directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddt_config import get_project_dir, run_with_pr_review_report
from ddt_reference_scope import (parse_references, resolve, parse_relationships,
                                  default_identifier_for, identifier_of, strip_identifier)

try:
    from openpyxl import load_workbook
except ImportError:
    print("ERROR: openpyxl is required. Install with: pip install openpyxl", file=sys.stderr)
    sys.exit(1)


def _norm_sheet(name):
    """Normalise a sheet name the same way the Java resolver does: strip non-alphanumerics, lowercase."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def format_value(val):
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val)


def read_sheet(wb, sheet_name):
    """Read a sheet into {code: row_idx} mapping. Returns (headers, codes_dict)."""
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
    return headers, codes


def load_reference_codes(dc_path):
    """Load all available codes from all reference data files for a DC file.

    Returns: {sheet_name_lower: {code: (source_file, row_idx)}}
    """
    wb = load_workbook(dc_path, read_only=True, data_only=True)

    # Collect codes from sheets within the DC file itself (excluding DataCombination and References)
    all_codes = {}
    for sheet_name in wb.sheetnames:
        if sheet_name.lower() in ("datacombination", "references"):
            continue
        key = _norm_sheet(sheet_name)
        _, codes = read_sheet(wb, sheet_name)
        if key not in all_codes:
            all_codes[key] = {}
        for code, row_idx in codes.items():
            all_codes[key][code] = (os.path.basename(dc_path), row_idx)

    # Determine the reference file locations: the DC's own References sheet (verbatim) when present,
    # otherwise the reference-centric $references scope (mirror of the Java resolver).
    refs_sheet_name = next((s for s in wb.sheetnames if s.lower() == "references"), None)
    has_refs_sheet = refs_sheet_name is not None
    locations = []
    if has_refs_sheet:
        ws = wb[refs_sheet_name]
        headers = None
        for row in ws.iter_rows(values_only=True):
            values = [format_value(c) for c in row]
            if all(v == "" for v in values):
                continue
            if headers is None:
                headers = [v.lower() for v in values]
                continue
            location = dict(zip(headers, values)).get("location", "")
            if location:
                locations.append(location)
    else:
        entries = parse_references(load_hierarchy())
        locations, _ = resolve(dc_path.replace("\\", "/"), None, entries)

    wb.close()

    for location in locations:
        ref_path = os.path.normpath(os.path.join(os.path.dirname(dc_path), location))
        if not os.path.isfile(ref_path):
            ref_path = location
        if os.path.isfile(ref_path):
            ref_wb = load_workbook(ref_path, read_only=True, data_only=True)
            for sheet_name in ref_wb.sheetnames:
                key = _norm_sheet(sheet_name)
                _, codes = read_sheet(ref_wb, sheet_name)
                if key not in all_codes:
                    all_codes[key] = {}
                for code, row_idx in codes.items():
                    if code not in all_codes[key]:
                        all_codes[key][code] = (os.path.basename(ref_path), row_idx)
            ref_wb.close()

    return all_codes


_hierarchy_cache = None


def load_hierarchy():
    global _hierarchy_cache
    if _hierarchy_cache is not None:
        return _hierarchy_cache
    hierarchy_path = "testdata/DataDrivenHierarchy.json"
    if os.path.isfile(hierarchy_path):
        with open(hierarchy_path) as f:
            _hierarchy_cache = json.load(f)
    else:
        _hierarchy_cache = {}
    return _hierarchy_cache


_dc_codes_cache = {}


def load_dc_codes(dc_file):
    """Return the set of Code values in a target DC's DataCombination sheet (cached)."""
    if dc_file in _dc_codes_cache:
        return _dc_codes_cache[dc_file]
    codes = set()
    try:
        wb = load_workbook(dc_file, read_only=True, data_only=True)
        dc_sheet = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
        if dc_sheet:
            _, code_map = read_sheet(wb, dc_sheet)
            codes = set(code_map.keys())
        wb.close()
    except Exception:
        pass
    _dc_codes_cache[dc_file] = codes
    return codes


def validate_reference_sheets(dc_path):
    """Validate #-prefixed columns on reference sheets within a DC file's scope.

    For each reference sheet (i.e. any non-DataCombination, non-References sheet in the DC
    file or its referenced files), finds columns whose header starts with '#' and validates
    every comma-split cell value against the resolved all_codes map for the target sheet
    (header[1:] lowercased, non-alphanumeric stripped — same normalisation Java uses).

    Returns list of (row, col, code, target_sheet, message) errors in the same shape as
    validate_dc.
    """
    if not os.path.isfile(dc_path):
        return []

    try:
        wb = load_workbook(dc_path, read_only=True, data_only=True)
    except Exception:
        return []

    errors = []
    all_codes = load_reference_codes(dc_path)

    # Collect all reference sheets: non-DataCombination, non-References sheets in the DC
    # file itself, plus all sheets in referenced files.
    # all_codes already maps sheet_name_lower -> {code: (file, row)}, so we only need the
    # actual sheet rows to walk.  Re-open the DC and referenced files to iterate rows.

    def _validate_sheet(ws_wb, ws_name):
        """Validate one reference sheet for #-column integrity; append to errors."""
        ws = ws_wb[ws_name]
        headers = None
        ref_cols = []   # [(col_idx, col_header, target_key)]
        data_rows = []  # [(row_idx, values)]
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            values = [format_value(c) for c in row]
            if all(v == "" for v in values):
                continue
            if headers is None:
                headers = values
                for i, h in enumerate(headers):
                    if h.startswith("#"):
                        # Normalise target sheet name: strip non-alphanumerics, lowercase
                        # (mirrors Java ReferenceToReferenceValidator.normalise)
                        target = _norm_sheet(h[1:])
                        ref_cols.append((i, h, target))
                continue
            data_rows.append((row_idx, values))

        if not ref_cols or not data_rows:
            return

        # First pass: one "unknown sheet" error per #-column (not one per row)
        unknown_cols = set()
        for col_idx, col_header, target_key in ref_cols:
            if target_key not in all_codes:
                has_values = any(
                    (row_vals[col_idx] if col_idx < len(row_vals) else "")
                    for _, row_vals in data_rows
                )
                if has_values:
                    unknown_cols.add(col_header)
                    errors.append((0, col_header, "", target_key,
                                   f"unknown sheet '{col_header[1:]}' (no matching sheet in scope)"))

        # Second pass: validate codes for columns whose target sheet exists
        for row_idx, values in data_rows:
            for col_idx, col_header, target_key in ref_cols:
                if col_header in unknown_cols:
                    continue
                cell_value = values[col_idx] if col_idx < len(values) else ""
                if not cell_value:
                    continue
                available = all_codes[target_key]
                for code in [c.strip() for c in cell_value.split(",")]:
                    if code and code not in available:
                        similar = [c for c in available if c.lower() == code.lower()]
                        hint = f" (did you mean '{similar[0]}'?)" if similar else ""
                        errors.append((row_idx, col_header, code, target_key,
                                       f"code not found{hint}"))

    # Walk reference sheets in the DC file itself
    for sheet_name in wb.sheetnames:
        lower = sheet_name.lower()
        if lower in ("datacombination", "references"):
            continue
        _validate_sheet(wb, sheet_name)
    wb.close()

    # Walk referenced files' sheets
    try:
        wb2 = load_workbook(dc_path, read_only=True, data_only=True)
        refs_sheet = next((s for s in wb2.sheetnames if s.lower() == "references"), None)
        locations = []
        if refs_sheet is not None:
            ws = wb2[refs_sheet]
            hdrs = None
            for row in ws.iter_rows(values_only=True):
                values = [format_value(c) for c in row]
                if all(v == "" for v in values):
                    continue
                if hdrs is None:
                    hdrs = [v.lower() for v in values]
                    continue
                location = dict(zip(hdrs, values)).get("location", "")
                if location:
                    locations.append(location)
        else:
            entries = parse_references(load_hierarchy())
            locations, _ = resolve(dc_path.replace("\\", "/"), None, entries)
        wb2.close()
        for location in locations:
            ref_path = os.path.normpath(os.path.join(os.path.dirname(dc_path), location))
            if not os.path.isfile(ref_path):
                ref_path = location
            if os.path.isfile(ref_path):
                ref_wb = load_workbook(ref_path, read_only=True, data_only=True)
                for sheet_name in ref_wb.sheetnames:
                    _validate_sheet(ref_wb, sheet_name)
                ref_wb.close()
    except Exception:
        pass

    return errors


def validate_dc(dc_path):
    """Validate a single DC file. Returns list of (row, col, code, sheet, message) errors."""
    if not os.path.isfile(dc_path):
        return [(0, "", "", "", f"File not found: {dc_path}")]

    try:
        wb = load_workbook(dc_path, read_only=True, data_only=True)
    except Exception as e:
        print(f"  WARNING: Skipping {dc_path} — cannot open: {e}", file=sys.stderr)
        return []

    # Find DataCombination sheet (case-insensitive)
    dc_sheet = None
    for name in wb.sheetnames:
        if name.lower() == "datacombination":
            dc_sheet = name
            break

    if dc_sheet is None:
        wb.close()
        return []

    # Read DataCombination headers
    ws = wb[dc_sheet]
    headers = None
    dc_rows = []
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        values = [format_value(c) for c in row]
        if all(v == "" for v in values):
            continue
        if headers is None:
            headers = values
        else:
            dc_rows.append((row_idx, dict(zip(headers, values))))

    wb.close()

    if not headers:
        return []

    # Find reference columns (#) and relationship columns (@)
    ref_columns = [h for h in headers if h.startswith("#")]
    rel_columns = [h for h in headers if h.startswith("@")]
    if not ref_columns and not rel_columns:
        return []

    errors = []

    # --- # reference columns: each code must exist in the resolved reference data ---
    if ref_columns:
        ref_codes = load_reference_codes(dc_path)

        # First pass: check which # columns have no matching sheet at all
        missing_sheets = set()
        for col in ref_columns:
            sheet_key = _norm_sheet(col[1:])
            if sheet_key not in ref_codes:
                has_values = any(row_data.get(col, "") for _, row_data in dc_rows)
                if has_values:
                    missing_sheets.add(col)
                    errors.append((0, col, "", sheet_key, "no matching sheet found in any reference file"))

        # Second pass: validate codes for columns that do have a matching sheet
        for row_idx, row_data in dc_rows:
            for col in ref_columns:
                if col in missing_sheets:
                    continue
                cell_value = row_data.get(col, "")
                if not cell_value:
                    continue

                sheet_key = _norm_sheet(col[1:])
                available = ref_codes[sheet_key]

                codes = [c.strip() for c in cell_value.split(",")]
                for code in codes:
                    if code and code not in available:
                        similar = [c for c in available if c.lower() == code.lower()]
                        hint = f" (did you mean '{similar[0]}'?)" if similar else ""
                        errors.append((row_idx, col, code, sheet_key, f"code not found{hint}"))

    # --- @ relationship columns: the resolved target DC file and referenced code must exist ---
    if rel_columns:
        by_relationship, identifiers = parse_relationships(load_hierarchy())
        try:
            default_id = default_identifier_for(dc_path.replace("\\", "/"), identifiers)
        except ValueError as e:
            default_id = ""
            errors.append((0, "", "", "relationship", str(e)))
        for row_idx, row_data in dc_rows:
            for col in rel_columns:
                cell_value = row_data.get(col, "")
                if not cell_value:
                    continue
                rel_name = col[1:].lower()
                targets = by_relationship.get(rel_name, {})
                for raw in [c.strip() for c in cell_value.split(",")]:
                    if not raw:
                        continue
                    ident = identifier_of(raw, default_id)
                    bare = strip_identifier(raw)
                    target_file = targets.get(ident)
                    if target_file is None:
                        errors.append((row_idx, col, raw, rel_name,
                                       f"unknown identifier '{ident}' for relationship '{rel_name}' (add it under $relationships)"))
                    elif not os.path.isfile(target_file):
                        errors.append((row_idx, col, raw, rel_name, f"target DC file not found: {target_file}"))
                    elif bare not in load_dc_codes(target_file):
                        errors.append((row_idx, col, raw, rel_name, f"code '{bare}' not found in {target_file}"))

    return errors


def find_all_dc_files():
    """Find all DC xlsx files in testdata/."""
    import glob
    files = glob.glob("testdata/**/*DC.xlsx", recursive=True) + glob.glob("testdata/*DC.xlsx")
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    return sorted(set(files))


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

    for dc_path in dc_files:
        try:
            errors = validate_dc(dc_path) + validate_reference_sheets(dc_path)
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

    if total_errors == 0:
        print("  All DC references are valid.")
    else:
        print(f"\n  Found {total_errors} broken reference(s) in {files_with_errors} file(s).")
        sys.exit(1)


if __name__ == "__main__":
    run_with_pr_review_report("xlsx-validate-refs", main)
