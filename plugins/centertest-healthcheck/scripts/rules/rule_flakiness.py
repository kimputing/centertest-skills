"""
Flakiness rules (issue #47): code that passes or fails depending on timing, row order, randomness or
the machine clock rather than on the application.

19001 -- Retry loop re-clicks with no pause or limit
19002 -- Page-changing click with no wait after it
19003 -- First search result taken unfiltered
19004 -- Unseeded Random in a step
19005 -- LocalDate.now() in business-date logic

Framework facts these rules rely on (centertest-platform, read only):
  * AbstractWidget.click()/pausableClick() wait for the Guidewire Ajax round trip
    (AjaxUtil.waitForAjax, waitForOverlayBusyThenIdle) and every widget read retries until the
    widget is found (AbstractWidget.getWebElement / actionForStaleElements). A click on Next or a
    tab that is simply followed by more widget calls is therefore NOT a race -- 19002 only flags
    the one read that does not retry: BaseScenarioGw.getPageTitle(), a single findElementByCss.
  * GW.LocalDate(context) / GW.LocalDateTime(context) are the Guidewire business date (machine
    clock + the server's time-travel offset); DateField.getAsDate(LocalDate systemDate) resolves a
    DDT date offset against a given date (getAsDate() alone resolves it against LocalDate.now()).
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, SourceCodeFile
from eir_rules import rule
from rule_helpers import ProjectIndex, body_start_line, latest_files, location, scanned_classes, snippet


# ---------------------------------------------------------------------------
# Shared private helpers
# ---------------------------------------------------------------------------

def _mask(text: str) -> str:
    """Same-length copy of `text` with comments turned into spaces and the contents of string and
    char literals into '_' (quotes and newlines kept): offsets and line numbers stay valid, and no
    pattern can match inside a comment or a literal."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if text[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if ch in "\"'":
            if text.startswith('"""', i):  # Java text block
                j = text.find('"""', i + 3)
                j = n if j < 0 else j
                for k in range(i + 3, j):
                    if text[k] != "\n":
                        out[k] = "_"
                i = j + 3
                continue
            j = i + 1
            while j < n and text[j] != ch and text[j] != "\n":
                if text[j] == "\\":
                    out[j] = "_"
                    j += 1
                    if j < n and text[j] != "\n":
                        out[j] = "_"
                    j += 1
                    continue
                out[j] = "_"
                j += 1
            i = j + 1
            continue
        i += 1
    return "".join(out)


def _close(code: str, open_index: int) -> int:
    """Index just past the bracket closing the one at open_index (masked code); len(code) if none."""
    pairs = {"{": "}", "(": ")", "[": "]"}
    opener, closer = code[open_index], pairs[code[open_index]]
    depth = 0
    for i in range(open_index, len(code)):
        if code[i] == opener:
            depth += 1
        elif code[i] == closer:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(code)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_generated(f: SourceCodeFile) -> bool:
    return "generated" in f.package_name.split(".") or "/generated/" in f.key.replace("\\", "/")


class _Spans:
    """Method spans of one file: (display class, ClassEntry, Method, first line, last line)."""

    def __init__(self, f: SourceCodeFile):
        self.items = []
        lines = f.source.splitlines()
        for name, ce in scanned_classes(f):
            for m in ce.methods:
                if not m.body or "abstract" in m.modifiers:
                    continue
                start = body_start_line(f, m) or m.line
                if not start:
                    continue
                end = start + max(len(m.body.splitlines()) - 1, 0)
                # body lines are stripped copies of the file's lines: re-anchor the end on the file
                end = min(end, len(lines))
                self.items.append((name, ce, m, m.line or start, end))

    def at(self, line: int):
        """Innermost method whose declaration..closing brace covers `line`, or None."""
        best = None
        for item in self.items:
            if item[3] <= line <= item[4] and (best is None or item[4] - item[3] < best[4] - best[3]):
                best = item
        return best


