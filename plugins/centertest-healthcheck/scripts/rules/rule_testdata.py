"""
Rules 21001-21006 (category TestData): test data written into Java instead of read from the DC.

21001  Test data hardcoded as constants in a step   (most .set() calls of a step enter constants/literals)
21002  Literal value set beside data-driven lines    (widget.set("x") in a method that also sets DDT values)
21003  Placeholder junk values in code               ("test", "xxx", keyboard mash sent to the app)
21004  Hardcoded policy, job or account number       (a 9-12 digit literal used as a policy/job/... number)
21005  Pinned DDTHelper code missing from its DC     (TRUST: DDTHelper.getX("Code") with no such row)
21006  One province or state hardcoded              (a jurisdiction literal in a multi-jurisdiction project)

Java is read from the parsed model (SourceCodeFile.source). Literals and comments are masked with an
offset-preserving mask (_mask) so a pattern never matches inside a string or a comment, while the
original text at the same offsets still gives the literal's value. Generated code (a `generated`
package; `datadriven` is already excluded by the parser) is never reported.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, SourceCodeFile
from eir_rules import rule
from rule_helpers import (ProjectIndex, all_methods, balanced_end, body_start_line, generated_resources,
                          latest_files, line_of_offset, location, scanned_classes, snippet)

CATEGORY = "TestData"
HEADERS = ["Class", "Method", "Line", "Issue", "Location"]


# ---------------------------------------------------------------------------
# Shared text helpers (private: offset-preserving, unlike rule_helpers.code_only)
# ---------------------------------------------------------------------------

def _mask(text: str) -> str:
    """Comments -> spaces and string/char literal contents -> 'x', newlines and offsets kept.
    `masked[i]` is code exactly where `text[i]` is code."""
    out = list(text)
    i, n = 0, len(text)

    def blank(a, b, ch):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = ch

    while i < n:
        c = text[i]
        if c == '"':
            if text.startswith('"""', i):  # text block
                j = text.find('"""', i + 3)
                j = n if j < 0 else j
                blank(i + 3, j, "x")
                i = j + 3
                continue
            j = i + 1
            while j < n and text[j] not in '"\n':
                j += 2 if text[j] == "\\" else 1
            blank(i + 1, j, "x")
            i = j + 1
            continue
        if c == "'":
            j = i + 1
            while j < n and text[j] not in "'\n":
                j += 2 if text[j] == "\\" else 1
            blank(i + 1, j, "x")
            i = j + 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j, " ")
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j, " ")
            i = j
            continue
        i += 1
    return "".join(out)


_LITERAL = re.compile(r'\s*"((?:[^"\\\n]|\\.)*)"\s*')
_NUMBER = re.compile(r"\s*-?\d+(?:\.\d+)?[lLdDfF]?\s*")


def _literal(arg: str) -> str | None:
    """The value of an argument that is exactly one string literal, else None."""
    m = _LITERAL.fullmatch(arg)
    return m.group(1) if m else None


