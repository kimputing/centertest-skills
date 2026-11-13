#!/usr/bin/env python3
"""
Java source file parser for eir-analyzer.

Primary: javalang library for AST parsing.
Body extraction: Source-position slicing with brace balancing.
Java 14+: when javalang fails, it parses a same-lines copy with bodies emptied and records
lowered to classes (_lower_for_javalang); bodies are still sliced from the real source.
Fallback: Regex-based extraction for files javalang cannot parse even then.

Matches Eir's CodeParser behavior:
- Scans {repo}/src/main/java/ recursively
- Package name derived from directory path (NOT from package statement)
- Only ClassOrInterfaceDeclaration types (skips enums, annotations, records)
- Inner classes: direct children only, one level deep

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/eir-analyzer/scripts/eir_parser.py
"""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

try:
    import javalang
except ImportError:
    javalang = None

from eir_models import SourceCodeFile, ClassEntry, Method, Field


# ---------------------------------------------------------------------------
# Package from directory path (matching Eir's RuleCore.getPackageFromPath)
# ---------------------------------------------------------------------------

def get_package_from_path(file_path: str, repo_dir: str, source_root: str = "src/main/java") -> str:
    """
    Derive Java package name from the file's directory path.

    Eir uses directory structure, NOT the package statement in source.
    Example: /repo/src/main/java/com/example/tests/MyTest.java → com.example.tests
    """
    base = os.path.join(repo_dir, source_root) + os.sep
    parent = os.path.dirname(file_path)
    if parent.startswith(base):
        relative = parent[len(base):]
    else:
        relative = parent.replace(base.rstrip(os.sep), "").lstrip(os.sep)
    return relative.replace(os.sep, ".")


# ---------------------------------------------------------------------------
# Line metrics
# ---------------------------------------------------------------------------

def _calculate_line_metrics(sf: SourceCodeFile, content: str, compat_comment_lines: bool = True):
    """
    Calculate line metrics: total, blank, comment, LOC.

    compat_comment_lines=True replicates Eir's bug where a top-level block comment
    overwrites the // count. Set False for corrected behavior.
    """
    raw_lines = content.splitlines()
    sf.lines = len(raw_lines)
    sf.blank_lines = sum(1 for line in raw_lines if line.strip() == "")

    # Count single-line comments (//)
    single_line_comments = sum(1 for line in raw_lines if line.strip().startswith("//"))

    # Count block comment lines (/* ... */)
    block_comment_lines = 0
    in_block = False
    top_level_block = None  # first block comment if it starts at line 1-ish

    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("/*"):
                in_block = True
                block_start = i
                if i <= 2 and top_level_block is None:  # near top of file
                    top_level_block = i
                block_comment_lines += 1
                if stripped.endswith("*/") and len(stripped) > 2:
                    in_block = False
            # Don't double count // lines already counted above
        else:
            block_comment_lines += 1
            if "*/" in stripped:
                in_block = False

    if compat_comment_lines and top_level_block is not None:
        # Eir bug: overwrites // count with blankLines + block comment lines
        # when CompilationUnit has a block comment
        sf.comment_lines = sf.blank_lines + block_comment_lines
    else:
        # Corrected: sum of // lines + block comment lines
        sf.comment_lines = single_line_comments + block_comment_lines

    sf.lines_of_code = sf.lines - sf.blank_lines - sf.comment_lines
    if sf.lines_of_code < 0:
        sf.lines_of_code = 0


# ---------------------------------------------------------------------------
# Method body extraction via source-position slicing
# ---------------------------------------------------------------------------

