"""
DeadCode rules (23001-23007): code that is there but never runs, or is never read.

23001 — Commented-out code
23002 — Commented-out annotation
23003 — Commented-out forced failure or debug switch
23004 — if (true) and the code it makes unreachable
23005 — TODO with no ticket
23006 — Debugger anchor statements
23007 — Field never read

Comment rules read the whole file (`SourceCodeFile.source`), since comments outside methods matter
(a commented-out annotation sits above a method). Code rules read method bodies through
rule_exceptions.mask_code (same length, comments and literal contents blanked).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, SourceCodeFile
from eir_rules import rule
from rule_helpers import all_methods, balanced_end, body_start_line, location, scanned_classes, snippet

from .rule_exceptions import body_hit, mask_code, project_files


# ---------------------------------------------------------------------------
# Comments of a file
# ---------------------------------------------------------------------------

@dataclass
class _Comment:
    line: int        # 1-based file line
    text: str        # comment text on that line, markers (// /* * */) removed
    kind: str        # "line" | "block" | "javadoc"
    full_line: bool  # nothing but whitespace before the comment on its line
    group: int       # comment id (a /* */ block, or a single // comment)


def _comments(source: str) -> list[_Comment]:
    """Every comment line of a Java file, string literals and text blocks respected."""
    out: list[_Comment] = []
    i, n, line, gid = 0, len(source), 1, 0
    line_start = 0
    while i < n:
        ch = source[i]
        if ch == "\n":
            line += 1
            line_start = i + 1
            i += 1
            continue
        if source.startswith('"""', i):
            j = source.find('"""', i + 3)
            j = n if j < 0 else j + 3
            line += source.count("\n", i, j)
            k = source.rfind("\n", i, j)
            line_start = k + 1 if k >= 0 else line_start
            i = j
            continue
        if ch in "\"'":
            j = i + 1
            while j < n and source[j] != ch and source[j] != "\n":
                j += 2 if source[j] == "\\" else 1
            i = j + 1 if j < n and source[j] == ch else j
            continue
        if source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            gid += 1
            full = not source[line_start:i].strip()
            out.append(_Comment(line, source[i + 2:j], "line", full, gid))
            i = j
            continue
        if source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            gid += 1
            kind = "javadoc" if source.startswith("/**", i) and not source.startswith("/**/", i) else "block"
            full = not source[line_start:i].strip()
            raw = source[i:j]
            for k, part in enumerate(raw.split("\n")):
                t = part.strip()
                if k == 0:
                    t = t[3:] if kind == "javadoc" else t[2:]
                if t.endswith("*/"):
                    t = t[:-2]
                t = t.strip()
                if k > 0 and t.startswith("*"):
                    t = t[1:]
                out.append(_Comment(line + k, t, kind, full or k > 0, gid))
            line += raw.count("\n")
            k = raw.rfind("\n")
            if k >= 0:
                line_start = i + k + 1
            i = j
            continue
        i += 1
    return out


def _runs(comments: list[_Comment]) -> list[list[_Comment]]:
    """Comment runs: consecutive full-line // comments on consecutive lines, or one /* */ block."""
    runs: list[list[_Comment]] = []
    for c in comments:
        if not c.full_line:
            continue
        prev = runs[-1] if runs else None
        if prev and c.kind == "line" and prev[-1].kind == "line" and c.line == prev[-1].line + 1:
            prev.append(c)
        elif prev and c.kind != "line" and prev[-1].group == c.group:
            prev.append(c)
        else:
            runs.append([c])
    return runs


def _header_end(source: str) -> int:
    """Line of the package statement (or first import/type); comments before it are a file header."""
    for i, line in enumerate(source.splitlines(), 1):
        if re.match(r"\s*(package|import)\s", line) or re.match(r"\s*(public\s+|final\s+|abstract\s+)*(class|interface|enum|record)\s", line):
            return i
    return 0


def _clean(text: str) -> str:
    """Comment text with extra leading slashes (`////`) and whitespace removed."""
    return text.lstrip("/").strip()


# ---------------------------------------------------------------------------
# Where a file line is: enclosing class / method
# ---------------------------------------------------------------------------

