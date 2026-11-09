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

Option terms (a term with covTermChoices: a limit, a deductible) list which of their options the
scenarios set (eir_uses.term_values: Coverage / CovTerm / CovtermValue rows they reach), matched by
name or code ignoring $, commas and spaces (a cell may list several options, comma-separated; a percent cell read as 0.1 is "10%"); a value that is none of the options is listed as
"not an option" in the product model -- the dropdown offers no such value.

Naming a coverage is a floor for "the suite selects it": a disabled row is skipped, but a row
in a workbook no suite runs still counts (the Test data panel lists those workbooks).
"""

from __future__ import annotations

import glob
import json
import os
import re

import xlsx_read

_DISABLED = {"true", "t", "yes", "y", "checked", "1"}  # CenterTest's TRUEOPTIONS (BaseTestData.isDisabled)
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


def _squeeze(value: str) -> str:
    """'$1,000 ' -> '1000': how a term option and a data cell are compared."""
    return re.sub(r"[\s$,]", "", str(value or "").lower())


def _keys_of(value: str) -> list[str]:
    """How a data cell may name an option: as written, or a percent cell (stored 0.1, shown "10%")."""
    keys = [_squeeze(value)]
    try:
        number = float(value)
    except ValueError:
        return keys
    if 0 < number <= 1:
        keys.append(_squeeze(f"{number * 100:g}%"))
    return keys


def _offered(models: list) -> dict[tuple, set]:
    """{(coverage name, term name) lower-cased: squeezed option names and codes} over every line: a coverage
    name several lines share (Sewer Back-Up on HOP and HO) offers what any of them offers."""
    out: dict[tuple, set] = {}
    for coverages in models:
        for c in coverages:
            for t in c.get("covTerms") or []:
                key = (str(c.get("name") or "").strip().lower(), str(t.get("name") or "").strip().lower())
                out.setdefault(key, set()).update(_squeeze(k) for ch in t.get("covTermChoices") or []
                                                  for k in (ch.get("name"), ch.get("codeIdentifier")) if k)
    return out


def option_index(cssids_dir: str | None) -> dict[tuple, list]:
    """{(coverage, term) lower-cased, by name or code: [(line, coverage name, term name, {squeezed key: option})]}
    over every line's option terms: what a Coverage / CovTerm / CovtermValue row can select."""
    index: dict[tuple, list] = {}
    for path in structure_files(cssids_dir):
        line = os.path.basename(path)[:-len("_coverage_structure.json")]
        try:
            with open(path, encoding="utf-8") as fh:
                coverages = json.load(fh)
        except (OSError, ValueError):
            continue
        for c in coverages if isinstance(coverages, list) else []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            for t in c.get("covTerms") or []:
                choices = [ch for ch in t.get("covTermChoices") or [] if ch.get("name")]
                if not choices or not t.get("name"):
                    continue
                by_key = {}
                for ch in choices:
                    for k in (ch.get("name"), ch.get("codeIdentifier")):
                        if k:
                            by_key.setdefault(_squeeze(k), ch["name"].strip())
                entry = (line, c["name"].strip(), t["name"].strip(), by_key)
                for ck in {c["name"].strip().lower(), str(c.get("codeIdentifier") or "").strip().lower()} - {""}:
                    for tk in {t["name"].strip().lower(), str(t.get("codeIdentifier") or "").strip().lower()} - {""}:
                        index.setdefault((ck, tk), []).append(entry)
    return index


def options_of(index: dict, coverage: str, term: str, value: str) -> set[tuple]:
    """("option", line, "Coverage / Term = Option") items a cell value selects (whole cell or comma list)."""
    out = set()
    for line, cov, term_name, by_key in index.get((coverage.lower(), term.lower()), ()):
        match = lambda text: next((by_key[k] for k in _keys_of(text) if k in by_key), None)
        parts = [value] if match(value) else [p for p in value.split(",") if p.strip()]
        if parts and all(match(p) for p in parts):
            out |= {("option", line, f"{cov} / {term_name} = {match(p)}") for p in parts}
    return out


