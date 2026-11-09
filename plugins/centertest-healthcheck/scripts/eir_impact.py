"""
What to rerun for a branch: the tests (and data rows) its code and data changes reach.

Inputs are the two exported trees of a review (merge-base and branch tip) and the list of
changed files. Three kinds of change are followed:

- Java: a changed class reaches every test class that refers to it, directly or through
  other classes (a test -> facade -> step chain), by simple-name references.
- DataCombination workbooks: rows (codes) added or changed reach the tests that read the
  workbook (@DataDriven, DDTHelper getters, DC class, @Rel relationships).
- Reference data: codes added or changed in a sheet reach the DC rows whose #Ref or @Rel.#Ref
  columns name them, and through those rows their tests.

The plan is a list of {test, codes, reasons}; codes empty means "the whole test".
"""

from __future__ import annotations

import os
import re
import subprocess

_WORD = re.compile(r"\b[A-Z]\w*\b")


def changed_files(repo_dir: str, base_sha: str, head_sha: str) -> list[str]:
    r = subprocess.run(["git", "diff", "--name-only", base_sha, head_sha],
                       cwd=repo_dir, capture_output=True, text=True)
    return [line.strip() for line in r.stdout.splitlines() if line.strip()] if r.returncode == 0 else []


def _java_sources(tree: str, source_root: str) -> dict[str, tuple[str, str]]:
    """{simple class name: (rel path, text)} for non-generated Java files."""
    out = {}
    root_dir = os.path.join(tree, source_root)
    for root, _dirs, files in os.walk(root_dir):
        if "datadriven" in root.replace("\\", "/").split("/"):
            continue
        for name in files:
            if name.endswith(".java"):
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    out[name[:-5]] = (os.path.relpath(path, tree).replace("\\", "/"), fh.read())
    return out


def _is_test(text: str) -> bool:
    return re.search(r"@CenterTest\b(?!Case)", text) is not None


_METHOD_DECL = re.compile(
    r"(?:public|protected|private|static|final|synchronized|abstract|default|\s)+[\w<>\[\],.? ]+?\s+(\w+)\s*\([^;{)]*\)\s*(?:throws[^{;]*)?\{")


_NOT_METHODS = ("if", "for", "while", "switch", "catch", "synchronized", "return", "new")


def _body_end(text: str, start: int) -> int:
    depth, k = 1, start
    while k < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        k += 1
    return k


def _methods(text: str) -> list[tuple[str, str]]:
    """[(method name, body)] by declaration regex and brace matching (good enough for reach)."""
    return [(m.group(1), text[m.end():_body_end(text, m.end())])
            for m in _METHOD_DECL.finditer(text) if m.group(1) not in _NOT_METHODS]


