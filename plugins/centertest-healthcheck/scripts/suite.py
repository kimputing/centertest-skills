#!/usr/bin/env python3
"""Build and edit CenterTest suites (CenterTestSuiteList.json) from the project's own tests.

Commands (run in the project, or pass --project):
    suite.py scan                              tests -> methods -> DataCombination codes
    suite.py list                              suites, their kind and the scenarios each runs
    suite.py show NAME                         a suite resolved; entries that match nothing
    suite.py pick [selectors]                  preview a selection (nothing written)
    suite.py create NAME [selectors]           new list suite from a selection
    suite.py add NAME [selectors]              add the selection to a suite
    suite.py remove NAME [selectors]           remove the selection from a suite
    suite.py delete NAME                       delete a suite
    suite.py rename OLD NEW                    rename (composite suites that name it follow)
    suite.py set NAME --entries-file F         replace a suite's List with entries from a file ("-" = stdin)
    suite.py uncovered                         scenarios that no suite runs
    suite.py doctor [NAME]                     entries that run nothing, why, and what they probably meant
    suite.py replace NAME --old E --new E      replace one entry (written exactly as in the file)
    suite.py drop NAME --entry E               drop entries written exactly so (e.g. a dead one)

Selectors (case-insensitive regular expressions, searched -- "Submission" matches WC_SubmissionTest):
    --class R  --method R  --code R  --desc R  --package R   (combine: all must match)
    --entry "Class method code"   a suite entry, read exactly as CenterTest reads it
    --include-disabled            also select DataCombination rows marked Disabled

create/add/remove/delete/rename/set only print the change unless --write is given. Writing keeps
the file's indentation and line endings. Entries are read the way CenterTest reads them: each
space-separated part is a case-insensitive regular expression matched against the whole class,
method or code. Entries this tool writes are compact -- "Class" for a whole class, "Class method"
for a whole method, "Class method (code1|code2)" for some rows -- and entries it did not touch are
kept exactly as written (patterns such as "NewSubmissionTest run tx_.*" stay patterns).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_read import WorkbookError, read_workbook  # noqa: E402

SUITE_FILE = "CenterTestSuiteList.json"
_TRUTHY = {"true", "t", "yes", "y", "checked", "1"}  # CenterTest's TRUEOPTIONS (BaseTestData.isDisabled)
_REGEX_META = set(".^$*+?()[]{}|\\")


# ---------------------------------------------------------------------------
# Scanning the project
# ---------------------------------------------------------------------------

def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


_DATASOURCE = re.compile(r"@DataDriven\s*\([^)]*?datasource\s*=\s*\"([^\"]+)\"")


def parse_test(source: str) -> dict | None:
    """A @CenterTest class -> {class, package, methods: [{name, datasource}]}; None for other classes."""
    src = _strip_comments(source)
    cls = re.search(r"@CenterTest\b(?!Case)[\s\S]*?\bclass\s+(\w+)", src)
    if not cls:
        return None
    pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", src, re.M)
    class_ds = _DATASOURCE.search(src[:cls.end()])
    methods = []
    for m in re.finditer(r"\bvoid\s+(\w+)\s*\(", src):
        start = max(src.rfind(";", 0, m.start()), src.rfind("}", 0, m.start()), src.rfind("{", 0, m.start()))
        block = src[start + 1:m.start()]
        if "@CenterTestCase" not in block:
            continue
        ds = _DATASOURCE.search(block)
        methods.append({"name": m.group(1), "datasource": ds.group(1) if ds else (class_ds.group(1) if class_ds else None)})
    if not methods:
        return None
    return {"class": cls.group(1), "package": pkg.group(1) if pkg else "", "methods": methods}


def _codes(path: str) -> list[dict]:
    """[{code, desc, disabled}] from a workbook's DataCombination sheet, in sheet order, unique."""
    sheets = read_workbook(path, "(?i)^datacombination$")
    rows = next(iter(sheets.values()), None)
    if rows is None:
        raise WorkbookError("no DataCombination sheet")
    out, seen = [], set()
    for row in rows:
        low = {str(k).strip().lower(): v for k, v in row.items()}
        code = str(low.get("code", "") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "desc": str(low.get("description", "") or "").strip(),
                    "disabled": str(low.get("disabled", "") or "").strip().lower() in _TRUTHY})
    return out