def _split_args(text: str, masked: str, start: int, end: int) -> list[tuple[str, int]]:
    """Top-level arguments of the call whose argument text is text[start:end]: [(arg text, offset)]."""
    out, depth, a = [], 0, start
    for i in range(start, end):
        ch = masked[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append((text[a:i], a))
            a = i + 1
    if text[a:end].strip() or out:
        out.append((text[a:end], a))
    return out


_CALL = re.compile(r"(?<![\w$])(\w+)\s*\(")


class _Java:
    """One file's text, mask, method spans, literal constants and data-driven variables."""

    def __init__(self, f: SourceCodeFile, idx: ProjectIndex | None = None):
        self.f = f
        self.text = f.source or ""
        self.masked = _mask(self.text)
        self.spans = []  # (start line, end line, display class, method name)
        for cname, _ce, m in all_methods(f):
            start = body_start_line(f, m)
            if start:
                self.spans.append((start, start + max(len(m.body.splitlines()) - 1, 0), cname, m.name))
        self.constants = self._constants(idx)
        self.data_names = self._data_names()

    # -- positions --
    def line(self, offset: int) -> int:
        return line_of_offset(self.text, offset)

    def code_line(self, line: int) -> str:
        lines = self.text.splitlines()
        return snippet(lines[line - 1]) if 0 < line <= len(lines) else ""

    def where(self, line: int) -> tuple[str, str]:
        """(display class, method) enclosing a line; the main class and '(class)' outside methods."""
        best = None
        for s, e, cname, mname in self.spans:
            if s <= line <= e and (best is None or e - s < best[1] - best[0]):
                best = (s, e, cname, mname)
        if best:
            return best[2], best[3]
        mc = self.f.main_class
        return (mc.class_name if mc else self.f.file_name), "(class)"

    # -- calls --
    def dotted(self, off: int) -> bool:
        """Whether the call at off is a member call (`x.name(`), not a bare `name(`."""
        i = off - 1
        while i >= 0 and self.masked[i] in " \t\r\n":
            i -= 1
        return i >= 0 and self.masked[i] == "."

    def calls(self, name_re: re.Pattern):
        """(name, args [(text, offset)], call offset, close offset) for calls whose name matches."""
        for m in _CALL.finditer(self.masked):
            if not name_re.fullmatch(m.group(1)):
                continue
            open_i = m.end() - 1
            close = balanced_end(self.masked, open_i)
            yield m.group(1), _split_args(self.text, self.masked, open_i + 1, close - 1), m.start(), close

    # -- constants --
    _CONST_DECL = re.compile(r'\bfinal\s+(?:static\s+)?String\s+(\w+)\s*=\s*"((?:[^"\\\n]|\\.)*)"\s*;')

    def _constants(self, idx):
        """{name: (value, line)} for final String fields initialised with one literal: the file's own
        (by regex, so a file javalang could not parse still has them) and the project superclasses'."""
        out = {}
        if idx is not None:
            for _n, ce in scanned_classes(self.f):
                for anc in reversed(idx.ancestors(ce)):
                    for fl in anc.fields:
                        value = _literal(fl.initializer or "")
                        if value is not None and "final" in fl.modifiers:
                            out[fl.name] = (value, 0)
        for m in self._CONST_DECL.finditer(self.text):
            if self.masked[m.start()] == self.text[m.start()]:  # not inside a comment or literal
                out[m.group(1)] = (m.group(2), self.line(m.start()))
        return out

    def constant(self, arg: str):
        """(name, value) when an argument is one literal constant (NAME, this.NAME, Cls.NAME)."""
        m = re.fullmatch(r"\s*(?:this\.|[A-Z]\w*\.)?([A-Za-z_]\w*)\s*", arg)
        if m and m.group(1) in self.constants:
            return m.group(1), self.constants[m.group(1)][0]
        return None

    # -- data-driven values --
    def _data_names(self) -> set:
        """Variables holding generated test data: declared with a type imported from a datadriven
        package, assigned from DDTHelper or from another data variable, or named *DDT / *DC."""
        types = {imp.rsplit(".", 1)[-1] for imp in self.f.imports if ".datadriven." in f".{imp}."}
        names = set(re.findall(r"\b(\w+(?:DDT|Ddt|DC|Dc))\b", self.masked))
        if types:
            decl = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(types))) +
                              r")(?:\.\w+)*(?:<[^;(){}]*?>)?\s+(\w+)\s*[=;,):]")
            names |= set(decl.findall(self.masked))
        assign = re.compile(r"\b(?:var|final\s+var|[A-Z]\w*(?:\.\w+)*)\s+(\w+)\s*=\s*([^;]*);")
        for _ in range(2):
            for m in assign.finditer(self.masked):
                rhs = m.group(2)
                if "DDTHelper" in rhs or any(re.search(rf"\b{re.escape(n)}\s*\.", rhs) for n in names):
                    names.add(m.group(1))
        return names

    def is_data(self, arg: str) -> bool:
        """An argument read from the DC: a getter on a data variable, or DDTHelper."""
        if "DDTHelper" in arg:
            return True
        return any(re.search(rf"\b{re.escape(n)}\s*(?:\(\s*\))?\s*\.\s*get\w*\s*\(", arg) for n in self.data_names)


