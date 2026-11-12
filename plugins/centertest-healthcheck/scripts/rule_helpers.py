"""
Shared helpers for the rules added in issue #47 (rules/rule_restart.py, rule_architecture.py, ...).

Rules read everything from the parsed model -- never the file path, which may not exist on disk in
git and --review modes:
    SourceCodeFile.source            the file's text
    ClassEntry.line / Method.line    1-based declaration lines
    *.annotation_args                {"CenterTestCase": {"testCaseId": "X"}} (literal values only)
    Method.parameters / return_type / is_constructor
    Field.line / initializer         initializer = source text after "=" (first declarator)
    SourceCodeFile.other_types       top-level and nested interfaces/enums (facades, RestartPoints)

A finding row should end with a "Location" column ("path:line", relative to the project) built with
location(); eir_locate then leaves the row alone.
"""

from __future__ import annotations

import os
import re
from typing import Iterator

from eir_models import ClassEntry, CommitsDict, Method, SourceCodeFile


# ---------------------------------------------------------------------------
# Iteration
# ---------------------------------------------------------------------------

def latest_files(commits: CommitsDict) -> list[SourceCodeFile]:
    """Files of the newest commit (snapshot rules get one commit; this also works for several)."""
    if not commits:
        return []
    return commits[max(commits.keys())]


def scanned_classes(f: SourceCodeFile) -> Iterator[tuple[str, ClassEntry]]:
    """(display name, ClassEntry) for the main class and its inner classes ("Outer.Inner")."""
    mc = f.main_class
    if mc is None:
        return
    yield mc.class_name, mc
    for inner in f.inner_classes:
        yield f"{mc.class_name}.{inner.class_name}", inner


def all_methods(f: SourceCodeFile) -> Iterator[tuple[str, ClassEntry, Method]]:
    """(display class name, class, method) for every method with a body, inner classes included."""
    for name, ce in scanned_classes(f):
        for m in ce.methods:
            yield name, ce, m


def test_methods(f: SourceCodeFile) -> list[Method]:
    """@CenterTestCase methods of a test class (main and inner classes)."""
    return [m for _, _, m in all_methods(f) if "CenterTestCase" in m.annotations]


def is_test_file(f: SourceCodeFile) -> bool:
    return f.is_test_class()


# ---------------------------------------------------------------------------
# Project index: classes by simple name, ancestry, steps, facades
# ---------------------------------------------------------------------------

class ProjectIndex:
    """Classes by simple name, so rules can walk extends chains across files."""

    def __init__(self, files: list[SourceCodeFile]):
        self.files = files
        self.by_name: dict[str, tuple[SourceCodeFile, ClassEntry]] = {}
        for f in files:
            for _, ce in scanned_classes(f):
                self.by_name.setdefault(ce.class_name, (f, ce))
            for ce in f.other_types:
                self.by_name.setdefault(ce.key.rsplit(".", 1)[-1], (f, ce))

    def ancestors(self, ce: ClassEntry) -> list[ClassEntry]:
        """Project superclasses, nearest first (stops at classes outside the project)."""
        out, seen, cur = [], {ce.class_name}, ce
        while cur.extensions:
            parent = cur.extensions[0].split(".")[-1]
            hit = self.by_name.get(parent)
            if hit is None or parent in seen:
                break
            seen.add(parent)
            cur = hit[1]
            out.append(cur)
        return out

    def superclass_names(self, ce: ClassEntry) -> list[str]:
        """Every extends name up the chain, including the first one outside the project."""
        names, cur, seen = [], ce, set()
        while cur is not None and cur.extensions:
            parent = cur.extensions[0].split(".")[-1]
            if parent in seen:
                break
            seen.add(parent)
            names.append(parent)
            hit = self.by_name.get(parent)
            cur = hit[1] if hit else None
        return names

    def is_step(self, ce: ClassEntry) -> bool:
        """A reusable CenterTest step: extends (directly or through project classes) a framework
        Base*/Scenario class, or a project class that does, or declares execute()."""
        if "CenterTest" in ce.annotations or "ScenarioContainer" in ce.annotations:
            return False
        for name in self.superclass_names(ce):
            if name.startswith("Base") or "Scenario" in name:
                return True
        return any(m.name == "execute" and not m.parameters for m in ce.methods)

    def facades(self) -> dict[str, ClassEntry]:
        """{name: interface} for facade interfaces (PC, BC, CC, AB ...): interfaces whose static
        methods return new steps."""
        out = {}
        for f in self.files:
            for ce in f.other_types:
                if ce.kind == "interface" and sum(1 for m in ce.methods if "static" in m.modifiers) >= 2:
                    out[ce.key.rsplit(".", 1)[-1]] = ce
        return out


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_STRING_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')
_CHAR_RE = re.compile(r"'(?:[^'\\\n]|\\.)'")