def scan(project: str, source_root: str = "src/main/java") -> list[dict]:
    """[{class, package, path, methods: [{name, datasource, codes, error}]}] sorted by package, class."""
    tests, cache = [], {}
    for root, dirs, files in os.walk(os.path.join(project, source_root)):
        dirs[:] = [d for d in dirs if d not in ("datadriven", "generated", "build")]
        for name in sorted(files):
            if not name.endswith(".java"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8", errors="replace") as fh:
                t = parse_test(fh.read())
            if not t:
                continue
            t["path"] = os.path.relpath(path, project).replace("\\", "/")
            for m in t["methods"]:
                m["codes"], m["error"] = [], None
                if not m["datasource"]:
                    continue
                if m["datasource"] not in cache:
                    try:
                        cache[m["datasource"]] = _codes(os.path.join(project, m["datasource"]))
                    except (OSError, WorkbookError) as e:
                        cache[m["datasource"]] = e
                got = cache[m["datasource"]]
                if isinstance(got, Exception):
                    m["error"] = f"{m['datasource']}: {got}"
                else:
                    m["codes"] = got
            tests.append(t)
    tests.sort(key=lambda t: (t["package"], t["class"]))
    return tests


def switched_off(tests: list[dict]) -> dict[tuple[str, str], str]:
    """{(class, method): workbook} for data-driven methods whose rows are all disabled (or that have
    none): they run no scenario, though the class exists and suites may list it."""
    return {(t["class"], m["name"]): m["datasource"] for t in tests for m in t["methods"]
            if m["datasource"] and not m["error"] and not any(not c["disabled"] for c in m["codes"])}


def why_nothing(entry: str, tests: list[dict]) -> str:
    """Why an entry that resolves to no scenario runs nothing."""
    parts = str(entry).split()
    off = switched_off(tests)
    hits = [(c, m, wb) for (c, m), wb in off.items()
            if _full(parts[0], c) and (len(parts) < 2 or _full(parts[1], m))]
    if hits:
        files = sorted({os.path.basename(wb) for _c, _m, wb in hits})
        return f"names a test whose rows are all disabled ({', '.join(files)}): it runs nothing"
    return "matches no test: CenterTest reports it as a failed scenario"


def scenarios_of(tests: list[dict], include_disabled: bool = False) -> list[tuple[str, str, str]]:
    """Every runnable (class, method, code); code is "" for a method without data."""
    out = []
    for t in tests:
        for m in t["methods"]:
            rows = [c for c in m["codes"] if include_disabled or not c["disabled"]]
            if m["datasource"] and not m["error"]:
                out += [(t["class"], m["name"], c["code"]) for c in rows]
            else:
                out.append((t["class"], m["name"], ""))
    return out


# ---------------------------------------------------------------------------
# The suite file
# ---------------------------------------------------------------------------

def find_suite_file(project: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    default = os.path.join(project, "src", "main", "resources", SUITE_FILE)
    if os.path.isfile(default):
        return default
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in ("build", ".git", "node_modules", "out", ".gradle")]
        if SUITE_FILE in files:
            return os.path.join(root, SUITE_FILE)
    return default


def loads_lenient(text: str):
    """json.loads that also accepts a trailing comma before ] or } -- hand-edited suite files
    have them and CenterTest runs them, so the tools must read them too."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if ch == ",":
            k = i + 1
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k < n and text[k] in "]}":
                i += 1
                continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def load_suites(path: str) -> tuple[dict, str]:
    if not os.path.isfile(path):
        return {"CenterTestSuites": []}, ""
    with open(path, encoding="utf-8", newline="") as fh:  # keep \r\n visible, to write it back
        text = fh.read()
    doc = loads_lenient(text) if text.strip() else {}
    doc.setdefault("CenterTestSuites", [])
    return doc, text


def serialize(doc: dict, original: str) -> str:
    """JSON in the file's own style: its indentation, line endings and trailing newline."""
    indent = 2
    m = re.search(r"\n([ \t]+)\S", original or "")
    if m:
        indent = "\t" if m.group(1).startswith("\t") else len(m.group(1))
    eol = "\r\n" if "\r\n" in (original or "") else "\n"
    trailing = eol if not original or re.search(r"\r?\n$", original) else ""
    return json.dumps(doc, indent=indent, ensure_ascii=False).replace("\n", eol) + trailing


# --- Minimal text edits: change only what changed, keep the rest of the file byte for byte ---

def _skip_string(text: str, i: int) -> int:
    """Index just past the JSON string starting at text[i] == '"'."""
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    raise ValueError("unterminated string")


def _match_close(text: str, i: int) -> int:
    """Index just past the bracket that closes the one at text[i] ('[' or '{')."""
    depth = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            i = _skip_string(text, i)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced brackets")


def _key_value_span(text: str, start: int, end: int, key: str):
    """(value start, value end) of "key": <value> directly inside the object text[start:end]."""
    i, depth = start, 0
    while i < end:
        ch = text[i]
        if ch == '"':
            j = _skip_string(text, i)
            if depth == 1 and text[i + 1:j - 1] == key:
                k = j
                while text[k] in " \t\r\n:":
                    k += 1
                v_end = _match_close(text, k) if text[k] in "[{" else (_skip_string(text, k) if text[k] == '"' else None)
                if v_end is None:
                    return None
                return k, v_end
            i = j
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        i += 1
    return None


def _suite_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each object in the CenterTestSuites array."""
    root = text.index("{")
    span = _key_value_span(text, root, _match_close(text, root), "CenterTestSuites")
    i, end = span[0] + 1, span[1] - 1
    out = []
    while i < end:
        if text[i] == "{":
            j = _match_close(text, i)
            out.append((i, j))
            i = j
        else:
            i += 1
    return out, span


def _line_indent(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    m = re.match(r"[ \t]*", text[line_start:])
    return m.group(0)


def _array_text(old: str, values: list, eol: str, unit: str) -> str:
    """A JSON array of strings laid out like the old one (one item per line, its item indent)."""
    if not values:
        return "[]"
    m = re.search(r"\[\s*?\r?\n([ \t]*)\S", old)
    item_indent = m.group(1) if m else None
    if item_indent is None:
        return json.dumps(values, ensure_ascii=False)
    close = re.search(r"\r?\n([ \t]*)\]$", old)
    close_indent = close.group(1) if close else item_indent[:-len(unit)] if len(item_indent) >= len(unit) else ""
    return "[" + eol + ("," + eol).join(item_indent + json.dumps(v, ensure_ascii=False) for v in values) + eol + close_indent + "]"


def minimal_edit(text: str, before: dict, after: dict) -> str | None:
    """`text` changed from `before` to `after` by touching only the edited suites, or None when
    the change is not one this can express (the caller then rewrites the whole file)."""
    if not text.strip():
        return None
    try:
        spans, array = _suite_spans(text)
        B, A = before["CenterTestSuites"], after["CenterTestSuites"]
        if len(spans) != len(B):
            return None
        eol = "\r\n" if "\r\n" in text else "\n"
        m = re.search(r"\n([ \t]+)\S", text)
        unit = (m.group(1) if m else "  ")
        edits = []  # (start, end, replacement)
        if len(A) == len(B):
            for (s0, s1), b, a in zip(spans, B, A):
                if a == b:
                    continue
                for key in set(a) | set(b):
                    if a.get(key) == b.get(key):
                        continue
                    if key not in ("List", "Suites", "Name") or key not in b or key not in a:
                        return None
                    v = _key_value_span(text, s0, s1, key)
                    if v is None:
                        return None
                    new = json.dumps(a[key], ensure_ascii=False) if key == "Name" else _array_text(text[v[0]:v[1]], a[key], eol, unit)
                    edits.append((v[0], v[1], new))
        elif len(A) == len(B) + 1 and A[:-1] == B:
            obj_indent = _line_indent(text, spans[-1][0]) if spans else unit * 2
            body = json.dumps(A[-1], indent=len(unit) if unit.strip(" ") == "" else unit, ensure_ascii=False)
            body = (eol + obj_indent).join(body.split("\n"))
            at = spans[-1][1] if spans else array[0] + 1
            edits.append((at, at, ("," if spans else "") + eol + obj_indent + body))
        elif len(A) == len(B) - 1:
            j = next((j for j in range(len(B)) if B[:j] + B[j + 1:] == A), None)
            if j is None:
                return None
            s0, s1 = spans[j]
            if j > 0:  # take the comma and space before it
                s0 = text.rindex(",", spans[j - 1][1], s0)
            elif len(spans) > 1:  # first one: take it and the comma after it, up to the next object
                s1 = spans[1][0]
                s0 = text.rfind("\n", 0, s0) + 1 if text.rfind("\n", 0, s0) > array[0] else s0
                s1 = text.rfind("\n", 0, s1) + 1 if text.rfind("\n", s0, s1) != -1 else s1
            edits.append((s0, s1, ""))
        else:
            return None
        out = text
        for s0, s1, new in sorted(edits, reverse=True):
            out = out[:s0] + new + out[s1:]
        return out if loads_lenient(out) == after else None
    except (ValueError, KeyError, IndexError, json.JSONDecodeError):
        return None


def find(doc: dict, name: str) -> dict | None:
    return next((s for s in doc["CenterTestSuites"] if str(s.get("Name", "")).lower() == name.lower()), None)


# ---------------------------------------------------------------------------
# Reading entries the way CenterTest does
# ---------------------------------------------------------------------------

def _full(pattern: str, value: str) -> bool:
    try:
        return re.fullmatch(pattern, value, re.I) is not None
    except re.error:
        return pattern.lower() == value.lower()


def resolve_entry(entry: str, scenarios: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """The scenarios one List entry selects: each part a case-insensitive regex on the whole name."""
    parts = str(entry).split()
    if not parts:
        return []
    out = []
    for cls, method, code in scenarios:
        if not _full(parts[0], cls):
            continue
        if len(parts) > 1 and not _full(parts[1], method):
            continue
        if len(parts) > 2 and not _full(" ".join(parts[2:]), code):
            continue
        out.append((cls, method, code))
    return out


def resolve_suite(doc: dict, name: str, tests: list[dict], seen=None) -> dict:
    """{scenarios: set, unmatched: [entry], packages: [...], missing_suites: [...]} for a suite."""
    seen = (seen or set()) | {name.lower()}
    s = find(doc, name) or {}
    scen = scenarios_of(tests)
    by_class = {t["class"]: t for t in tests}
    out = {"scenarios": set(), "unmatched": [], "missing_suites": [], "unmatched_packages": []}
    for entry in s.get("List", []) or []:
        hit = resolve_entry(entry, scen)
        if hit:
            out["scenarios"].update(hit)
        else:
            out["unmatched"].append(entry)
    for pattern in s.get("Packages", []) or []:
        hit = {(cls, method, code) for cls, method, code in scen
               if _full(pattern, by_class[cls]["package"]) or _full(pattern, by_class[cls]["package"] + "." + cls)}
        if not hit:
            out["unmatched_packages"].append(pattern)
        out["scenarios"] |= hit
    for child in s.get("Suites", []) or []:
        if child.lower() in seen:
            continue
        if not find(doc, child):
            out["missing_suites"].append(child)
            continue
        sub = resolve_suite(doc, child, tests, seen)
        out["scenarios"] |= sub["scenarios"]
        out["unmatched"] += sub["unmatched"]
        out["missing_suites"] += sub["missing_suites"]
        out["unmatched_packages"] += sub["unmatched_packages"]
    return out


def uncovered(doc: dict, tests: list[dict]) -> set[tuple[str, str, str]]:
    """Runnable scenarios that no suite runs (List, Packages or child Suites)."""
    covered = set()
    for s in doc["CenterTestSuites"]:
        covered |= resolve_suite(doc, str(s.get("Name", "")), tests)["scenarios"]
    return set(scenarios_of(tests)) - covered


# ---------------------------------------------------------------------------
# Selections and compact entries
# ---------------------------------------------------------------------------

def select(tests: list[dict], args) -> set[tuple[str, str, str]]:
    """Scenarios matching every given selector (regex search, case-insensitive) or --entry."""
    scen = scenarios_of(tests, getattr(args, "include_disabled", False))
    if getattr(args, "entry", None):
        return {s for e in args.entry for s in resolve_entry(e, scen)}
    desc = {(t["class"], m["name"], c["code"]): c["desc"] for t in tests for m in t["methods"] for c in m["codes"]}
    pkg = {t["class"]: t["package"] for t in tests}

    def ok(pattern, value):
        return pattern is None or re.search(pattern, value or "", re.I) is not None

    if not any(getattr(args, k, None) for k in ("cls", "method", "code", "desc", "package")):
        return set()
    return {(c, m, k) for c, m, k in scen
            if ok(args.cls, c) and ok(args.method, m) and ok(args.code, k)
            and ok(args.desc, desc.get((c, m, k), "")) and ok(args.package, pkg.get(c, ""))}


def _lit(value: str) -> str:
    """A name as a regex matching only itself (CenterTest splits entries on spaces first)."""
    out = "".join("\\" + ch if ch in _REGEX_META else ch for ch in value)
    return out.replace(" ", "\\s")


def compact(selected: set, tests: list[dict]) -> list[str]:
    """Entries for a set of scenarios: "Class" / "Class method" / "Class method (a|b)"."""
    entries = []
    for t in tests:
        per_method = {}
        for m in t["methods"]:
            runnable = {code for c, mm, code in scenarios_of([t]) if mm == m["name"]}
            chosen = {code for c, mm, code in selected if c == t["class"] and mm == m["name"]}
            per_method[m["name"]] = (runnable, chosen)
        if all(r and r == ch for r, ch in per_method.values()):
            entries.append(_lit(t["class"]))
            continue
        for name, (runnable, chosen) in per_method.items():
            if not chosen:
                continue
            if chosen == runnable or chosen == {""}:
                entries.append(f"{_lit(t['class'])} {_lit(name)}")
            else:
                codes = sorted(chosen - {""})
                left_out = sorted(runnable - chosen - {""})
                if len(left_out) < len(codes):
                    # "every row except these": shorter to read, and new rows are included too
                    alt = "(?!(?:" + "|".join(_lit(c) for c in left_out) + ")$).*"
                else:
                    alt = _lit(codes[0]) if len(codes) == 1 else "(" + "|".join(_lit(c) for c in codes) + ")"
                entries.append(f"{_lit(t['class'])} {_lit(name)} {alt}")
    return entries


# ---------------------------------------------------------------------------
# Edits
# ---------------------------------------------------------------------------

def add_to(suite: dict, selection: set, tests: list[dict]) -> list[str]:
    """Entries to append so the suite also runs the selection; existing entries are kept."""
    scen = scenarios_of(tests)
    covered = set()
    for e in suite.get("List", []) or []:
        covered.update(resolve_entry(e, scen))
    return compact(selection - covered, tests)


def remove_from(suite: dict, selection: set, tests: list[dict]) -> tuple[list[str], list[str]]:
    """(new List, entries that matched nothing and were kept). An entry wholly inside the selection
    is dropped, one partly inside is replaced by compact entries for what it keeps, one outside is
    kept verbatim."""
    scen = scenarios_of(tests)
    new, kept_unmatched = [], []
    for e in suite.get("List", []) or []:
        hit = set(resolve_entry(e, scen))
        if not hit:
            new.append(e)
            kept_unmatched.append(e)
        elif not hit & selection:
            new.append(e)
        else:
            new += compact(hit - selection, tests)
    return new, kept_unmatched


# ---------------------------------------------------------------------------
# Repairing dead entries
# ---------------------------------------------------------------------------

def _near(word: str, options, n: int = 4) -> list[str]:
    """Closest names to word: same text ignoring case first, then contains, then difflib."""
    import difflib
    opts = sorted(set(options))
    low = word.lower().strip("^$.*()")
    exact = [o for o in opts if o.lower() == low]
    contains = [o for o in opts if low and low in o.lower() and o not in exact]
    fuzzy = difflib.get_close_matches(word, opts, n=n, cutoff=0.6)
    out = []
    for o in exact + contains + fuzzy:
        if o not in out:
            out.append(o)
    return out[:n]


def diagnose(entry: str, tests: list[dict]) -> dict:
    """Why an entry runs nothing and what it probably meant:
    {part: class|method|code, value, suggestions: [entries]}."""
    parts = str(entry).split()
    scen = scenarios_of(tests)
    classes = {c for c, _m, _k in scen}
    cls_hit = [c for c in classes if _full(parts[0], c)]
    off = [(c, m, wb) for (c, m), wb in switched_off(tests).items()
           if _full(parts[0], c) and (len(parts) < 2 or _full(parts[1], m))]
    if not cls_hit and off:
        return {"part": "rows", "value": ", ".join(sorted({os.path.basename(wb) for _c, _m, wb in off})),
                "suggestions": []}
    if not cls_hit:
        return {"part": "class", "value": parts[0],
                "suggestions": [" ".join([_lit(c)] + parts[1:]) for c in _near(parts[0], classes)]}
    methods = {m for c, m, _k in scen if c in cls_hit}
    if len(parts) > 1 and not [m for m in methods if _full(parts[1], m)]:
        return {"part": "method", "value": parts[1],
                "suggestions": [" ".join([parts[0], _lit(m)] + parts[2:]) for m in _near(parts[1], methods)]}
    codes = {k for c, m, k in scen if c in cls_hit and (len(parts) < 2 or _full(parts[1], m)) and k}
    wanted = " ".join(parts[2:])
    # The same code under another test: the row may have moved to a different class or method.
    elsewhere = sorted({f"{_lit(c)} {_lit(m)} {_lit(k)}" for c, m, k in scen
                        if c not in cls_hit and k and k.lower() == wanted.lower()})
    if not codes:  # the method has no data: the code part can only be dropped
        return {"part": "code", "value": wanted, "suggestions": (elsewhere + [" ".join(parts[:2])])[:4]}
    same_class = [" ".join(parts[:2] + [_lit(k)]) for k in _near(wanted, codes)]
    return {"part": "code", "value": wanted, "suggestions": (elsewhere + same_class)[:4]}


# ---------------------------------------------------------------------------
# The picker page
# ---------------------------------------------------------------------------

def _membership(doc: dict, tests: list[dict]) -> dict:
    out: dict[str, list[str]] = {}
    for s_ in doc["CenterTestSuites"]:
        name = str(s_.get("Name", ""))
        for c, m, k in resolve_suite(doc, name, tests)["scenarios"]:
            out.setdefault(f"{c}\t{m}\t{k}", []).append(name)
    return out


def write_picker(project, source_root, tests, suite_path, doc, preselect=None, out=None) -> str:
    """A self-contained page to tick classes, methods and rows; it shows the suite's entries
    before -> after and the suite.py command that applies the change."""
    data = {
        "project": project, "projectName": os.path.basename(project), "sourceRoot": source_root,
        "suiteFile": os.path.relpath(suite_path, project).replace("\\", "/"),
        "engine": os.path.abspath(__file__), "tests": tests,
        "suites": doc["CenterTestSuites"], "preselect": preselect or "",
        # which suites run each scenario ("class\tmethod\tcode" -> names), Packages and child Suites resolved
        "membership": _membership(doc, tests),
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "picker.html"), encoding="utf-8") as fh:
        page = fh.read()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = page.replace("/*__DATA__*/", blob, 1)
    if not out:
        folder = os.path.expanduser("~/.centertest/reports")
        os.makedirs(folder, exist_ok=True)
        out = os.path.join(folder, f"suite-picker_{os.path.basename(project)}.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _fmt(s):
    c, m, k = s
    return f"{c} {m} {k}".rstrip()


def _print_change(name, before, after, before_scen, after_scen, write, path):
    print(f"Suite {name}: {len(before_scen)} -> {len(after_scen)} scenarios "
          f"(+{len(after_scen - before_scen)} -{len(before_scen - after_scen)})")
    for e in before:
        if e not in after:
            print(f"  - {e}")
    for e in after:
        if e not in before:
            print(f"  + {e}")
    print(f"{'Written to' if write else 'Not written (dry run; add --write):'} {path}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="suite.py", description=__doc__.split("\n")[0])
    p.add_argument("--project", default=".")
    p.add_argument("--source-root", default="src/main/java")
    p.add_argument("--suites", help=f"path of {SUITE_FILE} (default: found in the project)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    # The same options after the command ("scan --json"); SUPPRESS keeps a value given before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=argparse.SUPPRESS)
    common.add_argument("--source-root", default=argparse.SUPPRESS)
    common.add_argument("--suites", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    def selectors(sp):
        sp.add_argument("--class", dest="cls")
        sp.add_argument("--method")
        sp.add_argument("--code")
        sp.add_argument("--desc")
        sp.add_argument("--package")
        sp.add_argument("--entry", action="append")
        sp.add_argument("--include-disabled", action="store_true")

    sub.add_parser("scan")
    sub.add_parser("list")
    sp = sub.add_parser("show"); sp.add_argument("name")
    sp = sub.add_parser("pick"); selectors(sp)
    for cmd in ("create", "add", "remove"):
        sp = sub.add_parser(cmd); sp.add_argument("name"); selectors(sp); sp.add_argument("--write", action="store_true")
    sp = sub.add_parser("delete"); sp.add_argument("name"); sp.add_argument("--write", action="store_true")
    sp = sub.add_parser("rename"); sp.add_argument("old"); sp.add_argument("new"); sp.add_argument("--write", action="store_true")
    sub.add_parser("uncovered")
    sp = sub.add_parser("doctor"); sp.add_argument("name", nargs="?")
    sp = sub.add_parser("replace"); sp.add_argument("name"); sp.add_argument("--old", required=True)
    sp.add_argument("--new", required=True); sp.add_argument("--write", action="store_true")
    sp = sub.add_parser("drop"); sp.add_argument("name"); sp.add_argument("--entry", action="append", required=True)
    sp.add_argument("--write", action="store_true")
    sp = sub.add_parser("picker"); sp.add_argument("--suite", help="suite to open for editing")
    sp.add_argument("--out", help="where to write the page (default ~/.centertest/reports/)")
    sp.add_argument("--open", action="store_true", help="open the page in the default browser")
    sp = sub.add_parser("set"); sp.add_argument("name"); sp.add_argument("--entries-file", required=True)
    sp.add_argument("--write", action="store_true")
    args = p.parse_args(argv)

    project = os.path.abspath(args.project)
    tests = scan(project, args.source_root)
    path = find_suite_file(project, args.suites)
    doc, text = load_suites(path)
    original = json.loads(json.dumps(doc))

    if args.cmd == "scan":
        if args.json:
            print(json.dumps({"tests": tests, "suiteFile": os.path.relpath(path, project)}, indent=1))
            return 0
        for t in tests:
            print(f"{t['class']}  ({t['package']})")
            for m in t["methods"]:
                live = [c for c in m["codes"] if not c["disabled"]]
                extra = f"  ERROR {m['error']}" if m["error"] else ""
                rows = f"{len(live)} rows" + (f" (+{len(m['codes']) - len(live)} disabled)" if len(live) != len(m["codes"]) else "")
                print(f"    {m['name']:<24} {rows if m['datasource'] else 'no data'}{extra}")
        print(f"{len(tests)} test classes, {len(scenarios_of(tests))} runnable scenarios; suites: {os.path.relpath(path, project)}")
        return 0

    if args.cmd == "list":
        rows = []
        for s in doc["CenterTestSuites"]:
            r = resolve_suite(doc, s.get("Name", ""), tests)
            kind = "+".join(k for k in ("List", "Packages", "Suites") if s.get(k)) or "empty"
            rows.append({"name": s.get("Name", ""), "kind": kind, "entries": len(s.get("List", []) or []),
                         "scenarios": len(r["scenarios"]), "unmatched": r["unmatched"], "missingSuites": r["missing_suites"],
                         "unmatchedPackages": r["unmatched_packages"]})
        if args.json:
            print(json.dumps(rows, indent=1))
        else:
            for r in rows:
                warn = f"  {len(r['unmatched'])} entries match nothing" if r["unmatched"] else ""
                warn += f"  missing suites: {', '.join(r['missingSuites'])}" if r["missingSuites"] else ""
                warn += f"  packages matching no test: {', '.join(r['unmatchedPackages'])}" if r["unmatchedPackages"] else ""
                print(f"  {r['name']:<28} {r['kind']:<14} {r['scenarios']:>5} scenarios{warn}")
            print(f"{len(rows)} suites in {os.path.relpath(path, project)}")
            left = uncovered(doc, tests)
            if left:
                print(f"{len(left)} of {len(scenarios_of(tests))} scenarios are in no suite (suite.py uncovered lists them)")
        return 0

    if args.cmd == "show":
        s = find(doc, args.name)
        if not s:
            print(f"No suite named {args.name}", file=sys.stderr)
            return 2
        r = resolve_suite(doc, args.name, tests)
        if args.json:
            print(json.dumps({"suite": s, "scenarios": sorted(map(_fmt, r["scenarios"])), "unmatched": r["unmatched"],
                              "missingSuites": r["missing_suites"], "unmatchedPackages": r["unmatched_packages"]}, indent=1))
            return 0
        print(json.dumps(s, indent=2))
        print(f"Runs {len(r['scenarios'])} scenarios:")
        for line in sorted(map(_fmt, r["scenarios"])):
            print(f"  {line}")
        for e in r["unmatched"]:
            print(f"  ! matches nothing (CenterTest reports it as a failed scenario): {e}")
        for e in r["missing_suites"]:
            print(f"  ! names a suite that does not exist: {e}")
        for e in r["unmatched_packages"]:
            print(f"  ! package pattern matches no test class: {e}")
        return 0

    if args.cmd == "uncovered":
        left = uncovered(doc, tests)
        by_class: dict[str, list] = {}
        for c, m, k in sorted(left):
            by_class.setdefault(c, []).append(f"{m} {k}".strip())
        total = {c: sum(1 for x in scenarios_of(tests) if x[0] == c) for c in by_class}
        if args.json:
            print(json.dumps({"scenarios": sorted(map(_fmt, left)), "byClass": by_class}, indent=1))
            return 0
        for c, items in by_class.items():
            whole = len(items) == total[c]
            print(f"  {c}: {'the whole class' if whole else ''}{'' if whole else f'{len(items)} of {total[c]} scenarios'}")
            if not whole:
                for i in items[:6]:
                    print(f"      {i}")
                if len(items) > 6:
                    print(f"      ... {len(items) - 6} more")
        print(f"{len(left)} of {len(scenarios_of(tests))} scenarios are in no suite"
              + (" -- add them with suite.py add, or leave them out on purpose" if left else ""))
        return 0

    if args.cmd == "doctor":
        report = []
        for s_ in doc["CenterTestSuites"]:
            if args.name and str(s_.get("Name", "")).lower() != args.name.lower():
                continue
            scen = scenarios_of(tests)
            for e in s_.get("List", []) or []:
                if not resolve_entry(e, scen):
                    report.append({"suite": s_.get("Name", ""), "entry": e, **diagnose(e, tests)})
        if args.json:
            print(json.dumps(report, indent=1))
            return 0
        for r in report:
            if r["part"] == "rows":
                print(f"{r['suite']}: '{r['entry']}' -- every row of {r['value']} is disabled, so it runs nothing")
                print("    enable a row there, or drop the entry if the test is parked on purpose")
                continue
            print(f"{r['suite']}: '{r['entry']}' -- no test {r['part']} matches '{r['value']}'")
            for sug in r["suggestions"] or ["(nothing close: drop it?)"]:
                print(f"    try: {sug}")
        print(f"{len(report)} entries run nothing" + ("" if report else " -- every entry matches a test"))
        return 0

    if args.cmd == "picker":
        out = write_picker(project, args.source_root, tests, path, doc, args.suite, args.out)
        print(f"Suite picker: {out}")
        if args.open:
            opener = {"darwin": ["open"], "win32": ["cmd", "/c", "start", ""]}.get(sys.platform, ["xdg-open"])
            import subprocess
            subprocess.run(opener + [out], check=False)
        return 0

    if args.cmd == "pick":
        chosen = select(tests, args)
        if args.json:
            print(json.dumps({"scenarios": sorted(map(_fmt, chosen)), "entries": compact(chosen, tests)}, indent=1))
            return 0
        print(f"{len(chosen)} scenarios:")
        for line in sorted(map(_fmt, chosen)):
            print(f"  {line}")
        print("As entries:")
        for e in compact(chosen, tests):
            print(f"  {e}")
        return 0

    write = getattr(args, "write", False)
    name = getattr(args, "name", None) or getattr(args, "old", None)
    suite = find(doc, name) if name else None

    if args.cmd == "create":
        if suite:
            print(f"A suite named {suite['Name']} exists; use add, remove or set.", file=sys.stderr)
            return 2
        chosen = select(tests, args)
        if not chosen:
            print("The selection is empty: give --class/--method/--code/--desc/--package or --entry.", file=sys.stderr)
            return 2
        suite = {"Name": args.name, "List": compact(chosen, tests)}
        doc["CenterTestSuites"].append(suite)
        _print_change(args.name, [], suite["List"], set(), chosen, write, path)
    elif args.cmd in ("replace", "drop"):
        if not suite:
            print(f"No suite named {name}", file=sys.stderr)
            return 2
        before = list(suite.get("List", []) or [])
        before_scen = resolve_suite(doc, suite["Name"], tests)["scenarios"]
        if args.cmd == "replace":
            if args.old not in before:
                print(f"{suite['Name']} has no entry written exactly '{args.old}'", file=sys.stderr)
                return 2
            suite["List"] = [args.new if e == args.old else e for e in before]
        else:
            missing = [e for e in args.entry if e not in before]
            if missing:
                print(f"{suite['Name']} has no entry written exactly: {', '.join(missing)}", file=sys.stderr)
                return 2
            suite["List"] = [e for e in before if e not in args.entry]
        after_scen = resolve_suite(doc, suite["Name"], tests)["scenarios"]
        _print_change(suite["Name"], before, suite["List"], before_scen, after_scen, write, path)
    elif args.cmd in ("add", "remove", "set"):
        if not suite:
            print(f"No suite named {name}; create it first.", file=sys.stderr)
            return 2
        before = list(suite.get("List", []) or [])
        before_scen = resolve_suite(doc, suite["Name"], tests)["scenarios"]
        if args.cmd == "add":
            chosen = select(tests, args)
            if not chosen:
                print("The selection is empty.", file=sys.stderr)
                return 2
            suite["List"] = before + add_to(suite, chosen, tests)
        elif args.cmd == "remove":
            chosen = select(tests, args)
            if not chosen:
                print("The selection is empty.", file=sys.stderr)
                return 2
            suite["List"], _kept = remove_from(suite, chosen, tests)
        else:
            src = sys.stdin if args.entries_file == "-" else open(args.entries_file, encoding="utf-8")
            suite["List"] = [line.strip() for line in src if line.strip() and not line.strip().startswith("#")]
        after_scen = resolve_suite(doc, suite["Name"], tests)["scenarios"]
        _print_change(suite["Name"], before, suite["List"], before_scen, after_scen, write, path)
        for e in resolve_suite(doc, suite["Name"], tests)["unmatched"]:
            print(f"  ! matches nothing: {e}")
    elif args.cmd == "delete":
        if not suite:
            print(f"No suite named {name}", file=sys.stderr)
            return 2
        users = [s["Name"] for s in doc["CenterTestSuites"] if name.lower() in [x.lower() for x in s.get("Suites", []) or []]]
        doc["CenterTestSuites"].remove(suite)
        print(f"Delete suite {suite['Name']} ({len(suite.get('List', []) or [])} entries)")
        if users:
            print(f"  ! composite suites that name it: {', '.join(users)} (they will report it missing)")
        print(f"{'Written to' if write else 'Not written (dry run; add --write):'} {path}")
    elif args.cmd == "rename":
        if not suite:
            print(f"No suite named {name}", file=sys.stderr)
            return 2
        if find(doc, args.new):
            print(f"A suite named {args.new} exists.", file=sys.stderr)
            return 2
        old = suite["Name"]
        suite["Name"] = args.new
        for s in doc["CenterTestSuites"]:
            if s.get("Suites"):
                s["Suites"] = [args.new if x.lower() == old.lower() else x for x in s["Suites"]]
        print(f"Rename suite {old} -> {args.new}")
        print(f"{'Written to' if write else 'Not written (dry run; add --write):'} {path}")

    if write:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new_text = minimal_edit(text, original, doc) or serialize(doc, text)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