def _is_generated(f: SourceCodeFile) -> bool:
    parts = (f.package_name or "").split(".") + f.key.replace("\\", "/").split("/")
    return "generated" in parts or "datadriven" in parts


def _java_files(commits: CommitsDict):
    return [f for f in latest_files(commits) if f.main_class is not None and not _is_generated(f)]


def _threshold(config, rule_id: str, default: int) -> int:
    fn = getattr(config, "get_threshold", None)
    try:
        return int(fn(rule_id, default)) if fn else default
    except Exception:
        return default


_SET = re.compile(r"set")
_BOOLEAN_LIKE = {"true", "false", "yes", "no"}


def _neutral(arg: str) -> bool:
    """Arguments that are not test data: booleans, null, empty strings, typelist codes (TC_), and menu
    choices of a picker ("New...", "<none>")."""
    s = arg.strip()
    if s in ("true", "false", "null", "Boolean.TRUE", "Boolean.FALSE", ""):
        return True
    value = _literal(arg)
    if value is not None:
        v = value.strip()
        if not v or v.lower() in _BOOLEAN_LIKE or v.endswith(("...", "\u2026", "…")) or re.fullmatch(r"<[\w ]+>", v):
            return True
    return bool(re.match(r"(?:[\w.]*\.)?TC_\w+", s))


def _quote(value: str, limit: int = 40) -> str:
    return '"' + (value if len(value) <= limit else value[: limit - 1] + "…") + '"'


# ---------------------------------------------------------------------------
# 21001 Test data hardcoded as constants in a step
# ---------------------------------------------------------------------------

def _unique_looking(value: str) -> bool:
    """A value that identifies one thing (a VIN, a serial, a licence number), not a choice like "Yes"."""
    v = value.strip()
    if len(v) < 8 or " " in v or not any(c.isdigit() for c in v):
        return False
    if re.fullmatch(r"\d+", v):
        return len(v) >= 9
    return any(c.isalpha() for c in v) and not re.search(r"[/:]", v)


@rule(id="21001", description="Test data hardcoded as constants in a step", category=CATEGORY)
def hardcoded_step_data(commits: CommitsDict, config) -> RuleResult:
    """A reusable step whose `.set(...)` calls mostly enter constants or literals instead of DC values.

    Heuristic: in a step class (ProjectIndex.is_step; tests and generated code excluded) every
    `x.set(arg)` is classified: a string/number literal or a final String constant initialised with one
    literal (own or a superclass's) is hardcoded; booleans, "Yes"/"No", empty strings, null and
    typelist codes (TC_) are neutral; anything else (a DDT getter, Helper data, a variable) is dynamic.
    Flagged when hardcoded >= threshold (default 5) and >= 50% of the non-neutral sets (threshold
    "21001_ratio"). One row per class; a unique-looking value (a VIN, a long number) that another
    class repeats is named, since two steps then enter the same "unique" thing.
    """
    result = RuleResult(rule_id="21001", description="Test data hardcoded as constants in a step",
                        category=CATEGORY, headers=list(HEADERS))
    files = _java_files(commits)
    idx = ProjectIndex(latest_files(commits))
    minimum = _threshold(config, "21001", 5)
    ratio = _threshold(config, "21001_ratio", 50) / 100.0
    texts = {f.key: f.source or "" for f in files}
    for f in sorted(files, key=lambda x: x.key):
        if not idx.is_step(f.main_class):
            continue
        j = _Java(f, idx)
        hard, dynamic = [], 0
        for _name, args, off, _close in j.calls(_SET):
            if len(args) != 1 or not j.dotted(off):
                continue
            arg = args[0][0]
            if _neutral(arg):
                continue
            value = _literal(arg)
            if value is not None or _NUMBER.fullmatch(arg):
                hard.append((off, arg.strip(), value if value is not None else arg.strip()))
                continue
            const = j.constant(arg)
            if const:
                hard.append((off, const[0], const[1]))
            else:
                dynamic += 1
        total = len(hard) + dynamic
        if len(hard) < minimum or not total or len(hard) / total < ratio:
            continue
        names = list(dict.fromkeys(h[1] for h in hard))
        sample = ", ".join(names[:4]) + (", ..." if len(names) > 4 else "")
        shared = ""
        for _off, _n, value in hard:
            if not _unique_looking(value):
                continue
            needle = '"' + value + '"'
            others = sorted(os.path.basename(k)[:-5] for k, t in texts.items() if k != f.key and needle in t)
            if others:
                shared = f"; {_quote(value)} is also hardcoded in {', '.join(others[:2])}" + (
                    f" +{len(others) - 2}" if len(others) > 2 else "")
                break
        first = j.line(hard[0][0])
        result.rows.append([f.main_class.class_name, "(class)", j.code_line(first),
                            f"{len(hard)} of {total} .set() calls enter constants or literals ({sample}), so every "
                            f"scenario that runs this step enters the same data and no DC row can vary it{shared}",
                            location(f, first, config)])
    return result