def _row(f, spans: _Spans, line: int, issue: str, config) -> list | None:
    hit = spans.at(line)
    if hit is None:
        return None
    src_line = f.source.splitlines()[line - 1] if 0 < line <= len(f.source.splitlines()) else ""
    return [hit[0], hit[2].name, snippet(src_line), issue, location(f, line, config)]


def _files(commits: CommitsDict) -> list[SourceCodeFile]:
    return sorted((f for f in latest_files(commits)
                   if f.main_class is not None and f.source and not _is_generated(f)), key=lambda f: f.key)


def _sorted_rows(rows: list[list]) -> list[list]:
    def key(r):
        path, _, num = r[-1].rpartition(":")
        return (path, int(num) if num.isdigit() else 0, r[0], r[1])
    return sorted(rows, key=key)


# ---------------------------------------------------------------------------
# 19001 -- Retry loop re-clicks with no pause or limit
# ---------------------------------------------------------------------------

_CLICK = re.compile(r"\.(?:click|pausableClick|clickAndAccept|clickByName)\s*\(")
_PAUSE = re.compile(r"\bwaitFor\w*\s*\(|\bsleep\s*\(|\bSleep\b|\.wait\s*\(|\bawait\w*\s*\(")
_COUNTER = re.compile(r"\+\+|--|\+=|-=")
_DEADLINE = re.compile(
    r"currentTimeMillis|nanoTime|\b(?:Instant|LocalDateTime|LocalTime|LocalDate|ZonedDateTime|OffsetDateTime)\.now\b"
    r"|\bGW\.LocalDateTime\b|\bStopWatch\b|\bDuration\b|\bClock\b"
    r"|\b\w*(?:deadline|timeout|elapsed|expir\w*|attempt\w*|retr(?:y|ies)|tries|maxTries|limit)\b",
    re.IGNORECASE)
_ITERATION = re.compile(r"\bhasNext\s*\(|\(\s*\w+\s*=\s*[^;]+\)\s*!=\s*(?:null|-1)\b")
_WHILE = re.compile(r"\bwhile\s*\(")
_DO = re.compile(r"\bdo\s*\{")
_FOR_EVER = re.compile(r"\bfor\s*\(\s*;\s*;\s*\)\s*\{")
# what rule 15017 already reports (a while loop with none of these in its body)
_15017_SAFE = ("break", "return", "throw", "++", "--", "+=", "-=", "System.currentTimeMillis", "Instant.now",
               "System.nanoTime", "LocalDateTime.now", "LocalTime.now")


def _loops(code: str):
    """(kind, start offset, condition text, body text) for while / do-while / for(;;) loops."""
    for m in _WHILE.finditer(code):
        if code[:m.start()].rstrip().endswith("}"):
            continue  # the tail of a do { } while (...);
        cond_end = _close(code, m.end() - 1)
        rest = code[cond_end:]
        if not rest.lstrip().startswith("{"):
            continue
        brace = cond_end + (len(rest) - len(rest.lstrip()))
        yield "while", m.start(), code[m.end():cond_end - 1], code[brace + 1:_close(code, brace) - 1]
    for m in _DO.finditer(code):
        brace = m.end() - 1
        end = _close(code, brace)
        tail = re.match(r"\s*while\s*\(", code[end:])
        cond = ""
        if tail:
            open_paren = end + tail.end() - 1
            cond = code[open_paren + 1:_close(code, open_paren) - 1]
        yield "do", m.start(), cond, code[brace + 1:end - 1]
    for m in _FOR_EVER.finditer(code):
        brace = m.end() - 1
        yield "for", m.start(), "", code[brace + 1:_close(code, brace) - 1]


