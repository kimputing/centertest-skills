#!/usr/bin/env python3
"""Analyze CenterTest Data-Driven Testing structure and generate an Excel report.

Scans testdata/ for DC files, maps relationships between DataCombination files
and their referenced Data files, tracks code usage, and maps test classes to
datasources.

Usage:
    ddt-analyzer.py                         # analyze and generate report
    ddt-analyzer.py --exclude path1,path2   # exclude specific paths

Output: DDT_Analysis_<timestamp>.xlsx in the project's results/ directory.

Report sheets:
  1. DataCombination_References  — which Data files each DC file references
  2. ReferencedFiles_DataCombination — which DC files reference each Data file
  3. Codes_Usage — aggregated code usage counts across all DC files
  4. Codes_Usage_Detail — per-DC-file code usage breakdown
  5. DataCombination_Tests — which test classes use each DC file as datasource

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/ddt-analyzer/scripts/ddt-analyzer.py
"""

import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

# Add script directory to path for shared config
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ddt-tools", "scripts"))

try:
    from ddt_config import get_project_dir
except ImportError:
    # Fallback: inline config if ddt-tools not installed
    def get_project_dir():
        path = os.environ.get("CENTERTEST_PROJECT_DIR")
        if path:
            return path
        config_file = os.path.expanduser("~/.centertest/ddt-tools.json")
        if os.path.isfile(config_file):
            with open(config_file) as f:
                config = json.load(f)
            if config.get("project_dir"):
                return config["project_dir"]
        print("No CenterTest project path configured.")
        print("Enter the path to the CenterTest project root:")
        path = input("> ").strip()
        if not path or not os.path.isdir(os.path.expanduser(path)):
            print("Error: invalid path")
            sys.exit(1)
        return os.path.expanduser(path)

try:
    from openpyxl import load_workbook
    from openpyxl import Workbook
except ImportError:
    print("ERROR: openpyxl is required. Install with: pip install openpyxl", file=sys.stderr)
    sys.exit(1)


def format_value(val):
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val)


class SheetData:
    def __init__(self, name, codes=None):
        self.name = name
        self.codes = codes or set()


class ReferencedFile:
    def __init__(self, path):
        self.path = path
        self.sheets = []  # list of SheetData


class DataCombinationFile:
    def __init__(self, path):
        self.path = path
        self.referenced_files = []  # list of ReferencedFile
        self.references = {}  # {sheet_name: [code_values_from_dc_rows]}


def find_dc_files(exclude_paths=None):
    """Find all xlsx files with datacombination and references sheets."""
    exclude_paths = exclude_paths or []
    files = glob.glob("testdata/**/*.xlsx", recursive=True) + glob.glob("testdata/*.xlsx")
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    files = sorted(set(files))

    dc_files = []
    for f in files:
        if any(f.startswith(ep) for ep in exclude_paths):
            continue
        try:
            wb = load_workbook(f, read_only=True, data_only=True)
            sheet_names_lower = [s.lower() for s in wb.sheetnames]
            has_dc = "datacombination" in sheet_names_lower
            has_refs = "references" in sheet_names_lower
            wb.close()
            if has_dc and has_refs:
                dc_files.append(f)
        except Exception:
            continue

    return dc_files


def parse_dc_file(dc_path):
    """Parse a DataCombination file and return a DataCombinationFile object."""
    dc = DataCombinationFile(dc_path)

    wb = load_workbook(dc_path, read_only=True, data_only=True)

    # Find sheets case-insensitively
    dc_sheet_name = None
    ref_sheet_name = None
    for name in wb.sheetnames:
        if name.lower() == "datacombination":
            dc_sheet_name = name
        if name.lower() == "references":
            ref_sheet_name = name

    # Parse DataCombination sheet — extract # columns and their values
    if dc_sheet_name:
        ws = wb[dc_sheet_name]
        headers = None
        ref_columns = {}  # col_index -> sheet_name (without #)
        for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
            values = [format_value(c) for c in row]
            if all(v == "" for v in values):
                continue
            if headers is None:
                headers = values
                for i, h in enumerate(headers):
                    if h.startswith("#"):
                        ref_columns[i] = h[1:]
                        dc.references[h[1:]] = []
                continue
            for col_idx, sheet_name in ref_columns.items():
                val = values[col_idx] if col_idx < len(values) else ""
                if val:
                    # Handle comma-separated codes
                    for code in val.split(","):
                        code = code.strip()
                        if code:
                            dc.references[sheet_name].append(code)

    # Parse References sheet — find external data files
    if ref_sheet_name:
        ws = wb[ref_sheet_name]
        headers = None
        for row in ws.iter_rows(values_only=True):
            values = [format_value(c) for c in row]
            if all(v == "" for v in values):
                continue
            if headers is None:
                headers = [v.lower().strip() for v in values]
                continue
            row_dict = dict(zip(headers, values))
            location = row_dict.get("location", "")
            if location:
                # Resolve path relative to DC file
                ref_path = os.path.normpath(os.path.join(os.path.dirname(dc_path), location))
                if not os.path.isfile(ref_path):
                    ref_path = location  # Try as-is from project root
                if os.path.isfile(ref_path):
                    ref_file = parse_referenced_file(ref_path)
                    dc.referenced_files.append(ref_file)

    wb.close()
    return dc