def _method_spans(f: SourceCodeFile) -> list[tuple[int, int, str, object]]:
    """[(first line, last line, display class, method)] for every method with a body."""
    spans = []
    for cls, _ce, m in all_methods(f):
        if not m.body:
            continue
        start = body_start_line(f, m)
        if not start:
            continue
        spans.append((m.line or start, start + len(m.body.splitlines()) - 1, cls, m))
    return spans


def _where(f: SourceCodeFile, spans, line: int) -> tuple[str, str]:
    best = None
    for a, b, cls, m in spans:
        if a <= line <= b and (best is None or b - a < best[1] - best[0]):
            best = (a, b, cls, m)
    if best:
        return best[2], best[3].name
    return f.main_class.class_name, ""


# ---------------------------------------------------------------------------
# 23001 — Commented-out code
# ---------------------------------------------------------------------------

_CODE_LINE = [
    re.compile(r";\s*(//.*)?$"),                                    # ends a statement
    re.compile(r"^[{}]|\{\s*$|^\)\s*;?$"),                          # braces
    re.compile(r"^\.\s*[\w$]+\s*\("),                               # chained continuation .click()
    re.compile(r"^[\w$.]+(\s*<[^>]*>)?\s*\(.*\)\s*[.;)]?\s*$"),     # call: foo(...)  a.b.c(...)
    re.compile(r"^(var|final|if|for|while|return|else|try|catch|switch|case|throw|new)\b.*[(=;{]"),
    re.compile(r"^[\w$.<>\[\]]+(\s+[\w$]+)?\s*[+\-*/]?=(?!=)\s*\S"),  # assignment / declaration
    re.compile(r"^(public|private|protected|static|void)\b.*\("),   # method declaration
]


def _code_like(text: str) -> bool:
    t = _clean(text)
    if not t or t.startswith("@") or re.match(r"^(TODO|FIXME|XXX|HACK|NOTE)\b", t):
        return False
    return any(p.search(t) for p in _CODE_LINE)


def _code_blocks(f: SourceCodeFile, min_lines: int = 3) -> list[list[_Comment]]:
    """Comment runs (no Javadoc, no file header) of >= min_lines lines, most of them Java code."""
    header = _header_end(f.source)
    out = []
    for run in _runs(_comments(f.source)):
        if run[0].kind == "javadoc" or run[-1].line < header or len(run) < min_lines:
            continue
        nonempty = [c for c in run if _clean(c.text)]
        code = [c for c in nonempty if _code_like(c.text)]
        if len(code) >= min_lines and len(code) >= 0.6 * len(nonempty):
            out.append(run)
    return out


def _threshold(config, rule_id: str, default):
    getter = getattr(config, "get_threshold", None)
    if getter is None:
        return default
    try:
        return getter(rule_id, default)
    except Exception:
        return default