@rule(id="19001", description="Retry loop re-clicks with no pause or limit", category="Flakiness")
def retry_loop_without_pause_or_limit(commits: CommitsDict, config) -> RuleResult:
    """
    A while / do-while / for(;;) loop whose body clicks (click, pausableClick, clickAndAccept,
    clickByName) and that has NEITHER a pause between attempts (waitFor*, sleep, ImplicitSleep,
    .wait) NOR any limit (a counter ++/--/+=/-=, a clock or StopWatch, or a deadline / timeout /
    attempt / retry / limit variable) in its condition or body. Such a loop ends only when the
    application gives the answer it waits for; when it never does, the test spins until the suite
    times out, hammering the server meanwhile.

    Guards: iteration loops (hasNext(), read-until-null) are skipped; a `while` loop that rule
    15017 already reports (main class, body with no break/return/throw) is left to 15017, so this
    rule adds the shapes 15017 accepts: a success `break`/`return` or an error `throw` inside an
    otherwise unbounded loop, do-while loops and for(;;). A loop with a deadline but no pause is
    NOT flagged: click() waits for the Ajax response, so each attempt is paced by the server and
    the deadline ends it.
    """
    result = RuleResult(rule_id="19001", description="Retry loop re-clicks with no pause or limit",
                        category="Flakiness", headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in _files(commits):
        code = _mask(f.source)
        spans = _Spans(f)
        main = f.main_class
        for kind, start, cond, body in _loops(code):
            if not _CLICK.search(body):
                continue
            both = cond + "\n" + body
            if _PAUSE.search(both) or _COUNTER.search(both) or _DEADLINE.search(both) or _ITERATION.search(cond):
                continue
            line = _line(code, start)
            hit = spans.at(line)
            if hit is None:
                continue
            if kind == "while" and hit[1] is main and not any(tok in body for tok in _15017_SAFE):
                continue  # rule 15017 reports this one
            issue = ("The loop clicks again on every pass with no pause and no attempt limit or deadline, "
                     "so when the expected result never comes the test spins until the suite times out.")
            row = _row(f, spans, line, issue, config)
            if row:
                result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result


# ---------------------------------------------------------------------------
# 19002 -- Page-changing click with no wait after it
# ---------------------------------------------------------------------------

_CLICK_STATEMENT = re.compile(r"\.(?:click|pausableClick|clickAndAccept)\s*\(\s*\)\s*;")
_TITLE_READ = re.compile(r"(?<![\w.])getPageTitle\s*\(\s*\)|\bgetBrowser\s*\(\s*\)\s*\.\s*find\w*\s*\(")


@rule(id="19002", description="Page-changing click with no wait after it", category="Flakiness")
def click_then_unwaited_page_read(commits: CommitsDict, config) -> RuleResult:
    """
    A click statement directly followed by a statement that reads the current page with a single,
    non-retrying lookup -- getPageTitle() (BaseScenarioGw: one findElementByCss) or a raw
    getBrowser().find*() -- with no waitForPageTitle/waitForElement in between. The code expects the
    click may change the page and branches on which page is showing; when the response is slower
    than the click's Ajax wait it reads the old page and takes the wrong branch.

    Narrowed on purpose (verified in centertest-platform): AbstractWidget.click() already waits for
    the Guidewire Ajax round trip and the overlay, and widget reads retry until their widget is
    found, so a Next/tab click followed by more widget calls, or at the end of a method, is not a
    race and is not flagged. Fix: waitForPageTitle("A", "B") (it accepts several titles) before
    reading the title.
    """
    result = RuleResult(rule_id="19002", description="Page-changing click with no wait after it",
                        category="Flakiness", headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in _files(commits):
        code = _mask(f.source)
        spans = _Spans(f)
        for m in _CLICK_STATEMENT.finditer(code):
            rest = code[m.end():]
            stripped = rest.lstrip()
            if not stripped or stripped[0] in "}":
                continue
            ends = [i for i in (stripped.find(";"), stripped.find("{")) if i >= 0]
            nxt = stripped[:min(ends)] if ends else stripped
            if not _TITLE_READ.search(nxt) or re.search(r"\bwaitFor\w*\s*\(", nxt):
                continue
            line = _line(code, m.start())
            issue = ("getPageTitle() reads the page once, straight after a click that can change it and with no "
                     "waitForPageTitle(...) first, so a slow response is read as the old page and the wrong branch runs.")
            row = _row(f, spans, line, issue, config)
            if row:
                result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result


# ---------------------------------------------------------------------------
# 19003 -- First search result taken unfiltered
# ---------------------------------------------------------------------------

_FIRST_ROW_SELECT = re.compile(r"\.\s*getFirstRow\s*\(\s*\)\s*\.\s*select\s*\(\s*\)")
_SEARCH_TABLE = re.compile(r"search|result", re.IGNORECASE)
_UNIQUE_KEY_SET = re.compile(r"\bget(\w*?)(?:Number|Num|No|ID|Id)\s*\(\s*\)\s*\.\s*set\s*\(")
_RECEIVER = re.compile(r"(\w+)\s*(?:\(\s*\))?\s*$")


def _receiver_names(code: str, match_start: int, method_text: str) -> list[str]:
    """The table expression's last name (getter or variable) before .getFirstRow(), plus -- for a
    variable -- the last getter of its `var x = ...;` initializer in the method."""
    m = _RECEIVER.search(code[max(0, match_start - 200):match_start])
    if not m:
        return []
    name = m.group(1)
    names = [name]
    init = re.search(r"\b" + re.escape(name) + r"\s*=\s*([^;]+);", method_text)
    if init:
        getters = re.findall(r"\b(get\w+)\s*\(", init.group(1))
        if getters:
            names.append(getters[-1])
        news = re.findall(r"\bnew\s+(\w+)\s*\(", init.group(1))
        names += news[-1:]
    return names


@rule(id="19003", description="First search result taken unfiltered", category="Flakiness")
def first_search_row_unfiltered(commits: CommitsDict, config) -> RuleResult:
    """
    `table.getFirstRow().select()` -- the first row taken with no `.withX(...)` filter between
    getFirstRow() and select() -- on a search or result table (the table getter or variable name
    contains "Search" or "Result"). When the search returns several rows, or returns them in another
    order, the test silently works on the wrong record.

    Guards: only search/result tables (a policy's own vehicle or territory table holds rows the test
    created); a search whose criteria include a unique key of the same entity before the select
    (`getAccountNumber().set(...)` for an AccountSearchResults table, `getSubmissionNumber()` for a
    submission table) returns one row and is skipped. A key of another entity (searching recoveries
    by claim number) does not make the row unique and is still reported.
    """
    result = RuleResult(rule_id="19003", description="First search result taken unfiltered",
                        category="Flakiness", headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in _files(commits):
        code = _mask(f.source)
        spans = _Spans(f)
        lines_offsets = [0]
        for ln in code.splitlines(keepends=True):
            lines_offsets.append(lines_offsets[-1] + len(ln))
        for m in _FIRST_ROW_SELECT.finditer(code):
            line = _line(code, m.start())
            hit = spans.at(line)
            if hit is None:
                continue
            method_start = lines_offsets[hit[3] - 1] if hit[3] - 1 < len(lines_offsets) else 0
            method_text = code[method_start:m.start()]
            names = _receiver_names(code, m.start(), method_text)
            if not any(_SEARCH_TABLE.search(n) for n in names):
                continue
            joined = " ".join(names).lower()
            keys = [k for k in _UNIQUE_KEY_SET.findall(method_text) if k]
            if any(k.lower() in joined for k in keys):
                continue
            issue = ("The first row of a search result is taken with no .withX(...) filter, so when the search "
                     "returns more than one row, or another order, the test silently works on the wrong record.")
            row = _row(f, spans, line, issue, config)
            if row:
                result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result


# ---------------------------------------------------------------------------
# 19004 -- Unseeded Random in a step
# ---------------------------------------------------------------------------

_UNSEEDED = re.compile(
    r"\bnew\s+(?:java\.util\.)?Random\s*\(\s*(?:System\s*\.\s*(?:currentTimeMillis|nanoTime)\s*\(\s*\)\s*)?\)"
    r"|\bMath\s*\.\s*random\s*\(\s*\)"
    r"|\bThreadLocalRandom\s*\.\s*current\s*\(\s*\)")


def _is_test_or_step(f: SourceCodeFile, ce, index: ProjectIndex) -> bool:
    if any(i.startswith("I") and i.endswith("Exit") or i.endswith("Generator") for i in ce.interfaces):
        return False
    if ce.class_name.endswith(("Exit", "Generator")):
        return False
    if f.is_test_class() or "CenterTest" in ce.annotations or "ScenarioContainer" in ce.annotations:
        return True
    return index.is_step(ce)


@rule(id="19004", description="Unseeded Random in a step", category="Flakiness")
def unseeded_random(commits: CommitsDict, config) -> RuleResult:
    """
    `new Random()` (or seeded with the clock), `Math.random()` or `ThreadLocalRandom.current()` in a
    test class or a step (ProjectIndex.is_step, inner classes included). The value differs on every
    run and is not logged, so a failure that depends on it cannot be reproduced.

    Guards: only tests and steps -- a value-generator exit (implements I*Exit, or a *Exit/*Generator
    class) is exactly where random test data belongs and is skipped; `new Random(seed)` with a real
    seed is fine; the framework's own helpers (Utilities.getRandom*, the DC value tokens) are not
    matched.
    """
    result = RuleResult(rule_id="19004", description="Unseeded Random in a step",
                        category="Flakiness", headers=["Class", "Method", "Line", "Issue", "Location"])
    files = _files(commits)
    index = ProjectIndex(latest_files(commits))
    for f in files:
        code = _mask(f.source)
        spans = _Spans(f)
        for m in _UNSEEDED.finditer(code):
            line = _line(code, m.start())
            hit = spans.at(line)
            if hit is None or not _is_test_or_step(f, hit[1], index):
                continue
            issue = ("An unseeded random value changes on every run and is not recorded, so a failure that depends "
                     "on it cannot be reproduced; generate it with a DC value token or seed and log it.")
            row = _row(f, spans, line, issue, config)
            if row:
                result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result


# ---------------------------------------------------------------------------
# 19005 -- LocalDate.now() in business-date logic
# ---------------------------------------------------------------------------

_NOW = re.compile(
    r"\b(?:java\.time\.)?(?:LocalDate|LocalDateTime|ZonedDateTime|OffsetDateTime)\s*\.\s*now\s*\(\s*(?:ZoneId\b[^)]*\)?)?\)"
    r"|\bnew\s+(?:java\.util\.)?Date\s*\(\s*\)"
    r"|\bCalendar\s*\.\s*getInstance\s*\(\s*\)")
_DAY_MATH = re.compile(
    r"\.\s*(?:plus|minus)(?:Days|Weeks|Months|Years)\s*\("
    r"|\bPeriod\s*\.\s*between\s*\("
    r"|\bChronoUnit\s*\.\s*(?:DAYS|WEEKS|MONTHS|YEARS)\s*\.\s*between\s*\("
    r"|\.\s*with(?:DayOfMonth|DayOfYear|Month|Year)\s*\("
    r"|\.\s*(?:plus|minus)\s*\(\s*\d+\s*,\s*ChronoUnit\s*\.\s*(?:DAYS|WEEKS|MONTHS|YEARS)"
    r"|\.\s*(?:plus|minus)\s*\(\s*Period\b"
    r"|\.\s*datesUntil\s*\("
    r"|\badd(?:Days|Weeks|Months|Years)\s*\(")
_CAL_DAY_ADD = r"\.\s*(?:add|roll|set)\s*\(\s*Calendar\s*\.\s*(?:DATE|DAY_OF_MONTH|DAY_OF_YEAR|DAY_OF_WEEK|WEEK_OF_YEAR|MONTH|YEAR)\b"
_WIDGET_SET = re.compile(r"\.\s*set\s*\(")
_ASSIGN = re.compile(r"(?:\b[\w.<>]+\s+)?(\w+)\s*=\s*$")


def _statement_bounds(code: str, offset: int) -> tuple[int, int]:
    start = max(code.rfind(";", 0, offset), code.rfind("{", 0, offset), code.rfind("}", 0, offset)) + 1
    end = code.find(";", offset)
    return start, (len(code) if end < 0 else end)


@rule(id="19005", description="LocalDate.now() in business-date logic", category="Flakiness")
def machine_clock_in_business_dates(commits: CommitsDict, config) -> RuleResult:
    """
    The machine clock -- LocalDate.now(), LocalDateTime.now(), ZonedDateTime.now(), new Date(),
    Calendar.getInstance() -- used for business dates: in day/week/month/year arithmetic
    (plusDays, Period.between, ChronoUnit.DAYS.between, withDayOfMonth, Calendar.add(DATE ...)) or
    set into a widget, in the same statement or through a variable assigned from it in the same
    method. Under Guidewire time travel the application's date is GW.LocalDate(context), not the
    machine's, so the computed date is off by the travel offset (and by a day around midnight).

    Guards: timeouts and deadlines (now().plusSeconds(60), isAfter(deadline)), timestamps for
    unique names and log lines, `now(clock)` with an injected clock, and projects that do not use
    the Guidewire widgets (no com.ankrpt.centertest.guidewire import anywhere) are not flagged.
    """
    result = RuleResult(rule_id="19005", description="LocalDate.now() in business-date logic",
                        category="Flakiness", headers=["Class", "Method", "Line", "Issue", "Location"])
    all_files = latest_files(commits)
    if not any(imp.startswith("com.ankrpt.centertest.guidewire") for f in all_files for imp in f.imports):
        return result
    for f in _files(commits):
        code = _mask(f.source)
        spans = _Spans(f)
        offsets = [0]
        for ln in code.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(ln))
        for m in _NOW.finditer(code):
            line = _line(code, m.start())
            hit = spans.at(line)
            if hit is None:
                continue
            s, e = _statement_bounds(code, m.start())
            statement = code[s:e]
            business = bool(_DAY_MATH.search(statement)) or bool(_WIDGET_SET.search(code[s:m.start()]))
            if not business:
                # a variable assigned from the clock: follow it through the rest of the method
                assigned = _ASSIGN.search(code[s:m.start()])
                end_off = offsets[min(hit[4], len(offsets) - 1)]
                if assigned and re.fullmatch(r"\s*(?:\.\s*(?:plus|minus)(?:Seconds|Minutes|Hours|Millis|Nanos)\s*\([^;]*\))?\s*",
                                             code[m.end():e]) is not None:
                    var = re.escape(assigned.group(1))
                    later = code[e:end_off]
                    uses = (
                        re.search(r"\b" + var + r"\s*\.\s*(?:plus|minus)(?:Days|Weeks|Months|Years)\s*\(", later)
                        or re.search(r"\b" + var + r"\s*\.\s*with(?:DayOfMonth|DayOfYear|Month|Year)\s*\(", later)
                        or re.search(r"(?:Period|ChronoUnit\s*\.\s*(?:DAYS|WEEKS|MONTHS|YEARS))\s*\.\s*between\s*\([^;]*\b"
                                     + var + r"\b", later)
                        or re.search(r"\b" + var + r"\s*" + _CAL_DAY_ADD, later)
                        or re.search(r"\.\s*set\s*\(\s*" + var + r"\b", later)
                    )
                    business = bool(uses)
            if not business:
                continue
            issue = ("The machine clock feeds business-date arithmetic, so under Guidewire time travel the date is off "
                     "by the travel offset; use GW.LocalDate(context) (or DateField.getAsDate(businessDate)).")
            row = _row(f, spans, line, issue, config)
            if row:
                result.rows.append(row)
    result.rows = _sorted_rows(result.rows)
    return result