def _extract_method_body_from_source(source: str, start_line: int) -> str:
    """
    Extract method body from source starting at the given line (1-indexed).

    Uses brace balancing, handling string literals and comments
    to avoid false brace matches. Returns trimmed-per-line body matching Eir.
    """
    lines = source.splitlines()
    if start_line < 1 or start_line > len(lines):
        return ""

    tail = "\n".join(lines[start_line - 1:])

    depth = 0
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    escape_next = False
    buf = []
    started = False
    prev_ch = ""

    for ch in tail:
        if ch == "\n":
            in_line_comment = False

        if escape_next:
            escape_next = False
            if started:
                buf.append(ch)
            prev_ch = ch
            continue

        if (in_string or in_char) and ch == "\\":
            escape_next = True
            if started:
                buf.append(ch)
            prev_ch = ch
            continue

        # String literal handling
        if ch == '"' and not in_char and not in_line_comment and not in_block_comment:
            in_string = not in_string
        elif ch == "'" and not in_string and not in_line_comment and not in_block_comment:
            in_char = not in_char

        # Comment handling
        if not in_string and not in_char:
            if not in_block_comment and not in_line_comment:
                if ch == "/" and prev_ch == "/":
                    in_line_comment = True
                elif ch == "*" and prev_ch == "/":
                    in_block_comment = True
            elif in_block_comment:
                if ch == "/" and prev_ch == "*":
                    in_block_comment = False

        # Brace counting (only outside strings, chars, and comments)
        if not in_string and not in_char and not in_line_comment and not in_block_comment:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1

        if started:
            buf.append(ch)

        if started and depth == 0:
            break

        prev_ch = ch

    raw = "".join(buf)
    # Match Java: each line .trim()-ped, joined with newline
    return "\n".join(line.strip() for line in raw.splitlines())


# ---------------------------------------------------------------------------
# Annotation extraction helper
# ---------------------------------------------------------------------------

_ANNOTATION_RE = re.compile(r"@(\w+)")


def _extract_annotations(node) -> list[str]:
    """Extract simple annotation names from a javalang node."""
    if not hasattr(node, "annotations") or node.annotations is None:
        return []
    return [a.name for a in node.annotations]


def _literal(value):
    """Source-ish text of an annotation element value: string literals unquoted, references as
    Qualifier.member, arrays as lists; anything else (expressions) as None."""
    if value is None:
        return None
    if isinstance(value, javalang.tree.Literal):
        v = value.value
        if len(v) >= 2 and v[0] == v[-1] == '"':
            return bytes(v[1:-1], "utf-8").decode("unicode_escape", errors="replace") if "\\" in v else v[1:-1]
        return v
    if isinstance(value, javalang.tree.MemberReference):
        return f"{value.qualifier}.{value.member}" if value.qualifier else value.member
    if isinstance(value, javalang.tree.ElementArrayValue):
        return [_literal(v) for v in (value.values or [])]
    return None


def _extract_annotation_args(node) -> dict:
    """{annotation name: {element: value}} -- a single unnamed element is stored as "value"."""
    out = {}
    for a in (getattr(node, "annotations", None) or []):
        el = a.element
        if el is None:
            out[a.name] = {}
        elif isinstance(el, list):
            out[a.name] = {pair.name: _literal(pair.value) for pair in el
                           if isinstance(pair, javalang.tree.ElementValuePair)}
        else:
            out[a.name] = {"value": _literal(el)}
    return out


def _type_name(t) -> str:
    if t is None:
        return ""
    name = getattr(t, "name", "") or ""
    sub = getattr(t, "sub_type", None)
    while sub is not None:  # Map.Entry -> "Map.Entry"
        name += "." + sub.name
        sub = getattr(sub, "sub_type", None)
    return name + "[]" * len(getattr(t, "dimensions", None) or [])


def _initializer_text(source_lines: list[str], line: int) -> str:
    """Text after the first '=' of a field declaration starting at `line`, up to its ';'."""
    if line < 1:
        return ""
    chunk = []
    for text in source_lines[line - 1:line + 30]:
        chunk.append(text.strip())
        if text.rstrip().endswith(";"):
            break
    joined = " ".join(chunk)
    m = re.search(r"=\s*(.*);\s*(?://.*)?$", joined)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# javalang-based parsing
# ---------------------------------------------------------------------------

