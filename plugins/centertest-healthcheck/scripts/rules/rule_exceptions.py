"""
Exceptions rules (22001-22005): how test and step code fails, rethrows and logs.

22001 — catch (Exception) used as a branch
22002 — Rethrow that drops the cause
22003 — Generic RuntimeException for a test failure
22004 — Failure message copied from another class
22005 — Log message built with formatted() or +

Every rule reads method bodies from the parsed model. Bodies are scanned through mask_code(), which
keeps the text the same length (so an offset is still a line) but blanks comments and the contents
of string literals, so a pattern never matches inside a comment or a message.
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult, SourceCodeFile
from eir_rules import rule
from rule_helpers import (ProjectIndex, all_methods, balanced_end, body_line, latest_files, location, snippet,
                          string_literals)


# ---------------------------------------------------------------------------
# Shared text helpers (also used by rule_deadcode)
# ---------------------------------------------------------------------------

def mask_code(text: str) -> str:
    """Same-length copy of `text` with comments replaced by spaces and the contents of string/char
    literals (text blocks included) replaced by spaces; quotes and newlines are kept, so offsets and
    line numbers stay valid."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if text.startswith('"""', i):
            j = text.find('"""', i + 3)
            j = n if j < 0 else j
            for k in range(i + 3, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j + 3
            continue
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            for k in range(i + 1, min(j, n)):
                out[k] = " "
            i = j + 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def is_generated(f: SourceCodeFile) -> bool:
    """Generated code (a `generated` package) is not the project's to fix."""
    if "generated" in (f.package_name or "").split("."):
        return True
    return "/generated/" in (f.key or "").replace("\\", "/")


def project_files(commits: CommitsDict) -> list[SourceCodeFile]:
    return [f for f in latest_files(commits) if f.main_class is not None and not is_generated(f)]


def split_args(masked: str) -> list[str]:
    """Top-level comma-separated pieces of an argument list (masked text, no outer parens)."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(masked):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(masked[start:i])
            start = i + 1
    parts.append(masked[start:])
    return [p for p in parts if p.strip()] if any(p.strip() for p in parts) else []


def split_plus(masked: str) -> list[str]:
    """Top-level `+` operands of an expression (masked text)."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(masked):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "+" and depth == 0:
            if (i + 1 < len(masked) and masked[i + 1] in "+=") or (i > 0 and masked[i - 1] == "+"):
                continue
            parts.append(masked[start:i])
            start = i + 1
    parts.append(masked[start:])
    return parts


def body_hit(f: SourceCodeFile, m, body: str, offset: int, config) -> tuple[str, str]:
    """(trimmed code line, Location) for an offset in a method body."""
    idx = body.count("\n", 0, offset)
    lines = body.splitlines()
    text = lines[idx] if idx < len(lines) else ""
    return snippet(text), location(f, body_line(f, m, idx), config)


def _threshold(config, rule_id: str, default):
    getter = getattr(config, "get_threshold", None)
    if getter is None:
        return default
    try:
        return getter(rule_id, default)
    except Exception:
        return default


_CATCH_RE = re.compile(r"\bcatch\s*\(\s*(?:final\s+)?([\w.$|\s]+?)\s+([\w$]+)\s*\)\s*\{")


def catch_blocks(masked: str) -> list[tuple[list[str], str, int, int]]:
    """[(caught simple type names, variable, block '{' offset, offset past '}')] in a masked body."""
    out = []
    for m in _CATCH_RE.finditer(masked):
        types = [t.strip().split(".")[-1] for t in m.group(1).split("|") if t.strip()]
        brace = m.end() - 1
        out.append((types, m.group(2), brace, balanced_end(masked, brace)))
    return out


_THROW_NEW_RE = re.compile(r"\bthrow\s+new\s+([\w.$]+)\s*(?:<[^>()]*>)?\s*\(")


def throws_new(masked: str):
    """(match, simple type, args start, args end) for each `throw new X(...)`; args exclude parens."""
    for m in _THROW_NEW_RE.finditer(masked):
        paren = m.end() - 1
        end = balanced_end(masked, paren)
        yield m, m.group(1).split(".")[-1], paren + 1, end - 1


def _passes(var: str, args_masked: str) -> bool:
    """True when `var` itself (or var.getCause(), or a cast of it) is one of the arguments."""
    for a in split_args(args_masked):
        a = a.strip()
        if a == var or re.fullmatch(rf"\(\s*[\w.$<>]+\s*\)\s*{re.escape(var)}", a) \
                or re.fullmatch(rf"{re.escape(var)}\s*\.\s*getCause\s*\(\s*\)", a):
            return True
    return False


# ---------------------------------------------------------------------------
# 22001 — catch (Exception) used as a branch
# ---------------------------------------------------------------------------

_BROAD = {"Exception", "Throwable", "RuntimeException"}
_IGNORED_NAMES = {"ignored", "ignore", "expected"}


@rule(id="22001", description="catch (Exception) used as a branch", category="Exceptions")
def broad_catch_as_branch(commits: CommitsDict, config) -> RuleResult:
    """
    A `catch (Exception|Throwable|RuntimeException e)` whose block neither rethrows nor uses `e`:
    it logs a fixed message (a guess at the cause) or takes another path. Every failure, a
    NullPointerException or a missing widget included, then reads as the case the author expected.

    Guards: empty or comment-only blocks are 15005's (not reported twice); a block that throws
    anything, or mentions the variable at all (logs it, inspects it, rethrows it), is not reported;
    a variable named ignored/ignore/expected documents the intent and is skipped.
    """
    result = RuleResult(rule_id="22001", description="catch (Exception) used as a branch", category="Exceptions",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        for cls, _ce, m in all_methods(f):
            if not m.body or "catch" not in m.body:
                continue
            masked = mask_code(m.body)
            for types, var, brace, end in catch_blocks(masked):
                broad = [t for t in types if t in _BROAD]
                if not broad or var in _IGNORED_NAMES:
                    continue
                content = masked[brace + 1:end - 1]
                if not content.strip():
                    continue  # empty / comment-only: rule 15005
                if re.search(r"\bthrow\b", content) or re.search(rf"(?<![\w$.]){re.escape(var)}(?![\w$])", content):
                    continue
                code, loc = body_hit(f, m, m.body, brace, config)
                issue = (f"catch ({broad[0]} {var}) catches every failure, a NullPointerException or a missing widget "
                         f"too, and carries on without {var}, so a real defect is handled as the expected case; "
                         f"catch the specific exception, or at least log {var}")
                result.rows.append([cls, m.name, code, issue, loc])
    return result


# ---------------------------------------------------------------------------
# 22002 — Rethrow that drops the cause
# ---------------------------------------------------------------------------

_LOGS_VAR = r"\b(?:logger|log|LOGGER|LOG)\s*\.\s*\w+\s*\([^;]*(?<![\w$.]){var}(?![\w$])"


@rule(id="22002", description="Rethrow that drops the cause", category="Exceptions")
def rethrow_drops_cause(commits: CommitsDict, config) -> RuleResult:
    """
    Inside `catch (X e)`, a `throw new Y(...)` whose arguments do not pass `e` as the cause: the
    new exception's stack trace starts at the catch, and where it really failed is lost. A message
    built from e.getMessage() still counts as dropped (the trace is gone).

    Guards: `e`, a cast of it or e.getCause() as an argument, or `.initCause(e)` on the new
    exception, keeps the cause; a block that logs `e` (logger.x(..., e)) or prints its stack trace
    keeps the trace in the log and is not reported; a throw inside a nested catch is judged against
    that inner catch.
    """
    result = RuleResult(rule_id="22002", description="Rethrow that drops the cause", category="Exceptions",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        for cls, _ce, m in all_methods(f):
            if not m.body or "catch" not in m.body:
                continue
            masked = mask_code(m.body)
            blocks = catch_blocks(masked)
            for types, var, brace, end in blocks:
                content = masked[brace + 1:end - 1]
                v = re.escape(var)
                if re.search(_LOGS_VAR.format(var=v), content) or re.search(rf"\b{v}\s*\.\s*printStackTrace\s*\(", content):
                    continue
                inner = [(b, e) for _t, _v, b, e in blocks if brace < b < end]
                for tm, typ, a0, a1 in throws_new(content):
                    pos = brace + 1 + tm.start()
                    if any(b < pos < e for b, e in inner):
                        continue
                    args = content[a0:a1]
                    if _passes(var, args) or re.match(r"\s*\.\s*initCause\s*\(", content[a1 + 1:]):
                        continue
                    code, loc = body_hit(f, m, m.body, pos, config)
                    caught = types[0] if len(types) == 1 else " | ".join(types)
                    issue = (f"throw new {typ}(...) inside catch ({caught} {var}) does not pass {var} as the cause, so "
                             f"the stack trace of the real failure is lost; add {var} as the last argument")
                    result.rows.append([cls, m.name, code, issue, loc])
    return result


# ---------------------------------------------------------------------------
# 22003 — Generic RuntimeException for a test failure
# ---------------------------------------------------------------------------

_GENERIC = {"RuntimeException", "IllegalArgumentException", "IllegalStateException"}
_FAILURE_WORDS = re.compile(
    r"not found|could not|couldn't|cannot be found|can't be found|can not be found|\bfailed\b|did not|didn't|"
    r"was not|were not|is not in\b|not in status|not completed|\bexpected\b|unable to|can't be edited|"
    r"\bno \w+ (?:found|available)|not (?:displayed|visible|present|available|saved|created)", re.I)


def _project_exceptions(files: list[SourceCodeFile]) -> list[str]:
    names = set()
    for f in files:
        mc = f.main_class
        if mc and mc.kind == "class" and mc.class_name.endswith("Exception"):
            names.add(mc.class_name)
    return sorted(names)


@rule(id="22003", description="Generic RuntimeException for a test failure", category="Exceptions")
def generic_runtime_exception(commits: CommitsDict, config) -> RuleResult:
    """
    `throw new RuntimeException(...)` in test and step code, and RuntimeException /
    IllegalArgumentException / IllegalStateException anywhere whose message reads like a test
    failure (not found, could not, failed, expected, not in status ...). A plain exception does not
    say what kind of failure it is, so neither a report nor a catch can tell a failed check from a
    crash.

    Guards: a RuntimeException that wraps a caught exception (passes the catch variable) is the
    standard checked-to-unchecked wrap and is skipped; IllegalArgument/IllegalState with a message
    that does not read like a failure ("Unknown coverage tab: ") is argument validation and is
    skipped; outside tests and steps (utility code) only failure-worded messages count.
    The Issue names the project's own exception classes when it has some.
    """
    result = RuleResult(rule_id="22003", description="Generic RuntimeException for a test failure",
                        category="Exceptions", headers=["Class", "Method", "Line", "Issue", "Location"])
    files = project_files(commits)
    idx = ProjectIndex(latest_files(commits))
    typed = _project_exceptions(files)
    better = (f"a typed exception (this project has {', '.join(typed[:3])})" if typed
              else "a typed exception (a project exception class) or an AssertionError")
    for f in files:
        test_or_step_file = f.is_test_class() or idx.is_step(f.main_class)
        for cls, ce, m in all_methods(f):
            if not m.body or "throw" not in m.body:
                continue
            in_scope = test_or_step_file or idx.is_step(ce)
            masked = mask_code(m.body)
            blocks = catch_blocks(masked)
            for tm, typ, a0, a1 in throws_new(masked):
                if typ not in _GENERIC:
                    continue
                args = masked[a0:a1]
                if any(b < tm.start() < e and _passes(var, args) for _t, var, b, e in blocks):
                    continue
                message = " ".join(string_literals(m.body[a0:a1]))
                failure = bool(_FAILURE_WORDS.search(message))
                if typ == "RuntimeException":
                    if not (in_scope or failure):
                        continue
                elif not failure:
                    continue
                code, loc = body_hit(f, m, m.body, tm.start(), config)
                issue = (f"A plain {typ} does not say what kind of failure this is, so the report and any catch "
                         f"cannot tell a failed check from a crash; throw {better}")
                result.rows.append([cls, m.name, code, issue, loc])
    return result


# ---------------------------------------------------------------------------
# 22004 — Failure message copied from another class
# ---------------------------------------------------------------------------

_SUBJECTS = ["Submission", "Account", "Policy", "Claim", "Renewal", "Cancellation", "Reinstatement", "Rewrite",
             "Contact", "Quote", "Invoice", "Payment", "Exposure", "Activity", "Document", "Producer", "Vehicle",
             "Driver", "Coverage", "Contract", "Payee", "Check", "Matter", "Incident", "Building", "Location"]
_SUBJECT_RE = re.compile(r"\b(" + "|".join(_SUBJECTS) + r")s?\b")


def _class_words(name: str) -> set[str]:
    return set(re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])", name))


@rule(id="22004", description="Failure message copied from another class", category="Exceptions")
def copied_failure_message(commits: CommitsDict, config) -> RuleResult:
    """
    The same exception message text (its literal parts joined, at least ~15 characters) thrown in
    two or more classes, where the message names a subject (Submission, Account, Policy, Claim ...)
    that one of the classes does not work on: SearchForAccountPC failing with "Submission ... could
    not be found" because the text was copied from SearchForSubmissionPC.

    Guards: a class is reported only when its own name names a different subject and not the
    message's one, and another class with the same text does name the message's subject (so it is
    clear which one is the copy). Classes whose names name no subject are never reported.
    """
    result = RuleResult(rule_id="22004", description="Failure message copied from another class",
                        category="Exceptions", headers=["Class", "Method", "Line", "Issue", "Location"])
    min_len = int(_threshold(config, "22004", 15))
    by_message: dict[str, list] = defaultdict(list)
    for f in project_files(commits):
        for cls, _ce, m in all_methods(f):
            if not m.body or "throw" not in m.body:
                continue
            masked = mask_code(m.body)
            for tm, _typ, a0, a1 in throws_new(masked):
                parts = [p.strip() for p in string_literals(m.body[a0:a1]) if p.strip()]
                text = " … ".join(parts)
                if len(re.sub(r"[^A-Za-z]", "", text)) < min_len:
                    continue
                by_message[text].append((f, cls, m, tm.start()))
    for text in sorted(by_message):
        hits = by_message[text]
        top_classes = {h[0].main_class.class_name for h in hits}
        if len(top_classes) < 2:
            continue
        sm = _SUBJECT_RE.search(text)
        if not sm:
            continue
        subject = sm.group(1)
        owners = sorted({h[0].main_class.class_name for h in hits if subject in _class_words(h[0].main_class.class_name)})
        if not owners:
            continue
        for f, cls, m, off in hits:
            words = _class_words(f.main_class.class_name)
            if subject in words:
                continue
            own = sorted(w for w in words if w in _SUBJECTS)
            if not own:
                continue
            code, loc = body_hit(f, m, m.body, off, config)
            issue = (f'The message "{text}" names {subject}, but {f.main_class.class_name} works on {own[0]}: the same '
                     f"text is thrown in {', '.join(owners)}, so it was copied and the failure points at the wrong record")
            result.rows.append([cls, m.name, code, issue, loc])
    return result


# ---------------------------------------------------------------------------
# 22005 — Log message built with formatted() or +
# ---------------------------------------------------------------------------

_LOG_CALL_RE = re.compile(r"(?<![\w$])(?:logger|log|LOGGER|LOG)\s*\.\s*(info|debug|warn|error|trace)\s*\(")
_LITERAL_ONLY = re.compile(r'\s*(?:"[^"\n]*"|\'[^\'\n]*\')\s*')
_LEVEL_GUARD = re.compile(r"is(?:Debug|Trace|Info|Warn|Error)Enabled\s*\(|showDebug", re.I)


@rule(id="22005", description="Log message built with formatted() or +", category="Exceptions")
def log_message_built(commits: CommitsDict, config) -> RuleResult:
    """
    logger.info/debug/warn/error/trace whose message (first argument) is built with .formatted(),
    String.format or `+` concatenation of non-literals. The string is built even when the level is
    off, and each call logs a different text, so log search cannot group the messages. SLF4J
    placeholders (logger.info("Created {}", number)) are the good form; CenterTest logs through SLF4J
    (framework classes use LoggerFactory.getLogger).

    Guards: concatenation of literals only ("a" + "b") is fine; files that import java.util.logging
    (no placeholders) are skipped; a call guarded by isDebugEnabled()/showDebug on the same or the
    previous line is skipped.
    """
    result = RuleResult(rule_id="22005", description="Log message built with formatted() or +", category="Exceptions",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in project_files(commits):
        if any(i.startswith("java.util.logging") for i in f.imports):
            continue
        for cls, _ce, m in all_methods(f):
            if not m.body or "log" not in m.body.lower():
                continue
            masked = mask_code(m.body)
            lines = m.body.splitlines()
            for cm in _LOG_CALL_RE.finditer(masked):
                paren = cm.end() - 1
                end = balanced_end(masked, paren)
                args = split_args(masked[paren + 1:end - 1])
                if not args:
                    continue
                first = args[0]
                if re.search(r"\.\s*formatted\s*\(|\bString\s*\.\s*format\s*\(", first):
                    how = "formatted()/String.format"
                else:
                    operands = split_plus(first)
                    if len(operands) < 2 or all(_LITERAL_ONLY.fullmatch(o) for o in operands):
                        continue
                    how = "+ concatenation"
                idx = m.body.count("\n", 0, cm.start())
                near = " ".join(lines[max(0, idx - 1):idx + 1])
                if _LEVEL_GUARD.search(near):
                    continue
                code, loc = body_hit(f, m, m.body, cm.start(), config)
                issue = (f"The log message is built with {how}: the string is built even when {cm.group(1)} is off and "
                         f"every call logs a different text, so log search cannot group it; use placeholders, "
                         f'logger.{cm.group(1)}("... {{}}", value)')
                result.rows.append([cls, m.name, code, issue, loc])
    return result