# ---------------------------------------------------------------------------
# 21002 Literal value set beside data-driven lines
# ---------------------------------------------------------------------------

@rule(id="21002", description="Literal value set beside data-driven lines", category=CATEGORY)
def literal_beside_data(commits: CommitsDict, config) -> RuleResult:
    """`widget.set("literal")` in a method that also sets values read from the DC.

    Heuristic: per method, `.set(arg)` calls with one argument are split into data-driven ones (a
    getter on a variable holding generated test data -- typed with a datadriven import, assigned from
    DDTHelper, or named *DDT/*DC -- or DDTHelper itself) and literal ones (exactly one string literal).
    A literal is reported only when the same method has at least one data-driven set: the author
    reads this screen from the DC, so the literal is a value the DC cannot vary. Booleans, "Yes"/"No",
    empty strings and typelist codes (TC_) are ignored; constants are rule 21001's. Also ignored: a value
    set into a *Reason* widget (a justification typed to get past a validation warning) and a value the
    class name already says (SearchForPersonPC setting the contact type "Person").
    """
    result = RuleResult(rule_id="21002", description="Literal value set beside data-driven lines",
                        category=CATEGORY, headers=list(HEADERS))
    for f in sorted(_java_files(commits), key=lambda x: x.key):
        j = _Java(f)
        per_method: dict[tuple, dict] = {}
        for _name, args, off, _close in j.calls(_SET):
            if len(args) != 1 or not j.dotted(off):
                continue
            arg = args[0][0]
            line = j.line(off)
            where = j.where(line)
            if where[1] == "(class)":
                continue
            slot = per_method.setdefault(where, {"data": 0, "literals": []})
            if j.is_data(arg):
                slot["data"] += 1
            elif not _neutral(arg) and _literal(arg) is not None:
                value = _literal(arg)
                getter = re.search(r"(\w+)\s*\(\s*\)\s*\.$", j.masked[max(0, off - 300):off].rstrip())
                if getter and re.search(r"Reason", getter.group(1)):
                    continue  # a justification typed to get past a warning, not scenario data
                if value.strip().replace(" ", "").lower() in where[0].lower():
                    continue  # the step's own purpose: SearchForPersonPC sets "Person"
                slot["literals"].append((line, value))
        for (cname, mname), slot in per_method.items():
            if not slot["data"]:
                continue
            for line, value in slot["literals"]:
                result.rows.append([cname, mname, j.code_line(line),
                                    f"{_quote(value)} is typed in code while the method's other fields come from "
                                    f"the DC, so every data row enters this same value; add a DC column for it",
                                    location(f, line, config)])
    return result


# ---------------------------------------------------------------------------
# 21003 Placeholder junk values in code
# ---------------------------------------------------------------------------

_JUNK = re.compile(r"(?i)(?:test(?:ing)?\d*|tbd|tba|dummy|foo|foobar|x{3,}|asdf\w*|qwerty\w*|placeholder|"
                   r"lorem ipsum.*|blah+)")
_KEYBOARD = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_VOWELS = set("aeiouy")