def term_options(entries: list[dict], set_values: dict, offered: dict | None = None) -> list[dict]:
    """[{term, options, chosen, not_offered}] for the option terms of one coverage that the scenarios set.
    A value no line offers (`offered`, from _offered) is not_offered."""
    keys = {str(c.get(k) or "").strip().lower() for c in entries for k in ("name", "codeIdentifier")} - {""}
    out = {}
    for c in entries:
        for t in c.get("covTerms") or []:
            choices = [ch for ch in t.get("covTermChoices") or [] if ch.get("name")]
            name = str(t.get("name") or "").strip()
            if not choices or not name or name in out:
                continue
            tkeys = {name.lower(), str(t.get("codeIdentifier") or "").strip().lower()} - {""}
            values = set().union(*(v for (cov, term), v in set_values.items() if cov in keys and term in tkeys))
            if not values:
                continue
            by_key = {}
            for ch in choices:
                for k in (ch.get("name"), ch.get("codeIdentifier")):
                    if k:
                        by_key.setdefault(_squeeze(k), ch["name"].strip())
            options = list(dict.fromkeys(ch["name"].strip() for ch in choices))
            chosen, not_offered = set(), []
            for v in values:
                # the whole cell ("$1,000,000"), else a list of options ("No Coverage, Split Limit")
                match = lambda text: next((by_key[k] for k in _keys_of(text) if k in by_key), None)
                parts = [v] if match(v) else [p for p in v.split(",") if p.strip()]
                anywhere = (offered or {}).get((str(entries[0].get("name") or "").strip().lower(), name.lower()), set())
                known = lambda text: any(k in anywhere for k in _keys_of(text))
                if all(match(p) for p in parts):
                    chosen |= {match(p) for p in parts}
                elif not (known(v) or all(known(p) for p in v.split(",") if p.strip())):
                    not_offered.append(v)
            out[name] = {"term": name, "options": options, "chosen": [o for o in options if o in chosen],
                         "not_offered": sorted(not_offered)}
    return [out[n] for n in sorted(out, key=str.lower)]


def _named(entry: dict, names: set[str]) -> bool:
    return any(str(entry.get(k) or "").strip().lower() in names for k in ("name", "codeIdentifier"))


def product_coverage(repo_dir: str, cssids_dir: str | None, source_root: str = "src") -> list[dict] | None:
    """Per line: coverages (unique by name) named in test data / only in Java / not at all, and the
    terms of the named ones that are set. None when the generated project has no product model."""
    files = structure_files(cssids_dir)
    if not files:
        return None
    data, java = data_names(repo_dir), java_names(repo_dir, source_root)
    in_suites = None
    by_value, readers, set_values = {}, {}, {}
    try:
        from eir_uses import reached_values, rows_by_value, suite_rows, term_values
        set_values = term_values(repo_dir)
        exercised = reached_values(repo_dir, coverage_only=True)
        by_value = rows_by_value(repo_dir, coverage_only=True)
        # tests that read each workbook: @DataDriven, a DDTHelper getter or the DC class (rule 14003's readers)
        from eir_impact import _is_test, _java_sources
        from rules.rule_ddt import workbook_users
        sources = _java_sources(repo_dir, source_root)
        for dc, classes in workbook_users(repo_dir, source_root).items():
            readers[dc] = {c for c in classes if c in sources and _is_test(sources[c][1])}
        rows = suite_rows(repo_dir, source_root)
        if rows is not None:
            in_suites = reached_values(repo_dir, rows, coverage_only=True) if rows else set()
    except Exception:  # no openpyxl or an unreadable hierarchy: fall back to "named anywhere"
        exercised = data
    lines = []
    models = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                coverages = json.load(fh)
        except (OSError, ValueError):
            continue
        models.append((path, [c for c in coverages if isinstance(c, dict)] if isinstance(coverages, list) else []))
    offered = _offered([coverages for _path, coverages in models])
    for path, coverages in models:
        by_name: dict[str, list[dict]] = {}
        for c in coverages:
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
                rows = set().union(*(by_value.get(str(c.get(k) or "").strip().lower(), set())
                                     for c in entries for k in ("name", "codeIdentifier")))
                tests: dict[str, int] = {}
                for _kind, dc, _code in rows:
                    for test in readers.get(dc, ()):
                        tests[test] = tests.get(test, 0) + 1
                named.append({"name": name, "code": entries[0].get("codeIdentifier"),
                              "terms": len(terms), "terms_set": done, "tests": tests,
                              "options": term_options(entries, set_values, offered)})
            elif any(_named(c, data) for c in entries):
                unused.append(name)
            elif any(_named(c, java) for c in entries):
                in_java.append(name)
            else:
                missing.append(name)
        line = os.path.basename(path)[:-len("_coverage_structure.json")]
        outside = None if in_suites is None else sorted(
            c["name"] for c in named if not any(_named(e, in_suites) for e in by_name[c["name"]]))
        lines.append({"line": line, "coverages": len(by_name), "named": named, "unused": unused, "java": in_java,
                      "outside_suites": outside,
                      "missing": missing, "terms": terms_total, "terms_set": terms_set,
                      "option_terms": sum(len(c["options"]) for c in named),
                      "options_chosen": sum(len(o["chosen"]) for c in named for o in c["options"]),
                      "options_total": sum(len(o["options"]) for c in named for o in c["options"]),
                      "not_offered": [{"coverage": c["name"], "term": o["term"], "value": v, "options": o["options"]}
                                      for c in named for o in c["options"] for v in o["not_offered"]]})
    return lines