def _parse_with_javalang(content: str, sf: SourceCodeFile, repo_dir: str, source_root: str,
                         parse_text: str = None, records: set = frozenset()):
    """Parse a Java file using javalang and populate the SourceCodeFile.

    parse_text: a same-lines copy to hand javalang instead of content (_lower_for_javalang);
    bodies, initializers and lines are still read from content. records: class names in
    parse_text that were records -- they go to other_types with kind "record".
    """
    tree = javalang.parse.parse(parse_text if parse_text is not None else content)

    def is_record(decl):
        return isinstance(decl, javalang.tree.ClassDeclaration) and decl.name in records

    def other_type(decl, key):
        ce = _build_class_entry(decl, key, content)
        if is_record(decl):
            ce.kind = "record"
        sf.other_types.append(ce)

    # Imports — strip wildcard marker
    for imp in tree.imports:
        path = imp.path
        # javalang doesn't include .* for wildcard imports
        sf.imports.append(path)

    # Find class declarations (skip enums, annotations, interfaces for main class)
    class_decls = []
    for type_decl in (tree.types or []):
        if isinstance(type_decl, javalang.tree.ClassDeclaration) and not is_record(type_decl):
            class_decls.append(type_decl)
        elif isinstance(type_decl, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration,
                                    javalang.tree.EnumDeclaration)):
            other_type(type_decl, sf.package_name + "." + type_decl.name if sf.package_name else type_decl.name)

    if not class_decls:
        return

    # First class declaration is the main class
    main_decl = class_decls[0]
    parent_key = sf.package_name + "." + main_decl.name if sf.package_name else main_decl.name
    sf.main_class = _build_class_entry(main_decl, parent_key, content)

    # Inner classes: direct ClassDeclaration children of main class. Nested enums and interfaces
    # (a test's private enum RestartPoints) go to other_types, so rule 2002 does not compare them.
    for member in (main_decl.body or []):
        if isinstance(member, javalang.tree.ClassDeclaration) and not is_record(member):
            inner_key = parent_key + "." + member.name
            inner = _build_class_entry(member, inner_key, content)
            sf.inner_classes.append(inner)
        elif isinstance(member, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration,
                                 javalang.tree.EnumDeclaration)):
            other_type(member, parent_key + "." + member.name)


def _build_class_entry(decl, key: str, source: str) -> ClassEntry:
    """Build a ClassEntry from a javalang ClassDeclaration."""
    ce = ClassEntry(
        class_name=decl.name,
        key=key,
    )

    # Annotations
    ce.annotations = _extract_annotations(decl)
    ce.annotation_args = _extract_annotation_args(decl)
    ce.line = decl.position.line if getattr(decl, "position", None) else 0
    if isinstance(decl, javalang.tree.InterfaceDeclaration):
        ce.kind = "interface"
    elif isinstance(decl, javalang.tree.EnumDeclaration):
        ce.kind = "enum"
    source_lines = source.splitlines()

    # Extensions (simple names)
    if getattr(decl, "extends", None):
        if isinstance(decl.extends, list):
            ce.extensions = [ext.name for ext in decl.extends]
        else:
            ce.extensions = [decl.extends.name]

    # Interfaces (simple names)
    if getattr(decl, "implements", None):
        ce.interfaces = [iface.name for iface in decl.implements]

    body = decl.body or []
    if isinstance(decl, javalang.tree.EnumDeclaration):
        # Enum constants become fields of the enum's own type (RestartPoints.ACCOUNT ...)
        for const in (body.constants or []):
            line = const.position.line if getattr(const, "position", None) else 0
            if not line:  # javalang leaves some constants without a position ({ACCOUNT} on one line)
                start = max(ce.line - 1, 0)
                line = next((i + 1 for i in range(start, len(source_lines))
                             if re.search(r"\b" + re.escape(const.name) + r"\b", source_lines[i])), 0)
            ce.fields.append(Field(name=const.name, type=decl.name, modifiers=["public", "static", "final"], line=line))
        body = body.declarations or []

    # Methods
    method_count = 0
    for member in body:
        if isinstance(member, javalang.tree.MethodDeclaration):
            method_count += 1
            m = Method(name=member.name)
            m.annotations = _extract_annotations(member)
            m.annotation_args = _extract_annotation_args(member)
            m.modifiers = sorted(member.modifiers) if member.modifiers else []
            m.parameters = [(_type_name(p.type), p.name) for p in (member.parameters or [])]
            m.return_type = _type_name(member.return_type)
            # Extract body via source-position slicing (abstract/interface methods have none)
            if member.position:
                m.line = member.position.line
                if member.body is not None:
                    m.body = _extract_method_body_from_source(source, member.position.line)
            ce.methods.append(m)
        elif isinstance(member, javalang.tree.ConstructorDeclaration):
            method_count += 1
            m = Method(name=member.name, is_constructor=True)
            m.annotations = _extract_annotations(member)
            m.annotation_args = _extract_annotation_args(member)
            m.modifiers = sorted(member.modifiers) if member.modifiers else []
            m.parameters = [(_type_name(p.type), p.name) for p in (member.parameters or [])]
            if member.position:
                m.line = member.position.line
                m.body = _extract_method_body_from_source(source, member.position.line)
            ce.methods.append(m)

    ce.method_count = method_count

    # Fields
    for member in body:
        if isinstance(member, (javalang.tree.FieldDeclaration, javalang.tree.ConstantDeclaration)):
            # Only first variable from multi-variable declarations (matching Eir)
            if member.declarators:
                var = member.declarators[0]
                f = Field(
                    name=var.name,
                    type=member.type.name if member.type else "",
                )
                f.annotations = _extract_annotations(member)
                f.modifiers = sorted(member.modifiers) if member.modifiers else []
                if getattr(member, "position", None):
                    f.line = member.position.line
                    f.initializer = _initializer_text(source_lines, f.line) if var.initializer is not None else ""
                ce.fields.append(f)

    return ce