def tests_reaching(classes: set[str], sources: dict, start: dict | None = None) -> dict[str, str]:
    """{test class: the changed class it reaches} for tests that reach any of `classes`.

    Reach is followed per method, so a hub everyone uses (a facade like PC or BC) only passes
    the change on through the facade methods that use the changed class, and on to the
    classes that call those methods. A subclass of a changed class is changed as a whole.
    `start` gives, per class, only the methods that changed (e.g. the ones that read a changed
    workbook); a class missing from it is changed as a whole.
    """
    methods = {name: _methods(text) for name, (_p, text) in sources.items()}
    own_words = {name: set(_WORD.findall(text)) for name, (_p, text) in sources.items()}
    parent = {}
    for name, (_p, text) in sources.items():
        m = re.search(r"\bclass\s+" + re.escape(name) + r"\b[^{]*?\bextends\s+(\w+)", text)
        if m and m.group(1) in sources:
            parent[name] = m.group(1)

    def lineage(name):  # the class and its project superclasses: an inherited field counts as its own
        seen = [name]
        while parent.get(seen[-1]) and parent[seen[-1]] not in seen:
            seen.append(parent[seen[-1]])
        return seen

    words = {name: set().union(*(own_words[c] for c in lineage(name))) for name in sources}
    texts = {name: "\n".join(sources[c][1] for c in lineage(name)) for name in sources}
    reached: dict[str, str] = {}

    def closed(cls, names):
        """names plus the methods of cls that call them, until nothing new (execute() -> fill() -> ...)."""
        if names is None or cls not in methods:
            return names
        names = set(names)
        while True:
            pattern = re.compile(r"(?<![\w.])(?:this\.)?(?:" + "|".join(map(re.escape, names)) + r")\s*\(")
            more = {n for n, body in methods[cls] if n not in names and pattern.search(body)}
            if not more:
                return names
            names |= more

    for begin in classes:
        # affected[class] = None (the whole class) or the set of its affected method names
        affected: dict[str, set | None] = {begin: closed(begin, (start or {}).get(begin))}
        frontier = [begin]
        while frontier:
            current = frontier.pop()
            names = affected[current]
            if current in sources and _is_test(sources[current][1]):
                reached.setdefault(current, begin)
            alts = None if names is None else "|".join(map(re.escape, names))
            # a static call names its class (BC.createAccount, not PC.createAccount); a bare .name( counts
            # only where the class is used as an instance (new X(...), a variable or parameter of type X)
            static = None if names is None else re.compile(r"\b" + re.escape(current) + r"\s*\.\s*(?:" + alts + r")\s*\(")
            calls = None if names is None else re.compile(r"\.(?:" + alts + r")\s*\(")
            instance = re.compile(r"\bnew\s+" + re.escape(current) + r"\b|\b" + re.escape(current)
                                  + r"(?:<[^>]*>)?\s+\w+\s*[=;,)]")
            for other, (_p, text) in sources.items():
                if other == current or current not in words[other]:
                    continue
                if re.search(r"\b(?:extends|implements)\s+[\w\s,<>]*\b" + re.escape(current) + r"\b", text):
                    hit = None
                else:
                    typed = bool(instance.search(texts[other]))
                    # held in a field (its own or a superclass's): the methods that use that field
                    fields = set(re.findall(r"\b" + re.escape(current) + r"(?:<[^>]*>)?\s+(\w+)\s*[;=]", texts[other]))
                    uses = re.compile(r"\b(?:" + "|".join(map(re.escape, [current, *sorted(fields)])) + r")\b")
                    # a method that builds the step (a facade's `return new Step(...)`) hands it to a caller
                    # that runs it: it passes the change on once the step's execute() is affected
                    builds = names is not None and "execute" in names and re.compile(
                        r"\bnew\s+" + re.escape(current) + r"\s*[(<]")
                    hit = {name for name, body in methods[other]
                           if uses.search(body)
                           and (calls is None or static.search(body) or (typed and calls.search(body))
                                or (builds and builds.search(body)))}
                    if not hit:
                        continue
                known = affected.get(other, set())
                if known is None:
                    continue
                merged = None if hit is None else closed(other, known | hit)
                if other not in affected or merged is None or merged != known:
                    affected[other] = merged
                    frontier.append(other)
    return reached


def _sheet_rows(path: str) -> dict[str, dict[str, tuple]]:
    """{sheet: {code: row values}} for every sheet with a Code column."""
    from ddt_refcheck import load_workbook
    out: dict[str, dict[str, tuple]] = {}
    if not os.path.isfile(path):
        return out
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return out
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
        if not rows:
            continue
        headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
        if "code" not in headers:
            continue
        ci = headers.index("code")
        sheet = out.setdefault(ws.title, {})
        for r in rows[1:]:
            code = r[ci] if ci < len(r) else None
            if code not in (None, ""):
                sheet[str(code).strip()] = tuple("" if v is None else str(v) for v in r)
    wb.close()
    return out


def _sheet_tables(path: str) -> dict[str, tuple[list[str], dict[str, tuple]]]:
    """{sheet: (headers, {code: row values})} for every sheet with a Code column."""
    from ddt_refcheck import load_workbook
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return out
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
        if not rows:
            continue
        headers = ["" if h is None else str(h).strip() for h in rows[0]]
        lowered = [h.lower() for h in headers]
        if "code" not in lowered:
            continue
        ci = lowered.index("code")
        table = {}
        for r in rows[1:]:
            code = r[ci] if ci < len(r) else None
            if code not in (None, ""):
                table[str(code).strip()] = tuple("" if v is None else str(v) for v in r)
        out[ws.title] = (headers, table)
    wb.close()
    return out


