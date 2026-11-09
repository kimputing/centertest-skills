"""
What a test actually runs: forward reach from a test's methods through the project's code.

Followed per call, not per class, so a facade every test uses (PC, BC, CC) only contributes
the methods a test calls on it:

- ``Name.method(``      -> that method of class Name (and its superclasses when not declared)
- ``new Name(``         -> the whole class Name and its superclasses (a step's execute() runs it)
- ``extends Name``      -> the superclass's methods are part of the class

Used to find tests that verify nothing: no reached code makes an assertion, so the test passes
as long as the screens open. Assertion vocabulary matches the CenterTest MCP server.
"""

from __future__ import annotations

import os
import re

# The MCP server's vocabulary, plus explicit failures (fail(...), throw new ...AssertionError),
# which are verifications too: a step that throws when the value is wrong checks it.
ASSERTION = re.compile(r"\.assert\w*\(|\bassertThat\(|AnkrPtAssert\.|\bsoftAssert\w*\(|\.verify\w*\(|"
                       r"CenterTestAssertion\.|\bstopIfErrors\(|\bfail\(|throw\s+new\s+\w*AssertionError\b|"
                       # a check that throws a project/framework exception (EnvironmentalException ...) when a value
                       # is wrong; Java's own argument/state exceptions are guards, and a rethrow wrapping a caught
                       # exception is not a check
                       r"throw\s+new\s+(?!(?:IllegalArgument|IllegalState|UnsupportedOperation|NullPointer|"
                       r"IndexOutOfBounds|Runtime|IO|Interrupted|NumberFormat|ClassCast|DateTimeParse)?Exception\()"
                       r"\w+(?:Exception|Error)\((?![^;]*\b(?:e|ex|exc|exception|t|cause)\s*\)\s*;)")
_STATIC_CALL = re.compile(r"\b([A-Z]\w*)\s*\.\s*(\w+)\s*\(")
_NEW = re.compile(r"\bnew\s+([A-Z]\w*)\s*[(<]")
_TYPED = re.compile(r"\b([A-Z]\w*)(?:<[^<>;]*>)?\s+([a-z]\w*)\s*[=;,)]")      # Type name = / ; / , / )
_VAR_CALL = re.compile(r"\b([a-z]\w*)\s*\.\s*(\w+)\s*\(")
_METHOD_REF = re.compile(r"\b([A-Z]\w*)::(\w+)")
_BARE_CALL = re.compile(r"(?<![.\w])([a-z]\w*)\s*\(")
_EXTENDS = re.compile(r"\bclass\s+(\w+)[^{]*?\bextends\s+([A-Z]\w*)")
_METHOD_DECL = re.compile(
    r"(?:public|protected|private|static|final|synchronized|abstract|default|\s)+[\w<>\[\],.? ]+?\s+(\w+)\s*\([^;{)]*\)\s*(?:throws[^{;]*)?\{")
_KEYWORDS = {"if", "for", "while", "switch", "catch", "synchronized", "return", "new"}


def methods_of(text: str) -> list[tuple[str, str]]:
    """[(method name, body)] by declaration regex and brace matching."""
    out = []
    for m in _METHOD_DECL.finditer(text):
        if m.group(1) in _KEYWORDS:
            continue
        depth, k = 1, m.end()
        while k < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            k += 1
        out.append((m.group(1), text[m.end():k]))
    return out


class CodeIndex:
    """Non-generated project classes with their methods and superclass, for reach queries."""

    def __init__(self, sources: dict[str, str]):
        self.text = sources
        self.methods = {name: methods_of(text) for name, text in sources.items()}
        self.parent = {}
        for name, text in sources.items():
            m = _EXTENDS.search(text)
            if m and m.group(1) == name:
                self.parent[name] = m.group(2)

    @classmethod
    def from_tree(cls, root: str, source_root: str = "src/main/java") -> "CodeIndex":
        sources = {}
        for folder, _dirs, files in os.walk(os.path.join(root, source_root)):
            if "datadriven" in folder.replace("\\", "/").split("/"):
                continue
            for name in files:
                if name.endswith(".java"):
                    with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
                        sources[name[:-5]] = fh.read()
        return cls(sources)

    def _chain(self, cls: str):
        seen = set()
        while cls in self.text and cls not in seen:
            seen.add(cls)
            yield cls
            cls = self.parent.get(cls)

    def _types(self, cls: str) -> dict[str, str]:
        """{field or variable name: project class} declared anywhere in the class text."""
        if not hasattr(self, "_type_cache"):
            self._type_cache = {}
        if cls not in self._type_cache:
            self._type_cache[cls] = {var: t for t, var in _TYPED.findall(self.text.get(cls, "")) if t in self.text}
        return self._type_cache[cls]

    def _calls(self, body: str):
        """The calls one body makes, parsed once: every test that reaches a step re-reads it."""
        cache = self.__dict__.setdefault("_call_cache", {})
        if body not in cache:
            cache[body] = (_STATIC_CALL.findall(body) + _METHOD_REF.findall(body), _TYPED.findall(body),
                           _VAR_CALL.findall(body), _NEW.findall(body), _BARE_CALL.findall(body))
        return cache[body]

    def reach(self, start: str) -> list[str]:
        """Bodies of every method the class `start` runs, transitively."""
        bodies, seen = [], set()
        work = [(start, None)]
        while work:
            cls, method = work.pop()
            if (cls, method) in seen:
                continue
            seen.add((cls, method))
            for owner in self._chain(cls):
                found = [b for n, b in self.methods[owner] if method is None or n == method]
                if method is None:
                    # a class's own top-level code (fields, initialisers) can call too
                    found = found or [self.text[owner]]
                types = self._types(owner)
                own = {n for c in self._chain(owner) for n, _b in self.methods[c]}
                for body in found:
                    bodies.append(body)
                    statics, typed, var_calls, news, bare = self._calls(body)
                    local = dict(types)
                    local.update({var: t for t, var in typed if t in self.text})
                    for target, name in statics:
                        if target in self.text:
                            work.append((target, name))
                    for var, name in var_calls:
                        if var in local:
                            work.append((local[var], name))
                    for target in news:
                        if target in self.text:
                            work.append((target, None))
                    if method is not None:
                        for name in bare:
                            if name in own:
                                work.append((cls, name))
                if method is not None and found:
                    break  # the nearest declaration wins
        return bodies

    def assertions_reached(self, test: str) -> int:
        """Assertions in everything the test runs. A call on a project class named like a check
        (BC.assertDisbursement(...)) is not one: reach follows it into the code that checks."""
        cache = self.__dict__.setdefault("_assert_cache", {})
        count = 0
        for body in self.reach(test):
            if body not in cache:
                n = 0
                for m in ASSERTION.finditer(body):
                    receiver = re.search(r"(\w+)\s*$", body[:m.start()])
                    if m.group(0).startswith(".") and receiver and receiver.group(1) in self.text:
                        continue
                    n += 1
                cache[body] = n
            count += cache[body]
        return count
