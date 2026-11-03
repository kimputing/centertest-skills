#!/usr/bin/env python3
"""Read .xlsx workbooks with the standard library only (zipfile + ElementTree).

Library: read_workbook(path, sheet, max_rows) -> {sheet: [{header: value}]}, headers(path, sheet).
CLI:     xlsx_read.py <path> [--max-rows N] [--sheet REGEX]   (prints sheet names, header row, first rows)
"""
import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DIGITS = re.compile(r"\d")


class WorkbookError(Exception):
    """The file is not a readable xlsx workbook."""


def text_of(node) -> str:
    """Concatenated text of all <t> descendants (shared and inline strings)."""
    return "".join(t.text or "" for t in node.iter("{%s}t" % NS["m"]))


def _part(z: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        raise WorkbookError(f"workbook part missing: {name}")
    except ET.ParseError as error:
        raise WorkbookError(f"workbook part unreadable: {name}: {error}")


def _cell_value(cell, shared):
    kind, v = cell.get("t"), cell.find("m:v", NS)
    if kind == "inlineStr":
        return text_of(cell)
    if v is None or v.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(v.text)]
        except (ValueError, IndexError):
            raise WorkbookError(f"bad shared string index: {v.text}")
    return v.text


def _sheets(path: str, pattern: str):
    """Yield (sheet name, rows) for sheets whose name matches; a row is {column letter: non-empty value}."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise WorkbookError(f"not a readable xlsx: {path}: {error}")
    with z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = [text_of(si) for si in _part(z, "xl/sharedStrings.xml").findall("m:si", NS)]
        rels = {r.get("Id"): r.get("Target") for r in _part(z, "xl/_rels/workbook.xml.rels")}
        sheets = _part(z, "xl/workbook.xml").find("m:sheets", NS)
        for sheet in (sheets if sheets is not None else []):
            name = sheet.get("name") or ""  # a <sheet> without a name must not stop the scan
            if not re.search(pattern, name):
                continue
            target = rels.get(sheet.get(REL))
            if target is None:
                raise WorkbookError(f"sheet {name} has no relationship target")
            data = _part(z, "xl/" + re.sub(r"^/?xl/", "", target)).find("m:sheetData", NS)
            rows = []
            for row in (data.findall("m:row", NS) if data is not None else []):
                cells = {}
                for c in row.findall("m:c", NS):
                    value = _cell_value(c, shared)
                    if value != "":
                        cells[DIGITS.sub("", c.get("r", ""))] = value
                rows.append(cells)
            yield name, rows


def read_workbook(path: str, sheet: str = ".*", max_rows=None) -> dict:
    """Per sheet name, the data rows (header row excluded) as {header: value}; empty cells omitted."""
    result = {}
    for name, rows in _sheets(path, sheet):
        head = rows[0] if rows else {}
        data = rows[1:] if max_rows is None else rows[1:1 + max_rows]
        result[name] = [{head[col]: value for col, value in row.items() if col in head} for row in data]
    return result


def headers(path: str, sheet: str = ".*") -> dict:
    """Per sheet name, the header row values in column order."""
    return {name: list(rows[0].values()) if rows else [] for name, rows in _sheets(path, sheet)}


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Print sheet names, header row and first rows of an .xlsx")
    ap.add_argument("path")
    ap.add_argument("--max-rows", type=int, default=6)
    ap.add_argument("--sheet", default=".*")
    args = ap.parse_args(argv)
    try:
        for name, rows in _sheets(args.path, args.sheet):
            print("--- [%s]  data rows: %d" % (name, max(0, len(rows) - 1)))
            for row in rows[: args.max_rows]:
                print("   " + " | ".join("%s=%s" % item for item in row.items()))
    except WorkbookError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