_ref_file_cache = {}


def parse_referenced_file(path):
    """Parse a referenced data file and extract codes per sheet."""
    if path in _ref_file_cache:
        return _ref_file_cache[path]

    ref = ReferencedFile(path)
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            headers = None
            codes = set()
            for row in ws.iter_rows(values_only=True):
                values = [format_value(c) for c in row]
                if all(v == "" for v in values):
                    continue
                if headers is None:
                    headers = [v.lower() for v in values]
                    continue
                row_dict = dict(zip(headers, values))
                code = row_dict.get("code", "")
                if code:
                    codes.add(code)
            if codes:
                ref.sheets.append(SheetData(sheet_name, codes))
        wb.close()
    except Exception:
        pass

    _ref_file_cache[path] = ref
    return ref


def find_test_datasource_mappings():
    """Scan Java source for @DataDriven(datasource = "...") annotations and map to test classes."""
    test_map = defaultdict(list)  # datasource -> [test_class#method]

    java_files = glob.glob("src/**/*.java", recursive=True)
    # Pattern for @DataDriven annotation with datasource
    dd_pattern = re.compile(r'@DataDriven\s*\(\s*datasource\s*=\s*"([^"]+)"')
    # Pattern for class name
    class_pattern = re.compile(r'(?:public\s+)?(?:final\s+)?class\s+(\w+)')
    # Pattern for method with @DataDriven or @CenterTestCase above it
    method_pattern = re.compile(r'(?:public|protected|private)?\s*(?:void|[A-Za-z]\w*)\s+(\w+)\s*\(')

    for java_file in java_files:
        try:
            with open(java_file) as f:
                content = f.read()
        except Exception:
            continue

        # Find class name
        class_match = class_pattern.search(content)
        if not class_match:
            continue
        class_name = class_match.group(1)

        # Find package
        pkg_match = re.search(r'package\s+([\w.]+)\s*;', content)
        fqcn = f"{pkg_match.group(1)}.{class_name}" if pkg_match else class_name

        # Find all @DataDriven annotations with their associated methods
        # Look for @DataDriven followed by a method definition
        for dd_match in dd_pattern.finditer(content):
            datasource = dd_match.group(1)
            # Find the next method after this annotation
            remaining = content[dd_match.end():]
            method_match = method_pattern.search(remaining)
            if method_match:
                method_name = method_match.group(1)
                test_map[datasource].append(f"{fqcn}#{method_name}")

    return dict(test_map)