def print_products(lines: list[dict]) -> None:
    print("  PRODUCT COVERAGES THE SCENARIOS SELECT (per line; enabled rows and what they reference)")
    for l in lines:
        extra = (f" ({len(l['outside_suites'])} only outside every suite)" if l.get("outside_suites") else "") \
            + (f" +{len(l['unused'])} in rows no scenario reaches" if l.get("unused") else "") \
            + (f" +{len(l['java'])} only in Java" if l["java"] else "")
        terms = f"   terms {l['terms_set']}/{l['terms']}" if l["terms"] else ""
        options = (f"   options {l['options_chosen']}/{l['options_total']} of {l['option_terms']} option terms"
                   if l.get("option_terms") else "")
        print(f"  {l['line']:<24} coverages {len(l['named']):>4}/{l['coverages']:<4}{extra}{terms}{options}")
    off = [(l["line"], n) for l in lines for n in l.get("not_offered", [])]
    if off:
        print("  Term values that are not an option in the product model:")
        for line, n in off:
            shown = ", ".join(n["options"][:8]) + (", ..." if len(n["options"]) > 8 else "")
            print(f"    {line}: {n['coverage']} / {n['term']} = {n['value']}   (options: {shown})")


def _tests(c: dict) -> str:
    """'GL_SubmissionTest (2 rows), GL_PolicyChangeTest (1 row)': the tests whose scenarios select it."""
    tests = sorted((c.get("tests") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{t} ({n} row{'s' if n != 1 else ''})" for t, n in tests)


def options_text(c: dict) -> str:
    """'Medical Limit: 15,000 (1 of 5); Deductible: 9999 NOT AN OPTION (0 of 6)'."""
    return "; ".join(f"{o['term']}: " + ", ".join(o["chosen"] + [f"{v} NOT AN OPTION" for v in o["not_offered"]])
                     + f" ({len(o['chosen'])} of {len(o['options'])})" for o in c.get("options") or [])


def excel_rows(lines: list[dict]) -> list[list]:
    """Line, coverage, status, terms set, term options chosen — every coverage of every line."""
    rows = []
    for l in lines:
        outside = set(l.get("outside_suites") or [])
        rows += [[l["line"], c["name"],
                  "Selected only by scenarios no suite runs" if c["name"] in outside else "Selected by a scenario",
                  f"{len(c['terms_set'])}/{c['terms']}", ", ".join(c["terms_set"]), _tests(c), options_text(c)]
                 for c in l["named"]]
        rows += [[l["line"], n, "In a data row no scenario reaches", "", "", "", ""] for n in l.get("unused", [])]
        rows += [[l["line"], n, "Only in Java", "", "", "", ""] for n in l["java"]]
        rows += [[l["line"], n, "Not named", "", "", "", ""] for n in l["missing"]]
    return rows
