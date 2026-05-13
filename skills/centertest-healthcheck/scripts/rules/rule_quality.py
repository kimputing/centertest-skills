"""
Rules 15001-15017: Common Java quality issues (beyond Eir).

15001 — Null pointer risk detection
15002 — Potential IndexOutOfBoundsException (.get(N) on lists)
15004 — String comparison issues (== instead of .equals())
15005 — Exception handling anti-patterns (empty catch blocks)
15006 — Unused variable detection
15016 — Logging best practices (System.out.println detection)
15017 — Unbounded busy-waits and recursion (no deadline / no iteration cap)
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_core import get_implemented_classes

# Pattern for chained method calls without null checks (4+ calls = higher risk)
_CHAIN_RE = re.compile(r"(\w+(?:\.\w+\([^)]*\)){4,})")

# Pattern for string == comparison
_STRING_EQ_RE = re.compile(r'(?:getString|getValue|getText|getName|toString)\s*\(\s*\)\s*==\s*"')
_STRING_EQ_RE2 = re.compile(r'"\s*==\s*\w+')

# Pattern for empty catch blocks
_EMPTY_CATCH_RE = re.compile(r"catch\s*\([^)]+\)\s*\{\s*\}", re.DOTALL)


@rule(id="15001", description="Potential null pointer risks", category="Quality")
def null_pointer_risks(commits: CommitsDict, config) -> RuleResult:
    """
    Find method call chains that risk NullPointerException.

    In CenterTest projects, most getter chains on page objects and widgets are
    generated and null-safe. This rule focuses on genuinely risky patterns:
    - JSON/Map access chains (e.g., body.get("key").getAsJsonObject().get(...))
    - External API response chains
    - Chains mixing data access with value comparison
    """
    result = RuleResult(
        rule_id="15001",
        description="Potential null pointer risks",
        category="Quality",
        headers=["Class", "Method", "Chain"],
    )

    # Genuinely risky patterns — JSON/Map/external API access
    # These return null from .get() and NPE on the next call
    risky_patterns = [
        ".getAsJsonObject()",   # Gson — NPE if parent .get() returned null
        ".getAsString()",       # Gson — NPE if parent .get() returned null
        ".getAsInt()",          # Gson — NPE if parent .get() returned null
    ]

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                for match in _CHAIN_RE.finditer(method.body):
                    chain = match.group(1)

                    # Only flag chains with genuinely risky JSON/Map patterns
                    if any(rp in chain for rp in risky_patterns):
                        result.rows.append([mc.class_name, method.name, chain[:150]])

    return result


# Pattern for .get(N) on lists — potential IndexOutOfBoundsException
# Matches: .get(0), .get(1), .get(2), etc. but NOT .get("string") or .get(variable)
_LIST_GET_RE = re.compile(r'\.get\(\s*(\d+)\s*\)')


@rule(id="15002", description="Potential IndexOutOfBoundsException", category="Quality")
def index_out_of_bounds_risks(commits: CommitsDict, config) -> RuleResult:
    """
    Find .get(N) calls on lists/collections using a hardcoded numeric index
    that are NOT guarded by a size check or isEmpty check.

    Patterns like getOptionList().get(1), getRows().get(0) risk
    IndexOutOfBoundsException if the list is smaller than expected.

    Skips calls where the method body contains .size() or .isEmpty() checks
    on the same collection variable, indicating the developer is aware of bounds.
    """
    result = RuleResult(
        rule_id="15002",
        description="Potential IndexOutOfBoundsException",
        category="Quality",
        headers=["Class", "Method", "Index", "Line"],
    )

    # Patterns that indicate a size guard exists in the method
    _GUARD_PATTERNS = [".size()", ".isEmpty()", "!isEmpty()", ".isPresent()"]

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue

                body = method.body

                for line in body.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    for m in _LIST_GET_RE.finditer(stripped):
                        index = int(m.group(1))

                        # Skip getFirstRow()-style patterns
                        context = stripped[:m.start()]
                        if "getFirstRow" in context:
                            continue

                        # Try to identify the collection variable/expression
                        # before .get(N) — e.g. "rows.get(0)" → "rows",
                        # "getOptionList().get(1)" → "getOptionList()"
                        prefix = stripped[:m.start()].rstrip(".")
                        # Extract the last token (variable or method call)
                        col_name = ""
                        for part in reversed(prefix.split(".")):
                            col_name = part.strip()
                            break

                        # Check if the method body contains a size/isEmpty
                        # guard on the same collection
                        guarded = False
                        if col_name:
                            for guard in _GUARD_PATTERNS:
                                if col_name + guard in body or col_name.rstrip(")") + guard in body:
                                    guarded = True
                                    break

                        if guarded:
                            continue

                        result.rows.append([
                            mc.class_name,
                            method.name,
                            index,
                            stripped[:150],
                        ])

    return result


@rule(id="15004", description="String comparison with == instead of .equals()", category="Quality")
def string_comparison_issues(commits: CommitsDict, config) -> RuleResult:
    """
    Find string comparisons using == instead of .equals().

    Detects patterns like: getValue() == "expected" or "expected" == variable
    """
    result = RuleResult(
        rule_id="15004",
        description="String comparison with == instead of .equals()",
        category="Quality",
        headers=["Class", "Method", "Line"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                for line in method.body.splitlines():
                    stripped = line.strip()
                    if _STRING_EQ_RE.search(stripped) or _STRING_EQ_RE2.search(stripped):
                        result.rows.append([
                            mc.class_name,
                            method.name,
                            stripped[:150],
                        ])

    return result


@rule(id="15005", description="Empty catch blocks", category="Quality")
def empty_catch_blocks(commits: CommitsDict, config) -> RuleResult:
    """
    Find empty catch blocks that silently swallow exceptions.

    Detects: catch (Exception e) { } with nothing inside.
    """
    result = RuleResult(
        rule_id="15005",
        description="Empty catch blocks",
        category="Quality",
        headers=["Class", "Method"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                if _EMPTY_CATCH_RE.search(method.body):
                    result.rows.append([mc.class_name, method.name])

    return result


# Pattern for variable declarations: var x = ...; or Type x = ...;
_VAR_DECL_RE = re.compile(r'(?:var|final\s+\w+|\w+(?:<[^>]+>)?)\s+(\w+)\s*=')


@rule(id="15006", description="Unused variable detection", category="Quality")
def unused_variables(commits: CommitsDict, config) -> RuleResult:
    """
    Find local variables that are declared but never referenced again.

    Detects: var x = someCall(); where x is not used in subsequent lines.
    Skips common patterns like loop variables and return values.
    """
    result = RuleResult(
        rule_id="15006",
        description="Unused variable detection",
        category="Quality",
        headers=["Class", "Method", "Variable", "Declaration"],
    )

    # Common variable names that are typically used implicitly (e.g. by framework)
    skip_names = {"context", "scenarioContext", "data", "producer", "e", "ex", "ignored", "_"}

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                lines = method.body.splitlines()
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    m = _VAR_DECL_RE.search(stripped)
                    if not m:
                        continue
                    var_name = m.group(1)
                    if var_name in skip_names or len(var_name) <= 1:
                        continue
                    # Check if the variable is referenced in any subsequent line
                    remaining = "\n".join(lines[i + 1:])
                    if var_name not in remaining:
                        result.rows.append([
                            mc.class_name,
                            method.name,
                            var_name,
                            stripped[:150],
                        ])

    return result


# Patterns for System.out/err usage
_SYSOUT_RE = re.compile(r'System\.(out|err)\.(print|println)\(')


# --- Rule 15017 -------------------------------------------------------------
# Unbounded busy-waits and direct recursion.
#
# Flags two patterns that have caused real CI hangs in CenterTest projects:
#   1. `while (...) { ... }` loops with no exit marker — no break/return/throw,
#      no deadline check, no counter mutation. A flaky page state will spin
#      forever on a thread with no useful stack trace.
#   2. Methods that call themselves with no guard counter / depth parameter —
#      a persistent error state turns into a StackOverflowError instead of a
#      meaningful test failure.
#
# Scope is deliberately narrow:
#   - Only `while` is checked (not `for`, not `do/while`, not foreach), since
#     counting and foreach loops are almost always bounded by construction.
#   - Recursion is only flagged when the body contains no `max|attempt|depth|
#     limit|count|tries|retries` token — these strongly suggest a bounded retry.
#
# Suppress via healthcheck/suppressions.json when the loop terminates via an
# external invariant (e.g. reader.readLine() returning null) the rule can't see.

_WHILE_RE = re.compile(r"\bwhile\s*\(([^{]*?)\)\s*\{")
_RECURSION_GUARDS = ("max", "attempt", "depth", "limit", "count", "tries", "retries")
_DEADLINE_MARKERS = (
    "System.currentTimeMillis",
    "Instant.now",
    "System.nanoTime",
    "LocalDateTime.now",
    "LocalTime.now",
)
_BODY_SAFE_MARKERS = (
    "break",
    "return",
    "throw",
    "++",
    "--",
    "+=",
    "-=",
) + _DEADLINE_MARKERS


def _find_matching_brace(text: str, open_idx: int) -> int:
    """Return the index of the `}` matching the `{` at open_idx, or -1."""
    depth = 0
    i = open_idx
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
        elif in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif in_char:
            if c == "\\":
                i += 1
            elif c == "'":
                in_char = False
        else:
            if c == "/" and nxt == "/":
                in_line_comment = True
                i += 1
            elif c == "/" and nxt == "*":
                in_block_comment = True
                i += 1
            elif c == '"':
                in_string = True
            elif c == "'":
                in_char = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


@rule(id="15017", description="Unbounded busy-waits and recursion", category="Quality")
def unbounded_loops_and_recursion(commits: CommitsDict, config) -> RuleResult:
    """
    Detect `while` loops with no terminator and direct recursion with no guard.

    A `while` loop is flagged when its body contains none of:
        break, return, throw,
        System.currentTimeMillis / Instant.now / System.nanoTime  (deadline check),
        ++ / -- / += / -=  (counter mutation).

    A method is flagged as unbounded recursion when its body calls itself
    AND contains none of the guard tokens (max/attempt/depth/limit/count/tries/retries).
    """
    result = RuleResult(
        rule_id="15017",
        description="Unbounded busy-waits and recursion",
        category="Quality",
        headers=["Class", "Method", "Kind", "Snippet"],
    )

    for _, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            # Count method-name occurrences once per class; overloads make
            # self-call detection ambiguous (a `foo(x)` call may resolve to a
            # different overload, not recursion), so skip recursion checks for
            # overloaded names.
            name_counts = {}
            for mm in mc.methods:
                name_counts[mm.name] = name_counts.get(mm.name, 0) + 1

            for method in mc.methods:
                if "abstract" in method.modifiers:
                    continue
                body = method.body
                if not body:
                    continue

                # --- 1. Unbounded while loops -----------------------------
                for m in _WHILE_RE.finditer(body):
                    # Skip do { ... } while (...);  — match heuristically by
                    # checking the preceding non-whitespace char is `}`.
                    pre = body[:m.start()].rstrip()
                    if pre.endswith("}"):
                        continue
                    open_brace = body.find("{", m.end() - 1)
                    if open_brace < 0:
                        continue
                    close_brace = _find_matching_brace(body, open_brace)
                    if close_brace < 0:
                        continue
                    cond = m.group(1)
                    loop_body = body[open_brace + 1:close_brace]
                    # Deadline expressions in the condition count as bounded
                    # (e.g. `while (rows.isEmpty() && System.currentTimeMillis() < deadline)`).
                    if any(marker in cond for marker in _DEADLINE_MARKERS):
                        continue
                    if any(marker in loop_body for marker in _BODY_SAFE_MARKERS):
                        continue
                    # First non-empty line of the loop body for context.
                    first_line = next(
                        (ln.strip() for ln in loop_body.splitlines() if ln.strip()),
                        "",
                    )
                    snippet = f"while ({cond.strip()}) {{ {first_line[:80]} }}"
                    result.rows.append([
                        mc.class_name,
                        method.name,
                        "while-busy-wait",
                        snippet[:180],
                    ])

                # --- 2. Unbounded direct recursion ------------------------
                # Skip overloaded methods — a `foo(x)` call may resolve to a
                # different overload, not recursion. We can't disambiguate
                # without parameter info, so we err on the side of silence.
                if name_counts.get(method.name, 0) > 1:
                    continue
                # Match `methodName(` only when NOT preceded by `.` or another
                # identifier character. This excludes `super.foo()`,
                # `obj.foo()`, `this.foo()`, and `getXxx().foo()` — none of
                # which are direct self-recursion.
                self_call = re.compile(
                    r"(?<![\w.])" + re.escape(method.name) + r"\s*\("
                )
                # Find self-call lines, ignoring the method's own declaration
                # which may appear as the first matching line.
                call_lines = [
                    ln.strip()
                    for ln in body.splitlines()
                    if self_call.search(ln) and not ln.lstrip().startswith(("public ", "private ", "protected ", "static "))
                ]
                if not call_lines:
                    continue
                lowered = body.lower()
                if any(g in lowered for g in _RECURSION_GUARDS):
                    continue
                result.rows.append([
                    mc.class_name,
                    method.name,
                    "unbounded-recursion",
                    call_lines[0][:180],
                ])

    return result


@rule(id="15016", description="System.out.println usage instead of logger", category="Quality")
def logging_best_practices(commits: CommitsDict, config) -> RuleResult:
    """
    Find System.out.println and System.err.println calls.

    CenterTest projects should use the framework's logging mechanism
    instead of writing directly to stdout/stderr.
    """
    result = RuleResult(
        rule_id="15016",
        description="System.out.println usage instead of logger",
        category="Quality",
        headers=["Class", "Method", "Line"],
    )

    for commit_info, files in sorted(commits.items()):
        for f in get_implemented_classes(files):
            mc = f.main_class
            if mc is None:
                continue
            for method in mc.methods:
                if not method.body:
                    continue
                for line in method.body.splitlines():
                    stripped = line.strip()
                    if _SYSOUT_RE.search(stripped):
                        result.rows.append([
                            mc.class_name,
                            method.name,
                            stripped[:150],
                        ])

    return result