# ---------------------------------------------------------------------------
# Regex fallback parsing
# ---------------------------------------------------------------------------

_PKG_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)(?:\.\*)?\s*;", re.MULTILINE)
_CLASS_RE = re.compile(
    r"(?:@\w+(?:\s*\([^)]*\))?\s+)*"
    r"(?:(?:public|private|protected|abstract|final|static)\s+)*"
    r"class\s+(\w+)"
    r"(?:\s*<[^{]*>)?"
    r"(?:\s+extends\s+([\w.]+))?"
    r"(?:\s+implements\s+([\w.,\s]+))?"
    r"\s*\{"
)


def _parse_with_regex(content: str, sf: SourceCodeFile):
    """Regex fallback for files javalang cannot parse. Extracts minimal structure."""
    # Imports
    for m in _IMPORT_RE.finditer(content):
        sf.imports.append(m.group(1))

    # Find first class
    cm = _CLASS_RE.search(content)
    if not cm:
        return

    class_name = cm.group(1)
    extends = [cm.group(2)] if cm.group(2) else []
    implements = [i.strip() for i in cm.group(3).split(",")] if cm.group(3) else []

    key = sf.package_name + "." + class_name if sf.package_name else class_name

    # Annotations are part of the match (the pattern starts at the first one)
    head = cm.group(0)
    annotations = _ANNOTATION_RE.findall(head[:head.find("class ")])

    sf.main_class = ClassEntry(
        class_name=class_name,
        key=key,
        extensions=extends,
        interfaces=implements,
        annotations=annotations,
        line=content.count("\n", 0, cm.start()) + 1,
    )
    # Method bodies, so the body rules still read files javalang cannot parse (Java 14+ syntax).
    # Every method of the file goes to the main class: inner classes are not separated here.
    sf.main_class.methods = _regex_methods(content)
    sf.main_class.method_count = len(sf.main_class.methods)


_METHOD_DECL_RE = re.compile(
    r"^[ \t]*((?:@\w+(?:\s*\([^)]*\))?\s+)*)"
    r"((?:(?:public|protected|private|static|final|abstract|synchronized|default|native)\s+)*)"
    r"(?:<[^>{};]+>\s+)?"
    r"(?:([\w.]+(?:<[^{};=]*?>)?(?:\[\])*)\s+)?"
    r"(\w+)\s*\(([^;{}]*)\)\s*(?:throws\s+[\w.,\s]+)?\{",
    re.MULTILINE)