@rule(id="23001", description="Commented-out code", category="DeadCode")
def commented_out_code(commits: CommitsDict, config) -> RuleResult:
    """
    Runs of 3+ consecutive comment lines (a // run or one /* */ block) where at least 3 lines and
    60% of the non-blank lines read as Java: they end with `;`, open or close a brace, are a call or
    a chained `.call(`, an assignment/declaration, or start with if/for/return/var... One row per
    block, with its length.

    Guards: Javadoc is skipped, and so is a comment before the package/import line (licence
    header); prose lines, annotations and TODO lines do not count as code.
    """
    result = RuleResult(rule_id="23001", description="Commented-out code", category="DeadCode",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    min_lines = int(_threshold(config, "23001", 3))
    for f in project_files(commits):
        spans = None
        for run in _code_blocks(f, min_lines):
            spans = spans if spans is not None else _method_spans(f)
            first = next(c for c in run if _code_like(c.text))
            cls, meth = _where(f, spans, first.line)
            n = run[-1].line - run[0].line + 1
            issue = (f"{n} commented-out lines (lines {run[0].line}-{run[-1].line}): code that never compiles or runs, "
                     f"goes stale and misleads the next reader; delete it, git history keeps it")
            result.rows.append([cls, meth, snippet("// " + _clean(first.text)), issue, location(f, run[0].line, config)])
    return result


def _in_blocks(blocks: list[list[_Comment]], line: int) -> bool:
    return any(b[0].line <= line <= b[-1].line for b in blocks)


# ---------------------------------------------------------------------------
# 23002 — Commented-out annotation
# ---------------------------------------------------------------------------

_ANNOTATION_EFFECT = {
    "DataDriven": "the test no longer reads its workbook rows",
    "CenterTestCase": "the method is no longer discovered as a test (CenterTest runs only @CenterTestCase methods)",
    "CenterTest": "the class is no longer scanned for tests (CenterTest scans @CenterTest classes)",
    "ScenarioContainer": "the class is no longer scanned for scenarios",
    "FlowTags": "the flow is no longer tagged, so flow coverage and tag-based selection miss it",
    "Test": "the JUnit method is no longer run",
    "Disabled": "a test someone disabled runs again",
}
_ANNOTATION_RE = re.compile(r"^@(" + "|".join(sorted(_ANNOTATION_EFFECT, key=len, reverse=True))
                            + r")\b\s*(\(.*\))?\s*(//.*)?$")


@rule(id="23002", description="Commented-out annotation", category="DeadCode")
def commented_out_annotation(commits: CommitsDict, config) -> RuleResult:
    """
    A comment line that is a framework annotation: `// @DataDriven(...)`, `// @CenterTestCase`,
    `// @CenterTest`, `// @ScenarioContainer`, `// @FlowTags`, `// @Test`, `// @Disabled`. It
    quietly changes what a test is (verified in centertest-platform: BasicScenariosExtractor runs
    only @CenterTestCase methods, CenterTestClassScanner scans @CenterTest classes, FlowTagScanner
    reads @FlowTags).

    Guards: Javadoc and the file header are skipped; the comment must start with the annotation
    and be the whole line (`@Name` or `@Name(...)`), so prose
    that mentions one does not count; a line inside a larger commented-out code block
    (23001, e.g. a whole commented-out test method) is left to that rule.
    """
    result = RuleResult(rule_id="23002", description="Commented-out annotation", category="DeadCode",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        if "@" not in f.source:
            continue
        header = _header_end(f.source)
        blocks = _code_blocks(f)
        spans = None
        for c in _comments(f.source):
            if c.kind == "javadoc" or not c.full_line or c.line < header:
                continue
            am = _ANNOTATION_RE.match(_clean(c.text))
            if not am or _in_blocks(blocks, c.line):
                continue
            spans = spans if spans is not None else _method_spans(f)
            cls, meth = _where(f, spans, c.line)
            issue = (f"@{am.group(1)} is commented out: {_ANNOTATION_EFFECT[am.group(1)]}, and nothing says so; "
                     f"restore it or delete the line")
            result.rows.append([cls, meth, snippet("// " + _clean(c.text)), issue, location(f, c.line, config)])
    return result


# ---------------------------------------------------------------------------
# 23003 — Commented-out forced failure or debug switch
# ---------------------------------------------------------------------------

_SWITCH_RE = re.compile(r"^if\s*\(\s*(?:true|false|!?\s*[\w.]*debug\w*)\s*\)\s*\{?\s*(?:throw|return)\b", re.I)
_FORCED_RE = re.compile(r'^throw\s+new\s+[\w.]+\s*\(\s*"[^"]*(?:FAIL|HARD|DEBUG|STOP|BREAK|[Ff]orce)')


@rule(id="23003", description="Commented-out forced failure or debug switch", category="DeadCode")
def commented_out_debug_switch(commits: CommitsDict, config) -> RuleResult:
    """
    A comment that is a debug switch left behind: `// if (true) throw ...`, `// if (true) return;`,
    `// if (debug) return;`, or `// throw new RuntimeException("...FAIL...")` (a forced failure). One
    uncomment away from a test that always stops or always fails.

    Guards: Javadoc and the file header are skipped; the comment must start with the statement; a
    line inside a larger commented-out code block (23001) is left to that rule.
    """
    result = RuleResult(rule_id="23003", description="Commented-out forced failure or debug switch",
                        category="DeadCode", headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        if "if" not in f.source and "throw" not in f.source:
            continue
        header = _header_end(f.source)
        blocks = None
        spans = None
        for c in _comments(f.source):
            if c.kind == "javadoc" or c.line < header:
                continue
            t = _clean(c.text)
            if not (_SWITCH_RE.match(t) or _FORCED_RE.match(t)):
                continue
            blocks = blocks if blocks is not None else _code_blocks(f)
            if _in_blocks(blocks, c.line):
                continue
            spans = spans if spans is not None else _method_spans(f)
            cls, meth = _where(f, spans, c.line)
            issue = ("A commented-out debug switch (forced stop or failure) is left in the code: uncommenting it, or "
                     "copying the line, makes the test stop or fail every time; delete it")
            result.rows.append([cls, meth, snippet("// " + t), issue, location(f, c.line, config)])
    return result


# ---------------------------------------------------------------------------
# 23004 — if (true) and the code it makes unreachable
# ---------------------------------------------------------------------------

_CONST_IF_RE = re.compile(r"\bif\s*\(\s*(true|false)\s*\)")
_WHILE_FALSE_RE = re.compile(r"\bwhile\s*\(\s*false\s*\)")


def _statement_end(masked: str, start: int) -> int:
    """Offset past the statement that starts at `start` (a {...} block or up to a top-level ';')."""
    i = start
    while i < len(masked) and masked[i].isspace():
        i += 1
    if i < len(masked) and masked[i] == "{":
        return balanced_end(masked, i)
    depth = 0
    for j in range(i, len(masked)):
        ch = masked[j]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                return j
            depth -= 1
        elif ch == ";" and depth == 0:
            return j + 1
    return len(masked)


def _enclosing_close(masked: str, pos: int) -> int:
    """Offset of the '}' that closes the block containing pos."""
    depth = 0
    for j in range(pos, len(masked)):
        if masked[j] == "{":
            depth += 1
        elif masked[j] == "}":
            if depth == 0:
                return j
            depth -= 1
    return len(masked)


def _code_lines(masked: str) -> int:
    return sum(1 for ln in masked.splitlines() if ln.strip() and ln.strip() not in ("}", "{"))


@rule(id="23004", description="if (true) and the code it makes unreachable", category="DeadCode")
def constant_condition(commits: CommitsDict, config) -> RuleResult:
    """
    `if (true)` / `if (false)` in code (comments and strings ignored), and `while (false)`. An
    `if (true) throw/return` makes every statement after it in the same block dead, and the compiler
    allows it (JLS 14.22 treats `if` specially), so the test silently stops there; the Issue gives
    how many code lines it cuts off. `if (false) {...}` is a block that never runs.

    Not reported: statements after a plain `return;`/`throw` in the same block -- javac rejects
    them ("unreachable statement"), so compiling code cannot have them and a text match would only
    hit switch cases. `do { ... } while (false)` (a one-pass block) is skipped.
    """
    result = RuleResult(rule_id="23004", description="if (true) and the code it makes unreachable",
                        category="DeadCode", headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        for cls, _ce, m in all_methods(f):
            if not m.body or ("true" not in m.body and "false" not in m.body):
                continue
            masked = mask_code(m.body)
            for cm in _CONST_IF_RE.finditer(masked):
                end = _statement_end(masked, cm.end())
                stmt = masked[cm.end():end].strip().lstrip("{").strip()
                if cm.group(1) == "true":
                    last = re.split(r";", stmt.rstrip("}").strip().rstrip(";"))[-1].strip()
                    if re.match(r"(throw|return)\b", stmt) or re.match(r"(throw|return)\b", last):
                        verb = "throw" if (stmt.startswith("throw") or last.startswith("throw")) else "return"
                        dead = _code_lines(masked[end:_enclosing_close(masked, end)])
                        issue = (f"if (true) {verb} always leaves here, so the {dead} code line(s) after it "
                                 f"in this block never run and nobody sees it; remove the switch, or the dead code"
                                 if dead else
                                 f"if (true) {verb} is a debug switch left in place; write the statement "
                                 f"plainly or remove it")
                    else:
                        issue = "if (true) is a debug switch left in place: the condition is always met; remove the if"
                else:
                    issue = "if (false) makes its block dead code that never runs; delete it, git history keeps it"
                code, loc = body_hit(f, m, m.body, cm.start(), config)
                result.rows.append([cls, m.name, code, issue, loc])
            for wm in _WHILE_FALSE_RE.finditer(masked):
                if masked[:wm.start()].rstrip().endswith("}"):
                    continue  # do { } while (false)
                code, loc = body_hit(f, m, m.body, wm.start(), config)
                result.rows.append([cls, m.name, code, "while (false) never runs its body; delete it", loc])
    return result


# ---------------------------------------------------------------------------
# 23005 — TODO with no ticket
# ---------------------------------------------------------------------------

_TODO_RE = re.compile(r"(?<![\w-])(TODO|FIXME|XXX|HACK)(?![\w-])")
_TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b|#\d+\b|https?://|\b(?:CS|INC|RITM|CHG|PRB|SR)\d{5,}\b")
_STRING_IN_COMMENT = re.compile(r'"(?:[^"\\\n]|\\.)*"')


@rule(id="23005", description="TODO with no ticket", category="DeadCode")
def todo_without_ticket(commits: CommitsDict, config) -> RuleResult:
    """
    TODO / FIXME / XXX / HACK comments (any comment, trailing ones included) with no ticket
    reference: a key like ABC-123, #123, a ServiceNow number (CS0853057) or a URL. The reference may
    be on the following lines of the same comment run. A TODO with no ticket has no owner and no
    deadline, so it stays.

    Guards: the marker must be upper case and a whole word (XXX-XXXX placeholders do not count);
    text inside quotes in a comment ("TODO" in commented-out code) does not count.
    """
    result = RuleResult(rule_id="23005", description="TODO with no ticket", category="DeadCode",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        if not _TODO_RE.search(f.source):
            continue
        comments = _comments(f.source)
        runs = _runs(comments)
        run_of = {id(c): r for r in runs for c in r}
        blocks = _code_blocks(f)
        spans = None
        for c in comments:
            text = _STRING_IN_COMMENT.sub('""', c.text)
            tm = _TODO_RE.search(text)
            if not tm or _in_blocks(blocks, c.line):
                continue  # a TODO inside commented-out code goes with that code (23001)
            tail = [text[tm.start():]]
            run = run_of.get(id(c))
            if run:
                for nxt in run[run.index(c) + 1:]:
                    t2 = _STRING_IN_COMMENT.sub('""', nxt.text)
                    if _TODO_RE.search(t2):
                        break
                    tail.append(t2)
            if _TICKET_RE.search(" ".join(tail)):
                continue
            spans = spans if spans is not None else _method_spans(f)
            cls, meth = _where(f, spans, c.line)
            rest = text[tm.end():].strip(" :-")
            why = ("says nothing about what to do" if not rest else
                   "is addressed to a person, not a ticket" if re.fullmatch(r"[A-Z]{2,4}|@?\w+", rest) else
                   "has no ticket or link")
            issue = (f"{tm.group(1)} {why}, so nobody owns it and it stays; link a ticket (ABC-123, #123 or a URL) "
                     f"or do it now")
            result.rows.append([cls, meth, snippet(_clean(text)), issue, location(f, c.line, config)])
    return result


# ---------------------------------------------------------------------------
# 23006 — Debugger anchor statements
# ---------------------------------------------------------------------------

_ANCHOR_RE = re.compile(
    r"(?:^|(?<=[;{}]))\s*(?:final\s+)?(?:var|int|long|short|byte|boolean|char|double|float|String|Object|Integer)"
    r"\s+([\w$]+)\s*=\s*(-?\d[\w.]*|true|false|null)\s*;", re.M)
_EMPTY_BODY_RE = re.compile(r"\b(for|if)\s*\(")


@rule(id="23006", description="Debugger anchor statements", category="DeadCode")
def debugger_anchors(commits: CommitsDict, config) -> RuleResult:
    """
    Throwaway statements left to hang a breakpoint on: a local set to a number, boolean or null
    (`var x = 1;`, `int i = 0;`) whose name never appears again in the method (uses inside comments do not count),
    and `for`/`if` statements whose body is empty or only comments (the code that was in them was
    commented out).

    Guards: an empty `if` followed by `else` is a (clumsy) inverted condition and is skipped;
    `while` loops are left to 15017 (busy-waits) since `while (it.next()) {}` drains on purpose.
    An unused local holding a string or a call result is
    15006's (unused variables), not an anchor; 15006 may also list the constant one.
    """
    result = RuleResult(rule_id="23006", description="Debugger anchor statements", category="DeadCode",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        for cls, _ce, m in all_methods(f):
            if not m.body:
                continue
            masked = mask_code(m.body)
            hits = []
            for am in _ANCHOR_RE.finditer(masked):
                name = am.group(1)
                if len(re.findall(rf"(?<![\w$]){re.escape(name)}(?![\w$])", masked)) == 1:
                    off = am.start(1) - len(masked[am.start():am.start(1)].lstrip())
                    hits.append((off, f"{name} is set to a constant and never used: a leftover breakpoint anchor; "
                                      f"delete it"))
            for bm in _EMPTY_BODY_RE.finditer(masked):
                paren = bm.end() - 1
                close = balanced_end(masked, paren)
                rest = masked[close:]
                stripped = rest.lstrip()
                if not stripped.startswith("{"):
                    continue
                brace = close + (len(rest) - len(stripped))
                end = balanced_end(masked, brace)
                if masked[brace + 1:end - 1].strip():
                    continue
                if bm.group(1) == "if" and re.match(r"\s*else\b", masked[end:]):
                    continue
                inside = m.body[brace + 1:end - 1]
                what = "only comments" if inside.strip() else "empty"
                kind = "loop" if bm.group(1) == "for" else "if"
                hits.append((bm.start(), f"The {kind} body is {what}, so the {kind} does nothing (its code was "
                                         f"commented out, or it is a breakpoint anchor); delete it"))
            for off, issue in sorted(hits):
                code, loc = body_hit(f, m, m.body, off, config)
                result.rows.append([cls, m.name, code, issue, loc])
    return result


# ---------------------------------------------------------------------------
# 23007 — Field never read
# ---------------------------------------------------------------------------

_DATA_ANNOTATIONS = {"Getter", "Data", "Value", "ToString", "EqualsAndHashCode", "Builder", "Entity",
                     "JsonAutoDetect", "Embeddable"}
_NOT_TYPES = {"return", "throw", "new", "case", "else", "yield", "assert", "instanceof", "extends", "super",
              "this", "do", "goto", "in", "default", "package", "import"}
_SERIAL_IMPORTS = ("com.google.gson", "com.fasterxml.jackson", "javax.persistence", "jakarta.persistence",
                   "jakarta.xml.bind", "javax.xml.bind")


_FIELD_DECL_RE = re.compile(
    r"\s*(?:(?:private|protected|public|static|final|transient|volatile)\s+)*[\w$.]+(?:<[^;=()]*>)?(?:\[\])*"
    r"\s+([\w$]+)\s*(?:=|;)")


class _Reads:
    """Per-file cache of masked method bodies and the code outside methods."""

    def __init__(self, f: SourceCodeFile):
        self.f = f
        self.methods = []  # (masked body, parameter names)
        covered = set()
        for _cls, _ce, m in all_methods(f):
            if not m.body:
                continue
            self.methods.append((mask_code(m.body), {p[1] for p in (m.parameters or []) if len(p) > 1}))
            start = body_start_line(f, m)
            if start:
                covered.update(range(m.line or start, start + len(m.body.splitlines())))
        lines = mask_code(f.source).splitlines()
        self.outside = [(i, ln) for i, ln in enumerate(lines, 1) if i not in covered]
        self.tokens = set(re.findall(r"[\w$]+", mask_code(f.source)))
        self.field_names = {fd.name for _n, ce in scanned_classes(f) for fd in ce.fields}
        if f.cannot_compile:  # the regex fallback parses no fields: take declarations outside methods
            for _i, ln in self.outside:
                dm = _FIELD_DECL_RE.match(ln)
                if dm:
                    self.field_names.add(dm.group(1))


def _shadowed(masked: str, name: str) -> bool:
    n = re.escape(name)
    for dm in re.finditer(rf"([\w$]+)(\s*<[^;()]*>)?(\s*\[\s*\])*\s+{n}\s*(=(?!=)|;|:|,|\))", masked):
        if dm.group(1) not in _NOT_TYPES:
            return True
    return bool(re.search(rf"(?<![\w$.]){n}\s*\)?\s*->", masked))


def _reads_in(masked: str, name: str, shadowed: bool) -> bool:
    n = re.escape(name)
    for rm in re.finditer(rf"(this\s*\.\s*|super\s*\.\s*|\.\s*)?(?<![\w$]){n}(?![\w$])", masked):
        after = masked[rm.end():]
        if re.match(r"\s*\(", after):
            continue  # a method call of the same name
        prefix = rm.group(1) or ""
        if shadowed and not prefix:
            continue  # the local / parameter, not the field
        if re.match(r"\s*=(?!=)", after):
            continue  # a write
        return True
    return False


@rule(id="23007", description="Field never read", category="DeadCode")
def field_never_read(commits: CommitsDict, config) -> RuleResult:
    """
    Fields that nothing reads: private fields never read in their file (inner classes included);
    protected and package-private fields never read in any project file (which covers every
    subclass and the package). Assignments (`x = ...`, `this.x = ...`) are writes, not reads; a use
    of the name where a local or parameter of the same name shadows the field counts only with
    `this.`/`super.`; a same-named method call is not a read.

    Guards (precision first): public fields, annotated (injected/serialised) fields,
    serialVersionUID and loggers are skipped; classes with Lombok/JPA/Jackson-style annotations,
    files importing Gson/Jackson/JPA/JAXB (fields read by reflection), and classes with no methods
    other than constructors (data holders) are skipped; interface constants and enum constants are
    not fields of a class here. A file that declares its own field of the same name is not searched
    for reads of another class's field (its bare uses refer to its own). Files the parser could not
    read have no fields and are not checked.
    """
    result = RuleResult(rule_id="23007", description="Field never read", category="DeadCode",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    files = project_files(commits)
    cache: dict[str, _Reads] = {}

    def reads(f: SourceCodeFile) -> _Reads:
        if f.key not in cache:
            cache[f.key] = _Reads(f)
        return cache[f.key]

    def read_in_file(target: SourceCodeFile, fd, own: bool) -> bool:
        r = reads(target)
        if fd.name not in r.tokens:
            return False
        for masked, params in r.methods:
            if fd.name in masked and _reads_in(masked, fd.name, fd.name in params or _shadowed(masked, fd.name)):
                return True
        for i, ln in r.outside:
            if own and i == fd.line:
                continue
            if fd.name in ln and _reads_in(ln, fd.name, False):
                return True
        return False

    for f in files:
        if any(i.startswith(_SERIAL_IMPORTS) for i in f.imports):
            continue
        for cls, ce in scanned_classes(f):
            if ce.kind != "class" or _DATA_ANNOTATIONS & set(ce.annotations):
                continue
            if not any(not m.is_constructor for m in ce.methods):
                continue
            for fd in ce.fields:
                if (fd.annotations or "public" in fd.modifiers or fd.name == "serialVersionUID"
                        or fd.type.split(".")[-1].split("<")[0] == "Logger" or fd.name in ("logger", "log", "LOGGER", "LOG")):
                    continue
                if read_in_file(f, fd, True):
                    continue
                if "private" not in fd.modifiers:
                    if any(read_in_file(o, fd, False) for o in files
                           if o is not f and fd.name not in reads(o).field_names):
                        continue
                scope = "its class" if "private" in fd.modifiers else "its class, its subclasses or its package"
                decl = (f.source.splitlines()[fd.line - 1] if 0 < fd.line <= len(f.source.splitlines()) else
                        f"{fd.type} {fd.name};")
                issue = (f"Field {fd.name} is never read in {scope}: it is set (or not even that) and nothing uses it, "
                         f"so it misleads the reader about what the step depends on; delete it")
                result.rows.append([cls, "", snippet(decl), issue, location(f, fd.line, config)])
    return result