def generate_report(dc_files_data, test_map):
    """Generate the Excel analysis report."""
    wb = Workbook()

    # Sheet 1: DataCombination_References
    ws1 = wb.active
    ws1.title = "DataCombination_References"

    all_ref_files = set()
    for dc in dc_files_data:
        for ref in dc.referenced_files:
            all_ref_files.add(ref.path)
    all_ref_files = sorted(all_ref_files)

    # Header
    ws1.append(["Data Combination File"] + [os.path.basename(r) for r in all_ref_files])
    ref_index = {r: i + 1 for i, r in enumerate(all_ref_files)}

    for dc in dc_files_data:
        row = [""] * (len(all_ref_files) + 1)
        row[0] = dc.path
        for ref in dc.referenced_files:
            idx = ref_index.get(ref.path)
            if idx:
                row[idx] = "X"
        ws1.append(row)

    # Sheet 2: ReferencedFiles_DataCombination
    ws2 = wb.create_sheet("ReferencedFiles_DataCombination")

    ref_to_dc = defaultdict(list)
    for dc in dc_files_data:
        for ref in dc.referenced_files:
            ref_to_dc[ref.path].append(dc.path)

    all_dc_paths = sorted(set(dc.path for dc in dc_files_data))
    ws2.append(["Referenced File"] + [os.path.basename(d) for d in all_dc_paths])
    dc_index = {d: i + 1 for i, d in enumerate(all_dc_paths)}

    for ref_path in sorted(ref_to_dc.keys()):
        row = [""] * (len(all_dc_paths) + 1)
        row[0] = ref_path
        for dc_path in ref_to_dc[ref_path]:
            idx = dc_index.get(dc_path)
            if idx:
                row[idx] = "X"
        ws2.append(row)

    # Sheet 3: Codes_Usage (aggregated)
    ws3 = wb.create_sheet("Codes_Usage")
    ws3.append(["Referenced File", "Sheet", "Code", "Count"])

    for ref_path, ref_file in sorted(_ref_file_cache.items()):
        for sheet in ref_file.sheets:
            for code in sorted(sheet.codes):
                count = 0
                for dc in dc_files_data:
                    if any(r.path == ref_path for r in dc.referenced_files):
                        code_list = dc.references.get(sheet.name, [])
                        count += sum(1 for c in code_list if c.lower() == code.lower())
                ws3.append([ref_path, sheet.name, code, count])

    # Sheet 4: Codes_Usage_Detail
    ws4 = wb.create_sheet("Codes_Usage_Detail")
    ws4.append(["Referenced File", "Sheet", "Code", "Data Combination File"])

    for ref_path, ref_file in sorted(_ref_file_cache.items()):
        for sheet in ref_file.sheets:
            for code in sorted(sheet.codes):
                for dc in dc_files_data:
                    if any(r.path == ref_path for r in dc.referenced_files):
                        code_list = dc.references.get(sheet.name, [])
                        if any(c.lower() == code.lower() for c in code_list):
                            ws4.append([ref_path, sheet.name, code, dc.path])

    # Sheet 5: DataCombination_Tests
    ws5 = wb.create_sheet("DataCombination_Tests")
    ws5.append(["Data Combination File", "Test"])

    for datasource, tests in sorted(test_map.items()):
        for test in sorted(tests):
            ws5.append([datasource, test])

    # Save
    os.makedirs("results", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"results/DDT_Analysis_{timestamp}.xlsx"
    wb.save(output_path)
    return output_path


def main():
    project_dir = get_project_dir()
    os.chdir(project_dir)

    # Parse args
    exclude_paths = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--exclude" and i + 1 < len(args):
            exclude_paths = [p.strip() for p in args[i + 1].split(",")]
            i += 2
        else:
            i += 1

    print("DDT Analyzer")
    print("=" * 50)

    # Step 1: Find DC files
    print("\nScanning for DataCombination files...")
    dc_paths = find_dc_files(exclude_paths)
    print(f"  Found {len(dc_paths)} DC files")

    # Step 2: Parse each DC file
    print("\nParsing DC files and referenced data...")
    dc_files_data = []
    for dc_path in dc_paths:
        try:
            dc = parse_dc_file(dc_path)
            dc_files_data.append(dc)
            ref_count = len(dc.referenced_files)
            code_count = sum(len(codes) for codes in dc.references.values())
            print(f"  {dc_path}: {ref_count} refs, {code_count} code usages")
        except Exception as e:
            print(f"  {dc_path}: ERROR — {e}")

    print(f"\n  Total referenced data files: {len(_ref_file_cache)}")

    # Step 3: Find test-to-datasource mappings
    print("\nScanning Java source for @DataDriven tests...")
    test_map = find_test_datasource_mappings()
    total_tests = sum(len(v) for v in test_map.values())
    print(f"  Found {total_tests} test methods across {len(test_map)} datasources")

    # Step 4: Generate report
    print("\nGenerating report...")
    output_path = generate_report(dc_files_data, test_map)
    print(f"  Report saved to: {output_path}")

    # Step 5: Print summary
    print(f"\n{'=' * 50}")
    print("Summary:")
    print(f"  DC files:          {len(dc_files_data)}")
    print(f"  Referenced files:  {len(_ref_file_cache)}")
    print(f"  Test methods:      {total_tests}")
    print(f"  Report:            {output_path}")


if __name__ == "__main__":
    main()
