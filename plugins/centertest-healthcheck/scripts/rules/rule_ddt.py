"""
Rules 14002–14004: DDT data source integrity (cross-skill with ddt-tools).

14002 — @DataDriven datasource file existence check
14003 — DDT reference column integrity (# columns point to valid sheets/codes)
14004 — DDT relationship integrity (@ columns resolve to an existing target DC file + code)
        Also validates #-columns on reference sheets (reference-to-reference edges).
"""

from __future__ import annotations

import json
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


def _load_sheet_codes(wb, sheet_name: str) -> dict[str, int]:
    """Load {code: row_number} from a sheet's 'code' column."""
    codes = {}
    ws = wb[sheet_name]
    # Find 'code' column (case-insensitive)
    code_col = None
    header_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
    for i, h in enumerate(header_row):
        if h and str(h).strip().lower() == "code":
            code_col = i
            break

    if code_col is None:
        return codes

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row_idx > 1 and code_col < len(row) and row[code_col]:
            val = str(row[code_col]).strip()
            if val:
                codes[val] = row_idx
    return codes


def _get_ref_columns(ws) -> list[tuple[int, str]]:
    """Find columns starting with # (reference columns). Returns [(col_idx, sheet_name)]."""
    refs = []
    header_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
    for i, h in enumerate(header_row):
        if h and str(h).strip().startswith("#"):
            sheet_name = str(h).strip()[1:]  # remove #
            refs.append((i, sheet_name))
    return refs


@rule(id="14003", description="DDT reference column integrity", category="CenterTest")
def ddt_reference_integrity(commits: CommitsDict, config) -> RuleResult:
    """
    Verify DDT Excel reference columns (# columns) point to valid sheets and codes.

    For each @DataDriven datasource file:
    1. Find columns starting with # (e.g., #Payment, #Coverage)
    2. Check that the referenced sheet exists (in same file or reference files)
    3. Check that each code in the # column exists in the referenced sheet

    This replicates the core logic of ddt-tools/xlsx-validate-refs.py
    as a healthcheck rule.
    """
    result = RuleResult(
        rule_id="14003",
        description="DDT reference column integrity",
        category="CenterTest",
        headers=["File", "Sheet", "Row", "Column", "Code", "Issue"],
    )

    if not _HAS_OPENPYXL:
        result.error = "openpyxl required for DDT reference validation"
        return result

    repo_dir = config.repository_dir

    # Collect all unique datasource paths from @DataDriven annotations
    datasource_paths = set()
    for commit_info, files in sorted(commits.items()):
        for f in files:
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if method.body:
                    m = _DATASOURCE_RE.search(method.body)
                    if m:
                        datasource_paths.add(m.group(1))

    # Also scan testdata/ directory for all DC xlsx files
    testdata_dir = os.path.join(repo_dir, "testdata")
    if os.path.isdir(testdata_dir):
        for root, _dirs, filenames in os.walk(testdata_dir):
            for fname in filenames:
                if fname.endswith("DC.xlsx"):
                    rel = os.path.relpath(os.path.join(root, fname), repo_dir)
                    datasource_paths.add(rel)

    # Load reference data files (non-DC files in testdata/) for code lookup
    ref_codes: dict[str, dict[str, int]] = {}  # {sheet_name_lower: {code: row}}

    if os.path.isdir(testdata_dir):
        for fname in os.listdir(testdata_dir):
            if fname.endswith(".xlsx") and not fname.endswith("DC.xlsx"):
                ref_path = os.path.join(testdata_dir, fname)
                try:
                    wb_ref = load_workbook(ref_path, read_only=True, data_only=True)
                    for sheet_name in wb_ref.sheetnames:
                        codes = _load_sheet_codes(wb_ref, sheet_name)
                        if codes:
                            key = sheet_name.lower()
                            if key not in ref_codes:
                                ref_codes[key] = {}
                            ref_codes[key].update(codes)
                    wb_ref.close()
                except Exception:
                    pass

    # Validate each DC file
    for ds_path in sorted(datasource_paths):
        full_path = os.path.join(repo_dir, ds_path)
        if not os.path.isfile(full_path):
            continue  # rule 14002 handles missing files

        try:
            wb = load_workbook(full_path, read_only=True, data_only=True)
        except Exception:
            result.rows.append([ds_path, "-", "-", "-", "-", "Cannot open Excel file"])
            continue

        # Build local codes from all sheets in this DC file
        local_codes: dict[str, dict[str, int]] = {}
        for sheet_name in wb.sheetnames:
            codes = _load_sheet_codes(wb, sheet_name)
            if codes:
                local_codes[sheet_name.lower()] = codes

        # Check each sheet for # reference columns
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            ref_cols = _get_ref_columns(ws)
            if not ref_cols:
                continue

            for col_idx, ref_sheet_name in ref_cols:
                ref_key = ref_sheet_name.lower()

                # Check if referenced sheet exists anywhere
                available_codes = {}
                if ref_key in local_codes:
                    available_codes = local_codes[ref_key]
                elif ref_key in ref_codes:
                    available_codes = ref_codes[ref_key]
                else:
                    result.rows.append([
                        os.path.basename(ds_path),
                        sheet_name,
                        "-",
                        f"#{ref_sheet_name}",
                        "-",
                        f"Referenced sheet '{ref_sheet_name}' not found",
                    ])
                    continue

                # Validate each code in the reference column
                for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                    if col_idx >= len(row) or not row[col_idx]:
                        continue
                    cell_value = str(row[col_idx]).strip()
                    if not cell_value:
                        continue

                    # Handle comma-separated codes
                    codes_to_check = [c.strip() for c in cell_value.split(",")]
                    for code in codes_to_check:
                        if code and code not in available_codes:
                            result.rows.append([
                                os.path.basename(ds_path),
                                sheet_name,
                                row_idx,
                                f"#{ref_sheet_name}",
                                code,
                                "Code not found in referenced sheet",
                            ])

        wb.close()

    return result