_NOT_A_METHOD = {"if", "for", "while", "switch", "catch", "synchronized", "return", "new", "else", "throw",
                 "try", "do", "case", "yield"}


def _depths(content: str) -> list[int]:
    """Brace depth at each offset, ignoring braces in strings, chars and comments."""
    depth, out, i, n = 0, [0] * (len(content) + 1), 0, len(content)
    while i < n:
        out[i] = depth
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = content.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = depth
            i = j
            continue
        if ch == "/" and nxt == "*":
            j = content.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                out[k] = depth
            i = j
            continue
        if ch in "\"'":
            if content.startswith('"""', i):
                j = content.find('"""', i + 3)
                j = n if j < 0 else j + 3
            else:
                j = i + 1
                while j < n and content[j] != ch and content[j] != "\n":
                    j += 2 if content[j] == "\\" else 1
                j += 1
            for k in range(i, min(j, n)):
                out[k] = depth
            i = j
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    out[n] = depth
    return out


def _regex_methods(content: str) -> list[Method]:
    """Methods declared at class-body depth (1: the top class, 2: its inner classes)."""
    depths = _depths(content)
    methods = []
    for m in _METHOD_DECL_RE.finditer(content):
        annots, mods, rtype, name, params = m.groups()
        start = m.start(4)
        if name in _NOT_A_METHOD or (rtype or "") in _NOT_A_METHOD or depths[start] not in (1, 2):
            continue
        line = content.count("\n", 0, start) + 1
        method = Method(name=name, modifiers=sorted(mods.split()), annotations=_ANNOTATION_RE.findall(annots or ""),
                        line=line, return_type="" if rtype in (None, "void") else rtype,
                        is_constructor=rtype is None)
        method.parameters = [tuple(p.strip().rsplit(None, 1)) for p in re.split(r",(?![^<]*>)", params)
                             if len(p.split()) >= 2]
        method.body = _extract_method_body_from_source(content, line)
        methods.append(method)
    return methods


# ---------------------------------------------------------------------------
# Java 14+ lowering: a copy javalang (Java 8) can read, with the same line numbers
# ---------------------------------------------------------------------------

_TYPE_HEADER_RE = re.compile(r"(?<![\w.])(class|interface|enum|record)\s+([A-Za-z_]\w*)")
_THROWS_TAIL_RE = re.compile(r"\)\s*throws\s+[\w.<>,\s]+$")


def _blank(text: str) -> str:
    """Spaces for everything but newlines, so line numbers do not move."""
    return re.sub(r"[^\n]", " ", text)


def _lower_record_header(out: list[str], start: int, end: int):
    """`record R<T>(A a, B b) implements I` in out[start:end] -> `class  R<T>             implements I`."""
    head = "".join(out[start:end])
    m = re.search(r"(?<![\w.])record(\s+[A-Za-z_]\w*\s*(?:<[^>]*>)?\s*)\(", head)
    if not m:
        return
    for k in range(6):
        out[start + m.start() + k] = "class "[k]
    depth, j = 0, start + m.end() - 1
    while j < end:
        ch = out[j]
        depth += ch == "("
        depth -= ch == ")"
        out[j] = _blank(ch)
        j += 1
        if depth == 0:
            break


