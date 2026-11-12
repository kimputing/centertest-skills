"""
Widget rules (issue #47): raw ids, selectors and display texts where the generated project already
offers a getter or a typelist constant.

20001 -- Raw CSS id where a generated getter exists
20002 -- CSS selector passed as a widget id
20003 -- Same raw id or selector in several files
20004 -- Typelist set by display text when a TC_ constant exists

Framework facts (centertest-platform, read only):
  * A widget finds its element by id: AbstractWidget.getById -> Browser.findAllElementsById, i.e.
    By.id(...) / //*[@id='...']. A CSS selector given as the id never matches -- except WidgetLabel,
    whose getWebElementInternal() falls back to findAllElementsByCss(id) on purpose, so a selector
    there works and 20002 leaves it alone.
  * The generated cssids (src/main/resources/cssids/<app>/<Page>.properties) map each PCF id to
    its getter chain; the vendored find_getter.py reads them as cssid-finder does.
  * The generated typelists live in src/main/java/<pkg>/generated/typelist/<app>/: TC_<Name>
    (`public static TC_X Code() { return new TC_X("code", "Display", retired); }`) and the
    WidgetTypeKey(Input|Cell)<Name> widgets the pages return, whose set(TC_<Name>) sets the
    description -- so set("Display") and set(TC_X.Code()) do the same, but only the constant
    survives a renamed display text and is checked by the compiler.
"""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, SourceCodeFile
from eir_rules import rule
from rule_helpers import ProjectIndex, generated_resources, latest_files, location, scanned_classes, snippet
from rules.rule_flakiness import _Spans, _close, _files, _line, _mask, _sorted_rows

_HEADERS = ["Class", "Method", "Line", "Issue", "Location"]
_NO_GENERATED = "needs the generated project (--cssids or <project>-generated)"

# Widget id arguments: Widget*.get("id", ctx), new TableSortable("id", ...), .withCssId("id")
_CALL = re.compile(r"\b(Widget\w*)\s*\.\s*get\s*\(|\bnew\s+(TableSortable)\s*\(|\.\s*(withCssId)\s*\(")
_PCF_ID = re.compile(r"^[A-Za-z_$][\w$]*(?:[-:][\w$#\[\]]+)+$")
_JUSTIFIED = re.compile(r"TODO|FIXME|no\s+(?:generated\s+)?getters?|getters?\s+(?:is\s+|are\s+)?(?:missing|wrong|broken)"
                        r"|not\s+generated|live\s+(?:one|ids?)\b", re.IGNORECASE)
_CONST_DECL = re.compile(r"^\s*(?:(?:public|private|protected|static|final)\s+)+[\w<>\[\]]+\s+\w+\s*=")
_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def _is_selector(value: str) -> bool:
    """A CSS selector rather than a PCF id: starts with # or ., holds whitespace or a combinator,
    an attribute selector [x=...], or starts with an HTML tag followed by . # or [. Guidewire's own
    [X_tb] toolbar segments and [ROW] are PCF id syntax, not selectors."""
    v = value.strip()
    if not v:
        return False
    if re.match(r"[#.][A-Za-z_-]", v):
        return True
    if re.search(r"\[[\w-]+\s*[~|^$*]?=", v):
        return True
    if re.match(r"(?:div|span|a|input|button|table|tbody|tr|td|th|li|ul|label|select|textarea)[.#\[:]", v):
        return True
    # a descendant / child combinator between selector-like parts ("#panel .title", "div > span")
    return bool(re.search(r"[\w\])](?:\s*>\s*|\s+)[#.\[]?[A-Za-z]", v)) and bool(re.search(r"[#.>\[]", v)) \
        and not re.search(r"[a-z]\.\s", v)