def blank_strings(text: str) -> str:
    """Replace the contents of string and char literals with nothing ("" and ''), keeping quotes,
    so a pattern never matches inside a literal."""
    return _CHAR_RE.sub("''", _STRING_RE.sub('""', text))


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments (string literals are respected)."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            m = _STRING_RE.match(text, i)
            if m:
                out.append(m.group(0))
                i = m.end()
                continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            nl = text.count("\n", i, n if j < 0 else j)
            out.append("\n" * nl)  # keep line numbers
            i = n if j < 0 else j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def code_only(text: str) -> str:
    """Comments removed and literals blanked: what the compiler sees, for structural patterns."""
    return blank_strings(strip_comments(text))


def string_literals(text: str) -> list[str]:
    """Unquoted contents of the string literals in text (escapes kept as written)."""
    return [m.group(0)[1:-1] for m in _STRING_RE.finditer(strip_comments(text))]


def comment_blocks(source: str) -> list[tuple[int, list[str]]]:
    """[(first line, [comment text lines])] for runs of consecutive // lines and for /* */ blocks.
    Javadoc (/**) blocks are included; callers that want code-in-comments should skip them."""
    blocks: list[tuple[int, list[str]]] = []
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("//"):
            start, run = i, []
            while i < len(lines) and lines[i].strip().startswith("//"):
                run.append(lines[i].strip()[2:])
                i += 1
            blocks.append((start + 1, run))
            continue
        if s.startswith("/*"):
            start, run = i, []
            while i < len(lines):
                run.append(lines[i].strip())
                if "*/" in lines[i]:
                    i += 1
                    break
                i += 1
            blocks.append((start + 1, run))
            continue
        i += 1
    return blocks


# ---------------------------------------------------------------------------
# Lines and locations
# ---------------------------------------------------------------------------

def body_start_line(f: SourceCodeFile, method: Method) -> int:
    """1-based file line of the method body's opening brace (the body's first line)."""
    if not method.line:
        return 0
    lines = f.source.splitlines()
    for i in range(method.line - 1, min(len(lines), method.line + 40)):
        if "{" in strip_comments(blank_strings(lines[i])):
            return i + 1
    return method.line


def body_line(f: SourceCodeFile, method: Method, index: int) -> int:
    """File line of body line `index` (0-based, as in method.body.splitlines())."""
    start = body_start_line(f, method)
    return start + index if start else 0


def line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def rel_path(f: SourceCodeFile, config) -> str:
    repo = getattr(config, "repository_dir", "") or ""
    path = f.key
    if repo and os.path.isabs(path):
        try:
            path = os.path.relpath(path, repo)
        except ValueError:
            pass
    return path.replace("\\", "/")


def location(f: SourceCodeFile, line: int, config) -> str:
    """'relative/path.java:line' for a Location column."""
    return f"{rel_path(f, config)}:{line or 1}"


def file_location(path: str, line: int, config) -> str:
    """Location for a non-Java file (suite JSON, workbook): path relative to the project."""
    repo = getattr(config, "repository_dir", "") or ""
    rel = os.path.relpath(path, repo) if repo and os.path.isabs(path) else path
    return f"{rel.replace(os.sep, '/')}:{line or 1}"


def snippet(text: str, limit: int = 140) -> str:
    """One trimmed line of code for a finding (first line, cut at `limit`)."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first if len(first) <= limit else first[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Statements (flat, top level of a body) -- for order-sensitive rules
# ---------------------------------------------------------------------------

def balanced_end(text: str, open_index: int) -> int:
    """Index just past the brace/paren/bracket that closes the one at open_index (text should be
    code_only() so literals and comments cannot unbalance it); len(text) when unclosed."""
    pairs = {"{": "}", "(": ")", "[": "]"}
    opener = text[open_index]
    closer = pairs[opener]
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def blocks_after(code: str, pattern: re.Pattern) -> Iterator[tuple[re.Match, str, int, int]]:
    """For each match of `pattern` that is followed by a {...} block (e.g. `if (restart(X))`),
    yield (match, block text without braces, block start offset, block end offset)."""
    for m in pattern.finditer(code):
        brace = code.find("{", m.end())
        if brace < 0 or code[m.end():brace].strip(") \n\t"):
            continue
        end = balanced_end(code, brace)
        yield m, code[brace + 1:end - 1], brace, end


# ---------------------------------------------------------------------------
# Generated project and workbooks
# ---------------------------------------------------------------------------

def generated_resources(config) -> str | None:
    """The generated project's cssids folder -- `<generated>/src/main/resources/cssids` when it exists
    (Guidewire 10), else `<generated>/src/main/resources` (Guidewire 9) -- or None; found as the screens
    panel finds it (--cssids, then <project>-generated, then the cssid-finder config)."""
    try:
        import eir_screens
        return eir_screens.find_cssids_dir(getattr(config, "repository_dir", ""), getattr(config, "cssids", None))
    except Exception:
        return None


def testdata_dir(config) -> str:
    return os.path.join(getattr(config, "repository_dir", "") or "", "testdata")
