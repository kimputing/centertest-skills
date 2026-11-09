"""Reference-integrity engine for CenterTest DDT workbooks (the logic behind xlsx-validate-refs.py).

Mirrors how the framework reads a DataCombination header:

    #Ref                  reference: each code must exist in the Ref sheet in the DC's reference scope
    #Ref.Field            override: the cell is a value, not a code (not validated)
    #A<>#B                join: pairs instances of two declared references (not validated)
    @Rel                  relationship: each code must be a row of the target DC ($relationships)
    @Rel.#Ref             relationship hop: the code must exist in the Ref sheet in the *related*
                          DC's reference scope (the DC named by this row's @Rel cell)
    @Rel.Field, @Rel.#Ref.Field
                          override on the related row (not validated)

``<blank>`` and other ``<word>`` cells are framework sentinels, never codes.

All paths are relative to the current directory, which must be the project root. The same file
is vendored into centertest-healthcheck (rules 14003/14004) so both report the same findings;
tests keep the copies identical.
"""

import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddt_reference_scope import (parse_references, resolve, parse_relationships,
                                  default_identifier_for, identifier_of, strip_identifier)

from openpyxl import load_workbook


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


def _collect_ref_file_locations(dc_path):
    """Return the list of resolved reference file paths for a DC file.

    Reads the DC's own References sheet when present; otherwise falls back to the
    reference-centric $references scope from DataDrivenHierarchy.json.
    Returns a list of absolute/normalised file paths (strings).
    """
    try:
        wb = load_workbook(dc_path, read_only=True, data_only=True)
    except Exception:
        return []
    refs_sheet = next((s for s in wb.sheetnames if s.lower() == "references"), None)
    locations = []
    if refs_sheet is not None:
        ws = wb[refs_sheet]
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
    wb.close()

    resolved = []
    for location in locations:
        ref_path = os.path.normpath(os.path.join(os.path.dirname(dc_path), location))
        if not os.path.isfile(ref_path):
            ref_path = location
        if os.path.isfile(ref_path):
            resolved.append(os.path.abspath(ref_path))
    return resolved


def _build_global_ref_codes(ref_file_paths):
    """Build a unified all_codes map from a collection of reference file paths.

    Returns: {sheet_name_lower: {code: (source_file, row_idx)}}
    All non-DC xlsx files in the same testdata/ directories are included so that
    #-column targets on reference sheets resolve against the full scope.
    """
    all_codes = {}
    for ref_path in ref_file_paths:
        try:
            ref_wb = load_workbook(ref_path, read_only=True, data_only=True)
        except Exception:
            continue
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


def _validate_one_ref_file(ref_path, all_codes):
    """Validate #-prefixed columns in a single reference file's sheets.

    Validates every non-DC sheet whose header row contains a #-prefixed column,
    checking that each comma-split code value exists in the resolved all_codes scope.

    Returns list of (row, col, code, target_sheet, message) errors attributed to
    this reference file.
    """
    errors = []
    try:
        ref_wb = load_workbook(ref_path, read_only=True, data_only=True)
    except Exception:
        return errors

    def _validate_sheet(ws_wb, ws_name):
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
                    if h.startswith("#") and "." not in h and JOIN_SEPARATOR not in h:
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
                    if code and not SENTINEL_RE.fullmatch(code) and code not in available:
                        similar = [c for c in available if c.lower() == code.lower()]
                        hint = f" (did you mean '{similar[0]}'?)" if similar else ""
                        errors.append((row_idx, col_header, code, target_key,
                                       f"code not found{hint}"))

    for sheet_name in ref_wb.sheetnames:
        lower = sheet_name.lower()
        if lower in ("datacombination", "references"):
            continue
        _validate_sheet(ref_wb, sheet_name)
    ref_wb.close()
    return errors


def validate_all_reference_sheets(dc_files):
    """Validate #-prefixed columns on reference sheets, once per unique reference file.

    Collects the union of all reference files across all DC files, then validates each
    unique reference file exactly once.  Findings are attributed to the reference file
    (not to each DC that happens to reference it).

    Returns: {ref_file_path: [(row, col, code, target_sheet, message)]}
    """
    # Step 1: collect unique reference file paths across all DCs
    all_ref_paths = set()
    for dc_path in dc_files:
        for ref_path in _collect_ref_file_locations(dc_path):
            all_ref_paths.add(ref_path)

    if not all_ref_paths:
        return {}

    # Step 2: build a global scope from ALL reference files (union)
    all_codes = _build_global_ref_codes(all_ref_paths)

    # Step 3: validate each reference file exactly once
    results = {}
    for ref_path in sorted(all_ref_paths):
        errors = _validate_one_ref_file(ref_path, all_codes)
        if errors:
            results[ref_path] = errors

    return results


# Framework sentinels, not codes: "<blank>" clears an inherited reference. Never validated.
SENTINEL_RE = re.compile(r"<[A-Za-z]+>")

# "@Rel.#Ref": a relationship-hop reference (a code). With a trailing ".Field" it is an override.
HOP_REF_RE = re.compile(r"@(\w+)\.#(\w+)")

# "#A<>#B" pairs instances of two declared references; it holds group lines, not a code.
JOIN_SEPARATOR = "<>"