def _lower_for_javalang(content: str) -> tuple[str, set[str]]:
    """
    A copy of `content` that javalang can parse although the file uses Java 14+ syntax, and the
    names of the records in it. Only declarations are read from javalang's tree (bodies are sliced
    from the real source), so the copy keeps declarations and empties everything else:
      - method, constructor, initializer and lambda bodies keep their braces, the inside is blanked
        (switch expressions, yield, instanceof patterns, var lambdas, text blocks live there);
      - `record R(components)` becomes `class R` and a compact constructor `R {` becomes `R() {`;
      - a text block outside a body becomes "".
    Every newline stays where it was, so javalang's line numbers are those of the real file.
    """
    out = list(content)            # one string per source char; an element may grow ("R" -> "R()")
    n = len(content)
    stack: list[tuple[str, str]] = []   # (kind, record name) per open brace: type | code | other
    header: list[str] = []         # code-only text since the last ; { } (strings as "")
    header_start = 0
    code_depth = 0                 # > 0 while inside a blanked body
    records: set[str] = set()
    i = 0
    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""
        # comments, strings, chars and text blocks: skipped whole (blanked inside bodies)
        end = None
        if ch == "/" and nxt == "/":
            end = content.find("\n", i)
            end = n if end < 0 else end
        elif ch == "/" and nxt == "*":
            end = content.find("*/", i + 2)
            end = n if end < 0 else end + 2
        elif content.startswith('"""', i):
            end = content.find('"""', i + 3)
            while end > 0 and content[end - 1] == "\\":
                end = content.find('"""', end + 1)
            end = n if end < 0 else end + 3
            if not code_depth:      # text block outside a body: "" plus its newlines
                out[i] = '""'
                for k in range(i + 1, end):
                    out[k] = _blank(content[k])
                header.append('""')
                i = end
                continue
        elif ch in "\"'":
            end = i + 1
            while end < n and content[end] != ch and content[end] != "\n":
                end += 2 if content[end] == "\\" else 1
            end = min(end + 1, n)
            if not code_depth:
                header.append('""')
        if end is not None:
            if code_depth:
                for k in range(i, end):
                    out[k] = _blank(content[k])
            i = end
            continue

        if code_depth:
            if ch == "{":
                code_depth += 1
            elif ch == "}":
                code_depth -= 1
            if code_depth:          # the closing brace of the body itself is kept
                out[i] = _blank(ch)
            else:
                stack.pop()
                header, header_start = [], i + 1
            i += 1
            continue

        if ch == "{":
            text = "".join(header).strip()
            parent = stack[-1] if stack else ("type", "")
            m = _TYPE_HEADER_RE.search(text)
            if m:
                name = m.group(2)
                if m.group(1) == "record":
                    records.add(name)
                    _lower_record_header(out, header_start, i)
                stack.append(("type", name if m.group(1) == "record" else ""))
            elif (parent[1] and re.fullmatch(r"(?:@\w+\s*)*(?:\w+\s+)*" + re.escape(parent[1]), text)):
                # compact constructor of the enclosing record: `R {` -> `R() {`
                j = i - 1
                while j >= 0 and content[j].isspace():
                    j -= 1
                out[j] = out[j] + "()"
                stack.append(("code", ""))
                code_depth = 1
            elif (text.endswith(")") or text.endswith("->") or text in ("", "static")
                  or _THROWS_TAIL_RE.search(text)):
                stack.append(("code", ""))
                code_depth = 1
            else:                   # array or annotation value, enum constant list: kept as is
                stack.append(("other", ""))
            header, header_start = [], i + 1
        elif ch == "}":
            if stack:
                stack.pop()
            header, header_start = [], i + 1
        elif ch == ";":
            header, header_start = [], i + 1
        else:
            header.append(ch)
        i += 1
    return "".join(out), records