def data_changes(base_tree: str, head_tree: str, changed: list[str]) -> list[dict]:
    """[{file, sheet, added: [code], removed: [code], changed: [(code, [(column, old, new)])]}]
    for every workbook the branch changed, by Code."""
    out = []
    for rel in sorted(p for p in changed if p.startswith("testdata/") and p.endswith(".xlsx")):
        base, head = _sheet_tables(os.path.join(base_tree, rel)), _sheet_tables(os.path.join(head_tree, rel))
        for sheet in sorted(set(base) | set(head)):
            bh, brows = base.get(sheet, ([], {}))
            hh, hrows = head.get(sheet, ([], {}))
            entry = {"file": rel, "sheet": sheet,
                     "added": sorted(c for c in hrows if c not in brows),
                     "removed": sorted(c for c in brows if c not in hrows), "changed": []}
            for code in sorted(c for c in hrows if c in brows and hrows[c] != brows[c]):
                old = dict(zip(bh, brows[code]))
                new = dict(zip(hh, hrows[code]))
                cols = [(col, old.get(col, ""), new.get(col, "")) for col in hh if old.get(col, "") != new.get(col, "")]
                cols += [(col, old[col], "") for col in bh if col not in new and old[col]]
                entry["changed"].append((code, cols))
            if entry["added"] or entry["removed"] or entry["changed"]:
                out.append(entry)
    return out


def suite_changes(base_tree: str, head_tree: str, suite_rel: str, source_root: str) -> list[dict]:
    """Per suite the branch changed: scenarios before -> after, and its new entries that add nothing
    (already covered by the suite) or match no test. Uses the vendored suite-builder engine."""
    import suite as suites
    base_path, head_path = os.path.join(base_tree, suite_rel), os.path.join(head_tree, suite_rel)
    if not os.path.isfile(head_path):
        return []
    base_doc = suites.load_suites(base_path)[0] if os.path.isfile(base_path) else {"CenterTestSuites": []}
    head_doc = suites.load_suites(head_path)[0]
    base_tests, head_tests = suites.scan(base_tree, source_root), suites.scan(head_tree, source_root)
    head_scen = suites.scenarios_of(head_tests)
    out = []
    names = [str(s.get("Name", "")) for s in head_doc["CenterTestSuites"]]
    gone = [str(s.get("Name", "")) for s in base_doc["CenterTestSuites"] if not suites.find(head_doc, str(s.get("Name", "")))]
    for name in names + gone:
        b = suites.find(base_doc, name)
        h = suites.find(head_doc, name)
        if b == h:
            continue
        before = suites.resolve_suite(base_doc, name, base_tests)["scenarios"] if b else set()
        after = suites.resolve_suite(head_doc, name, head_tests)["scenarios"] if h else set()
        old_entries = (b or {}).get("List", []) or []
        new_entries = [e for e in (h or {}).get("List", []) or [] if e not in old_entries or
                       (h or {}).get("List", []).count(e) > old_entries.count(e)]
        adds_nothing, dead = [], []
        entries = (h or {}).get("List", []) or []
        earlier: set = set()
        seen_new = set()
        for i, e in enumerate(entries):
            hit = set(suites.resolve_entry(e, head_scen))
            # a new entry is redundant when entries before it already run all of it (first one wins)
            is_new = e in new_entries and (e not in old_entries or entries[:i].count(e) >= old_entries.count(e))
            if is_new and e not in seen_new:
                if not hit:
                    dead.append(e)
                elif hit <= earlier:
                    adds_nothing.append(e)
                seen_new.add(e)
            earlier |= hit
        out.append({"suite": name, "status": "new" if not b else "deleted" if not h else "changed",
                    "before": len(before), "after": len(after),
                    "added": sorted(after - before), "removed": sorted(before - after),
                    "adds_nothing": adds_nothing, "dead": dead})
    return out