def _first_arg(code: str, text: str, open_paren: int) -> tuple[str, int]:
    """(source text of the first argument, its start offset) of the call whose '(' is at open_paren."""
    end = _close(code, open_paren) - 1
    depth, i = 0, open_paren + 1
    while i < end:
        c = code[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            break
        i += 1
    return text[open_paren + 1:i].strip(), open_paren + 1


def _split_plus(expr: str) -> list[str]:
    masked = _mask(expr)
    parts, depth, last = [], 0, 0
    for i, c in enumerate(masked):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "+" and depth == 0:
            parts.append(expr[last:i].strip())
            last = i + 1
    parts.append(expr[last:].strip())
    return parts


class _Constants:
    """String constants visible from a class: its own fields, its file's other classes, project
    superclasses, and `Other.NAME` through the project index."""

    def __init__(self, files: list[SourceCodeFile]):
        self.index = ProjectIndex(files)
        self.by_class: dict[int, dict[str, tuple]] = {}

    def _fields(self, f: SourceCodeFile, ce) -> dict[str, tuple]:
        key = id(ce)
        if key not in self.by_class:
            own = {}
            for fl in ce.fields:
                if fl.initializer and (fl.type == "String" or ce.kind == "interface"):
                    if "final" in fl.modifiers or ce.kind == "interface":
                        own[fl.name] = (f, ce, fl)
            self.by_class[key] = own
        return self.by_class[key]

    def lookup(self, f: SourceCodeFile, ce, name: str):
        if "." in name:
            owner, _, attr = name.rpartition(".")
            hit = self.index.by_name.get(owner.split(".")[-1])
            return self._fields(hit[0], hit[1]).get(attr) if hit else None
        chain = [(f, ce)]
        chain += [(f, c) for _, c in scanned_classes(f) if c is not ce]
        for anc in self.index.ancestors(ce):
            hit = self.index.by_name.get(anc.class_name)
            if hit:
                chain.append(hit)
        for fi, c in chain:
            got = self._fields(fi, c).get(name)
            if got:
                return got
        return None

    def resolve(self, f: SourceCodeFile, ce, expr: str, depth: int = 0):
        """(value, constants used [(file, field)], only literals) for a + concatenation of string
        literals and constants; None when any part is something else."""
        if depth > 5 or not expr:
            return None
        value, used, literal_only = "", [], True
        for part in _split_plus(expr):
            lit = re.fullmatch(r'"((?:[^"\\\n]|\\.)*)"', part)
            if lit:
                value += _unescape(lit.group(1))
                continue
            if not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", part):
                return None
            const = self.lookup(f, ce, part)
            if const is None:
                return None
            cf, cce, fl = const
            inner = self.resolve(cf, cce, fl.initializer, depth + 1)
            if inner is None:
                return None
            value += inner[0]
            used += [(cf, fl)] + inner[1]
            literal_only = False
        return value, used, literal_only


def _justified(source_lines: list[str], line: int, walk_constants: bool = False) -> bool:
    """A TODO / "no getter" comment on the line itself, or in the comment block directly above it
    (above a run of constant declarations when walk_constants)."""
    if 0 < line <= len(source_lines) and "//" in source_lines[line - 1] \
            and _JUSTIFIED.search(source_lines[line - 1].split("//", 1)[1]):
        return True
    i = line - 2
    while i >= 0:
        s = source_lines[i].strip()
        if s.startswith(("//", "/*", "*")):
            if _JUSTIFIED.search(s):
                return True
            i -= 1
            continue
        if walk_constants and _CONST_DECL.match(source_lines[i]):
            i -= 1
            continue
        break
    return False


def _statement_line(code: str, offset: int) -> int:
    """Line where the statement holding `offset` starts (after the previous ; { or })."""
    start = max(code.rfind(";", 0, offset), code.rfind("{", 0, offset), code.rfind("}", 0, offset)) + 1
    while start < offset and code[start].isspace():
        start += 1
    return _line(code, start)


def _last_getter(chain: str) -> str:
    """Last getter of a cssids hierarchy path, with [X_tb] segments dropped: 'getAddDriver'."""
    getters = re.findall(r"\.(get[\w\[\]]*)\(", chain)
    return re.sub(r"\[[^\]]*\]", "", getters[-1]) if getters else ""


def _calls(f: SourceCodeFile):
    """(line, widget class or 'withCssId'/'TableSortable', argument text, receiver getter of a
    withCssId, statement start line) for every widget id call."""
    code = _mask(f.source)
    text = f.source
    for m in _CALL.finditer(code):
        kind = m.group(1) or m.group(2) or m.group(3)
        open_paren = m.end() - 1
        arg, _ = _first_arg(code, text, open_paren)
        receiver = ""
        if kind == "withCssId":
            what, name = _receiver(code, m.start())
            receiver = name if what == "getter" else ""
        yield _line(code, m.start()), kind, arg, receiver, _statement_line(code, m.start())


def _string_constants(f: SourceCodeFile):
    """(class, field) for String constants with an initializer, in the file's classes."""
    for _, ce in scanned_classes(f):
        for fl in ce.fields:
            if fl.initializer and fl.type == "String" and "final" in fl.modifiers and fl.line:
                yield ce, fl
    for ce in f.other_types:
        for fl in ce.fields:
            if fl.initializer and fl.type == "String" and fl.line:
                yield ce, fl


def _const_row(f, ce, fl, issue, config) -> list:
    lines = f.source.splitlines()
    text = lines[fl.line - 1] if 0 < fl.line <= len(lines) else ""
    return [ce.class_name, f"field {fl.name}", snippet(text), issue, location(f, fl.line, config)]


def _call_row(f, spans: _Spans, line: int, issue: str, config) -> list | None:
    hit = spans.at(line)
    lines = f.source.splitlines()
    text = lines[line - 1] if 0 < line <= len(lines) else ""
    if hit is None:
        mc = f.main_class
        return [mc.class_name if mc else f.file_name, "", snippet(text), issue, location(f, line, config)]
    return [hit[0], hit[2].name, snippet(text), issue, location(f, line, config)]


def _class_at(f: SourceCodeFile, spans: _Spans, line: int):
    hit = spans.at(line)
    return hit[1] if hit else f.main_class


def _threshold(config, rule_id: str, default: int) -> int:
    getter = getattr(config, "get_threshold", None)
    try:
        return int(getter(rule_id, default)) if getter else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 20001 -- Raw CSS id where a generated getter exists
# ---------------------------------------------------------------------------

class _GetterLookup:
    """Exact getter chains for a PCF id in the generated cssids (vendored find_getter.py)."""

    def __init__(self, cssids_dir: str):
        import find_getter
        self.fg = find_getter
        roots = [cssids_dir, os.path.dirname(os.path.abspath(cssids_dir))]
        self.layouts = []
        for app in ("pc", "bc", "cc", "ab"):
            for r in roots:
                layout, path = find_getter.detect_layout(r, app)
                if layout:
                    self.layouts.append((layout, path))
                    break
        self.cache: dict[str, list[str]] = {}

    def chains(self, widget_id: str) -> list[str]:
        if widget_id not in self.cache:
            found = []
            for layout, path in self.layouts:
                for form in self.fg.normalize_css_id(widget_id):
                    try:
                        hits = (self.fg.search_properties(path, form, exact_only=True) if layout == "properties"
                                else self.fg.search_legacy(path, form))
                    except OSError:
                        hits = []
                    if hits:
                        found += hits
                        break
                if found:
                    break
            self.cache[widget_id] = list(dict.fromkeys(found))
        return self.cache[widget_id]


def _chain_text(chains: list[str]) -> str:
    more = f" (+{len(chains) - 1} more)" if len(chains) > 1 else ""
    return chains[0] + more


@rule(id="20001", description="Raw CSS id where a generated getter exists", category="Widgets")
def raw_id_with_generated_getter(commits: CommitsDict, config) -> RuleResult:
    """
    A widget built from a raw PCF id -- `Widget*.get("id", ctx)`, `new TableSortable("id", ...)`,
    `.withCssId("id")`, or a String constant holding such an id -- where the generated cssids
    resolve that exact id (iterator/row indices normalized as cssid-finder does) to a getter chain.
    The Issue names the chain. A raw id breaks silently when the PCF changes; the getter fails to
    compile after regeneration instead.

    Ids are resolved through literals and `CONST + "suffix"` concatenations of String constants
    (own class, same file, project superclasses). Guards: exact matches only (a partial match is
    no proof a getter exists); a TODO / "no getter" comment on the line or in the comment block
    above the line or its statement (above a run of constant declarations, for constants) accepts
    the raw id; `getX().withCssId(id)` where the id's own getter IS getX is a deliberate override of
    a generated id that does not resolve at runtime (e.g. an unresolved [X_tb] segment) and is
    skipped, also through a constant; a call whose argument is just a constant is reported once, at
    the constant. Without the generated project
    the rule reports an error instead of findings.
    """
    result = RuleResult(rule_id="20001", description="Raw CSS id where a generated getter exists",
                        category="Widgets", headers=list(_HEADERS))
    cssids = generated_resources(config)
    if not cssids:
        result.error = _NO_GENERATED
        return result
    lookup = _GetterLookup(cssids)
    if not lookup.layouts:
        result.error = _NO_GENERATED
        return result
    constants = _Constants(latest_files(commits))
    for f in _files(commits):
        lines = f.source.splitlines()
        spans = _Spans(f)
        calls = list(_calls(f))
        # a constant used to re-point the very getter it resolves to (getX().withCssId(CONST)) is a
        # deliberate override of a generated id that does not work at runtime
        overrides: dict[str, set[str]] = {}
        for _line_no, kind, arg, receiver, _stmt in calls:
            if kind == "withCssId" and receiver and re.fullmatch(r"[A-Za-z_$][\w$]*", arg):
                overrides.setdefault(arg, set()).add(receiver)
        for ce, fl in _string_constants(f):
            resolved = constants.resolve(f, ce, fl.initializer)
            if not resolved or not _PCF_ID.match(resolved[0]) or _is_selector(resolved[0]):
                continue
            chains = lookup.chains(resolved[0])
            if not chains or _justified(lines, fl.line, walk_constants=True):
                continue
            if overrides.get(fl.name) and overrides[fl.name] & {_last_getter(c) for c in chains}:
                continue
            result.rows.append(_const_row(f, ce, fl, (
                f"The constant holds a raw widget id that has a generated getter, {_chain_text(chains)}, "
                "so a PCF change breaks it silently instead of failing to compile."), config))
        for line, kind, arg, receiver, stmt_line in calls:
            if re.fullmatch(r"[A-Za-z_$][\w$.]*", arg):
                continue  # a bare constant: reported at the constant
            ce = _class_at(f, spans, line)
            resolved = constants.resolve(f, ce, arg) if ce is not None else None
            if not resolved or not _PCF_ID.match(resolved[0]) or _is_selector(resolved[0]):
                continue
            chains = lookup.chains(resolved[0])
            if not chains or _justified(lines, line) or _justified(lines, stmt_line):
                continue
            if receiver and receiver in {_last_getter(c) for c in chains}:
                continue  # getX().withCssId(id of getX): a deliberate override of the generated id
            if any(_justified(cf.source.splitlines(), cfl.line, walk_constants=True) for cf, cfl in resolved[1]):
                continue
            row = _call_row(f, spans, line, (
                f"{kind} is built from a raw id that has a generated getter, {_chain_text(chains)}, "
                "so a PCF change breaks it silently instead of failing to compile."), config)
            result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result


# ---------------------------------------------------------------------------
# 20002 -- CSS selector passed as a widget id
# ---------------------------------------------------------------------------

@rule(id="20002", description="CSS selector passed as a widget id", category="Widgets")
def selector_as_widget_id(commits: CommitsDict, config) -> RuleResult:
    """
    A widget id argument (Widget*.get, new TableSortable, .withCssId; literal, constant or
    concatenation) that is a CSS selector, not a PCF id: it starts with # or ., contains whitespace
    or >, an attribute selector [x="..."], or starts with an HTML tag and . # [. Widgets look their
    element up by id (By.id / //*[@id='...']), so such a widget is never found.

    Guards: WidgetLabel is skipped -- it falls back to a CSS lookup on purpose (WidgetLabel.
    getWebElementInternal), so a selector there works; Guidewire [X_tb] / [ROW] segments are id
    syntax; only Widget* classes (not PortalWidget*) are matched.
    """
    result = RuleResult(rule_id="20002", description="CSS selector passed as a widget id",
                        category="Widgets", headers=list(_HEADERS))
    constants = _Constants(latest_files(commits))
    for f in _files(commits):
        spans = _Spans(f)
        for line, kind, arg, receiver, stmt_line in _calls(f):
            if kind == "WidgetLabel":
                continue
            ce = _class_at(f, spans, line)
            resolved = constants.resolve(f, ce, arg) if ce is not None else None
            if not resolved or not _is_selector(resolved[0]):
                continue
            row = _call_row(f, spans, line, (
                f'"{resolved[0][:60]}" is a CSS selector, but {kind} looks its element up by id, '
                "so the widget is never found; use the generated getter or the element's PCF id."), config)
            result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result


# ---------------------------------------------------------------------------
# 20003 -- Same raw id or selector in several files
# ---------------------------------------------------------------------------

@rule(id="20003", description="Same raw id or selector in several files", category="Widgets")
def same_raw_id_in_several_files(commits: CommitsDict, config) -> RuleResult:
    """
    The same raw widget id or selector string literal -- written as the whole id argument of a
    widget call, or as the initializer of a String constant -- in at least N files (threshold
    20003, default 2). Ids shorter than 30 characters, or not PCF-shaped / selector-shaped, are
    ignored. One row per id, at its first occurrence, naming the other files: the id should live in
    one place (a getter, a shared constant, or a step that takes the prefix).

    Guards: only literals written in the file count -- a call that uses a constant declared
    elsewhere is the sharing this rule asks for, and concatenations are left out.
    """
    result = RuleResult(rule_id="20003", description="Same raw id or selector in several files",
                        category="Widgets", headers=list(_HEADERS))
    min_files = max(2, _threshold(config, "20003", 2))
    seen: dict[str, dict[str, tuple]] = {}
    for f in _files(commits):
        spans = _Spans(f)
        found = []
        for line, kind, arg, receiver, stmt_line in _calls(f):
            lit = re.fullmatch(r'"((?:[^"\\\n]|\\.)*)"', arg)
            if lit:
                found.append((line, _unescape(lit.group(1)), None))
        for ce, fl in _string_constants(f):
            lit = re.fullmatch(r'"((?:[^"\\\n]|\\.)*)"', fl.initializer.strip())
            if lit:
                found.append((fl.line, _unescape(lit.group(1)), (ce, fl)))
        for line, value, const in sorted(found, key=lambda x: x[0]):
            if len(value) < 30 or not (_PCF_ID.match(value) or _is_selector(value)):
                continue
            seen.setdefault(value, {}).setdefault(f.key, (f, spans, line, const))
    for value, by_file in sorted(seen.items()):
        if len(by_file) < min_files:
            continue
        ordered = [by_file[k] for k in sorted(by_file)]
        f, spans, line, const = ordered[0]
        others = ", ".join(f"{o[0].file_name}:{o[2]}" for o in ordered[1:])
        issue = (f"The same raw id is written in {len(ordered)} files (also {others}), so a PCF change must be "
                 "found and fixed in each; keep it in one getter, constant or step.")
        row = _const_row(f, const[0], const[1], issue, config) if const else _call_row(f, spans, line, issue, config)
        result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result


# ---------------------------------------------------------------------------
# 20004 -- Typelist set by display text when a TC_ constant exists
# ---------------------------------------------------------------------------

_SET_CALL = re.compile(r"\.\s*(get\w+)\s*\(\s*\)\s*\.\s*set\s*\(")
_TYPEKEY = re.compile(r"^WidgetTypeKey(?:Input|Cell)(\w+)$")
_PAGE_DECL = re.compile(r"^public (?:final |static |abstract )*(?:class (\w+)|([\w.<>]+) (get\w+)\()", re.M)
_TC_VALUE = re.compile(r'public static TC_\w+ (\w+)\(\)\s*\{\s*return new TC_\w+\("((?:[^"\\]|\\.)*)",\s*'
                       r'"((?:[^"\\]|\\.)*)",\s*(true|false)\)')


def _generated_java(cssids: str) -> str:
    resources = os.path.abspath(cssids)
    if os.path.basename(resources) == "cssids":
        resources = os.path.dirname(resources)
    return os.path.join(os.path.dirname(resources), "java")


class _Generated:
    """Getter declarations of the generated pages (only the names asked for) and TC_ typelists."""

    def __init__(self, java_dir: str, names: set[str]):
        self.java = java_dir
        self.decls: dict[str, list[tuple[str, str, str]]] = {}   # getter -> [(app, class, return type)]
        self.typelist_dirs: dict[str, str] = {}
        for d in glob.glob(os.path.join(java_dir, "**", "typelist", "*"), recursive=True):
            if os.path.isdir(d):
                self.typelist_dirs.setdefault(os.path.basename(d), d)
        pages = [d for d in glob.glob(os.path.join(java_dir, "**", "pages"), recursive=True) if os.path.isdir(d)]
        for root_dir in pages:
            for root, _, files in os.walk(root_dir):
                rel = os.path.relpath(root, root_dir).replace("\\", "/")
                app = rel.split("/")[0] if rel != "." else ""
                for name in files:
                    if not name.endswith(".java"):
                        continue
                    try:
                        with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                            text = fh.read()
                    except OSError:
                        continue
                    cls = name[:-5]
                    for m in _PAGE_DECL.finditer(text):
                        if m.group(1):
                            cls = m.group(1)
                        elif m.group(3) in names:
                            self.decls.setdefault(m.group(3), []).append((app, cls, m.group(2)))
        self.tc_cache: dict[tuple[str, str], dict[str, list[tuple[str, bool]]]] = {}

    def returns_in(self, getter: str, classes: set[str] | None) -> list[tuple[str, str]]:
        """[(app, return type)] of `getter`, declared in `classes` (all classes when None)."""
        return [(app, ret) for app, cls, ret in self.decls.get(getter, [])
                if classes is None or cls in classes]

    def classes_returned(self, getter: str) -> set[str]:
        return {re.sub(r"<.*", "", ret).split(".")[-1] for _, _, ret in self.decls.get(getter, [])}

    def typelist(self, app: str, name: str) -> dict[str, list[tuple[str, bool]]]:
        """{display text: [(constant method, retired)]} of TC_<name> in app's typelist package."""
        key = (app, name)
        if key not in self.tc_cache:
            values: dict[str, list[tuple[str, bool]]] = {}
            d = self.typelist_dirs.get(app)
            path = os.path.join(d, f"TC_{name}.java") if d else ""
            if path and os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for method, _code, desc, retired in _TC_VALUE.findall(fh.read()):
                        values.setdefault(_unescape(desc), []).append((method, retired == "true"))
            self.tc_cache[key] = values
        return self.tc_cache[key]


def _receiver(code: str, dot: int) -> tuple[str, str]:
    """What precedes `.getX()` at offset `dot`: ('getter', name) | ('class', Name) | ('var', name) | ('', '')."""
    i = dot - 1
    while i >= 0 and code[i].isspace():
        i -= 1
    if i >= 0 and code[i] == ")":
        depth = 0
        while i >= 0:
            if code[i] == ")":
                depth += 1
            elif code[i] == "(":
                depth -= 1
                if depth == 0:
                    break
            i -= 1
        j = i - 1
        while j >= 0 and code[j].isspace():
            j -= 1
        m = re.search(r"(?:\bnew\s+([\w.]+)|(\w+))\s*$", code[max(0, j - 200):j + 1])
        if not m:
            return "", ""
        if m.group(1):
            return "class", m.group(1).split(".")[-1]
        return ("getter", m.group(2)) if m.group(2).startswith("get") else ("", "")
    m = re.search(r"(\w+)\s*$", code[max(0, i - 200):i + 1])
    return ("var", m.group(1)) if m else ("", "")


def _resolve_var(code: str, method_text: str, name: str, f: SourceCodeFile, ce, index: ProjectIndex):
    """('getter', g) | ('class', C) for a variable: its `name = expr;` in the method, a typed
    parameter/local, or a field of the class or a project superclass."""
    init = None
    for m in re.finditer(r"\b" + re.escape(name) + r"\s*=\s*([^;=][^;]*);", method_text):
        init = m.group(1)
    if init is None:
        for c in [ce] + (index.ancestors(ce) if ce is not None else []):
            for fl in c.fields:
                if fl.name == name:
                    if fl.initializer:
                        init = fl.initializer
                    elif fl.type and fl.type[0].isupper():
                        return "class", fl.type.split(".")[-1]
                    break
            if init:
                break
    if init:
        news = re.search(r"\bnew\s+([\w.]+)\s*\([^;]*$", init)
        getters = re.findall(r"\b(get\w+)\s*\(", init)
        if getters and (not news or init.rfind(getters[-1]) > init.rfind("new ")):
            return "getter", getters[-1]
        if news:
            return "class", news.group(1).split(".")[-1]
        return "", ""
    typed = re.search(r"\b([A-Z][\w.]*)(?:<[^>]*>)?\s+" + re.escape(name) + r"\b", method_text)
    if typed and typed.group(1) not in ("var", "String", "final"):
        return "class", typed.group(1).split(".")[-1]
    return "", ""


@rule(id="20004", description="Typelist set by display text when a TC_ constant exists", category="Widgets")
def typelist_set_by_display_text(commits: CommitsDict, config) -> RuleResult:
    """
    `.getX().set("Display text")` (or a String constant holding it) where getX returns a generated
    WidgetTypeKeyInput<Name>/WidgetTypeKeyCell<Name> and the generated TC_<Name> typelist has a value
    with exactly that display text: the widget has set(TC_<Name>) and the constant should be used --
    it is compile-checked and survives a changed display text.

    Which getX is meant is resolved through the generated pages: the receiver of getX (the getter
    before it, `new Page(...)`, or a variable / field and its initializer or type) gives the page
    classes, and getX's return type in those classes gives the typelist. When the receiver cannot be
    resolved, every generated getX must return the same typelist widget. Guards: a getX returning a
    plain WidgetRangeInput/TextInput is never flagged (it has no TC_ overload); a display text two
    values share is skipped. Without the generated project the rule reports an error.
    """
    result = RuleResult(rule_id="20004", description="Typelist set by display text when a TC_ constant exists",
                        category="Widgets", headers=list(_HEADERS))
    cssids = generated_resources(config)
    java = _generated_java(cssids) if cssids else ""
    if not cssids or not os.path.isdir(java):
        result.error = _NO_GENERATED
        return result
    all_files = latest_files(commits)
    constants = _Constants(all_files)
    index = constants.index
    candidates = []
    for f in _files(commits):
        code = _mask(f.source)
        spans = _Spans(f)
        offsets = [0]
        for ln in code.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(ln))
        for m in _SET_CALL.finditer(code):
            open_paren = m.end() - 1
            end = _close(code, open_paren) - 1
            if "," in code[open_paren + 1:end]:
                continue
            arg = f.source[open_paren + 1:end].strip()
            line = _line(code, m.start())
            hit = spans.at(line)
            if hit is None:
                continue
            resolved = constants.resolve(f, hit[1], arg)
            if not resolved or not resolved[0].strip():
                continue
            kind, name = _receiver(code, m.start())
            if kind == "var":
                method_text = code[offsets[hit[3] - 1]:m.start()]
                kind, name = _resolve_var(code, method_text, name, f, hit[1], index)
            candidates.append((f, spans, line, m.group(1), resolved[0], kind, name))
    if not candidates:
        return result
    names = {c[3] for c in candidates} | {c[6] for c in candidates if c[5] == "getter"}
    gen = _Generated(java, names)
    for f, spans, line, getter, value, kind, name in candidates:
        classes = None
        if kind == "getter":
            classes = gen.classes_returned(name)
        elif kind == "class":
            classes = {name}
        returns = gen.returns_in(getter, classes) if classes else []
        if not returns:
            returns = gen.returns_in(getter, None)
        typelists = set()
        plain = False
        for app, ret in returns:
            tk = _TYPEKEY.match(re.sub(r"<.*", "", ret).split(".")[-1])
            if tk:
                typelists.add((app, tk.group(1)))
            else:
                plain = True
        if plain or len({t for _, t in typelists}) != 1:
            continue
        name_tl = next(iter(typelists))[1]
        matches = set()
        for app, _ in typelists:
            for method, _retired in gen.typelist(app, name_tl).get(value, []):
                matches.add(method)
        if len(matches) != 1:
            continue
        constant = f"TC_{name_tl}.{next(iter(matches))}()"
        issue = (f'{getter}() is a TC_{name_tl} typelist field set by its display text "{value}"; use {constant}, '
                 "which the compiler checks and which survives a changed display text.")
        row = _call_row(f, spans, line, issue, config)
        result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result