def _describe_parse_error(exc: Exception) -> str:
    at = getattr(exc, "at", None)
    pos = getattr(at, "position", None)
    where = f" at line {pos.line}" if pos else ""
    token = f" near '{at.value}'" if getattr(at, "value", None) else ""
    return f"{type(exc).__name__}{where}{token}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_file(content: str, file_path: str, repo_dir: str,
               source_root: str = "src/main/java",
               compat_comment_lines: bool = True) -> SourceCodeFile:
    """
    Parse a single Java file and return a SourceCodeFile.

    Uses javalang if available, falls back to regex.
    Package name is derived from directory path (matching Eir).
    """
    sf = SourceCodeFile(
        key=file_path,
        file_name=os.path.basename(file_path),
        parent_directory=os.path.dirname(file_path),
    )
    sf.package_name = get_package_from_path(file_path, repo_dir, source_root)

    sf.source = content
    try:
        if javalang is not None:
            try:
                _parse_with_javalang(content, sf, repo_dir, source_root)
            except Exception as first_error:
                # Java 14+ syntax (javalang reads Java 8): parse a same-lines copy with bodies emptied
                # and records lowered to classes; the first error is the one reported if that fails too
                lowered, records = _lower_for_javalang(content)
                sf.main_class, sf.inner_classes, sf.other_types, sf.imports = None, [], [], []
                try:
                    _parse_with_javalang(content, sf, repo_dir, source_root, lowered, records)
                except Exception:
                    raise first_error from None
        else:
            _parse_with_regex(content, sf)
    except Exception as exc:
        sf.cannot_compile = True
        sf.parse_error = _describe_parse_error(exc)
        sf.main_class = None
        sf.inner_classes = []
        sf.other_types = []
        sf.imports = []
        try:
            # Try regex fallback even on javalang failure
            if javalang is not None and sf.main_class is None:
                _parse_with_regex(content, sf)
        except Exception:
            pass  # already marked cannot_compile

    _calculate_line_metrics(sf, content, compat_comment_lines)
    return sf


def is_excluded(file_path: str, package_name: str,
                exclude_packages: list[str] = None,
                exclude_files: list[str] = None) -> bool:
    """Check if a file should be excluded based on package and file patterns."""
    if exclude_packages is None:
        exclude_packages = []
    if exclude_files is None:
        exclude_files = []

    # Package exclusion (full-string regex match, matching Java .matches())
    for pattern in exclude_packages:
        try:
            if re.fullmatch(pattern, package_name):
                return True
        except re.error:
            if pattern in package_name:
                return True

    # File exclusion
    fname = os.path.basename(file_path)
    for pattern in exclude_files:
        try:
            if "." in pattern and os.sep not in pattern and "/" not in pattern:
                # Pattern with dot: match against package.filename
                target = package_name + "." + fname
                if re.fullmatch(pattern, target):
                    return True
            elif os.sep in pattern or "/" in pattern:
                # Pattern with separator: match against full path
                target = os.path.dirname(file_path) + "/" + fname
                if re.fullmatch(pattern, target):
                    return True
            else:
                # Simple pattern: match against filename
                if re.fullmatch(pattern, fname):
                    return True
        except re.error:
            if pattern in fname:
                return True

    return False


def parse_directory(repo_dir: str, source_root: str = "src/main/java",
                    exclude_packages: list[str] = None,
                    exclude_files: list[str] = None,
                    compat_comment_lines: bool = True,
                    specific_files: list[str] = None) -> list[SourceCodeFile]:
    """
    Parse all .java files under {repo_dir}/{source_root}/ recursively.

    Returns list of SourceCodeFile (including cannot_compile files).
    """
    if exclude_packages is None:
        exclude_packages = []
    if exclude_files is None:
        exclude_files = []

    base_dir = os.path.join(repo_dir, source_root)
    if not os.path.isdir(base_dir):
        print(f"  Warning: source directory not found: {base_dir}", file=sys.stderr)
        return []

    results = []
    files_to_parse = []

    if specific_files:
        files_to_parse = [os.path.join(repo_dir, f) for f in specific_files if f.endswith(".java")]
    else:
        for root, _dirs, filenames in os.walk(base_dir):
            for fname in filenames:
                if fname.endswith(".java"):
                    files_to_parse.append(os.path.join(root, fname))

    for file_path in sorted(files_to_parse):
        # Derive package for exclusion check
        pkg = get_package_from_path(file_path, repo_dir, source_root)

        if is_excluded(file_path, pkg, exclude_packages, exclude_files):
            continue

        # Read and parse
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            sf = SourceCodeFile(key=file_path, file_name=fname,
                                parent_directory=os.path.dirname(file_path),
                                cannot_compile=True)
            sf.package_name = pkg
            results.append(sf)
            continue

        sf = parse_file(content, file_path, repo_dir, source_root, compat_comment_lines)
        results.append(sf)

    return results
