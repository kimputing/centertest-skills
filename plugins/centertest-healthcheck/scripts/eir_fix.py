"""
--fix 15018: turn checks that can never fail into the assertions they were meant to be.

A discarded `x.equals(y);` checks nothing. The fix follows the CenterTest MCP server's
review_test_code(fix=true), so both tools rewrite the same way:

- `....getCurrentEvent().equals(expected);` -- a getter that returns a widget (not getValue,
  getText, ...) -> `....getCurrentEvent().assertEquals(expected);` (widget assertion: it records
  the field, actual and expected value);
- anything else -> `Assertions.assertThat(x).isEqualTo(y);` (`isEqualToIgnoringCase` for
  equalsIgnoreCase) with com.ankrpt.centertest.assertion.Assertions, imported when missing, or
  written fully qualified when the file imports raw AssertJ's Assertions.

The change is printed as a unified diff; files are written only with --write.
"""

from __future__ import annotations

import difflib
import os
import re

VALUE_GETTERS = {"getValue", "getText", "getString", "getName", "toString", "getLabel", "trim", "toLowerCase",
                 "toUpperCase", "getTitle", "getDisplayValue"}
_WIDGET_EQUALS = re.compile(r"\.(get[A-Z]\w*)\(\)\.equals\(")
_STATEMENT = re.compile(r"^(\s*)(.+?)\.(equals|equalsIgnoreCase)\((.*)\);(\s*(?://.*)?)$")
FRAMEWORK = "com.ankrpt.centertest.assertion.Assertions"


def fix_line(line: str, qualified: bool) -> str | None:
    """The line rewritten as an assertion, or None when it is not a plain `x.equals(y);` statement."""
    m = _STATEMENT.match(line.rstrip("\r\n"))
    if not m:
        return None
    indent, receiver, method, arg, tail = m.groups()
    if arg.count("(") != arg.count(")") or receiver.count("(") != receiver.count(")"):
        return None
    # an assignment, a condition or a return uses the result: not a discarded check
    if re.search(r"(?<![=!<>])=(?!=)", receiver) or re.match(
            r"(?:if|while|for|return|assert|throw|else|case|do)\b", receiver.strip()):
        return None
    eol = line[len(line.rstrip("\r\n")):]
    widget = _WIDGET_EQUALS.search(line)
    if method == "equals" and widget and widget.group(1) not in VALUE_GETTERS:
        return f"{indent}{receiver}.assertEquals({arg});{tail}{eol}"
    factory = FRAMEWORK if qualified else "Assertions"
    check = "isEqualToIgnoringCase" if method == "equalsIgnoreCase" else "isEqualTo"
    return f"{indent}{factory}.assertThat({receiver}).{check}({arg});{tail}{eol}"


def _with_import(lines: list[str]) -> tuple[list[str], bool]:
    """(lines with the framework Assertions imported if needed, whether calls must be fully qualified)."""
    text = "".join(lines)
    if re.search(r"^import\s+" + re.escape(FRAMEWORK) + r"\s*;", text, re.M):
        return lines, False
    if re.search(r"^import\s+[\w.]+\.Assertions\s*;", text, re.M):
        return lines, True  # another Assertions is imported: do not shadow it
    last = max((i for i, l in enumerate(lines) if l.startswith("import ")), default=None)
    eol = "\r\n" if text.count("\r\n") else "\n"
    if last is None:
        pkg = next((i for i, l in enumerate(lines) if l.startswith("package ")), -1)
        return lines[:pkg + 1] + [eol, f"import {FRAMEWORK};{eol}"] + lines[pkg + 1:], False
    return lines[:last + 1] + [f"import {FRAMEWORK};{eol}"] + lines[last + 1:], False


def plan_fixes(repo_dir: str, results) -> dict[str, tuple[list[str], list[str]]]:
    """{relative path: (old lines, new lines)} for every 15018 finding that can be rewritten."""
    by_file: dict[str, set[int]] = {}
    for r in results:
        if r.rule_id != "15018" or "Location" not in r.headers:
            continue
        li = r.headers.index("Location")
        for row in r.rows:
            loc = str(row[li]) if li < len(row) else ""
            path, _, line = loc.rpartition(":")
            if path and line.isdigit():
                by_file.setdefault(path, set()).add(int(line))
    plans = {}
    for rel, numbers in sorted(by_file.items()):
        with open(os.path.join(repo_dir, rel), encoding="utf-8", newline="") as fh:
            old = fh.readlines()
        needs_factory = False
        new = list(old)
        for n in sorted(numbers):
            if 0 < n <= len(new):
                probe = fix_line(new[n - 1], qualified=False)
                if probe and "Assertions.assertThat(" in probe:
                    needs_factory = True
        qualified = False
        if needs_factory:
            new, qualified = _with_import(new)
        shift = len(new) - len(old)
        for n in sorted(numbers):
            i = n - 1 + shift
            if 0 <= i < len(new):
                fixed = fix_line(new[i], qualified)
                if fixed:
                    new[i] = fixed
        if new != old:
            plans[rel] = (old, new)
    return plans


def run_fix(repo_dir: str, results, write: bool) -> int:
    plans = plan_fixes(repo_dir, results)
    if not plans:
        print("\n  Nothing to fix: no discarded .equals() that can be rewritten.")
        return 0
    for rel, (old, new) in plans.items():
        print("".join(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}")))
        if write:
            with open(os.path.join(repo_dir, rel), "w", encoding="utf-8", newline="") as fh:
                fh.write("".join(new))
    print(f"  {'Fixed' if write else 'Would fix'} {len(plans)} file(s)."
          + ("" if write else " Re-run with --write to apply; compile and run the tests afterwards."))
    return 0
