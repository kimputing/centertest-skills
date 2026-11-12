"""
Rules 18001-18006: assertions that cannot fail, or fail without saying why.

18001 -- Verification step short-circuited (TRUST): an assert*/verify*/check* method, or execute() of an
         Assert*/Verify*/Check* step, whose first statement returns unconditionally.
18002 -- Empty step or assert method: a called assert*/verify* method (or execute() of an assert step, or a
         step method marked TODO) whose body holds nothing but comments.
18003 -- AssertJ check without a description: assertThat(x) chains with no .as()/.describedAs()/
         .withFailMessage()/.overridingErrorMessage().
18004 -- Assertion on formatted money text: contains(".00") or a comparison with a "$0.00"-style literal
         (or a constant holding one).
18005 -- Value compared with itself (TRUST): x.equals(x), Objects.equals(x, x), assertThat(x).isEqualTo(x),
         assertEquals(x, x), x == x.
18006 -- Soft assertions never asserted: a SoftAssertions/AnkrPtSoftAssertions object the code creates
         itself, collects checks into, and never calls assertAll() on.

All rules read method bodies through mask_code(): comments and the contents of string literals are
replaced by spaces, so offsets still match the original text (a literal's value is read back from the
original at the same offsets) and no pattern ever matches inside a comment or a string.

The small text helpers (mask_code, expr_start, split_args, ...) are also used by rule_bugs.py.
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, SourceCodeFile
from eir_rules import rule
from rule_helpers import (ProjectIndex, all_methods, balanced_end, body_line, latest_files, location,
                          scanned_classes, snippet)

HEADERS = ["Class", "Method", "Line", "Issue", "Location"]


# ---------------------------------------------------------------------------
# Text helpers (offset-preserving)
# ---------------------------------------------------------------------------

def mask_code(text: str) -> str:
    """Comments and the contents of string/char literals replaced by spaces (newlines and quote
    characters kept), so every offset still points at the same place in `text`."""
    out = list(text)
    i, n = 0, len(text)

    def blank(a, b):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = text[i]
        if c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
            continue
        if c == '"':
            if text.startswith('"""', i):
                j = text.find('"""', i + 3)
                j = n if j < 0 else j
                blank(i + 3, j)
                i = j + 3
                continue
            j = i + 1
            while j < n and text[j] not in '"\n':
                j += 2 if text[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
            continue
        if c == "'":
            j = i + 1
            while j < n and text[j] not in "'\n":
                j += 2 if text[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
            continue
        i += 1
    return "".join(out)


_OPEN = {")": "(", "]": "[", "}": "{"}


def match_back(code: str, close_index: int) -> int:
    """Index of the bracket that opens the one closing at close_index (masked code); -1 if none."""
    closer = code[close_index]
    opener = _OPEN[closer]
    depth = 0
    for i in range(close_index, -1, -1):
        if code[i] == closer:
            depth += 1
        elif code[i] == opener:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _is_ident(ch: str) -> bool:
    return ch.isalnum() or ch in "_$"


def expr_start(code: str, end: int) -> int:
    """Start offset of the primary expression (a dotted chain of names, calls, indexes, a literal or a
    parenthesised expression, `new X(...)` included) that ends just before `end` (masked code)."""
    i = end - 1
    while i >= 0 and code[i].isspace():
        i -= 1
    start = end
    while i >= 0:
        c = code[i]
        if c == '"':
            j = code.rfind('"', 0, i)
            if j < 0:
                break
            return j
        if c in ")]":
            j = match_back(code, i)
            if j < 0:
                break
            start, i = j, j - 1
            k = i
            while k >= 0 and _is_ident(code[k]):
                k -= 1
            if k < i:
                start, i = k + 1, k
        elif _is_ident(c):
            k = i
            while k >= 0 and _is_ident(code[k]):
                k -= 1
            start, i = k + 1, k
        else:
            break
        p = i
        while p >= 0 and code[p].isspace():
            p -= 1
        if p >= 0 and code[p] == ".":
            i = p - 1
            while i >= 0 and code[i].isspace():
                i -= 1
            continue
        break
    # include a leading `new`
    p = start - 1
    while p >= 0 and code[p].isspace():
        p -= 1
    if p >= 2 and code[p - 2:p + 1] == "new" and (p - 3 < 0 or not _is_ident(code[p - 3])):
        return p - 2
    return start


def split_args(code: str, open_index: int) -> list[tuple[int, int]]:
    """[(start, end)] of the top-level arguments of the call whose '(' is at open_index (whitespace
    trimmed); [] for an empty argument list."""
    end = balanced_end(code, open_index) - 1
    out, depth, s = [], 0, open_index + 1
    for i in range(open_index + 1, end):
        ch = code[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append((s, i))
            s = i + 1
    out.append((s, end))
    trimmed = []
    for a, b in out:
        while a < b and code[a].isspace():
            a += 1
        while b > a and code[b - 1].isspace():
            b -= 1
        trimmed.append((a, b))
    if len(trimmed) == 1 and trimmed[0][0] == trimmed[0][1]:
        return []
    return trimmed


def norm(text: str) -> str:
    """Expression text without whitespace, for identity comparisons."""
    return re.sub(r"\s+", "", text)


def chain_after(code: str, pos: int) -> list[tuple[str, int, int]]:
    """Calls chained after `pos` (just past a closing paren): [(name, open paren, end)]."""
    out = []
    rx = re.compile(r"\s*\.\s*(\w+)\s*(?:<[^<>()]*>)?\s*\(")
    while True:
        m = rx.match(code, pos)
        if not m:
            return out
        op = m.end() - 1
        end = balanced_end(code, op)
        out.append((m.group(1), op, end))
        pos = end


def is_generated(f: SourceCodeFile) -> bool:
    parts = (f.package_name or "").split(".")
    path = (f.key or "").replace("\\", "/")
    return "generated" in parts or "/generated/" in path


def project_files(commits: CommitsDict) -> list[SourceCodeFile]:
    return [f for f in latest_files(commits) if not is_generated(f)]


def method_bodies(files) -> list[tuple[SourceCodeFile, str, object, object, str]]:
    """(file, display class, class, method, masked body) for every method with a body."""
    out = []
    for f in files:
        for disp, ce, m in all_methods(f):
            if m.body:
                out.append((f, disp, ce, m, mask_code(m.body)))
    return out


def line_at(f, m, body: str, offset: int) -> tuple[int, str]:
    """(file line, trimmed code line) of a body offset."""
    idx = body.count("\n", 0, offset)
    lines = body.splitlines()
    text = lines[idx] if idx < len(lines) else ""
    return body_line(f, m, idx), snippet(text)


def _row(f, disp, m, body, offset, issue, config):
    line_no, text = line_at(f, m, body, offset)
    return [disp, m.name, text, issue, location(f, line_no, config)]


def _decl_row(f, disp, m, issue, config):
    """Row pointing at the method's declaration line."""
    lines = f.source.splitlines()
    text = lines[m.line - 1] if 0 < m.line <= len(lines) else ""
    return [disp, m.name, snippet(text), issue, location(f, m.line, config)]


def _sorted(rows):
    return sorted(rows, key=lambda r: (r[4].rsplit(":", 1)[0], int(r[4].rsplit(":", 1)[1]), r[1], r[3]))


def _descendants(index: ProjectIndex, files) -> dict[str, list]:
    """{class name: [project subclasses at any depth]}."""
    out = defaultdict(list)
    for f in files:
        for _, ce in scanned_classes(f):
            for a in index.ancestors(ce):
                out[a.class_name].append(ce)
    return out


_CALL_RE = re.compile(r"(?<![\w$])(\w+)\s*\(")
_REF_RE = re.compile(r"::\s*(\w+)")
_NEW_RE = re.compile(r"\bnew\s+(?:[\w$]+\.)*([\w$]+)\s*(?:<[^<>()]*>)?\s*\(")


def _call_counts(bodies) -> Counter:
    counts = Counter()
    for _, _, _, _, code in bodies:
        for m in _CALL_RE.finditer(code):
            counts[m.group(1)] += 1
        for m in _REF_RE.finditer(code):
            counts[m.group(1)] += 1
    return counts


_VERIFY_NAME = re.compile(r"^(assert|verify|check)(?:[A-Z_0-9]|$)")
_VERIFY_CLASS = re.compile(r"^(Assert|Verify|Check)[A-Z_0-9]")


def _is_verification(ce, m) -> bool:
    if m.is_constructor:
        return False
    if _VERIFY_NAME.match(m.name):
        return True
    return m.name == "execute" and not m.parameters and bool(_VERIFY_CLASS.match(ce.class_name))


# ---------------------------------------------------------------------------
# 18001
# ---------------------------------------------------------------------------

_IF_TRUE_RETURN = re.compile(r"\{\s*if\s*\(\s*true\s*\)\s*(?:\{\s*)?return\b")
_PLAIN_RETURN = re.compile(r"\{\s*return\s*;")


def _users(cls_name: str, files, index: ProjectIndex) -> list[str]:
    """Classes (simple names) that create the step `cls_name`, directly or through a facade method."""
    facade_methods = []
    for fname, fce in index.facades().items():
        for fm in fce.methods:
            if fm.body and re.search(r"\bnew\s+%s\s*\(" % re.escape(cls_name), mask_code(fm.body)):
                facade_methods.append((fname, fm.name))
    users = set()
    for f in files:
        if f.main_class is None:
            continue  # interfaces/enums only (the facades themselves)
        code = mask_code(f.source)
        own = f.main_class.class_name
        if own == cls_name:
            continue
        if re.search(r"\bnew\s+%s\s*\(" % re.escape(cls_name), code) or any(
                re.search(r"\b%s\s*\.\s*%s\s*\(" % (re.escape(fn), re.escape(mn)), code) for fn, mn in facade_methods):
            users.add(own)
    return sorted(users)


@rule(id="18001", description="Verification step short-circuited", category="Assertions")
def verification_short_circuited(commits: CommitsDict, config) -> RuleResult:
    """
    An assert*/verify*/check* method (or execute() of an Assert*/Verify*/Check* step class) whose first
    statement is `if (true) return ...` -- or, for a method nothing overrides, a bare `return;` -- so
    every test that calls it passes after checking nothing.

    Heuristic: the first token after the body's opening brace (comments ignored) is `if (true) return`
    or `return;`. `if (true) return` is always reported (it exists only to switch the check off);
    a body that is just `return;` is skipped when a project subclass overrides the method (an
    optional template-method hook, as rule 18002 treats empty hooks) or the method is an @Override
    (a subclass deliberately opting out of its parent's check). The Issue names the classes that use
    the step (they create it, directly or through a facade method) or how often the method is called.
    """
    result = RuleResult(rule_id="18001", description="Verification step short-circuited",
                        category="Assertions", headers=HEADERS)
    files = project_files(commits)
    index = ProjectIndex(files)
    bodies = method_bodies(files)
    calls = _call_counts(bodies)
    desc = _descendants(index, files)
    for f, disp, ce, m, code in bodies:
        if not _is_verification(ce, m):
            continue
        hit = _IF_TRUE_RETURN.match(code)
        kind = "if (true) return"
        if not hit:
            hit = _PLAIN_RETURN.match(code)
            kind = "return;"
            if not hit or "Override" in m.annotations:
                continue
            if any(any(sm.name == m.name for sm in sub.methods) for sub in desc.get(ce.class_name, [])):
                continue
        offset = code.index("return", 0) if kind == "return;" else hit.start() + code[hit.start():].index("if")
        users = _users(ce.class_name, files, index) if index.is_step(ce) else []
        n_calls = calls.get(m.name, 0)
        if m.name == "execute":
            used = f"the step is used by {len(users)} class(es)" + (f" ({', '.join(users[:5])})" if users else "")
        else:
            used = f"it is called {n_calls} time(s)"
            if users:
                used += f"; the step is used by {len(users)} class(es) ({', '.join(users[:5])})"
        issue = (f"{m.name}() starts with `{kind}`, so it checks nothing and every test that runs it passes; "
                 f"{used}")
        result.rows.append(_row(f, disp, m, m.body, offset, issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} verification method(s) return before their first check"
    return result


# ---------------------------------------------------------------------------
# 18002
# ---------------------------------------------------------------------------

_TODO_RE = re.compile(r"\b(todo|fixme|tbd|implement)\b", re.IGNORECASE)


@rule(id="18002", description="Empty step or assert method", category="Assertions")
def empty_step_or_assert(commits: CommitsDict, config) -> RuleResult:
    """
    A method whose body is empty or holds only comments, that something calls, and that is either
      * a verification method (assert*/verify*, or execute() of an Assert*/Verify*/Check* step), or
      * a method of a step class whose comments mark it unfinished (TODO/FIXME/TBD/implement).

    Template-method hooks are NOT reported:
      * the method is overridden (same name) by a project subclass -- an optional hook the subclasses
        fill in where they need it;
      * the method is itself an @Override -- a subclass deliberately switching its parent's check off;
      * abstract methods (no body) and constructors.
    An empty hook in an abstract base that no subclass overrides IS reported: the base calls a check
    that nobody ever wrote (PMIC: AbstractPolicyChange.assertPreemption()).
    check* methods are left out here (checkX() is as often a checkbox action as a verification).
    """
    result = RuleResult(rule_id="18002", description="Empty step or assert method",
                        category="Assertions", headers=HEADERS)
    files = project_files(commits)
    index = ProjectIndex(files)
    bodies = method_bodies(files)
    calls = _call_counts(bodies)
    desc = _descendants(index, files)
    for f, disp, ce, m, code in bodies:
        if m.is_constructor or "Override" in m.annotations or "abstract" in m.modifiers:
            continue
        if code.strip().strip("{}").strip():
            continue
        verification = bool(re.match(r"^(assert|verify)(?:[A-Z_0-9]|$)", m.name)) or (
            m.name == "execute" and not m.parameters and bool(_VERIFY_CLASS.match(ce.class_name)))
        todo = bool(_TODO_RE.search(m.body)) and index.is_step(ce)
        if not (verification or todo):
            continue
        if any(any(sm.name == m.name for sm in sub.methods) for sub in desc.get(ce.class_name, [])):
            continue
        if m.name == "execute":
            users = _users(ce.class_name, files, index)
            if not users:
                continue
            used = f"the step is used by {len(users)} class(es) ({', '.join(users[:5])})"
        else:
            n = calls.get(m.name, 0)
            if n == 0:
                continue
            used = f"it is called {n} time(s)"
        what = "verifies nothing" if verification else "is an unfinished stub (TODO) that does nothing"
        issue = f"{m.name}() has an empty body but {used}, so the step {what} and the test still passes"
        result.rows.append(_decl_row(f, disp, m, issue, config) if m.line else
                           _row(f, disp, m, m.body, 0, issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} called method(s) with an empty body"
    return result


# ---------------------------------------------------------------------------
# 18003
# ---------------------------------------------------------------------------

_ASSERT_THAT = re.compile(r"(?<![\w$])assertThat\s*\(")
_DESCRIBERS = {"as", "describedAs", "withFailMessage", "overridingErrorMessage"}


@rule(id="18003", description="AssertJ check without a description", category="Assertions")
def assertj_without_description(commits: CommitsDict, config) -> RuleResult:
    """
    `assertThat(actual)` (AssertJ: one argument, followed by a chained verb) with no .as(...),
    .describedAs(...), .withFailMessage(...) or .overridingErrorMessage(...) anywhere in its chain.
    The failure then says only that 'expected' differs from 'actual', not what was being checked.

    Skipped: Hamcrest/JUnit assertThat(actual, matcher) (2+ arguments); CenterTestAssertion's
    assertThat(() -> ...) (its argument is a lambda); an AssertJ check inside a CenterTestAssertion
    statement that has .withDescription(...) or .withFailure(...) -- the framework puts that text on the
    error (CenterTestAssertion.enrich, centertest-core).
    """
    result = RuleResult(rule_id="18003", description="AssertJ check without a description",
                        category="Assertions", headers=HEADERS)
    for f, disp, ce, m, code in method_bodies(project_files(commits)):
        for hit in _ASSERT_THAT.finditer(code):
            op = hit.end() - 1
            args = split_args(code, op)
            if len(args) != 1 or code[args[0][0]:args[0][1]].lstrip().startswith("()"):
                continue
            if re.match(r"\(\s*\w*\s*\)\s*->|\w+\s*->", code[args[0][0]:args[0][1]]):
                continue
            chain = chain_after(code, balanced_end(code, op))
            if not chain or any(name in _DESCRIBERS for name, _, _ in chain):
                continue
            stmt_start = max(code.rfind(";", 0, hit.start()), 0)
            context = code[stmt_start:hit.start()]
            if "withDescription" in context or "withFailure" in context:
                continue
            verb = chain[-1][0]
            issue = (f"assertThat(...).{verb}(...) has no .as(\"...\") description, so a failure says only "
                     "expected vs actual, not what the test was checking")
            result.rows.append(_row(f, disp, m, m.body, hit.start(), issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} AssertJ check(s) without a description"
    return result


# ---------------------------------------------------------------------------
# 18004
# ---------------------------------------------------------------------------

_MONEY_LITERAL = re.compile(r"^\s*\(?-?\(?\$\s?-?\d[\d,]*\.\d{2}\)?\s*$")
_CENTS_ONLY = re.compile(r"^\.\d{2}$")
_TEXT_VERBS = {"isEqualTo", "isNotEqualTo", "isEqualToIgnoringCase", "isEqualToIgnoringWhitespace",
               "contains", "doesNotContain", "startsWith", "endsWith", "equals", "equalsIgnoreCase",
               "contentEquals", "assertEquals", "assertNotEquals", "assertContains", "assertNotContains",
               "assertEqualsSoft", "assertNotEqualsSoft", "assertValue", "assertText", "matches"}
_VERB_CALL = re.compile(r"(?<![\w$])(\w+)\s*\(")


def _money_constants(files) -> dict[str, str]:
    """{constant name: literal} for project fields initialised with a "$1,234.56"-style literal."""
    out = {}
    for f in files:
        for _, ce in scanned_classes(f):
            for fld in ce.fields:
                lit = fld.initializer.strip()
                if len(lit) >= 2 and lit[0] == '"' and lit[-1] == '"' and _MONEY_LITERAL.match(lit[1:-1]):
                    out[fld.name] = lit
    return out


@rule(id="18004", description="Assertion on formatted money text", category="Assertions")
def money_as_text(commits: CommitsDict, config) -> RuleResult:
    """
    Money checked as formatted text, so the result depends on currency symbol, separators, locale and
    rounding instead of the amount:
      * contains/endsWith/startsWith(".00")-style cents checks;
      * a comparison or assertion (isEqualTo, isNotEqualTo, equals, assertEquals, contains, ...) whose
        argument -- or receiver -- is a "$0.00"/"$1,234.56" literal or a project constant holding one.

    Only amounts written WITH cents count: whole-dollar labels such as "$500" or "$1,000" are usually
    coverage-term option labels (a deductible picked from a dropdown) and comparing an option's label is
    legitimate. Numeric assertions (assertEqualsNumeric, ...Numeric) are the fix and never match.
    """
    result = RuleResult(rule_id="18004", description="Assertion on formatted money text",
                        category="Assertions", headers=HEADERS)
    files = project_files(commits)
    consts = _money_constants(files)
    for f, disp, ce, m, code in method_bodies(files):
        raw = m.body
        for hit in _VERB_CALL.finditer(code):
            verb = hit.group(1)
            if verb not in _TEXT_VERBS:
                continue
            op = hit.end() - 1
            args = split_args(code, op)
            found = None
            for a, b in args:
                text = raw[a:b].strip()
                lit = text[1:-1] if len(text) >= 2 and text[0] == '"' and text[-1] == '"' else None
                if lit is not None and verb in ("contains", "endsWith", "startsWith", "doesNotContain") \
                        and _CENTS_ONLY.match(lit):
                    found = f'{verb}("{lit}") checks the cents as text'
                elif lit is not None and _MONEY_LITERAL.match(lit):
                    found = f'{verb}("{lit}") compares money as formatted text'
                elif re.fullmatch(r"(?:[\w$]+\.)*([A-Z][A-Z0-9_]*)", text) and \
                        text.rsplit(".", 1)[-1] in consts:
                    name = text.rsplit(".", 1)[-1]
                    found = f"{verb}({name}) compares money as formatted text ({name} = {consts[name]})"
                if found:
                    break
            if not found and hit.start() > 0 and code[:hit.start()].rstrip().endswith("."):
                dot = code[:hit.start()].rstrip()
                rs = expr_start(code, len(dot) - 1)
                recv = raw[rs:len(dot) - 1].strip()
                if len(recv) >= 2 and recv[0] == '"' and recv[-1] == '"' and _MONEY_LITERAL.match(recv[1:-1]):
                    found = f'"{recv[1:-1]}".{verb}(...) compares money as formatted text'
            if not found:
                continue
            issue = (f"{found}; the check depends on currency symbol, separators and rounding -- compare the "
                     "amount numerically (assertEqualsNumeric or BigDecimal)")
            result.rows.append(_row(f, disp, m, m.body, hit.start(), issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} money check(s) on formatted text"
    return result


# ---------------------------------------------------------------------------
# 18005
# ---------------------------------------------------------------------------

_SELF_INSTANCE = re.compile(r"\.\s*(equals|equalsIgnoreCase|contentEquals|assertEquals|isSameAs)\s*\(")
_OBJECTS_EQUALS = re.compile(r"(?<![\w$.])(?:java\.util\.)?Objects\s*\.\s*(equals|deepEquals)\s*\(")
_STATIC_ASSERT_EQ = re.compile(r"(?<![\w$])(?:(?:Assert|Assertions)\s*\.\s*)?(assertEquals|assertSame)\s*\(")
_SAME_VERBS = {"isEqualTo", "isSameAs", "isEqualToIgnoringCase", "isEqualToIgnoringWhitespace"}
_IMPURE = re.compile(r"(?<![\w$])(?:next\w*|poll\w*|pop|remove\w*|read\w*|random\w*|now|currentTimeMillis|nanoTime|"
                     r"randomUUID|generate\w*|create\w*|add\w*|put\w*|increment\w*|getAndIncrement|take|"
                     r"push|offer|click\w*|set\w*)\s*\(|\bnew\b|\+\+|--")
_EQ_OPERAND = re.compile(r"(?<![\w$.)\]])([A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\s*==\s*"
                         r"([A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)(?![\w$.(\[])")


def _pure(expr: str) -> bool:
    """An expression that reads the same value twice (no calls with side effects, no literals)."""
    e = expr.strip()
    if not e or e[0] in "\"'" or re.fullmatch(r"[\d.]+[lLfFdD]?|true|false|null", e):
        return False
    return not _IMPURE.search(e)


@rule(id="18005", description="Value compared with itself", category="Assertions")
def compared_with_itself(commits: CommitsDict, config) -> RuleResult:
    """
    A comparison whose two sides are the same expression, so it is always true and the check passes
    whatever the application shows:
      x.equals(x) / equalsIgnoreCase / contentEquals / x.assertEquals(x) / x.isSameAs(x),
      Objects.equals(x, x), assertEquals(x, x) (a leading String message is ignored),
      assertThat(x).isEqualTo(x) (also through .as(...)), and x == x for plain names.

    Guards (zero false positives): sides are compared as whitespace-free text; an expression with a
    call that can change state or return something new each time (next(), read*(), random*(), now(),
    create*(), new, ++, --, ...) is skipped, as are literals; `x == x` needs plain dotted names with
    nothing but a boolean/statement boundary on either side, and is skipped for names declared
    double/float (x == x is the NaN test there). `!=` is never reported (x != x is the NaN idiom).
    """
    result = RuleResult(rule_id="18005", description="Value compared with itself",
                        category="Assertions", headers=HEADERS)
    for f, disp, ce, m, code in method_bodies(project_files(commits)):
        raw = m.body
        hits = []

        def report(offset, a, b, form):
            ta, tb = raw[a[0]:a[1]], raw[b[0]:b[1]]
            if norm(ta) == norm(tb) and _pure(code[a[0]:a[1]]):
                hits.append((offset, f"{form} compares {snippet(norm(ta), 60)} with itself"))

        for hit in _SELF_INSTANCE.finditer(code):
            op = hit.end() - 1
            args = split_args(code, op)
            if len(args) != 1:
                continue
            rs = expr_start(code, hit.start())
            if rs >= hit.start():
                continue
            report(rs, (rs, hit.start()), args[0], f"{hit.group(1)}()")
        for rx in (_OBJECTS_EQUALS, _STATIC_ASSERT_EQ):
            for hit in rx.finditer(code):
                if rx is _STATIC_ASSERT_EQ and code[:hit.start()].rstrip().endswith("."):
                    continue  # an instance method (widget.assertEquals(a, b)): not the static form
                args = split_args(code, hit.end() - 1)
                if len(args) == 3:
                    first = raw[args[0][0]:args[0][1]].strip()
                    args = args[1:] if first.startswith('"') else args[:2]
                if len(args) == 2:
                    report(hit.start(), args[0], args[1], f"{hit.group(1)}()")
        for hit in _ASSERT_THAT.finditer(code):
            op = hit.end() - 1
            args = split_args(code, op)
            if len(args) != 1:
                continue
            for name, vop, _ in chain_after(code, balanced_end(code, op)):
                if name in _DESCRIBERS:
                    continue
                if name in _SAME_VERBS:
                    vargs = split_args(code, vop)
                    if len(vargs) == 1:
                        report(hit.start(), args[0], vargs[0], f"assertThat(...).{name}()")
                break
        for hit in _EQ_OPERAND.finditer(code):
            left, right = hit.group(1), hit.group(2)
            if norm(left) != norm(right) or left in ("true", "false", "null"):
                continue
            before = code[:hit.start()].rstrip()
            after = code[hit.end():].lstrip()
            if not (re.search(r"(?:[(,?:!]|&&|\|\||(?<![=!<>])=|\breturn)$", before) and
                    re.match(r"(?:[);?,:]|&&|\|\|)", after)):
                continue
            var = norm(left).split(".")[-1]
            if re.search(r"\b(?:double|float|Double|Float)\s+%s\b" % re.escape(var), mask_code(f.source)):
                continue
            hits.append((hit.start(), f"{norm(left)} == {norm(right)} compares a value with itself"))
        seen = set()
        for offset, what in sorted(hits):
            if offset in seen:
                continue
            seen.add(offset)
            issue = f"{what}, so it is always true and the check passes whatever the application shows"
            result.rows.append(_row(f, disp, m, raw, offset, issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} comparison(s) of a value with itself"
    return result


# ---------------------------------------------------------------------------
# 18006
# ---------------------------------------------------------------------------

_SOFT_TYPES = {"SoftAssertions", "AnkrPtSoftAssertions", "BDDSoftAssertions"}
_SOFT_READS = re.compile(r"\.\s*(assertAll|errorsCollected|assertionErrorsCollected|wasSuccess)\s*\(")


def _soft_types(files, index: ProjectIndex) -> set[str]:
    """The soft-assertion classes plus project subclasses of them."""
    names = set(_SOFT_TYPES)
    for f in files:
        for _, ce in scanned_classes(f):
            if any(n in _SOFT_TYPES for n in index.superclass_names(ce)):
                names.add(ce.class_name)
    return names


def _uses(code: str, name: str):
    """(collects, finished, escapes) for variable `name` in masked code."""
    n = re.escape(name)
    ref = r"(?<![\w$.])(?:this\s*\.\s*)?%s" % n
    collects = bool(re.search(ref + r"\s*\.\s*(?!assertAll\b|errorsCollected\b|assertionErrorsCollected\b|"
                                     r"wasSuccess\b)\w+\s*\(", code))
    finished = bool(re.search(ref + r"\s*\.\s*(?:assertAll|errorsCollected|assertionErrorsCollected|wasSuccess)"
                                    r"\s*\(", code))
    escapes = bool(re.search(r"[(,]\s*(?:this\s*\.\s*)?%s\s*[,)]" % n, code)
                   or re.search(r"\breturn\s+(?:this\s*\.\s*)?%s\s*;" % n, code)
                   or re.search(r"(?<![=!<>])=\s*(?:this\s*\.\s*)?%s\s*;" % n, code))
    return collects, finished, escapes


@rule(id="18006", description="Soft assertions never asserted", category="Assertions")
def soft_assertions_never_asserted(commits: CommitsDict, config) -> RuleResult:
    """
    A soft-assertions object the code creates itself (`new SoftAssertions()`, `new AnkrPtSoftAssertions()`,
    BDDSoftAssertions, or a project subclass of them), collects checks into, and never finishes with
    assertAll() in its scope: its failures are collected and dropped, so the test passes.

    Scope: a local variable -> its method; a field -> its class and the project subclasses.

    Not reported:
      * the framework's own soft assertions -- getSoftAssertions() / AnkrPtAssert.softAssertThat /
        CenterTestAssertion.softAssertThat collect into the InvocationContext's AnkrPtSoftAssertions, and
        TestExecutor.checkForUnfinishedSoftAssertions (centertest-core) fails the scenario at its end when
        that object holds errors; an object obtained from getSoftAssertions() is therefore excluded;
      * an object that escapes (passed as an argument, returned, or assigned elsewhere): someone else may
        assert it; one whose errors are read (errorsCollected(), wasSuccess());
      * SoftAssertions.assertSoftly(...), JUnitSoftAssertions and AutoCloseableSoftAssertions, which
        assert themselves;
      * a field that is declared but never created or used: dead code, not a lost failure.
    """
    result = RuleResult(rule_id="18006", description="Soft assertions never asserted",
                        category="Assertions", headers=HEADERS)
    files = project_files(commits)
    index = ProjectIndex(files)
    soft = _soft_types(files, index)
    bodies = method_bodies(files)
    desc = _descendants(index, files)
    type_alt = "|".join(sorted(re.escape(t) for t in soft))
    local_re = re.compile(r"(?:\bvar|\b(?:%s))\s+(\w+)\s*=\s*new\s+(?:[\w$]+\.)*(%s)\s*\(" % (type_alt, type_alt))
    # locals
    for f, disp, ce, m, code in bodies:
        for hit in local_re.finditer(code):
            name = hit.group(1)
            collects, finished, escapes = _uses(code[hit.end():], name)
            if collects and not finished and not escapes:
                issue = (f"{name} = new {hit.group(2)}() collects checks but {name}.assertAll() is never called, "
                         "so its failures are dropped and the test passes")
                result.rows.append(_row(f, disp, m, m.body, hit.start(), issue, config))
    # fields
    by_class = defaultdict(list)
    for f, disp, ce, m, code in bodies:
        by_class[id(ce)].append(code)
    for f in files:
        for disp, ce in scanned_classes(f):
            for fld in ce.fields:
                if fld.type.split("<")[0].split(".")[-1] not in soft:
                    continue
                scope = [ce] + desc.get(ce.class_name, [])
                code = "\n".join(c for cls in scope for c in by_class.get(id(cls), []))
                created = bool(re.match(r"\s*new\s", fld.initializer or "")) or bool(
                    re.search(r"(?<![\w$.])(?:this\s*\.\s*)?%s\s*=\s*new\s" % re.escape(fld.name), code))
                if not created:
                    continue
                collects, finished, escapes = _uses(code, fld.name)
                if collects and not finished and not escapes:
                    issue = (f"field {fld.name} ({fld.type}) collects checks but assertAll() is never called on it "
                             f"in {ce.class_name} or its subclasses, so its failures are dropped")
                    line = fld.line or ce.line
                    text = f.source.splitlines()[line - 1].strip() if 0 < line <= len(f.source.splitlines()) else ""
                    result.rows.append([disp, "", snippet(text), issue, location(f, line, config)])
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} soft-assertion object(s) never asserted"
    return result
