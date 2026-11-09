"""
Where a finding is: adds a "Location" column (path:line, relative to the project) to every
rule result whose rows name a Class, so a reviewer can jump to the line instead of searching.

The line is the flagged snippet's line when the rule reports one (a "Line"/"Snippet"/"Pattern
Found" column holding code), otherwise the method's declaration, otherwise the class
declaration. Classes are matched by simple name, "Outer.Inner", or the last segments of a
fully qualified name.
"""

from __future__ import annotations

import os
import re

from eir_models import CommitsDict, RuleResult

_SNIPPET_COLUMNS = ("Line", "Snippet")
_DECL_PREFIX = r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|protected|private|static|final|abstract|synchronized|default)\s+)*"


def _class_index(commits: CommitsDict) -> dict[str, str]:
    """{class name: absolute file path} for main classes ("A") and inner classes ("A.B" and "B")."""
    index: dict[str, str] = {}
    for files in commits.values():
        for f in files:
            if f.main_class is None:
                continue
            outer = f.main_class.class_name
            index.setdefault(outer, f.key)
            for inner in f.inner_classes:
                index.setdefault(f"{outer}.{inner.class_name}", f.key)
                index.setdefault(inner.class_name, f.key)
    return index


def _lookup(index: dict[str, str], cls: str) -> str | None:
    parts = cls.split(".")
    for k in range(min(len(parts), 2), 0, -1):  # "Outer.Inner", then "Inner"; FQNs end in the class
        hit = index.get(".".join(parts[-k:]))
        if hit:
            return hit
    return None


def find_line(lines: list[str], cls: str, method: str | None, snippet: str | None) -> int:
    """1-based line of the snippet, else the method declaration, else the class declaration, else 1."""
    simple = cls.split(".")[-1]
    start = 0
    decl = re.compile(_DECL_PREFIX + r"(?:class|interface|enum|record)\s+" + re.escape(simple) + r"\b")
    for i, text in enumerate(lines):
        if decl.search(text):
            start = i
            break
    method_line = None
    if method:
        mdecl = re.compile(_DECL_PREFIX + r"(?:<[^>]+>\s+)?[\w<>\[\],.? ]+\s+" + re.escape(method) + r"\s*\(")
        for i in range(start, len(lines)):
            if mdecl.search(lines[i]) and not lines[i].rstrip().endswith(";"):
                method_line = i
                break
    if snippet:
        probe = snippet.strip()[:60]
        if probe:
            for i in range(method_line if method_line is not None else start, len(lines)):
                if probe in lines[i]:
                    return i + 1
    if method_line is not None:
        return method_line + 1
    return start + 1


def annotate_locations(results: list[RuleResult], commits: CommitsDict, repo_dir: str) -> None:
    """Append a Location column to each result whose rows have a Class column (in place)."""
    index = _class_index(commits)
    cache: dict[str, list[str]] = {}
    for r in results:
        if "Class" not in r.headers or "Location" in r.headers or not r.rows:
            continue
        ci = r.headers.index("Class")
        mi = r.headers.index("Method") if "Method" in r.headers else None
        si = next((r.headers.index(h) for h in _SNIPPET_COLUMNS if h in r.headers), None)
        width = len(r.headers)
        r.headers.append("Location")
        for row in r.rows:
            row.extend([""] * (width - len(row)))
            path = _lookup(index, str(row[ci]))
            if not path:
                row.append("")
                continue
            if path not in cache:
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        cache[path] = fh.read().splitlines()
                except OSError:
                    cache[path] = []
            method = str(row[mi]) if mi is not None and row[mi] else None
            snippet = str(row[si]) if si is not None and row[si] else None
            line = find_line(cache[path], str(row[ci]), method, snippet)
            rel = os.path.relpath(path, repo_dir).replace("\\", "/")
            row.append(f"{rel}:{line}")