def _keyboard_mash(value: str) -> bool:
    """A lower-case letter run nobody would type as data: no vowels to speak of and a long consonant
    run ("vczxbvcxbgffghs"), or five keys in a row of the keyboard ("asdfg", "zxcvb")."""
    v = value.strip()
    if not re.fullmatch(r"[a-z]{6,}", v):
        return False
    if any(row[i:i + 5] in v for row in _KEYBOARD for i in range(len(row) - 4)):
        return True
    vowels = sum(1 for c in v if c in _VOWELS)
    longest = max(len(r) for r in re.findall(r"[^aeiouy]+", v)) if re.search(r"[^aeiouy]", v) else 0
    return len(v) >= 8 and vowels / len(v) <= 0.15 and longest >= 6


def _junk(value: str) -> bool:
    return bool(_JUNK.fullmatch(value.strip())) or _keyboard_mash(value)


# Calls that send a value to the application (widget sets, coverage terms, builders).
_SENDS = re.compile(r"(?:set|with|type|enter|fill|select|sendKeys|input)\w*")
_NOT_SENDS = re.compile(r"(?:setCustom|setUp|setDescription|setName|setCode|setProperty)\w*")


@rule(id="21003", description="Placeholder junk values in code", category=CATEGORY)
def placeholder_values(commits: CommitsDict, config) -> RuleResult:
    """Placeholder values such as "test", "xxx", "asdf", "tbd", "dummy" or keyboard mash sent to the app.

    Heuristic: a string literal is checked when it is an argument of a call that enters data
    (set*/with*/type*/enter*/fill*/select*/sendKeys, not setCustom/setUp/...), or the initialiser of a
    final String constant that such a call uses. Matching is whole-value: "test", "testing", "test1",
    "tbd", "dummy", "foo", "xxx", "asdf...", "qwerty...", "lorem ipsum", or a lower-case keyboard mash
    (5 adjacent keys of one keyboard row, or >= 8 letters, almost no vowels, a run of >= 6 consonants).
    A word that merely contains "test" ("Test Insured", "contest") is never flagged.
    """
    result = RuleResult(rule_id="21003", description="Placeholder junk values in code",
                        category=CATEGORY, headers=list(HEADERS))
    for f in sorted(_java_files(commits), key=lambda x: x.key):
        j = _Java(f)
        seen_lines, used_constants = set(), {}
        for name, args, off, _close in j.calls(_SENDS):
            if _NOT_SENDS.fullmatch(name):
                continue
            for arg, a_off in args:
                value = _literal(arg)
                if value is not None and _junk(value):
                    line = j.line(a_off + len(arg) - len(arg.lstrip()))
                    if line not in seen_lines:
                        seen_lines.add(line)
                        cname, mname = j.where(line)
                        result.rows.append([cname, mname, j.code_line(line),
                                            f"{_quote(value)} is a placeholder typed into the application; it ends "
                                            f"up as data in the environment and tells a reader nothing",
                                            location(f, line, config)])
                    continue
                for ident in re.findall(r"\b[A-Za-z_]\w*\b", j.masked[a_off:a_off + len(arg)]):
                    if ident in j.constants:
                        used_constants.setdefault(ident, name)
        for const, via in sorted(used_constants.items()):
            value, line = j.constants[const]
            if not line or not _junk(value) or line in seen_lines:
                continue
            seen_lines.add(line)
            cname, _m = j.where(line)
            result.rows.append([cname, "(class)", j.code_line(line),
                                f"{const} = {_quote(value)} is a placeholder that {via}() sends to the application; "
                                f"it ends up as data in the environment and tells a reader nothing",
                                location(f, line, config)])
    result.rows.sort(key=lambda r: (r[4].rsplit(":", 1)[0], int(r[4].rsplit(":", 1)[1])))
    return result


# ---------------------------------------------------------------------------
# 21004 Hardcoded policy, job or account number
# ---------------------------------------------------------------------------

_NUMBER_LITERAL = re.compile(r'"(\d{9,12})"')
_BUSINESS_NUMBER = re.compile(r"(?i)(?<!bank)(?<!bank_)(policy|job|account|claim|submission)(?:_?(?:number|num|no|nbr|id))?")


def _statement(masked: str, offset: int) -> tuple[int, int]:
    """Bounds of the statement around an offset: after the previous ; { } and up to the next ;."""
    start = max(masked.rfind(c, 0, offset) for c in ";{}") + 1
    end = masked.find(";", offset)
    return start, (len(masked) if end < 0 else end)


