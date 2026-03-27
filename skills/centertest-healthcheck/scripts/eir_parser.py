#!/usr/bin/env python3
"""
Java source file parser for eir-analyzer.

Primary: javalang library for AST parsing.
Body extraction: Source-position slicing with brace balancing.
Fallback: Regex-based extraction for files javalang cannot parse.

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


# ---------------------------------------------------------------------------
# javalang-based parsing
# ---------------------------------------------------------------------------

def _parse_with_javalang(content: str, sf: SourceCodeFile, repo_dir: str, source_root: str):
    """Parse a Java file using javalang and populate the SourceCodeFile."""
    tree = javalang.parse.parse(content)

    # Imports — strip wildcard marker
    for imp in tree.imports:
        path = imp.path
        # javalang doesn't include .* for wildcard imports
        sf.imports.append(path)

    # Find class declarations (skip enums, annotations, interfaces for main class)
    class_decls = []
    for type_decl in (tree.types or []):
        if isinstance(type_decl, javalang.tree.ClassDeclaration):
            class_decls.append(type_decl)

    if not class_decls:
        return

    # First class declaration is the main class
    main_decl = class_decls[0]
    parent_key = sf.package_name + "." + main_decl.name if sf.package_name else main_decl.name
    sf.main_class = _build_class_entry(main_decl, parent_key, content)

    # Inner classes: direct ClassDeclaration children of main class
    for member in (main_decl.body or []):
        if isinstance(member, javalang.tree.ClassDeclaration):
            inner_key = parent_key + "." + member.name
            inner = _build_class_entry(member, inner_key, content)
            sf.inner_classes.append(inner)


def _build_class_entry(decl, key: str, source: str) -> ClassEntry:
    """Build a ClassEntry from a javalang ClassDeclaration."""
    ce = ClassEntry(
        class_name=decl.name,
        key=key,
    )

    # Annotations
    ce.annotations = _extract_annotations(decl)

    # Extensions (simple names)
    if decl.extends:
        if isinstance(decl.extends, list):
            ce.extensions = [ext.name for ext in decl.extends]
        else:
            ce.extensions = [decl.extends.name]

    # Interfaces (simple names)
    if decl.implements:
        ce.interfaces = [iface.name for iface in decl.implements]

    # Methods
    method_count = 0
    for member in (decl.body or []):
        if isinstance(member, javalang.tree.MethodDeclaration):
            method_count += 1
            m = Method(name=member.name)
            m.annotations = _extract_annotations(member)
            m.modifiers = sorted(member.modifiers) if member.modifiers else []
            # Extract body via source-position slicing
            if member.position:
                m.body = _extract_method_body_from_source(source, member.position.line)
            ce.methods.append(m)
        elif isinstance(member, javalang.tree.ConstructorDeclaration):
            method_count += 1
            m = Method(name=member.name)
            m.annotations = _extract_annotations(member)
            m.modifiers = sorted(member.modifiers) if member.modifiers else []
            if member.position:
                m.body = _extract_method_body_from_source(source, member.position.line)
            ce.methods.append(m)

    ce.method_count = method_count

    # Fields
    for member in (decl.body or []):
        if isinstance(member, javalang.tree.FieldDeclaration):
            # Only first variable from multi-variable declarations (matching Eir)
            if member.declarators:
                var = member.declarators[0]
                f = Field(
                    name=var.name,
                    type=member.type.name if member.type else "",
                )
                f.annotations = _extract_annotations(member)
                f.modifiers = sorted(member.modifiers) if member.modifiers else []
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

    # Extract annotations before the class declaration
    pre_class = content[:cm.start()]
    annotations = _ANNOTATION_RE.findall(pre_class.split("\n")[-1] if "\n" in pre_class else pre_class)

    sf.main_class = ClassEntry(
        class_name=class_name,
        key=key,
        extensions=extends,
        interfaces=implements,
        annotations=annotations,
        method_count=0,
    )


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

    try:
        if javalang is not None:
            _parse_with_javalang(content, sf, repo_dir, source_root)
        else:
            _parse_with_regex(content, sf)
    except Exception:
        sf.cannot_compile = True
        try:
            # Try regex fallback even on javalang failure
            if javalang is not None and sf.main_class is None:
                _parse_with_regex(content, sf)
        except Exception:
            pass  # already marked cannot_compile

    _calculate_line_metrics(sf, content, compat_comment_lines)
    return sf


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

        # Package exclusion (full-string regex match, matching Java .matches())
        excluded = False
        for pattern in exclude_packages:
            try:
                if re.fullmatch(pattern, pkg):
                    excluded = True
                    break
            except re.error:
                if pattern in pkg:
                    excluded = True
                    break
        if excluded:
            continue

        # File exclusion
        fname = os.path.basename(file_path)
        for pattern in exclude_files:
            try:
                if "." in pattern and os.sep not in pattern:
                    # Pattern with dot: match against package.filename
                    target = pkg + "." + fname
                    if re.fullmatch(pattern, target):
                        excluded = True
                        break
                elif os.sep in pattern:
                    # Pattern with separator: match against full path
                    target = os.path.dirname(file_path) + os.sep + fname
                    if re.fullmatch(pattern, target):
                        excluded = True
                        break
                else:
                    # Simple pattern: match against filename
                    if re.fullmatch(pattern, fname):
                        excluded = True
                        break
            except re.error:
                if pattern in fname:
                    excluded = True
                    break
        if excluded:
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