# --- Rule 14004: DC -> DC @-relationship integrity -------------------------------

_IDENTIFIER_PREFIX = re.compile(r"^([A-Za-z0-9_]+)\..+$")


def _norm_sheet(name: str) -> str:
    """Normalise a sheet name: strip non-alphanumerics, lowercase (mirrors Java resolver)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _identifier_of(raw_code: str, default_identifier: str) -> str:
    """Identifier (UPPER) of a relationship code: the ``token.`` prefix, else the default."""
    if raw_code is not None:
        m = _IDENTIFIER_PREFIX.match(raw_code.strip())
        if m:
            return m.group(1).upper()
    return (default_identifier or "").strip().upper()


def _strip_identifier(raw_code: str) -> str:
    """The bare code with any ``identifier.`` prefix removed."""
    trimmed = (raw_code or "").strip()
    m = _IDENTIFIER_PREFIX.match(trimmed)
    if m:
        return trimmed[len(m.group(1)) + 1:].strip()
    return trimmed


def _parse_relationships(hierarchy: dict):
    """($relationships + $identifiers) -> (by_relationship{rel_lower:{ID:target}}, [(ID,[patterns])])."""
    by_rel: dict = {}
    identifiers: list = []
    ids = hierarchy.get("$identifiers") if isinstance(hierarchy, dict) else None
    if isinstance(ids, dict):
        for ident, patterns in ids.items():
            compiled = []
            for p in (patterns if isinstance(patterns, list) else []):
                try:
                    compiled.append(re.compile(p))
                except re.error:
                    pass
            identifiers.append((ident.upper(), compiled))
    rels = hierarchy.get("$relationships") if isinstance(hierarchy, dict) else None
    if isinstance(rels, dict):
        for rel, targets in rels.items():
            target_map = {}
            if isinstance(targets, dict):
                for ident, target in targets.items():
                    target_map[ident.upper()] = target
            by_rel[rel.lower()] = target_map
    return by_rel, identifiers


def _default_identifier_for(dc_path: str, identifiers) -> str:
    """Default identifier (UPPER) for a DC path; '' if none or ambiguous."""
    normalized = dc_path.replace("\\", "/").strip()
    match = ""
    for ident, patterns in identifiers:
        for pattern in patterns:
            if pattern.fullmatch(normalized):
                if match and match != ident:
                    return ""  # ambiguous — treated as no default
                match = ident
    return match


@rule(id="14004", description="DDT relationship (@) target integrity", category="CenterTest")
def ddt_relationship_integrity(commits: CommitsDict, config) -> RuleResult:
    """
    Verify DC-to-DC @-relationship columns resolve to an existing target DC file and code.

    For each DC file's @<Relationship> column (e.g. @Submission):
      1. resolve the identifier ($identifiers default for the DC, or a Prefix. on the value)
      2. look up the target DC file via $relationships[relationship][identifier]
      3. check the target DC file exists and the referenced Code is a row in it
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

    repo_dir = config.repository_dir
    hierarchy_path = os.path.join(repo_dir, "testdata", "DataDrivenHierarchy.json")
    if not os.path.isfile(hierarchy_path):
        return result
    try:
        with open(hierarchy_path) as fh:
            hierarchy = json.load(fh)
    except Exception:
        result.error = "Cannot read testdata/DataDrivenHierarchy.json"
        return result

    by_relationship, identifiers = _parse_relationships(hierarchy)
    if not by_relationship:
        return result  # no relationships configured — nothing to validate

    testdata_dir = os.path.join(repo_dir, "testdata")
    if not os.path.isdir(testdata_dir):
        return result

    code_cache: dict = {}

    def codes_of(target_rel_path: str) -> set:
        if target_rel_path in code_cache:
            return code_cache[target_rel_path]
        codes: set = set()
        try:
            wb = load_workbook(os.path.join(repo_dir, target_rel_path), read_only=True, data_only=True)
            name = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
            if name:
                codes = set(_load_sheet_codes(wb, name).keys())
            wb.close()
        except Exception:
            pass
        code_cache[target_rel_path] = codes
        return codes

    for root, _dirs, filenames in os.walk(testdata_dir):
        for fname in filenames:
            if not fname.endswith("DC.xlsx") or fname.startswith("~$"):
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, repo_dir).replace("\\", "/")
            try:
                wb = load_workbook(full_path, read_only=True, data_only=True)
            except Exception:
                continue
            dc_sheet = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
            if dc_sheet is None:
                wb.close()
                continue
            ws = wb[dc_sheet]
            header_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
            rel_cols = [(i, str(h).strip()[1:]) for i, h in enumerate(header_row)
                        if h and str(h).strip().startswith("@")]
            if not rel_cols:
                wb.close()
                continue
            default_id = _default_identifier_for(rel_path, identifiers)
            for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                for col_idx, rel_name in rel_cols:
                    if col_idx >= len(row) or not row[col_idx]:
                        continue
                    cell_value = str(row[col_idx]).strip()
                    if not cell_value:
                        continue
                    targets = by_relationship.get(rel_name.lower(), {})
                    for raw in [c.strip() for c in cell_value.split(",")]:
                        if not raw:
                            continue
                        ident = _identifier_of(raw, default_id)
                        bare = _strip_identifier(raw)
                        target = targets.get(ident)
                        if target is None:
                            issue = f"Unknown identifier '{ident}' for relationship '{rel_name}'"
                        elif not os.path.isfile(os.path.join(repo_dir, target)):
                            issue = f"Target DC file not found: {target}"
                        elif bare not in codes_of(target):
                            issue = f"Code '{bare}' not found in {target}"
                        else:
                            continue
                        result.rows.append([fname, row_idx, f"@{rel_name}", raw, issue])
            wb.close()

    # --- Reference-to-reference: #-columns on reference (non-DC) sheets ---
    # Build a global scope: sheet_name_lower -> {code: row} from all non-DC xlsx in testdata/
    ref_sheet_codes: dict[str, dict[str, int]] = {}
    for root, _dirs, filenames in os.walk(testdata_dir):
        for fname in filenames:
            if not fname.endswith(".xlsx") or fname.endswith("DC.xlsx") or fname.startswith("~$"):
                continue
            full_path = os.path.join(root, fname)
            try:
                wb_ref = load_workbook(full_path, read_only=True, data_only=True)
                for sheet_name in wb_ref.sheetnames:
                    key = _norm_sheet(sheet_name)
                    codes = _load_sheet_codes(wb_ref, sheet_name)
                    if codes and key not in ref_sheet_codes:
                        ref_sheet_codes[key] = codes
                wb_ref.close()
            except Exception:
                pass

    # Validate #-columns on each reference (non-DC) file's sheets
    for root, _dirs, filenames in os.walk(testdata_dir):
        for fname in filenames:
            if not fname.endswith(".xlsx") or fname.endswith("DC.xlsx") or fname.startswith("~$"):
                continue
            full_path = os.path.join(root, fname)
            try:
                wb_ref = load_workbook(full_path, read_only=True, data_only=True)
            except Exception:
                continue
            for sheet_name in wb_ref.sheetnames:
                ws = wb_ref[sheet_name]
                header_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
                r2r_cols = []
                for i, h in enumerate(header_row):
                    if h and str(h).strip().startswith("#"):
                        raw_target = str(h).strip()[1:]
                        # Normalise: strip non-alphanumerics, lowercase (mirrors Java)
                        target_lower = _norm_sheet(raw_target)
                        r2r_cols.append((i, str(h).strip(), raw_target, target_lower))
                if not r2r_cols:
                    continue
                for col_idx, col_header, raw_target, target_lower in r2r_cols:
                    if target_lower not in ref_sheet_codes:
                        result.rows.append([fname, sheet_name, "-", col_header, "-",
                                            f"Referenced sheet '{raw_target}' not found"])
                        continue
                    available = ref_sheet_codes[target_lower]
                    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                        if col_idx >= len(row) or not row[col_idx]:
                            continue
                        cell_value = str(row[col_idx]).strip()
                        if not cell_value:
                            continue
                        for code in [c.strip() for c in cell_value.split(",")]:
                            if code and code not in available:
                                result.rows.append([fname, sheet_name, row_idx, col_header,
                                                    code, f"Code not found in '{raw_target}' sheet"])
            wb_ref.close()

    return result