def classify_headers(headers):
    """Split DataCombination headers into (ref_columns, rel_columns, hop_columns).

    ref_columns: "#Ref" headers holding codes; rel_columns: "@Rel" headers holding target DC codes;
    hop_columns: [(header, relationship, normalised sheet)] for "@Rel.#Ref". Overrides ("#Ref.Field",
    "@Rel.Field", "@Rel.#Ref.Field") and joins ("#A<>#B") hold values, so they are in none of them.
    """
    ref_columns, rel_columns, hop_columns = [], [], []
    for h in headers:
        if not h or JOIN_SEPARATOR in h:
            continue
        if h.startswith("#") and "." not in h:
            ref_columns.append(h)
        elif h.startswith("@") and "." not in h:
            rel_columns.append(h)
        else:
            m = HOP_REF_RE.fullmatch(h)
            if m:
                hop_columns.append((h, m.group(1), _norm_sheet(m.group(2))))
    return ref_columns, rel_columns, hop_columns


def _missing_codes(row_idx, col, cell_value, available, sheet_key):
    """Errors for each comma-separated code in cell_value that is not in available."""
    errors = []
    for code in [c.strip() for c in (cell_value or "").split(",")]:
        if code and not SENTINEL_RE.fullmatch(code) and code not in available:
            similar = [c for c in available if c.lower() == code.lower()]
            hint = f" (did you mean '{similar[0]}'?)" if similar else ""
            errors.append((row_idx, col, code, sheet_key, f"code not found{hint}"))
    return errors


_ref_codes_cache = {}


def reference_codes_for(dc_path):
    """load_reference_codes, memoised: hop columns ask for the same related DCs on every row."""
    if dc_path not in _ref_codes_cache:
        _ref_codes_cache[dc_path] = load_reference_codes(dc_path)
    return _ref_codes_cache[dc_path]


def reset_caches():
    """Forget cached workbooks and hierarchy (for a second project in the same process)."""
    global _hierarchy_cache
    _hierarchy_cache = None
    _dc_codes_cache.clear()
    _ref_codes_cache.clear()


def validate_project(dc_files=None):
    """Validate every DC (or the given ones) and their reference sheets.

    Returns {file: [(row, col, code, sheet, message)]} with only files that have findings;
    reference-sheet files are keyed by their absolute path, DC files as given.
    """
    if dc_files is None:
        dc_files = find_all_dc_files()
    findings = {}
    for dc_path in dc_files:
        try:
            errors = validate_dc(dc_path)
        except Exception as e:  # one unreadable workbook must not hide every other finding
            errors = [(0, "", "", "", f"could not validate: {type(e).__name__}: {e}")]
        if errors:
            findings[dc_path] = errors
    findings.update(validate_all_reference_sheets(dc_files))
    return findings


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

    ref_columns, rel_columns, hop_columns = classify_headers(headers)
    if not ref_columns and not rel_columns and not hop_columns:
        return []

    errors = []

    # --- # reference columns: each code must exist in the resolved reference data ---
    if ref_columns:
        ref_codes = reference_codes_for(dc_path)

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
                sheet_key = _norm_sheet(col[1:])
                if col in missing_sheets or sheet_key not in ref_codes:
                    continue  # reported once above, or an empty column naming no sheet
                errors.extend(_missing_codes(row_idx, col, row_data.get(col, ""),
                                             ref_codes[sheet_key], sheet_key))

    by_relationship, identifiers = parse_relationships(load_hierarchy())
    default_id = ""
    if rel_columns or hop_columns:
        try:
            default_id = default_identifier_for(dc_path.replace("\\", "/"), identifiers)
        except ValueError as e:
            errors.append((0, "", "", "relationship", str(e)))

    # --- @ relationship columns: the resolved target DC file and referenced code must exist ---
    for row_idx, row_data in dc_rows:
        for col in rel_columns:
            cell_value = row_data.get(col, "")
            if not cell_value:
                continue
            rel_name = col[1:].lower()
            targets = by_relationship.get(rel_name, {})
            for raw in [c.strip() for c in cell_value.split(",")]:
                if not raw or SENTINEL_RE.fullmatch(raw):
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

    # --- @Rel.#Ref hop columns: the code must exist in the *related* DC's reference scope ---
    for row_idx, row_data in dc_rows:
        for col, relationship, sheet_key in hop_columns:
            cell_value = row_data.get(col, "")
            if not cell_value:
                continue
            rel_targets = by_relationship.get(relationship.lower(), {})
            related = []
            for raw in (row_data.get("@" + relationship, "") or "").split(","):
                raw = raw.strip()
                if not raw or SENTINEL_RE.fullmatch(raw):
                    continue
                target = rel_targets.get(identifier_of(raw, default_id))
                if target and target not in related:
                    related.append(target)
            if not related:
                # No related row named here (inherited or unresolvable): accept the code if any
                # DC this relationship can point at supplies it, rather than guess a scope.
                related = sorted(set(rel_targets.values()))
            available = {}
            for target in related:
                if os.path.isfile(target):
                    available.update(reference_codes_for(target).get(sheet_key, {}))
            if not available:
                continue  # the related DC has no such sheet in scope: not this file's error
            errors.extend(_missing_codes(row_idx, col, cell_value, available, sheet_key))

    return errors


def find_all_dc_files():
    """Find all DC xlsx files in testdata/."""
    import glob
    files = glob.glob("testdata/**/*DC.xlsx", recursive=True) + glob.glob("testdata/*DC.xlsx")
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    return sorted(set(files))