def changed_codes(base_tree: str, head_tree: str, rel: str) -> dict[str, set[str]]:
    """{sheet: codes added or changed} between the two versions of a workbook."""
    base, head = _sheet_rows(os.path.join(base_tree, rel)), _sheet_rows(os.path.join(head_tree, rel))
    out = {}
    for sheet, rows in head.items():
        before = base.get(sheet, {})
        codes = {c for c, values in rows.items() if before.get(c) != values}
        if codes:
            out[sheet] = codes
    return out


def _dc_rows_using(head_tree: str, sheet_codes: dict[str, set[str]]) -> dict[str, set[str]]:
    """{DC rel path: DC codes} for DataCombination rows whose #Ref / @Rel.#Ref cells name a changed code."""
    import ddt_refcheck
    from ddt_refcheck import load_workbook
    wanted = {ddt_refcheck._norm_sheet(s): codes for s, codes in sheet_codes.items()}
    out: dict[str, set[str]] = {}
    previous = os.getcwd()
    try:
        os.chdir(head_tree)
        for dc in ddt_refcheck.find_all_dc_files():
            try:
                wb = load_workbook(dc, read_only=True, data_only=True)
            except Exception:
                continue
            sheet = next((n for n in wb.sheetnames if n.lower() == "datacombination"), None)
            rows = [r for r in wb[sheet].iter_rows(values_only=True) if any(c not in (None, "") for c in r)] if sheet else []
            wb.close()
            if not rows:
                continue
            headers = [ddt_refcheck.format_value(h) for h in rows[0]]
            refs, _rels, hops = ddt_refcheck.classify_headers(headers)
            columns = [(headers.index(c), ddt_refcheck._norm_sheet(c[1:])) for c in refs]
            columns += [(headers.index(c), s) for c, _r, s in hops]
            ci = next((i for i, h in enumerate(headers) if h.lower() == "code"), None)
            for r in rows[1:]:
                for i, key in columns:
                    cell = ddt_refcheck.format_value(r[i]) if i < len(r) else ""
                    if key in wanted and {c.strip().lower() for c in cell.split(",")} & {w.lower() for w in wanted[key]}:
                        if ci is not None and ci < len(r) and r[ci] not in (None, ""):
                            out.setdefault(dc, set()).add(str(r[ci]).strip())
    finally:
        os.chdir(previous)
    return out


_DATASOURCE = re.compile(r'datasource\s*=\s*"([^"]+)"')


def _reading_methods(classes: set, sources: dict, names: set) -> dict:
    """{class: its methods whose body names the workbook} -- only those pass a data change on. A class
    that names it outside every method (a field, an annotation) is left out: changed as a whole."""
    if not names:
        return {}
    pattern = re.compile("|".join(r"(?<![\w/])" + re.escape(n) + r"(?![\w])" for n in sorted(names, key=len, reverse=True)))
    out = {}
    for cls in classes:
        text = re.sub(r"^\s*(?:import|package)\s[^;]*;", "", sources[cls][1], flags=re.M)
        # each method with its declaration line: a DC type is often a parameter
        methods = [(m.group(1), text[text.rfind("\n", 0, m.start() + len(m.group(0)) - len(m.group(0).lstrip())) + 1:end])
                   for m, end in ((m, _body_end(text, m.end())) for m in _METHOD_DECL.finditer(text))
                   if m.group(1) not in _NOT_METHODS]
        hits = {name for name, body in methods if pattern.search(body)}
        if hits and len(pattern.findall(text)) == sum(len(pattern.findall(b)) for n, b in methods if n in hits):
            out[cls] = hits
    return out