@rule(id="21004", description="Hardcoded policy, job or account number", category=CATEGORY)
def hardcoded_business_number(commits: CommitsDict, config) -> RuleResult:
    """A 9-12 digit string literal used as a policy, job, account, claim or submission number.

    Heuristic: a literal of 9-12 digits whose statement (masked: comments and literals blanked) names a
    policy/job/account/claim/submission identifier -- the variable or constant it is stored in, the
    setter it is passed to, or the widget getter it is set into (getPolicyNumber().set("...")). Bank
    account numbers are not reported here (they are not environment-specific). Such a number exists in
    one environment only, so the test fails everywhere else and once that environment is refreshed.
    """
    result = RuleResult(rule_id="21004", description="Hardcoded policy, job or account number",
                        category=CATEGORY, headers=list(HEADERS))
    for f in sorted(_java_files(commits), key=lambda x: x.key):
        j = _Java(f)
        for m in _NUMBER_LITERAL.finditer(j.text):
            if j.masked[m.start()] != '"' or j.masked[m.start() + 1] != "x":  # inside a comment
                continue
            s, e = _statement(j.masked, m.start())
            words = [w for w in re.findall(r"[A-Za-z_]\w*", j.masked[s:e]) if not re.fullmatch(r"x+", w)]
            hit = next((w for w in words if _BUSINESS_NUMBER.search(w) and "bank" not in w.lower()), None)
            if not hit:
                continue
            line = j.line(m.start())
            cname, mname = j.where(line)
            result.rows.append([cname, mname, j.code_line(line),
                                f'"{m.group(1)}" ({hit}) is a number that exists in one environment only, so the '
                                f"test fails everywhere else and after a refresh; create it in the flow or read it "
                                f"from the DC or Helper data", location(f, line, config)])
    return result


# ---------------------------------------------------------------------------
# 21005 Pinned DDTHelper code missing from its DC  (TRUST)
# ---------------------------------------------------------------------------

_DC_GETTER = re.compile(r'public\s+static\s+[\w.]+\s+(get\w+)\s*\(\s*String\s+\w+\s*\)\s*\{[^\n]*?'
                        r'getExcelInputFileByCode\(\s*"([^"]+)"')
_REF_GETTER = re.compile(r'public\s+static\s+[\w.]+\s+(get\w+)\s*\(\s*String\s+\w+\s*\)\s*\{[^\n]*?'
                         r'provideDataRecordAsExcelInput\(\s*"([^"]+)"\s*,\s*"([^"]+)"')


