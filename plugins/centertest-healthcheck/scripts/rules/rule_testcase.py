"""
Rules 9012-9014: how CenterTest finds, creates and reports a @CenterTest class.

Verified in centertest-platform (centertest-core, runner/):
  * CenterTestClassScanner -- Spring's ClassPathScanningCandidateComponentProvider with an
    @CenterTest include filter: concrete top-level (or static nested) classes only, so an abstract
    @CenterTest base class is never a candidate. @CenterTest is not @Inherited.
  * BasicScenariosExtractor.mapToContainer -- Class.forName(name).getDeclaredConstructor().newInstance():
    one instance per class, created through its no-arg constructor without setAccessible. A class
    that is not public, or whose no-arg constructor is missing or not public, throws there, and the
    RuntimeException ends the scan of every test.
  * BasicScenariosExtractor.extractScenarios -- getClass().getDeclaredMethods() filtered on
    isAnnotationPresent(CenterTestCase): any method name, but only methods declared in the class
    itself (a @CenterTestCase method inherited from a superclass is never found).
  * TestExecutor.executeScenario -- org.springframework.util.ReflectionUtils.invokeMethod(method,
    container, scenarioContext): plain Method.invoke without setAccessible, with exactly one argument.
    A non-public method fails with IllegalAccessException; a method that does not take exactly one
    ScenarioContext (a final class, so the parameter can only be ScenarioContext or Object) fails
    with IllegalArgumentException -- on every run.
  * ScenarioDescriptor.copy() (DataDrivenScenariosExtractor, MultiplyExtractor) reuses the same
    container: every DC row and every @CenterTestCase method of a class runs on ONE instance, and
    the rows run concurrently on the parallel.threads pool.
  * TestRailAPI.getCaseId -- the DC row's TestInfo testCaseId, else @CenterTestCase(testCaseId):
    the test-manager case a scenario's result and saved restart point are written to.
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule
from rule_helpers import ProjectIndex, code_only, latest_files, location, scanned_classes, snippet


def _is_generated(f) -> bool:
    return "generated" in (f.package_name or "").split(".")


def _center_test_files(commits: CommitsDict):
    for f in latest_files(commits):
        mc = f.main_class
        if mc is None or "CenterTest" not in mc.annotations or _is_generated(f):
            continue
        yield f


def _line_text(f, line: int) -> str:
    lines = f.source.splitlines()
    return lines[line - 1] if 0 < line <= len(lines) else ""


# ---------------------------------------------------------------------------
# 9012 -- Two tests share a testCaseId
# ---------------------------------------------------------------------------

@rule(id="9012", description="Two tests share a testCaseId", category="CenterTest")
def shared_test_case_ids(commits: CommitsDict, config) -> RuleResult:
    """The same literal testCaseId on @CenterTestCase methods of two different test methods or classes.

    CenterTest writes a scenario's result (and its saved restart point) to the test-manager case
    named by testCaseId (TestRailAPI.getCaseId), so two tests with one id overwrite each other's
    result. Heuristic: annotation_args["CenterTestCase"]["testCaseId"] of every @CenterTestCase
    method (main and inner classes); empty ids and non-literal values are skipped. One row per
    occurrence, grouped by id.
    """
    result = RuleResult(rule_id="9012", description="Two tests share a testCaseId", category="CenterTest",
                        headers=["Class", "Method", "Line", "Issue", "Location"])
    by_id: dict[str, list] = defaultdict(list)
    for f in _center_test_files(commits):
        for cls_name, ce in scanned_classes(f):
            for m in ce.methods:
                if "CenterTestCase" not in m.annotations:
                    continue
                tc_id = (m.annotation_args.get("CenterTestCase") or {}).get("testCaseId")
                if not isinstance(tc_id, str) or not tc_id.strip():
                    continue
                by_id[tc_id.strip()].append((f, cls_name, m))
    for tc_id in sorted(by_id):
        hits = by_id[tc_id]
        if len(hits) < 2:
            continue
        for f, cls_name, m in sorted(hits, key=lambda h: (h[1], h[2].name, h[2].line)):
            others = sorted({f"{c}.{mm.name}" for ff, c, mm in hits if mm is not m})
            line = m.line or 1
            ann_line = next((i for i in range(line, max(0, line - 8), -1)
                             if "@CenterTestCase" in _line_text(f, i)), line)
            result.rows.append([
                cls_name, m.name, snippet(_line_text(f, ann_line)),
                f'testCaseId "{tc_id}" is also used by {", ".join(others)}: both report to the same test-manager '
                f"case, so one test's result (and saved restart point) overwrites the other's",
                location(f, ann_line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} test method(s) share a testCaseId with another test"
    return result


# ---------------------------------------------------------------------------
# 9013 -- @CenterTest class that CenterTest can't run
# ---------------------------------------------------------------------------

_MODIFIERS = {"public", "protected", "private", "abstract", "final", "static", "strictfp", "sealed", "non-sealed"}


def _class_modifiers(f, class_name: str) -> set[str] | None:
    """Modifiers written before `class Name` in the file, or None when the declaration is not found."""
    code = code_only(f.source)
    m = re.search(r"((?:@\w+(?:\.\w+)*(?:\s*\([^)]*\))?\s*|\b[\w-]+\s+)*)\bclass\s+" + re.escape(class_name) + r"\b", code)
    if not m:
        return None
    head = re.sub(r"@\w+(?:\.\w+)*(?:\s*\([^)]*\))?", " ", m.group(1))
    return {w for w in head.split() if w in _MODIFIERS}


@rule(id="9013", description="@CenterTest class that CenterTest can't run", category="CenterTest")
def unrunnable_test_classes(commits: CommitsDict, config) -> RuleResult:
    """A @CenterTest class whose test-case method CenterTest will not run (trust rule).

    Flags, for each concrete top-level @CenterTest class (abstract classes are never scanned):
      * the class is not public, or declares constructors but no public no-arg one -- the
        reflective newInstance() fails and the scan of every test fails with it;
      * no @CenterTestCase method declared in the class itself -- getDeclaredMethods() finds no
        scenario (an inherited @CenterTestCase method does not count). Skipped when another
        project class extends it (a base class) or when the parser could not read the file and
        its text has a @CenterTestCase;
      * a @CenterTestCase method that is not public, or does not take exactly one ScenarioContext
        (or Object) parameter -- invokeMethod(method, container, scenarioContext) throws on every run.
    Method-level checks need javalang's parse (modifiers, parameters), so files the parser could
    not read only get the class-level checks.
    """
    result = RuleResult(rule_id="9013", description="@CenterTest class that CenterTest can't run",
                        category="CenterTest", headers=["Class", "Method", "Line", "Issue", "Location"])
    files = latest_files(commits)
    index = ProjectIndex(files)
    extended = {ce.extensions[0].split(".")[-1] for f in files for _, ce in scanned_classes(f) if ce.extensions}
    for f in _center_test_files(commits):
        mc = f.main_class
        name = mc.class_name
        mods = _class_modifiers(f, name)
        if mods is None or "abstract" in mods:
            continue
        decl_line = mc.line or 1
        decl = snippet(_line_text(f, decl_line))

        if "public" not in mods:
            result.rows.append([name, "", decl,
                                "the class is not public, so CenterTest cannot create it (IllegalAccessException) "
                                "and the scan of every test fails", location(f, decl_line, config)])
            continue
        ctors = [m for m in mc.methods if m.is_constructor]
        if ctors and not f.cannot_compile:
            no_arg = [m for m in ctors if not m.parameters]
            if not no_arg:
                result.rows.append([name, "", decl,
                                    "the class has no no-arg constructor, so CenterTest cannot create it "
                                    "(NoSuchMethodException) and the scan of every test fails",
                                    location(f, decl_line, config)])
                continue
            if "public" not in no_arg[0].modifiers:
                line = no_arg[0].line or decl_line
                result.rows.append([name, name, snippet(_line_text(f, line)),
                                    "the no-arg constructor is not public, so CenterTest cannot create the class "
                                    "(IllegalAccessException) and the scan of every test fails",
                                    location(f, line, config)])
                continue

        cases = [m for m in mc.methods if "CenterTestCase" in m.annotations and not m.is_constructor]
        if not cases:
            if name in extended:
                continue  # a base class other tests extend
            if f.cannot_compile and re.search(r"@CenterTestCase\b", code_only(f.source)):
                continue
            inherited = [a.class_name for a in index.ancestors(mc)
                         if any("CenterTestCase" in m.annotations for m in a.methods)]
            why = (f"its @CenterTestCase method is inherited from {inherited[0]}, and CenterTest only reads "
                   "methods the class declares itself" if inherited else "it has no @CenterTestCase method")
            result.rows.append([name, "", decl, f"CenterTest finds no scenario in this class: {why}, so its "
                                "suite entries run nothing", location(f, decl_line, config)])
            continue
        if f.cannot_compile:
            continue
        for m in cases:
            line = m.line or decl_line
            problems = []
            if "public" not in m.modifiers:
                problems.append("is not public (CenterTest invokes it without setAccessible: IllegalAccessException)")
            types = [p[0].split(".")[-1] for p in m.parameters]
            if types not in (["ScenarioContext"], ["Object"]):
                got = ", ".join(t for t in types) or "no parameters"
                problems.append(f"takes ({got}) instead of one ScenarioContext (IllegalArgumentException)")
            if problems:
                result.rows.append([name, m.name, snippet(_line_text(f, line)),
                                    f"the @CenterTestCase method {' and '.join(problems)}, so the test fails on "
                                    "every run without executing a step", location(f, line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} @CenterTest class(es) or method(s) CenterTest cannot run"
    return result


# ---------------------------------------------------------------------------
# 9014 -- Mutable instance field on a test class
# ---------------------------------------------------------------------------

_LOGGER_TYPES = {"Logger", "Log", "XLogger", "ExtLogger"}
_MUTATORS = r"(?:add|addAll|put|putAll|putIfAbsent|remove|removeAll|clear|set|push|pop|offer|poll|merge|compute\w*)"


def _writes(body: str, name: str, mutable_init: bool) -> bool:
    """True when `body` (code_only) assigns field `name`, or mutates it when it holds a new object."""
    shadowed = re.search(r"(?:\bvar|[\w>\]])\s+" + re.escape(name) + r"\s*[=;:,)]", body)
    target = r"\bthis\." + re.escape(name) if shadowed else r"(?<![\w.])(?:this\.)?" + re.escape(name)
    if re.search(target + r"\s*(?:[+\-*/%&|^]|<<|>>>?)?=(?!=)", body):
        return True
    if re.search(target + r"\s*(?:\+\+|--)", body) or re.search(r"(?:\+\+|--)\s*" + target + r"\b", body):
        return True
    if mutable_init and re.search(target + r"\s*\.\s*" + _MUTATORS + r"\s*\(", body):
        return True
    return False


@rule(id="9014", description="Mutable instance field on a test class", category="CenterTest")
def mutable_test_class_fields(commits: CommitsDict, config) -> RuleResult:
    """Non-static, non-final instance fields of a @CenterTest class that a method writes.

    CenterTest creates ONE instance per test class and runs every scenario of it on that instance:
    every DC row and every @CenterTestCase method (ScenarioDescriptor.copy() keeps the container),
    concurrently on the parallel.threads pool. A field a scenario writes is therefore seen and
    overwritten by the other rows running at the same time.

    Narrowed to fields that are actually written outside the declaration and constructors (an
    assignment, ++/--, or add/put/... on a field initialised with `new ...`) by a method of the
    class or its inner classes; a field only set at its declaration or in a constructor is
    effectively constant. Skipped: static/final fields, annotated (injected) fields, loggers,
    generated packages and files the parser could not read.
    """
    result = RuleResult(rule_id="9014", description="Mutable instance field on a test class",
                        category="CenterTest", headers=["Class", "Method", "Line", "Issue", "Location"])
    for f in _center_test_files(commits):
        if f.cannot_compile:
            continue
        mc = f.main_class
        bodies = [(m.name, code_only(m.body)) for _, ce in scanned_classes(f) for m in ce.methods
                  if m.body and not m.is_constructor]
        for fld in sorted(mc.fields, key=lambda x: x.line):
            if "static" in fld.modifiers or "final" in fld.modifiers or fld.annotations:
                continue
            if fld.type in _LOGGER_TYPES:
                continue
            mutable_init = fld.initializer.startswith("new ")
            writers = [n for n, body in bodies if _writes(body, fld.name, mutable_init)]
            if not writers:
                continue
            writers = sorted(set(writers), key=writers.index)
            line = fld.line or 1
            result.rows.append([
                mc.class_name, writers[0], snippet(_line_text(f, line)),
                f"field `{fld.name}` is written by {', '.join(w + '()' for w in writers)}, but CenterTest runs every "
                "scenario of this class (each DC row, in parallel threads) on one shared instance, so one "
                "scenario's value leaks into another; use a local variable or the ScenarioContext",
                location(f, line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} mutable field(s) shared by every scenario of their test class"
    return result
