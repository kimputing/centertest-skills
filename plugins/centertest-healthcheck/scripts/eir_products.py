"""
Which of the product's coverages the test data exercises, per line of business.

The generated project ships the product model as <Line>_coverage_structure.json next to its
cssids (codeIdentifier, name, covTerms per coverage). A coverage counts as exercised when a row an
enabled DataCombination row reaches (through #Ref, joins and @Rel, as eir_uses follows them)
names it, by name or code. A coverage named only in rows no scenario reaches (a Coverage sheet row
nothing references) is listed apart; so is one named only in hand-written Java. A coverage named only in hand-written Java
is listed apart. A term counts only under an exercised coverage, so a generic term name such
as "Limit" does not make every coverage look tested. Coverage names repeat across sub-lines
(the same exclusion on several parts); each name is counted once per line.

Naming a coverage is a floor for "the suite selects it": a disabled row is skipped, but a row
in a workbook no suite runs still counts (the Test data panel lists those workbooks).
"""

from __future__ import annotations

import glob
import json
import os
import re

import xlsx_read

_DISABLED = {"true", "yes", "y", "x", "1"}
_LITERAL = re.compile(r'"((?:[^"\\]|\\.){3,})"')


def structure_files(cssids_dir: str | None) -> list[str]:
    """The *_coverage_structure.json files beside the cssids (GW10: the cssids folder's parent)."""
    if not cssids_dir:
        return []
    for folder in (cssids_dir, os.path.dirname(os.path.abspath(cssids_dir))):
        files = sorted(glob.glob(os.path.join(folder, "*_coverage_structure.json")))
        if files:
            return files
    return []


def data_names(repo_dir: str) -> set[str]:
    """Lower-cased values and plain headers of every enabled row in the testdata workbooks."""
    names = set()
    for path in sorted(glob.glob(os.path.join(repo_dir, "testdata", "**", "*.xlsx"), recursive=True)):
        if os.path.basename(path).startswith("~$"):
            continue
        try:
            sheets = xlsx_read.read_workbook(path)
        except (xlsx_read.WorkbookError, OSError, KeyError, ValueError):
            continue
        for rows in sheets.values():
            for row in rows:
                if str(row.get("Disabled") or "").strip().lower() in _DISABLED:
                    continue
                for header, value in row.items():
                    header = str(header).strip()
                    if header and header[0] not in "#@":
                        names.add(header.lower())
                    if isinstance(value, str) and value.strip():
                        names.add(value.strip().lower())
    return names


def java_names(repo_dir: str, source_root: str = "src") -> set[str]:
    """Lower-cased string literals of the hand-written Java (generated code excluded)."""
    names = set()
    for path in glob.glob(os.path.join(repo_dir, source_root, "**", "*.java"), recursive=True):
        parts = path.replace("\\", "/").lower().split("/")
        if "generated" in parts or "datadriven" in parts:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                names.update(m.strip().lower() for m in _LITERAL.findall(fh.read()))
        except OSError:
            continue
    return names


def _named(entry: dict, names: set[str]) -> bool:
    return any(str(entry.get(k) or "").strip().lower() in names for k in ("name", "codeIdentifier"))


def product_coverage(repo_dir: str, cssids_dir: str | None, source_root: str = "src") -> list[dict] | None:
    """Per line: coverages (unique by name) named in test data / only in Java / not at all, and the
    terms of the named ones that are set. None when the generated project has no product model."""
    files = structure_files(cssids_dir)
    if not files:
        return None
    data, java = data_names(repo_dir), java_names(repo_dir, source_root)
    try:
        from eir_uses import reached_values
        exercised = reached_values(repo_dir)
    except Exception:  # no openpyxl or an unreadable hierarchy: fall back to "named anywhere"
        exercised = data
    lines = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                coverages = json.load(fh)
        except (OSError, ValueError):
            continue
        by_name: dict[str, list[dict]] = {}
        for c in coverages if isinstance(coverages, list) else []:
            if isinstance(c, dict) and c.get("name"):
                by_name.setdefault(c["name"].strip(), []).append(c)
        named, unused, in_java, missing = [], [], [], []
        terms_total = terms_set = 0
        for name, entries in sorted(by_name.items(), key=lambda kv: kv[0].lower()):
            if any(_named(c, exercised) for c in entries):
                terms = {t["name"].strip(): t for c in entries for t in c.get("covTerms") or [] if t.get("name")}
                done = sorted(n for n, t in terms.items() if _named(t, exercised))
                terms_total += len(terms)
                terms_set += len(done)
                named.append({"name": name, "code": entries[0].get("codeIdentifier"),
                              "terms": len(terms), "terms_set": done})
            elif any(_named(c, data) for c in entries):
                unused.append(name)
            elif any(_named(c, java) for c in entries):
                in_java.append(name)
            else:
                missing.append(name)
        line = os.path.basename(path)[:-len("_coverage_structure.json")]
        lines.append({"line": line, "coverages": len(by_name), "named": named, "unused": unused, "java": in_java,
                      "missing": missing, "terms": terms_total, "terms_set": terms_set})
    return lines


def print_products(lines: list[dict]) -> None:
    print("  PRODUCT COVERAGES THE SCENARIOS SELECT (per line; enabled rows and what they reference)")
    for l in lines:
        extra = (f" +{len(l['unused'])} in rows no scenario reaches" if l.get("unused") else "") \
            + (f" +{len(l['java'])} only in Java" if l["java"] else "")
        terms = f"   terms {l['terms_set']}/{l['terms']}" if l["terms"] else ""
        print(f"  {l['line']:<24} coverages {len(l['named']):>4}/{l['coverages']:<4}{extra}{terms}")


def excel_rows(lines: list[dict]) -> list[list]:
    """Line, coverage, status, terms set — every coverage of every line."""
    rows = []
    for l in lines:
        rows += [[l["line"], c["name"], "Selected by a scenario", f"{len(c['terms_set'])}/{c['terms']}",
                  ", ".join(c["terms_set"])] for c in l["named"]]
        rows += [[l["line"], n, "In a data row no scenario reaches", "", ""] for n in l.get("unused", [])]
        rows += [[l["line"], n, "Only in Java", "", ""] for n in l["java"]]
        rows += [[l["line"], n, "Not named", "", ""] for n in l["missing"]]
    return rows
