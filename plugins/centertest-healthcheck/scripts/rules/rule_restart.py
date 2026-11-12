"""
Rules 16001-16004: restart points (scenarioContext.restart / restartComplete).

Verified in centertest-platform (centertest-core, runner/context/ScenarioContext.java):
  * restart(point) returns true when the point's ordinal is >= the saved resume point (or nothing is
    saved), false otherwise -- on a rerun every block before the resume point is skipped. Without a
    test manager restart() always returns true.
  * The points are the constants of the CALLER's nested enum `RestartPoints`
    (Class.forName(caller + "$RestartPoints")): their order is the ordinal order.
  * restartComplete(X) saves X's successor (by ordinal) as the resume point, or FINAL after the last
    one. Nothing else advances it: a point that is never completed leaves the resume point where it
    was, so a rerun after a later failure runs that block again; a point completed under another
    constant Y moves the resume point to Y's successor, so a rerun skips every block up to Y, done
    or not.
  * TestRailAPI clears the saved point (withRestart(null)) when the test passes.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_helpers import (ProjectIndex, all_methods, balanced_end, body_line, code_only, latest_files,
                          line_of_offset, location, snippet)

_HEADERS = ["Class", "Method", "Line", "Issue", "Location"]
_RESTART_CALL = re.compile(r"\.\s*restart\s*\(\s*([\w.]+)\s*[,)]")
_COMPLETE_CALL = re.compile(r"\.\s*restartComplete\s*\(\s*([\w.]+)\s*\)")
_ANY_RESTART = re.compile(r"\.\s*restart\s*\(")
_ENUM_RE = re.compile(r"\benum\s+(\w+)\s*\{([^{}]*?)(?:;[^{}]*)?\}")


def _is_generated(f) -> bool:
    return "generated" in (f.package_name or "").split(".")


def _files(commits: CommitsDict):
    return [f for f in latest_files(commits) if f.main_class is not None and not _is_generated(f)]


def _lines(f) -> list[str]:
    return f.source.splitlines()


def _line(f, n: int) -> str:
    lines = _lines(f)
    return snippet(lines[n - 1]) if 0 < n <= len(lines) else ""


def _enums(f) -> list[tuple[str, list[tuple[str, int]]]]:
    """[(enum simple name, [(constant, line)])] declared in the file (javalang, or a regex fallback)."""
    out = []
    code = None
    for ce in f.other_types:
        if ce.kind != "enum":
            continue
        consts = []
        for fl in ce.fields:
            if fl.type != ce.class_name:
                continue
            line = fl.line
            if not line:  # javalang leaves some constants without a position: find it after `enum Name`
                code = code if code is not None else code_only(f.source)
                em = re.search(r"\benum\s+" + re.escape(ce.class_name) + r"\b", code)
                cm = em and re.compile(r"\b" + re.escape(fl.name) + r"\b").search(code, em.end())
                line = line_of_offset(code, cm.start()) if cm else (ce.line or 1)
            consts.append((fl.name, line))
        out.append((ce.key.rsplit(".", 1)[-1], consts))
    if not out and f.cannot_compile:
        code = code_only(f.source)
        for m in _ENUM_RE.finditer(code):
            consts = []
            for cm in re.finditer(r"\b([A-Z_][A-Z0-9_]*)\b", m.group(2)):
                consts.append((cm.group(1), line_of_offset(code, m.start(2) + cm.start())))
            out.append((m.group(1), consts))
    return out


def _restart_enum_names(files) -> set[str]:
    """Enums used as restart points: every `RestartPoints`, plus any enum a restart(...) call qualifies."""
    names = {"RestartPoints"}
    for f in files:
        for m in _RESTART_CALL.finditer(code_only(f.source)):
            parts = m.group(1).split(".")
            if len(parts) >= 2 and parts[-2][:1].isupper():
                names.add(parts[-2])
    return names


def _point(arg: str, enum_names: set[str], local_consts: set[str]) -> str | None:
    """The restart point a call argument names (`RestartPoints.X`, `Outer.RestartPoints.X`, or a bare
    constant of the file's enum), else None (a variable, a string, an expression)."""
    parts = arg.split(".")
    if len(parts) >= 2 and parts[-2] in enum_names:
        return parts[-1]
    if len(parts) == 1 and arg in local_consts:
        return arg
    return None


def _owner(f, offset: int, code: str) -> tuple[str, str]:
    """(display class, method) whose body holds the code offset (the innermost by declaration line)."""
    line = line_of_offset(code, offset)
    best = (f.main_class.class_name, "", 0)
    for cls, _, m in all_methods(f):
        if m.line and m.line <= line <= m.line + m.body.count("\n") + 12 and m.line >= best[2]:
            best = (cls, m.name, m.line)
    return best[0], best[1]


# ---------------------------------------------------------------------------
# 16001 -- Login inside a restart block
# ---------------------------------------------------------------------------

_LOGIN = re.compile(r"\b([A-Z]\w*)\s*\.\s*(login\w*)\s*\(\s*(\w+)")
_IF_RESTART = re.compile(r"\bif\s*\(\s*(!?)\s*[\w.()]*?\.\s*restart\s*\(")


def _restart_blocks(code: str):
    """(condition end, block start, block end, else text, end of if/else) for each
    `if (x.restart(...)) { ... }` (a negated condition is skipped: its block runs on the rerun)."""
    for m in _IF_RESTART.finditer(code):
        if m.group(1):
            continue
        open_paren = code.find("(", m.start())
        cond_end = balanced_end(code, open_paren)
        brace = cond_end
        while brace < len(code) and code[brace] in " \t\r\n":
            brace += 1
        if brace >= len(code) or code[brace] != "{":
            continue
        end = balanced_end(code, brace)
        else_text, after = "", end
        em = re.match(r"\s*else\s*\{", code[end:])
        if em:
            eb = end + em.end() - 1
            after = balanced_end(code, eb)
            else_text = code[eb:after]
        yield cond_end, brace, end, else_text, after


@rule(id="16001", description="Login inside a restart block", category="Restart")
def login_inside_restart_block(commits: CommitsDict, config) -> RuleResult:
    """A facade login (`PC.loginToPC(producer)`, any facade method named login*) inside
    `if (scenarioContext.restart(...)) { ... }` whose user is needed after the block.

    On a rerun that resumes after that point the block is skipped, login included. Flagged only
    when the first later call of the same facade with the same context variable (after the block,
    or in its else branch) is not itself a login -- so a test whose block holds the only work
    for that context (e.g. a PC login and policy, then a CC login and claim) is not flagged.
    Facade = a project facade interface (ProjectIndex.facades) or an all-capitals qualifier.
    """
    result = RuleResult(rule_id="16001", description="Login inside a restart block", category="Restart",
                        headers=list(_HEADERS))
    files = _files(commits)
    facades = set(ProjectIndex(latest_files(commits)).facades())
    for f in files:
        for cls, ce, m in all_methods(f):
            if not m.body or ".restart" not in m.body:
                continue
            code = code_only(m.body)
            seen = set()
            for _, start, end, else_text, after in _restart_blocks(code):
                for lm in _LOGIN.finditer(code, start, end):
                    facade, method, ctx = lm.groups()
                    if facade not in facades and not re.fullmatch(r"[A-Z]{2,4}", facade):
                        continue
                    use = re.compile(r"\b" + re.escape(facade) + r"\s*\.\s*(\w+)\s*\([^;]*?\b" + re.escape(ctx) + r"\b")
                    if any(u.group(1).startswith("login") for u in use.finditer(else_text)):
                        continue
                    nxt = use.search(else_text) or use.search(code, after)
                    if nxt is None or nxt.group(1).startswith("login") or lm.start() in seen:
                        continue
                    seen.add(lm.start())
                    file_line = _body_file_line(f, m, code, lm.start())
                    result.rows.append([
                        cls, m.name, _line(f, file_line),
                        f"{facade}.{method}({ctx}) runs only inside the restart block, but {facade}.{nxt.group(1)}"
                        f"({ctx}...) after it needs that login: on a rerun the block is skipped and the test "
                        "continues logged out; log in before the block", location(f, file_line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} login(s) a rerun skips while later steps still need them"
    return result


def _body_file_line(f, m, code: str, offset: int) -> int:
    return body_line(f, m, line_of_offset(code, offset) - 1)


# ---------------------------------------------------------------------------
# 16002 -- restart() without a matching restartComplete()
# ---------------------------------------------------------------------------

@rule(id="16002", description="restart() without a matching restartComplete()", category="Restart")
def restart_without_complete(commits: CommitsDict, config) -> RuleResult:
    """A restart(X) whose point no restartComplete(X) completes in the same file (trust rule).

    Points are resolved by name: `RestartPoints.X` (or any enum a restart() call qualifies), or a
    bare constant of the file's own enum. Guards: a file where restartComplete() takes anything
    else (a variable -- a wrapper that completes whatever it was given) is skipped; a point
    completed in another file that names the enum's owner class counts as completed. When the
    restart block completes a different constant the Issue says so.
    """
    result = RuleResult(rule_id="16002", description="restart() without a matching restartComplete()",
                        category="Restart", headers=list(_HEADERS))
    files = _files(commits)
    enum_names = _restart_enum_names(files)
    codes = {f.key: code_only(f.source) for f in files}
    for f in files:
        code = codes[f.key]
        if not _ANY_RESTART.search(code):
            continue
        local = {c for name, consts in _enums(f) if name in enum_names for c, _ in consts}
        completes = [(_point(m.group(1), enum_names, local), m) for m in _COMPLETE_CALL.finditer(code)]
        if any(p is None for p, _ in completes) or re.search(r"\.\s*restartComplete\s*\(\s*[^\w\s]", code):
            continue  # restartComplete(variable or expression): cannot tell which point it completes
        done = {p for p, _ in completes}
        owner = f.main_class.class_name
        for m in _RESTART_CALL.finditer(code):
            point = _point(m.group(1), enum_names, local)
            if point is None or point in done:
                continue
            if any(re.search(r"\brestartComplete\s*\(\s*[\w.]*\b" + re.escape(owner) + r"\.\w+\." + re.escape(point) + r"\s*\)",
                             codes[g.key]) for g in files if g is not f):
                continue
            other = None
            for cond_end, start, end, _, _ in _restart_blocks(code):
                if m.start() < cond_end <= start and not code[m.end():cond_end].count(";"):
                    inner = [p for p, cm in completes if start <= cm.start() < end]
                    other = inner[0] if inner else None
                    break
            line = line_of_offset(code, m.start())
            cls, meth = _owner(f, m.start(), code)
            if other:
                issue = (f"restart({point}) is completed as restartComplete({other}): the saved resume point jumps "
                         f"past {other} whether or not its block ran, so a rerun skips or repeats that work")
            else:
                issue = (f"no restartComplete({point}) closes restart({point}): the resume point never moves past "
                         "it, so a rerun after a later failure runs that block again")
            result.rows.append([cls, meth, _line(f, line), issue, location(f, line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} restart point(s) never completed under their own constant"
    return result


# ---------------------------------------------------------------------------
# 16003 -- RestartPoints constant never used
# ---------------------------------------------------------------------------

@rule(id="16003", description="RestartPoints constant never used", category="Restart")
def unused_restart_points(commits: CommitsDict, config) -> RuleResult:
    """Constants of a restart enum (`RestartPoints`, or any enum a restart() call qualifies) that no
    restart(...) call uses.

    A constant is used when a restart() call in the declaring file names it (bare or qualified),
    or a restart() call elsewhere names `<enum>.X` in a file that mentions the declaring class.
    Guard: when the declaring file calls restart() with a variable (a wrapper method), any other
    reference to the constant in that file counts as a use.
    """
    result = RuleResult(rule_id="16003", description="RestartPoints constant never used", category="Restart",
                        headers=["Class", "Constant", "Line", "Issue", "Location"])
    files = _files(commits)
    enum_names = _restart_enum_names(files)
    codes = {f.key: code_only(f.source) for f in files}
    for f in files:
        code = codes[f.key]
        for enum_name, consts in _enums(f):
            if enum_name not in enum_names or not consts:
                continue
            if re.search(r"\b" + re.escape(enum_name) + r"\s*\.\s*(?:values|valueOf)\s*\(", code):
                continue
            local = {c for c, _ in consts}
            used = set()
            wrapper = False
            for m in _RESTART_CALL.finditer(code):
                p = _point(m.group(1), {enum_name}, local)
                if p:
                    used.add(p)
                elif "." not in m.group(1):
                    wrapper = True
            owner = f.main_class.class_name
            for g in files:
                if g is f or owner not in codes[g.key]:
                    continue
                for m in _RESTART_CALL.finditer(codes[g.key]):
                    p = _point(m.group(1), {enum_name}, set())
                    if p:
                        used.add(p)
            for const, line in consts:
                if const in used:
                    continue
                if wrapper and re.search(r"\b" + re.escape(enum_name) + r"\s*\.\s*" + re.escape(const) + r"\b", code):
                    continue
                if not _ANY_RESTART.search(code):
                    issue = (f"restart point {const} is declared but the class never calls restart(): the enum is "
                             "dead code that suggests a rerun resumes where it cannot; remove it")
                else:
                    issue = (f"restart point {const} is declared but no restart() call uses it: a leftover that "
                             "misleads readers about which steps a rerun skips; remove it or add its block")
                result.rows.append([owner, f"{enum_name}.{const}", _line(f, line), issue, location(f, line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} restart point constant(s) no restart() call uses"
    return result


# ---------------------------------------------------------------------------
# 16004 -- Long flow with no restart points
# ---------------------------------------------------------------------------

def _threshold(config, rule_id: str, default: int) -> int:
    getter = getattr(config, "get_threshold", None)
    if getter is None:
        return default
    try:
        return int(getter(rule_id, default))
    except (TypeError, ValueError):
        return default


@rule(id="16004", description="Long flow with no restart points", category="Restart")
def long_flow_without_restart(commits: CommitsDict, config) -> RuleResult:
    """A @CenterTestCase method that runs >= N step `.execute()` calls (threshold 16004, default 4)
    while its class has no restart(...) call at all.

    A failure late in the flow then repeats every step on a rerun. Counting is textual on the
    method body (comments and strings removed); a class with any restart() call anywhere (a helper
    may hold the blocks) is skipped, as are classes that are not @CenterTest.
    """
    limit = _threshold(config, "16004", 4)
    result = RuleResult(rule_id="16004", description="Long flow with no restart points", category="Restart",
                        headers=list(_HEADERS))
    for f in _files(commits):
        if "CenterTest" not in f.main_class.annotations:
            continue
        if _ANY_RESTART.search(code_only(f.source)):
            continue
        for cls, ce, m in all_methods(f):
            if "CenterTestCase" not in m.annotations:
                continue
            n = len(re.findall(r"\.\s*execute\s*\(", code_only(m.body)))
            if n < limit:
                continue
            line = m.line or 1
            result.rows.append([cls, m.name, _line(f, line),
                                f"the test runs {n} steps with no restart point, so a failure in a late step "
                                "repeats the whole flow on every rerun; wrap the costly setup (account, policy) in "
                                "restart(...) blocks", location(f, line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} test(s) with {limit}+ steps and no restart point"
    return result
