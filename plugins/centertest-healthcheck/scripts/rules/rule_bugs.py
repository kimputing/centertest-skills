"""
Rules 24001-24004: plain Java bugs that make a test check or record the wrong value.

24001 -- Data field concatenated without getValue(): a page widget concatenated into a String or passed to
         a format call, so its toString() ("WidgetTextInput[cssid]") is used instead of its value.
24002 -- Same argument twice in a format call: String.format / .formatted / logger placeholders given the
         identical (non-trivial) expression twice.
24003 -- Money parsed as float: Float/Double parse or valueOf of currency text.
24004 -- Same Helper value set twice, or stored under the wrong key: in one block, two different setters
         on the same receiver get the identical value, or a run of setters sets one key twice.

Text helpers (mask_code, expr_start, split_args, ...) come from rule_assertions.
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_helpers import ProjectIndex, balanced_end, body_line, snippet
from rules.rule_assertions import (HEADERS, _row, _sorted, expr_start, mask_code, method_bodies, norm,
                                   project_files, split_args)


# ---------------------------------------------------------------------------
# Expression parsing (forward)
# ---------------------------------------------------------------------------

def expr_end(code: str, start: int) -> int:
    """End offset of the primary expression (dotted chain of names, calls, indexes) starting at `start`."""
    i, n = start, len(code)
    while i < n and code[i].isspace():
        i += 1
    if code.startswith("new", i) and i + 3 < n and not (code[i + 3].isalnum() or code[i + 3] in "_$"):
        i += 3
        while i < n and code[i].isspace():
            i += 1
    if i < n and code[i] == '"':
        j = code.find('"', i + 1)
        return j + 1 if j >= 0 else n
    if i < n and code[i] == "(":
        i = balanced_end(code, i)
    else:
        j = i
        while j < n and (code[j].isalnum() or code[j] in "_$"):
            j += 1
        if j == i:
            return i
        i = j
    while True:
        k = i
        while k < n and code[k].isspace():
            k += 1
        if k < n and code[k] in "([":
            i = balanced_end(code, k)
            continue
        if k < n and code[k] == ".":
            k += 1
            while k < n and code[k].isspace():
                k += 1
            j = k
            while j < n and (code[j].isalnum() or code[j] in "_$"):
                j += 1
            if j == k:
                return i
            i = j
            continue
        return i


_SEG = re.compile(r"\.\s*([\w$]+)\s*(\()?")


def _segments(text: str):
    """Root text and [(name, args text or None)] of a chain like `a.getB().get("x").c`."""
    t = text.strip()
    if t.startswith("new") and re.match(r"new\s", t):
        m = re.match(r"new\s+(?:[\w$]+\.)*([\w$]+)\s*(?:<[^<>()]*>)?\s*\(", t)
        if not m:
            return None, []
        end = balanced_end(t, m.end() - 1)
        root, rest = ("new", m.group(1)), t[end:]
    else:
        m = re.match(r"([\w$]+)\s*(\()?", t)
        if not m:
            return None, []
        if m.group(2):
            end = balanced_end(t, m.end() - 1)
            root, rest = ("call", m.group(1), t[m.end():end - 1]), t[end:]
        else:
            root, rest = ("name", m.group(1)), t[m.end():]
    segs, pos = [], 0
    while pos < len(rest):
        m = _SEG.match(rest, pos)
        if not m:
            return root, None  # indexes, casts, ... : not a plain chain
        if m.group(2):
            end = balanced_end(rest, m.end() - 1)
            segs.append((m.group(1), rest[m.end():end - 1].strip()))
            pos = end
        else:
            segs.append((m.group(1), None))
            pos = m.end()
        while pos < len(rest) and rest[pos].isspace():
            pos += 1
    return root, segs


# ---------------------------------------------------------------------------
# 24001
# ---------------------------------------------------------------------------

# Widget/page getters that return a String, a number, a flag or a collection, not another widget
# (AbstractWidget and the gw widgets in centertest-platform).
_VALUE_GETTERS = {
    "getValue", "getText", "getLabel", "getCssId", "getId", "getAnalyticId", "getAsDate", "getBoolean",
    "getBooleanV9", "getBooleanV10", "getChecked", "getOptionList", "getOptions", "getOptionsSelected",
    "getOptionsNotSelected", "getSelected", "getSelectedText", "getSelectedElements", "getMessageText",
    "getRowText", "getReadonlyValue", "getPageTitle", "getCount", "getContainerLabel", "getTypeLabel",
    "getType", "getCode", "getDescription", "getContext", "getSoftAssertions", "getWebElement", "getRows",
    "getColumns", "getPageCount", "getPageNumber", "getUserName", "getMode", "getWidgetRuntime", "getRuntime",
    "getClass", "getSimpleName", "getName", "getKey", "getMessage", "getTitle", "getAttribute", "getSize",
    "getValueInternal", "getPostOnChange", "getCssSelector", "getBodyCount", "getRuntimeIndex", "getSourceIndex",
    "getRowIdentifier", "getRowSelectName", "getUpdateValue", "getInvocationContext", "getGuidewireVersion",
}


def _page_classes(f) -> set[str]:
    """Simple names of generated page classes this file imports (…generated.pages…)."""
    out = set()
    for imp in f.imports:
        if ".pages." in imp and not imp.endswith("*"):
            out.add(imp.rsplit(".", 1)[-1])
    return out


def _is_widget_type(t: str, pages: set[str]) -> bool:
    t = (t or "").split("<")[0].split(".")[-1].strip()
    return bool(t) and (t in pages or bool(re.match(r"Widget[A-Z]\w*$", t)))


class _Env:
    """Types and initialisers of a method's names: parameters, locals and the class's (and its project
    superclasses') fields."""

    def __init__(self, f, ce, m, code, raw, index: ProjectIndex):
        self.pages = _page_classes(f)
        self.types, self.inits = {}, {}
        for anc in [ce] + index.ancestors(ce):
            for fld in anc.fields:
                self.types.setdefault(fld.name, fld.type)
                if fld.initializer:
                    self.inits.setdefault(fld.name, fld.initializer)
            hit = index.by_name.get(anc.class_name)
            if hit:
                self.pages |= _page_classes(hit[0])
        for t, n in m.parameters:
            self.types[n] = t
        for hit in re.finditer(r"(?<![\w$.])([\w$.<>]+)\s+([\w$]+)\s*=(?!=)", code):
            t, n = hit.group(1), hit.group(2)
            if t in ("return", "new", "else", "throw"):
                continue
            end = code.find(";", hit.end())
            if end < 0:
                continue
            if t == "var":
                self.types.pop(n, None)
                self.inits[n] = raw[hit.end():end].strip()
            else:
                self.types[n] = t
                self.inits.pop(n, None)


def _ui_kind(text: str, env: _Env, depth: int = 0) -> str | None:
    """'widget' when `text` evaluates to a page widget (never its value), 'page' for a page object itself,
    None otherwise. A widget is a chain of no-arg widget getters (or .get("label")) rooted at a generated
    page (`new XPage(...)`, a variable/field/parameter typed or initialised as one) or at WidgetX.get(...)."""
    if depth > 4:
        return None
    root, segs = _segments(text)
    if root is None or segs is None:
        return None
    if root[0] == "new":
        if not _is_widget_type(root[1], env.pages):
            return None
        kind = "widget" if re.match(r"Widget[A-Z]", root[1]) else "page"
    elif root[0] == "name":
        name = root[1]
        if re.match(r"Widget[A-Z]\w*$", name) and segs and segs[0][0] == "get" and segs[0][1] is not None:
            kind, segs = "widget", segs[1:]
        elif name in env.types:
            t = env.types[name]
            if not _is_widget_type(t, env.pages):
                return None
            kind = "widget" if re.match(r"Widget[A-Z]", t.split("<")[0].split(".")[-1]) else "page"
        elif name in env.inits:
            kind = _ui_kind(env.inits[name], env, depth + 1)
            if kind is None:
                return None
        else:
            return None
    else:
        return None
    for name, args in segs:
        if args is None or name in _VALUE_GETTERS:
            return None  # a field access, or a getter that returns a value
        if re.match(r"get[A-Z][\w$]*$", name) and args == "":
            kind = "widget"
            continue
        if name == "get" and args:
            kind = "widget"
            continue  # table cell / menu item by label
        return None
    return kind


def _widget_expr(text: str, env: _Env) -> bool:
    return _ui_kind(text, env) == "widget"


_FORMAT_CALLS = re.compile(r"(?<![\w$])(String\s*\.\s*format|\.\s*formatted|"
                           r"(?:log|logger|LOG|LOGGER)\s*\.\s*(?:info|debug|warn|error|trace))\s*\(")


@rule(id="24001", description="Data field concatenated without getValue()", category="Bugs")
def widget_concatenated(commits: CommitsDict, config) -> RuleResult:
    """
    A page widget concatenated with `+` or passed to String.format / .formatted / a logger without
    .getValue(), so its toString() -- "WidgetTextInput[<css id>]" (AbstractWidget.toString, centertest-core)
    -- lands in the text instead of what the field shows.

    Only widgets are reported. A DDT DataField is NOT: AbstractDataField.toString() returns its value
    (centertest-core datadriven/AbstractDataField.java), so `"x" + ddt.getName()` prints the same as
    `.getValue()`.

    Evidence required (precision): the expression is a chain of no-arg widget getters (or .get("label"))
    rooted at a generated page -- `new XPage(...)`, a variable/field/parameter typed as a class imported
    from a `.pages.` package, a `var` initialised from such a chain -- or at WidgetX.get(...). A chain that
    ends in a value getter (getValue, getText, getLabel, getRows, ...) or passes through anything else is
    not reported.
    """
    result = RuleResult(rule_id="24001", description="Data field concatenated without getValue()",
                        category="Bugs", headers=HEADERS)
    files = project_files(commits)
    index = ProjectIndex(files)
    for f, disp, ce, m, code in method_bodies(files):
        raw = m.body
        env = None
        found = {}
        for i, ch in enumerate(code):
            if ch != "+" or code[i - 1:i + 1] == "++" or code[i:i + 2] in ("++", "+="):
                continue
            prev = code[:i].rstrip()
            if not prev or prev[-1] in "(=,+-*/?:!&|{;<>":
                continue  # unary plus
            env = env or _Env(f, ce, m, code, raw, index)
            ls = expr_start(code, i)
            re_ = expr_end(code, i + 1)
            rs = len(code[:i + 1]) + (len(code[i + 1:re_]) - len(code[i + 1:re_].lstrip()))
            for a, b in ((ls, len(prev)), (rs, re_)):
                text = raw[a:b]
                if a < b and _widget_expr(text, env):
                    found.setdefault(a, ("concatenated", norm(text)))
        for hit in _FORMAT_CALLS.finditer(code):
            args = split_args(code, hit.end() - 1)
            if "formatted" not in hit.group(1):
                args = args[1:]
            env = env or _Env(f, ce, m, code, raw, index)
            for a, b in args:
                if _widget_expr(raw[a:b], env):
                    found.setdefault(a, ("formatted", norm(raw[a:b])))
        for offset, (how, text) in sorted(found.items()):
            issue = (f"{snippet(text, 70)} is {how} without .getValue(), so the text gets the widget's "
                     "toString() (its class and css id), not the value on screen")
            result.rows.append(_row(f, disp, m, raw, offset, issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} widget(s) used as text without .getValue()"
    return result


# ---------------------------------------------------------------------------
# 24002
# ---------------------------------------------------------------------------

@rule(id="24002", description="Same argument twice in a format call", category="Bugs")
def same_format_argument_twice(commits: CommitsDict, config) -> RuleResult:
    """
    String.format(fmt, ...), fmt.formatted(...) or logger.info/debug/warn/error/trace("...{}...", ...) given
    the identical argument expression twice -- usually a copy-paste where a different value was meant
    (PMIC: model year printed twice, the model never).

    Non-trivial arguments only: a call or a dotted chain (a bare name or literal may repeat on purpose).
    Skipped when the format string is a literal that uses explicit indexes (%1$s), where repeating an
    argument would be pointless anyway, and logger calls whose first argument is not a literal with {}.
    """
    result = RuleResult(rule_id="24002", description="Same argument twice in a format call",
                        category="Bugs", headers=HEADERS)
    for f, disp, ce, m, code in method_bodies(project_files(commits)):
        raw = m.body
        for hit in _FORMAT_CALLS.finditer(code):
            call = hit.group(1)
            args = split_args(code, hit.end() - 1)
            if "formatted" in call:
                rs = expr_start(code, hit.start())
                fmt = raw[rs:hit.start()].strip()
            else:
                if not args:
                    continue
                first = raw[args[0][0]:args[0][1]].strip()
                if "format" in call and not first.startswith('"') and len(args) > 1 and \
                        raw[args[1][0]:args[1][1]].strip().startswith('"'):
                    args = args[1:]  # String.format(Locale, fmt, ...)
                    first = raw[args[0][0]:args[0][1]].strip()
                fmt, args = first, args[1:]
                if "format" not in call and not (fmt.startswith('"') and "{}" in fmt):
                    continue
            if re.search(r"%\d+\$", fmt):
                continue
            seen = {}
            for a, b in args:
                text = norm(raw[a:b])
                if not text or text[0] in "\"'" or not re.search(r"[.(]", text):
                    continue
                if text in seen:
                    issue = (f"{snippet(text, 70)} is passed twice (arguments {seen[text] + 1} and "
                             f"{[x for x, _ in args].index(a) + 1}), so one placeholder shows the wrong value")
                    result.rows.append(_row(f, disp, m, raw, hit.start(), issue, config))
                    break
                seen[text] = [x for x, _ in args].index(a)
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} format call(s) with the same argument twice"
    return result


# ---------------------------------------------------------------------------
# 24003
# ---------------------------------------------------------------------------

_PARSE_FLOAT = re.compile(r"(?<![\w$.])(Float\s*\.\s*parseFloat|Float\s*\.\s*valueOf|Double\s*\.\s*parseDouble|"
                          r"Double\s*\.\s*valueOf|new\s+Float|new\s+Double)\s*\(")
_MONEY_WORD = re.compile(r"amount|amt(?![a-z])|cost|premium|total|payment|price|balance|fee(?!d)|tax(?!onom)|"
                         r"paid|charge|invoice|refund|deductible|dollar|money|due(?!l)", re.IGNORECASE)
_NOT_MONEY = re.compile(r"count|num|size|rows|pages|percent|pct|rate|ratio|factor|index|age|year|days|score",
                        re.IGNORECASE)


def _money_identifier(text: str) -> str | None:
    for ident in re.findall(r"[A-Za-z_$][\w$]*", text):
        if _MONEY_WORD.search(ident) and not _NOT_MONEY.search(ident):
            return ident
    return None


@rule(id="24003", description="Money parsed as float", category="Bugs")
def money_parsed_as_float(commits: CommitsDict, config) -> RuleResult:
    """
    Float.parseFloat / Float.valueOf / Double.parseDouble / Double.valueOf / new Float|Double(...) of currency
    text. Binary floating point cannot hold most cent values exactly, so sums, rounding and comparisons drift
    (use BigDecimal, or the widgets' numeric assertions).

    Money evidence, one of:
      * the argument strips a currency symbol (a replace/replaceAll whose literal contains `$`);
      * an identifier in the argument, or the variable it is assigned to, names money (amount, cost,
        premium, total, payment, price, balance, fee, tax, paid, charge, invoice, refund, deductible ...),
        unless it also names a count/rate/percent/size/index/age/year (totalCount, premiumRate).
    float/double casts are not reported: a cast cannot turn text into a number, so there is nothing to
    see at the cast itself.
    """
    result = RuleResult(rule_id="24003", description="Money parsed as float", category="Bugs", headers=HEADERS)
    for f, disp, ce, m, code in method_bodies(project_files(commits)):
        raw = m.body
        for hit in _PARSE_FLOAT.finditer(code):
            args = split_args(code, hit.end() - 1)
            if len(args) != 1:
                continue
            arg = raw[args[0][0]:args[0][1]]
            why = None
            for lit in re.finditer(r"\.\s*replace(?:All|First)?\s*\(\s*\"([^\"]*)\"", arg):
                if "$" in lit.group(1):
                    why = "the text has its $ stripped"
                    break
            if not why:
                ident = _money_identifier(code[args[0][0]:args[0][1]])
                if not ident:
                    target = re.search(r"([\w$]+)\s*=\s*$", code[:hit.start()].rsplit(";", 1)[-1])
                    ident = _money_identifier(target.group(1)) if target else None
                if ident:
                    why = f"{ident} is a money amount"
            if not why:
                continue
            fn = norm(hit.group(1)).replace("new", "new ")
            issue = (f"{fn}(...) parses money as binary floating point ({why}), so cents can be off by rounding; "
                     "use BigDecimal or a numeric widget assertion")
            result.rows.append(_row(f, disp, m, raw, hit.start(), issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} money value(s) parsed as float/double"
    return result


# ---------------------------------------------------------------------------
# 24004
# ---------------------------------------------------------------------------

_SETTER = re.compile(r"\.\s*(set[A-Z][\w$]*)\s*\(")
_GETTER_IN = re.compile(r"(?:^|[.\s(])get[A-Z]?[\w$]*\s*\(")
_IMPURE_VALUE = re.compile(r"(?<![\w$])(?:next\w*|random\w*|now|currentTimeMillis|nanoTime|randomUUID|"
                           r"generate\w*|create\w*|read\w*|poll\w*|pop)\s*\(|\bnew\b")


_DATA_RECEIVER = re.compile(r"helper|data", re.IGNORECASE)


def _blocks(code: str) -> list[int]:
    """For every offset, the offset of the innermost enclosing '{' (-1 outside)."""
    out, stack = [0] * len(code), []
    for i, ch in enumerate(code):
        if ch == "{":
            stack.append(i)
        out[i] = stack[-1] if stack else -1
        if ch == "}" and stack:
            stack.pop()
    return out


@rule(id="24004", description="Same Helper value set twice, or stored under the wrong key", category="Bugs")
def setter_value_twice(commits: CommitsDict, config) -> RuleResult:
    """
    In a run of consecutive setter statements (nothing else in between) on the same data receiver --
    Helper.getData(...), a local `var` holding it (receivers are compared after resolving such locals), or
    any receiver whose text names helper/data:
      * two DIFFERENT setters get the identical value expression -- one of them was meant to read a
        different field (PMIC: setInvoiceDate(summary.getEffectiveDate().getValue()));
      * one setter is called twice -- the first value is overwritten before anything reads it.
    A setter's identity is its name plus every argument but the last (setCustom("Key", v) and
    setCoverage(COV, TERM, v) are keyed setters; the last argument is the value).

    Guards: each call must be a whole statement (not after `if (...)`/`else` without braces); calls in
    different blocks (if/else branches, loops) or with any other statement between them (a page action
    may change what the getter reads) are never paired; widget/UI receivers are left out (unchecking and
    re-checking a coverage is a deliberate toggle); the shared value must read something
    (contain a get...() call) and must not produce a new value each time (now(), random, new ...).
    """
    result = RuleResult(rule_id="24004", description="Same Helper value set twice, or stored under the wrong key",
                        category="Bugs", headers=HEADERS)
    for f, disp, ce, m, code in method_bodies(project_files(commits)):
        raw = m.body
        if "set" not in code:
            continue
        aliases = {}
        for hit in re.finditer(r"\bvar\s+([\w$]+)\s*=", code):
            end = code.find(";", hit.end())
            if end > 0:
                aliases[hit.group(1)] = norm(raw[hit.end():end])
        blocks = None
        calls = []
        for hit in _SETTER.finditer(code):
            rs = expr_start(code, hit.start())
            if rs >= hit.start():
                continue
            before = code[:rs].rstrip()
            if before and before[-1] not in ";{}":
                continue
            end = balanced_end(code, hit.end() - 1)
            if not code[end:].lstrip().startswith(";"):
                continue
            recv = norm(raw[rs:hit.start()])
            recv = aliases.get(recv, recv)
            args = split_args(code, hit.end() - 1)
            if not args:
                continue
            # identity = setter + every argument but the last (setCustom("Key", v), setCoverage(COV, TERM, v))
            key, vals = hit.group(1), args[-1:]
            if len(args) >= 2:
                key = f"{key}({', '.join(norm(raw[a:b]) for a, b in args[:-1])})"
            value = ",".join(norm(raw[a:b]) for a, b in vals)
            blocks = blocks or _blocks(code)
            calls.append(dict(start=rs, end=code.find(";", end) + 1, recv=recv, key=key, value=value,
                              masked_value=",".join(code[a:b] for a, b in vals), block=blocks[rs]))
        groups = defaultdict(list)
        for c in calls:
            groups[(c["block"], c["recv"])].append(c)
        flagged = set()
        for (_, recv), group in groups.items():
            if not _DATA_RECEIVER.search(recv):
                continue  # widgets and UI helpers: setSelected(false) then (true) is a deliberate toggle
            group.sort(key=lambda c: c["start"])
            runs, run = [], []
            for c in group:
                if run and code[run[-1]["end"]:c["start"]].strip() != "":
                    runs.append(run)
                    run = []
                run.append(c)
            if run:
                runs.append(run)
            for run in runs:
                for i, c in enumerate(run):
                    if c["start"] in flagged:
                        continue
                    # one key twice
                    dups = [p for p in run[:i] if p["key"] == c["key"]]
                    if dups:
                        flagged.add(c["start"])
                        same = dups[-1]["value"] == c["value"]
                        issue = (f"{c['key']}() is called twice in the same run of setters"
                                 + (" with the same value (a copy-paste; another key was probably meant)" if same
                                    else ", so the first value is overwritten before anything reads it"))
                        result.rows.append(_row(f, disp, m, raw, c["start"], issue, config))
                        continue
                    # different setters, same value
                    if not _GETTER_IN.search(c["masked_value"]) or _IMPURE_VALUE.search(c["masked_value"]):
                        continue
                    prev = next((p for p in run[:i] if p["value"] == c["value"] and p["key"] != c["key"]), None)
                    if prev:
                        flagged.add(c["start"])
                        line = body_line(f, m, raw.count("\n", 0, prev["start"]))
                        issue = (f"{c['key']}() gets the same value as {prev['key']}() (line {line}): "
                                 f"{snippet(c['value'], 60)} -- one of them was probably meant to read another field")
                        result.rows.append(_row(f, disp, m, raw, c["start"], issue, config))
    result.rows = _sorted(result.rows)
    if result.rows:
        result.summary = f"{len(result.rows)} setter call(s) storing a value twice or under another key"
    return result