def rerun_plan(base_tree: str, head_tree: str, changed: list[str], source_root: str) -> list[dict]:
    """[{test, codes (sorted, empty = whole test), reasons}] sorted by test name."""
    from rules.rule_ddt import _workbook_users
    sources = _java_sources(head_tree, source_root)
    plan: dict[str, dict] = {}

    def add(test, reason, codes=None):
        entry = plan.setdefault(test, {"test": test, "codes": set(), "whole": False, "reasons": []})
        if codes:
            entry["codes"].update(codes)
        else:
            entry["whole"] = True
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    java = {os.path.basename(p)[:-5] for p in changed if p.endswith(".java")}
    for test, via in tests_reaching(java & set(sources), sources).items():
        add(test, f"{via}.java changed" if via != test else "test changed")

    dc_codes: dict[str, set[str]] = {}
    for rel in (p for p in changed if p.startswith("testdata/") and p.endswith(".xlsx")):
        changes = changed_codes(base_tree, head_tree, rel)
        if rel.endswith("DC.xlsx"):
            codes = changes.get(next((s for s in changes if s.lower() == "datacombination"), ""), set())
            if codes:
                dc_codes.setdefault(rel, set()).update(codes)
            other = {s: c for s, c in changes.items() if s.lower() != "datacombination"}
            if other:
                for dc, codes in _dc_rows_using(head_tree, other).items():
                    dc_codes.setdefault(dc, set()).update(codes)
        elif changes:
            for dc, codes in _dc_rows_using(head_tree, changes).items():
                dc_codes.setdefault(dc, set()).update(codes)

    if dc_codes:
        from rules.rule_ddt import _workbook_tokens
        users = _workbook_users(head_tree, source_root)
        tokens = _workbook_tokens(head_tree, source_root)
        for dc, codes in dc_codes.items():
            readers = users.get(dc, [])
            tests = {c for c in readers if c in sources and _is_test(sources[c][1])}
            steps = (set(readers) - tests) & set(sources)
            tests |= set(tests_reaching(steps, sources, _reading_methods(steps, sources, tokens.get(dc, set()))))
            for test in tests:
                # row codes filter only the test whose own datasource is this workbook; a test that
                # reaches it through a step or an @Rel column runs its own rows: rerun it whole
                own = dc in _DATASOURCE.findall(sources[test][1])
                add(test, f"{os.path.basename(dc)} rows changed", codes if own else None)

    result = []
    for entry in sorted(plan.values(), key=lambda e: e["test"]):
        result.append({"test": entry["test"], "codes": [] if entry["whole"] else sorted(entry["codes"]),
                       "reasons": entry["reasons"]})
    return result


def run_commands(repo_dir: str) -> tuple[bool, bool]:
    """Whether the project's build.gradle forwards -PcenterTest and -Pfilter (as a column filter)."""
    try:
        with open(os.path.join(repo_dir, "build.gradle"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return False, False
    return ("hasProperty('centerTest')" in text or 'hasProperty("centerTest")' in text,
            "centertest.runtime.filter.column" in text)


def rerun_suite(head_tree: str, rerun: list[dict], source_root: str) -> tuple[list[str], list[str]]:
    """(suite entries that run exactly the rerun plan's scenarios -- a whole test, or only its changed
    rows -- written by the vendored suite-builder engine, so one bootRun replaces one per test;
    planned tests that run no scenario, e.g. every row disabled)."""
    import suite as suites
    plan = {e["test"]: e for e in rerun}
    tests = [t for t in suites.scan(head_tree, source_root) if t["class"] in plan]
    selected = {(cls, method, code) for cls, method, code in suites.scenarios_of(tests)
                if not plan[cls]["codes"] or code in plan[cls]["codes"]}
    idle = sorted(set(plan) - {cls for cls, _, _ in selected})
    return suites.compact(selected, tests), idle


def suite_command(repo_dir: str, name: str) -> str:
    """How to run one suite: -PsuiteFilter when build.gradle forwards it, else CenterTest's variable."""
    try:
        with open(os.path.join(repo_dir, "build.gradle"), encoding="utf-8", errors="replace") as fh:
            forwards = "suiteFilter" in fh.read()
    except OSError:
        forwards = False
    return (f"./gradlew bootRun -PsuiteFilter={name}" if forwards
            else f"CENTERTESTFILTERCENTERTESTSUITE={name} ./gradlew bootRun")


def command_for(entry: dict, forwards: tuple[bool, bool]) -> str | None:
    """The bootRun command for a plan entry, when the project's build forwards what it needs."""
    test_ok, filter_ok = forwards
    if not test_ok:
        return None
    cmd = f'./gradlew bootRun -PcenterTest="{entry["test"]} run"'
    if entry["codes"]:
        if not filter_ok:
            return None
        cmd += ' -Pfilter="Code=^(' + "|".join(re.escape(c) for c in entry["codes"]) + ')$"'
    return cmd