def _ddthelper_getters(repo_dir: str, source_root: str) -> dict:
    """{getter: ("dc", workbook) | ("ref", workbook, sheet)} from the generated DDTHelper (String overloads)."""
    getters = {}
    for root, _dirs, files in os.walk(os.path.join(repo_dir, source_root or "src/main/java")):
        if "DDTHelper.java" not in files or "datadriven" not in root.replace("\\", "/").split("/"):
            continue
        try:
            with open(os.path.join(root, "DDTHelper.java"), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _DC_GETTER.finditer(text):
            getters.setdefault(m.group(1), ("dc", m.group(2)))
        for m in _REF_GETTER.finditer(text):
            getters.setdefault(m.group(1), ("ref", m.group(2), m.group(3)))
    return getters


def _sheet_codes(path: str) -> dict | None:
    """{sheet key (lower-cased, trimmed, as ExcelDataReader keys it): {codes lower-cased}}; None if unreadable.
    A sheet without a Code column is left out (CenterTest keys no rows there)."""
    from ddt_refcheck import format_value, load_workbook
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return None
    out = {}
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
        if not rows:
            continue
        header = [re.sub(r"\s+", "", format_value(h).lower()) for h in rows[0]]
        if "code" not in header:
            continue
        i = header.index("code")
        out[ws.title.lower().strip()] = {format_value(r[i]).strip().lower() for r in rows[1:]
                                         if i < len(r) and format_value(r[i]).strip()}
    return out


_DDT_CALL = re.compile(r"\bDDTHelper\s*\.\s*(get\w+)\s*\(")


@rule(id="21005", description="Pinned DDTHelper code missing from its DC", category=CATEGORY)
def pinned_code_missing(commits: CommitsDict, config) -> RuleResult:
    """`DDTHelper.getX("Code")` where the workbook that getter reads has no row "Code".

    TRUST rule, zero false positives by construction:
      * the getter's workbook comes from the generated DDTHelper on disk (its `String` overload names
        the file: getExcelInputFileByCode("testdata/...DC.xlsx", code) for a DC, or
        provideDataRecordAsExcelInput("testdata/X.xlsx", "sheet", code) for a reference sheet);
      * the code is one string literal, or a final String constant of the same class (or a superclass)
        initialised with one literal; anything else (a parameter, a DDT field) is skipped;
      * codes match as CenterTest matches them (TestDataProvider.getExcelInputFileByCode: equalsIgnoreCase;
        TestDataUtility.getXlsRecord: lower-cased key), and leniently beyond that: trimmed, an instance
        copy "Coupe(2)" as its record (ddt_refcheck.base_code), and for a reference sheet any workbook's
        sheet of that name (the framework merges reference workbooks into one cache);
      * an unknown getter, a missing workbook or sheet, or a sheet without a Code column is skipped.
    A missing row makes CenterTest throw MISSING_RECORD, so the test cannot run its data.
    """
    result = RuleResult(rule_id="21005", description="Pinned DDTHelper code missing from its DC",
                        category=CATEGORY, headers=list(HEADERS))
    try:
        from ddt_refcheck import base_code
    except ImportError:
        result.error = "openpyxl required to read the DC workbooks"
        return result
    repo = getattr(config, "repository_dir", "") or ""
    getters = _ddthelper_getters(repo, getattr(config, "source_root", "src/main/java"))
    if not getters:
        return result
    files = _java_files(commits)
    idx = ProjectIndex(latest_files(commits))
    books: dict[str, dict | None] = {}

    def codes_of(rel: str):
        if rel not in books:
            path = os.path.join(repo, rel)
            books[rel] = _sheet_codes(path) if os.path.isfile(path) else None
        return books[rel]

    all_sheets = None

    def any_sheet(sheet: str) -> set:
        nonlocal all_sheets
        if all_sheets is None:
            all_sheets = {}
            for root, _d, names in os.walk(os.path.join(repo, "testdata")):
                for name in names:
                    if name.endswith(".xlsx") and not name.startswith("~$"):
                        rel = os.path.relpath(os.path.join(root, name), repo)
                        for key, codes in (codes_of(rel) or {}).items():
                            all_sheets.setdefault(key, set()).update(codes)
        return all_sheets.get(sheet, set())

    for f in sorted(files, key=lambda x: x.key):
        if "DDTHelper" not in (f.source or ""):
            continue
        j = _Java(f, idx)
        for m in _DDT_CALL.finditer(j.masked):
            getter = m.group(1)
            target = getters.get(getter)
            if target is None:
                continue
            open_i = m.end() - 1
            args = _split_args(j.text, j.masked, open_i + 1, balanced_end(j.masked, open_i) - 1)
            if len(args) != 1:
                continue
            code, via = _literal(args[0][0]), ""
            if code is None:
                const = j.constant(args[0][0])
                if not const:
                    continue
                via, code = f" ({const[0]})", const[1]
            wanted = base_code(code).lower()
            if not wanted:
                continue
            book = codes_of(target[1])
            if book is None:
                continue
            if target[0] == "dc":
                sheet = "datacombination"
                if sheet not in book:
                    continue
                present = book[sheet]
            else:
                sheet = target[2].lower().strip()
                if sheet not in book:
                    continue
                present = book[sheet] | any_sheet(sheet)
            if wanted in present or code.strip().lower() in present:
                continue
            line = j.line(m.start())
            cname, mname = j.where(line)
            what = "DataCombination" if target[0] == "dc" else f"sheet {target[2]}"
            result.rows.append([cname, mname, j.code_line(line),
                                f'{getter}("{code}"){via} loads row "{code}", but {target[1]} has no such code in '
                                f"its {what}, so CenterTest throws MISSING_RECORD and the test runs no data",
                                location(f, line, config)])
    return result


# ---------------------------------------------------------------------------
# 21006 One province or state hardcoded
# ---------------------------------------------------------------------------

def _words(identifier: str) -> list[str]:
    """camelCase / snake_case identifier -> lower-case words."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", identifier.replace("_", " "))
    return [w.lower() for w in re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced).split()]


_JURISDICTION_WORDS = {"province", "state", "jurisdiction", "prov", "governinglaw"}


def _about_jurisdiction(identifier: str) -> bool:
    words = _words(identifier)
    return bool(_JURISDICTION_WORDS & set(words)) or "governing" in words and "law" in words


def _covered_jurisdictions(config) -> tuple[dict, set]:
    """({lower-cased code or name: code} of the generated Jurisdiction typelist, {codes the data covers})."""
    try:
        import eir_states
        cssids = generated_resources(config)
        codes = eir_states.jurisdictions(cssids)
        if not codes:
            return {}, set()
        lines = eir_states.state_coverage(getattr(config, "repository_dir", ""), cssids) or []
    except Exception:
        return {}, set()
    covered = set()
    for line in lines:
        covered |= set(line["states"])
    return codes, covered


@rule(id="21006", description="One province or state hardcoded", category=CATEGORY)
def hardcoded_jurisdiction(commits: CommitsDict, config) -> RuleResult:
    """A province/state literal in code, in a project whose data covers two or more jurisdictions.

    Jurisdictions come from the generated TC_Jurisdiction typelist and the DC data (eir_states: the
    State/Jurisdiction cells the enabled scenarios reach); the rule does nothing with fewer than two.
    A literal counts when its value is a jurisdiction code or name (case-insensitive) AND its context
    is about a jurisdiction (a word province/state/jurisdiction in the name):
      * `x.getLicenseProvince().set("Alberta")` -- the widget getter right before .set;
      * `withProvince("AB")`, `setState("ON")` -- the call name;
      * `LICENCE_PROVINCE = "Alberta"` -- a final String constant (reported once, at its declaration).
    A class whose name ends in that jurisdiction's code or contains its name (CreateSubmissionON) is
    jurisdiction-specific by design and skipped.
    """
    result = RuleResult(rule_id="21006", description="One province or state hardcoded",
                        category=CATEGORY, headers=list(HEADERS))
    codes, covered = _covered_jurisdictions(config)
    if len(covered) < 2:
        return result
    shown = ", ".join(sorted(covered)[:8]) + (", ..." if len(covered) > 8 else "")
    for f in sorted(_java_files(commits), key=lambda x: x.key):
        j = _Java(f)
        cls = f.main_class.class_name

        def specific(code: str, value: str) -> bool:
            return cls.endswith(code) or value.lower().replace(" ", "") in cls.lower() and len(value) > 2

        found = {}  # line -> (value, code, context)
        for name, args, off, _close in j.calls(re.compile(r"\w+")):
            if not args:
                continue
            context = None
            if _about_jurisdiction(name):
                context = name
            elif name == "set":
                before = j.masked[max(0, off - 300):off].rstrip()
                g = re.search(r"(\w+)\s*\(\s*\)\s*\.$", before)
                if g and _about_jurisdiction(g.group(1)):
                    context = g.group(1)
            if not context:
                continue
            for arg, a_off in args:
                value = _literal(arg)
                code = codes.get((value or "").strip().lower())
                if code and not specific(code, value.strip()):
                    found.setdefault(j.line(a_off + len(arg) - len(arg.lstrip())), (value.strip(), code, context))
        for const, (value, line) in j.constants.items():
            code = codes.get(value.strip().lower())
            if line and code and _about_jurisdiction(const) and not specific(code, value.strip()):
                found.setdefault(line, (value.strip(), code, const))
        for line in sorted(found):
            value, code, context = found[line]
            cname, mname = j.where(line)
            result.rows.append([cname, mname, j.code_line(line),
                                f"{_quote(value)} ({code}) is fixed in {context} while the data covers {len(covered)} "
                                f"jurisdictions ({shown}), so scenarios for the others run with this one's value; "
                                f"read it from the DC", location(f, line, config)])
    return result
