"""
Rules 17001-17009: architecture -- where UI access, step overrides, logins and copied code live.

17001 -- Test drives widgets directly (UI access in the test class instead of a step)
17002 -- Large step override inside a test (inner class extending a project step, > N lines)
17003 -- Widget access outside the steps package (util/ helpers that drive the UI)
17004 -- Override that only calls super
17005 -- Field re-declared in a subclass (shadows a project ancestor's field)
17006 -- Page object re-created inside a step
17007 -- Step logs in as another user behind the test's back
17008 -- Near-duplicate test classes
17009 -- Same private helper line in many tests

What counts as what (checked against the CenterTest framework and the PMIC/OOTB layouts):
  * a test is a class annotated @CenterTest / @ScenarioContainer;
  * a step is what ProjectIndex.is_step says: it extends (through project classes) a framework
    Base*/Scenario class (BaseScenarioPC/BC/CC/AB/Gw), or declares execute();
  * a page object is a generated class from a `...generated.pages...` import (PcfPage subclasses
    in the generated project: 1221 *Page, 873 *Popup in PMIC), or a project class that extends a
    page (OOTB's pages/portal/*Page extends PortalPage). A page constructor only stores the context
    and builds a WebDriverWait (PcfPage), so re-creating one is redundant, never needed;
  * widget lookups are the static factories `Widget*.get...(` / `PortalWidget*.get...(` and
    `Widget*.class` handles (row.get("Premium", WidgetGwCell.class)).
Generated code (any `generated` package) is never reported.
"""

from __future__ import annotations

import os
import difflib
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import ClassEntry, CommitsDict, Method, RuleResult, SourceCodeFile
from eir_rules import rule
from rule_helpers import (ProjectIndex, balanced_end, body_line, code_only, latest_files, location,
                          scanned_classes, snippet, strip_comments)

CATEGORY = "Architecture"
_HEADERS = ["Class", "Method", "Line", "Issue", "Location"]


# ---------------------------------------------------------------------------
# Shared helpers (private to this file)
# ---------------------------------------------------------------------------

def _threshold(config, rule_id: str, default: int) -> int:
    getter = getattr(config, "get_threshold", None)
    if getter is None:
        return default
    try:
        return int(getter(rule_id, default))
    except (TypeError, ValueError):
        return default


_GENERATED_PKG = re.compile(r"(^|\.)generated(\.|$)")


def _is_generated(f: SourceCodeFile) -> bool:
    return bool(_GENERATED_PKG.search(f.package_name or ""))


def _project_files(commits: CommitsDict) -> list[SourceCodeFile]:
    return [f for f in latest_files(commits) if f.main_class is not None and not _is_generated(f)]


def _is_test(f: SourceCodeFile) -> bool:
    return f.is_test_class()


def _result(rule_id: str, description: str, headers=None) -> RuleResult:
    return RuleResult(rule_id=rule_id, description=description, category=CATEGORY,
                      headers=list(headers or _HEADERS))


_PAGE_SUFFIX = re.compile(r"(Page|Popup|Worksheet)$")
_PAGE_BASES = {"PcfPage", "PortalPage", "Page", "BasePage", "AbstractPage"}


def _page_types(f: SourceCodeFile, idx: ProjectIndex | None = None) -> tuple[set[str], bool]:
    """(simple names of page classes this file can construct, has a wildcard pages import).

    Pages are the classes imported from a `.generated.pages.` package, plus project classes that
    extend a page (PcfPage/PortalPage or another page)."""
    names, wildcard = set(), False
    for imp in f.imports:
        last = imp.rsplit(".", 1)[-1]
        if ".generated.pages." in imp or imp.endswith(".generated.pages"):
            # the parser records `import x.pages.pc.*;` as the bare package (javalang drops the .*)
            if last == "*" or not last[:1].isupper():
                wildcard = True
            else:
                names.add(last)
        elif ".pages." in imp and _PAGE_SUFFIX.search(last):
            names.add(last)
    if idx is not None:
        for name, (_, ce) in idx.by_name.items():
            if _is_page_class(ce, idx):
                names.add(name)
    return names, wildcard


def _is_page_class(ce: ClassEntry, idx: ProjectIndex) -> bool:
    """A project class that extends a page: PcfPage/PortalPage up its chain, or a *Page/*Popup class
    that is not in the project (a generated page)."""
    return any(s in _PAGE_BASES or (_PAGE_SUFFIX.search(s) and s not in idx.by_name)
               for s in idx.superclass_names(ce))


def _is_page_name(name: str, pages: set[str], wildcard: bool) -> bool:
    return name in pages or (wildcard and bool(_PAGE_SUFFIX.search(name)))


def _is_ui_class(f: SourceCodeFile, ce: ClassEntry, idx: ProjectIndex) -> bool:
    """Page objects, widget extensions and classes in a pages/widgets package: UI access is their job."""
    pkg_parts = set((f.package_name or "").lower().split("."))
    if pkg_parts & {"pages", "page", "widget", "widgets", "widgetoverrides", "components"}:
        return True
    if "Widget" in ce.class_name or _PAGE_SUFFIX.search(ce.class_name):
        return True
    for s in idx.superclass_names(ce):
        if s in _PAGE_BASES or "Widget" in s or _PAGE_SUFFIX.search(s):
            return True
    return False


def _is_step_class(ce: ClassEntry, idx: ProjectIndex) -> bool:
    return ce.kind == "class" and idx.is_step(ce)


_NEW_RE = re.compile(r"\bnew\s+([A-Z]\w*)\s*(?:<[^<>()]*>)?\s*\(")


def _blank_anonymous_steps(code: str, idx: ProjectIndex) -> str:
    """Blank (keeping newlines) the bodies of anonymous subclasses of project steps
    (`new ApproveUWIssues(ctx) { @Override ... }`): code there is a step, not the caller."""
    out = code
    for m in _NEW_RE.finditer(code):
        hit = idx.by_name.get(m.group(1))
        if hit is None or not idx.is_step(hit[1]):
            continue
        close = balanced_end(code, m.end() - 1)
        rest = code[close:]
        stripped = rest.lstrip()
        if not stripped.startswith("{"):
            continue
        brace = close + (len(rest) - len(stripped))
        end = balanced_end(code, brace)
        block = out[brace:end]
        out = out[:brace] + re.sub(r"[^\n]", " ", block) + out[end:]
    return out


_WIDGET_STATIC = re.compile(r"\b[A-Z]\w*Widget\w*\s*\.\s*get\w*\s*\(|\bWidget\w*\s*\.\s*get\w*\s*\(")
_WIDGET_CLASS = re.compile(r"\b\w*Widget\w*\s*\.\s*class\b")
_DECL_RE = re.compile(r"^\s*(?:final\s+)?(?:var|[A-Z][\w.]*(?:<[^=;]*>)?(?:\[\])?)\s+(\w+)\s*=\s*(.+)$")
_ASSIGN_RE = re.compile(r"^\s*(?:this\.)?(\w+)\s*=\s*(.+)$")
_FOR_EACH_RE = re.compile(r"\bfor\s*\(\s*(?:final\s+)?[\w.<>\[\]]+\s+(\w+)\s*:\s*(.+)\)")


def _ui_lines(code: str, pages: set[str], wildcard: bool, page_fields: set[str]) -> list[tuple[int, str]]:
    """[(0-based line index, what)] for the lines of a (code_only) body that locate or drive widgets:
    a page constructed, a static widget lookup, a widget class handle, or a call on a variable or
    field that holds a page / something reached from a page."""
    page_vars = set(page_fields)
    hits = []
    for i, line in enumerate(code.splitlines()):
        what = ""
        for m in _NEW_RE.finditer(line):
            if _is_page_name(m.group(1), pages, wildcard):
                what = f"new {m.group(1)}(...)"
                break
        if not what:
            m = _WIDGET_STATIC.search(line) or _WIDGET_CLASS.search(line)
            if m:
                what = re.sub(r"\s+", "", m.group(0)).rstrip("(")
        if not what and page_vars:
            m = re.search(r"\b(" + "|".join(map(re.escape, sorted(page_vars))) + r")\s*\.\s*\w+\s*\(", line)
            if m:
                what = f"{m.group(1)}.{line[m.end(1):m.end()].strip(' .(')}()"
        # variables that now hold a page or something reached from one
        decl = _DECL_RE.match(line) or _ASSIGN_RE.match(line)
        if decl and what:
            page_vars.add(decl.group(1))
        fe = _FOR_EACH_RE.search(line)
        if fe and what:
            page_vars.add(fe.group(1))
        if what:
            hits.append((i, what))
    return hits


def _page_fields(ce: ClassEntry, idx: ProjectIndex, pages: set[str], wildcard: bool, inherit=True) -> dict[str, str]:
    """{field name: page type} for the class's fields of a page type (and non-private inherited ones)."""
    out = {}
    classes = [ce] + (idx.ancestors(ce) if inherit else [])
    for k, c in enumerate(classes):
        for fd in c.fields:
            t = re.sub(r"<.*", "", fd.type or "").split(".")[-1]
            if k > 0 and "private" in fd.modifiers:
                continue
            if "static" in fd.modifiers:
                continue
            if _is_page_name(t, pages, wildcard) or (_PAGE_SUFFIX.search(t) and t != ce.class_name):
                out.setdefault(fd.name, t)
    return out


def _widget_method_rows(f, display, ce, idx, pages, wildcard, issue_fn, config, skip=lambda m: False):
    rows = []
    fields = set(_page_fields(ce, idx, pages, wildcard, inherit=False))
    for m in ce.methods:
        if skip(m) or not m.body:
            continue
        code = _blank_anonymous_steps(code_only(m.body), idx)
        hits = _ui_lines(code, pages, wildcard, fields)
        if not hits:
            continue
        i, what = hits[0]
        raw = m.body.splitlines()
        line_no = body_line(f, m, i)
        rows.append([display, m.name, snippet(raw[i] if i < len(raw) else ""), issue_fn(len(hits), what),
                     location(f, line_no, config)])
    return rows


# ---------------------------------------------------------------------------
# 17001
# ---------------------------------------------------------------------------

@rule(id="17001", description="Test drives widgets directly", category=CATEGORY)
def test_drives_widgets(commits: CommitsDict, config) -> RuleResult:
    """A @CenterTest class whose own code locates or drives widgets: it constructs a generated page
    object (`new SubmissionWizardPage(ctx)`), calls a static widget lookup (`WidgetButton.getByLabel`),
    uses a widget class handle, or calls into a variable/field that holds a page or something reached
    from one (`lineStep.getCoveragesTab().click()`). UI access belongs in steps, where other tests reuse
    it and a screen change is fixed once.

    Scope: the test's main class and its inner classes that are NOT steps. An inner class that extends
    a project step (an override of a reusable step) is a step: its UI code is reported by 17002 when the
    override is large, not here, so the same lines are never reported twice. Code inside an anonymous
    subclass of a step (`new ApproveX(ctx) { ... }`) is skipped for the same reason. One row per method
    (the first UI line), with the count of UI lines in the Issue."""
    result = _result("17001", "Test drives widgets directly")
    files = _project_files(commits)
    idx = ProjectIndex(latest_files(commits))
    for f in sorted(files, key=lambda x: x.key):
        if not _is_test(f):
            continue
        pages, wildcard = _page_types(f, idx)
        for display, ce in scanned_classes(f):
            if ce is not f.main_class and (_is_step_class(ce, idx) or ce.kind != "class"):
                continue
            result.rows.extend(_widget_method_rows(
                f, display, ce, idx, pages, wildcard,
                lambda n, what: (f"The test drives the UI itself ({what}{f', {n} UI lines' if n > 1 else ''}): "
                                 "UI access belongs in a step, so other tests can reuse it and a screen "
                                 "change is fixed in one place"),
                config))
    if result.rows:
        result.summary = f"{len(result.rows)} test method(s) locate or drive widgets themselves instead of calling a step"
    return result


# ---------------------------------------------------------------------------
# 17002
# ---------------------------------------------------------------------------

def _class_span(f: SourceCodeFile, ce: ClassEntry) -> tuple[int, int]:
    """(first line, last line) of a class, from its declaration line to its closing brace."""
    if not ce.line:
        return 0, 0
    code = _mask_literals(strip_comments(f.source))  # strip_comments keeps line numbers
    off = sum(len(x) for x in code.splitlines(keepends=True)[: ce.line - 1])
    brace = code.find("{", off)
    if brace < 0:
        return ce.line, ce.line
    end = balanced_end(code, brace)
    return ce.line, code.count("\n", 0, max(end - 1, 0)) + 1


@rule(id="17002", description="Large step override inside a test", category=CATEGORY)
def large_step_override_in_test(commits: CommitsDict, config) -> RuleResult:
    """An inner class of a test class that extends a project class which is a step
    (ProjectIndex.is_step) and is longer than the threshold (17002, default 40 lines, declaration to
    closing brace). Such an override hides a variant of a reusable flow inside one test: once a second
    test needs it, it gets copied. Inner classes extending framework classes directly (a small local
    step) and short overrides are not reported."""
    result = _result("17002", "Large step override inside a test",
                     ["Class", "Extends", "Lines", "Issue", "Location"])
    limit = _threshold(config, "17002", 40)
    idx = ProjectIndex(latest_files(commits))
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        if not _is_test(f):
            continue
        for display, ce in scanned_classes(f):
            if ce is f.main_class or not ce.extensions:
                continue
            parent = ce.extensions[0].split(".")[-1]
            hit = idx.by_name.get(parent)
            if hit is None or hit[1] is ce or not idx.is_step(hit[1]):
                continue
            start, end = _class_span(f, ce)
            size = end - start + 1 if start else 0
            if size <= limit:
                continue
            result.rows.append([display, parent, size,
                                f"A {size}-line override of the step {parent} lives inside the test: move it to "
                                f"the reusable steps (a subclass or an option of {parent}) so the next test "
                                "reuses it instead of copying it",
                                location(f, start, config)])
    result.rows.sort(key=lambda r: (-r[2], r[0]))
    if result.rows:
        result.summary = f"{len(result.rows)} step override(s) longer than {limit} lines inside test classes"
    return result


# ---------------------------------------------------------------------------
# 17003
# ---------------------------------------------------------------------------

@rule(id="17003", description="Widget access outside the steps package", category=CATEGORY)
def widget_access_outside_steps(commits: CommitsDict, config) -> RuleResult:
    """Widget/page access (a page constructed, a static `Widget*.get...` lookup, calls on a page
    variable or field) in a class that is neither a test nor a step nor a UI class -- typically a util/
    helper such as `GeneralUtil.saveDraft` clicking `WidgetButton.getByLabel("Save Draft")`. The UI is
    then driven from places that do not show up as steps.

    Not reported: tests (17001), steps (ProjectIndex.is_step: extends a Base*/Scenario framework class
    through project classes, or declares execute()), and UI classes (page objects -- a class extending
    PcfPage/PortalPage/a *Page/*Popup, widget extensions, anything in a pages/widgets package).
    Anonymous step subclasses inside a helper are skipped. A helper that only receives a widget as a
    parameter (an assertion helper) does not locate UI and is not reported. One row per method."""
    result = _result("17003", "Widget access outside the steps package")
    idx = ProjectIndex(latest_files(commits))
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        if _is_test(f):
            continue
        mc = f.main_class
        if mc.kind != "class" or _is_step_class(mc, idx) or _is_ui_class(f, mc, idx):
            continue
        pages, wildcard = _page_types(f, idx)
        for display, ce in scanned_classes(f):
            if ce.kind != "class" or _is_step_class(ce, idx) or _is_ui_class(f, ce, idx):
                continue
            result.rows.extend(_widget_method_rows(
                f, display, ce, idx, pages, wildcard,
                lambda n, what: (f"{what} in a class that is neither a step nor a page"
                                 f"{f' ({n} UI lines)' if n > 1 else ''}: the UI is driven from a helper the "
                                 "tests do not show as a step; move it into a step or a page object"),
                config))
    if result.rows:
        result.summary = f"{len(result.rows)} helper method(s) outside the steps drive the UI"
    return result


# ---------------------------------------------------------------------------
# 17004
# ---------------------------------------------------------------------------

_VISIBILITY = ("public", "protected", "private")


def _visibility(m: Method) -> str:
    return next((v for v in _VISIBILITY if v in m.modifiers), "")


def _ancestor_method(ce: ClassEntry, idx: ProjectIndex, m: Method) -> Method | None:
    for anc in idx.ancestors(ce):
        for pm in anc.methods:
            if pm.name == m.name and len(pm.parameters) == len(m.parameters):
                return pm
    return None


@rule(id="17004", description="Override that only calls super", category=CATEGORY)
def override_only_calls_super(commits: CommitsDict, config) -> RuleResult:
    """An @Override method whose whole body is `super.sameName(sameArgs);` (or `return super...;`) with
    the parameters passed through in order: the override changes nothing and only adds noise.

    Guards: the method carries no annotation besides @Override (a @CenterTestCase/@DataDriven override
    is how a subclass becomes a test); when the overridden method is found in a project ancestor its
    visibility must be the same (an override that widens protected -> public is deliberate); a method
    whose parent is outside the project is reported only when it is not public (widening a framework
    method's visibility cannot be ruled out otherwise); `final`/`synchronized` overrides are skipped."""
    result = _result("17004", "Override that only calls super")
    idx = ProjectIndex(latest_files(commits))
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        for display, ce in scanned_classes(f):
            for m in ce.methods:
                if m.is_constructor or set(m.annotations) != {"Override"}:
                    continue
                if {"final", "synchronized"} & set(m.modifiers):
                    continue
                body = re.sub(r"\s+", "", code_only(m.body))
                args = ",".join(name for _, name in m.parameters)
                if body not in (f"{{super.{m.name}({args});}}", f"{{returnsuper.{m.name}({args});}}"):
                    continue
                parent = _ancestor_method(ce, idx, m)
                if parent is not None:
                    if _visibility(parent) != _visibility(m):
                        continue
                elif _visibility(m) == "public":
                    continue
                result.rows.append([display, m.name, snippet(f"super.{m.name}({args});"),
                                    f"{m.name}() only calls super.{m.name}(): the parent's method runs anyway, "
                                    "so the override is dead weight that hides where the behaviour lives",
                                    location(f, m.line, config)])
    if result.rows:
        result.summary = f"{len(result.rows)} override(s) that only call super"
    return result


# ---------------------------------------------------------------------------
# 17005
# ---------------------------------------------------------------------------

def _simple_type(t: str) -> str:
    return re.sub(r"<.*", "", t or "").split(".")[-1].strip()


@rule(id="17005", description="Field re-declared in a subclass", category=CATEGORY)
def field_redeclared_in_subclass(commits: CommitsDict, config) -> RuleResult:
    """A field whose name is also declared by a project ancestor class: the subclass's methods use its
    own field and the parent's methods use the other one, so a value set in one is not seen by the
    other (`protected PolicyChangeWizardPage policyChangeWizardPage` in CreatePersonalAutoOOSPolicyChange
    and in AbstractPolicyChange).

    Guards: static fields on either side (constants, loggers) are ignored; a private ancestor field is
    ignored (the subclass cannot see it, so it is not a shadow it could have used); a re-declaration
    with a different (narrower) type is ignored -- `protected WorkersCompDataCombination data` over the
    parent's `OotbDataCombination data` is the usual typed-access idiom (OOTB v9), not an accident; only
    project ancestors are checked (framework fields are not parsed)."""
    result = _result("17005", "Field re-declared in a subclass")
    idx = ProjectIndex(latest_files(commits))
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        for display, ce in scanned_classes(f):
            ancestors = idx.ancestors(ce)
            if not ancestors:
                continue
            for fd in ce.fields:
                if "static" in fd.modifiers:
                    continue
                for anc in ancestors:
                    pf = next((x for x in anc.fields if x.name == fd.name), None)
                    if pf is None:
                        continue
                    if "static" in pf.modifiers or "private" in pf.modifiers or _simple_type(pf.type) != _simple_type(fd.type):
                        break
                    line = f.source.splitlines()[fd.line - 1] if fd.line and fd.line <= len(f.source.splitlines()) else f"{fd.type} {fd.name};"
                    result.rows.append([display, fd.name, snippet(line),
                                        f"{fd.name} is already declared in {anc.class_name}: the subclass's code uses "
                                        "its own copy and the parent's code the inherited one, so a value set in one "
                                        "is not seen by the other; use the inherited field",
                                        location(f, fd.line, config)])
                    break
    if result.rows:
        result.summary = f"{len(result.rows)} field(s) shadow a field of a parent class"
    return result


# ---------------------------------------------------------------------------
# 17006
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _constructions(code: str, pages: set[str], wildcard: bool):
    """(type, normalized args, offset) for each `new Page(args)` in code_only text."""
    for m in _NEW_RE.finditer(code):
        name = m.group(1)
        if not (_is_page_name(name, pages, wildcard) or _PAGE_SUFFIX.search(name)):
            continue
        end = balanced_end(code, m.end() - 1)
        args = _norm(code[m.end():end - 1])
        # an anonymous subclass is not a re-creation of the same object
        if code[end:].lstrip().startswith("{"):
            continue
        yield name, args, m.start()


@rule(id="17006", description="Page object re-created inside a step", category=CATEGORY)
def page_recreated_in_step(commits: CommitsDict, config) -> RuleResult:
    """Inside a step: `new XxxPage(args)` / `new XxxPopup(args)` although the class (or a project
    ancestor, non-private) already holds a field of that type built with the same arguments, or the
    same `new X(args)` built twice in one method. A page object only wraps the invocation context
    (PcfPage's constructor stores it and builds a wait), so re-creating it is pure noise -- and a field
    that is not used invites the two to drift apart.

    Guards: constructors are skipped; an assignment to the field itself (`wizardPage = new ...`) is the
    field's initialization, not a re-creation; the field case needs the field's own construction to be
    found (initializer or `field = new X(args)` in the class or an ancestor) with the same arguments,
    so a page built for another user's context is not reported; anonymous subclasses are skipped."""
    result = _result("17006", "Page object re-created inside a step")
    idx = ProjectIndex(latest_files(commits))
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        for display, ce in scanned_classes(f):
            if ce.kind != "class" or not idx.is_step(ce):
                continue
            pages, wildcard = _page_types(f, idx)
            fields = _page_fields(ce, idx, pages, wildcard)
            # how each page field is built: {type: {args}} from initializers and assignments
            built: dict[str, set[str]] = defaultdict(set)
            for c in [ce] + idx.ancestors(ce):
                for fd in c.fields:
                    if fd.name in fields and fd.initializer:
                        for name, args, _ in _constructions(code_only(fd.initializer), pages, wildcard):
                            built[fields[fd.name]].add(args)
                for m in c.methods:
                    code = code_only(m.body)
                    for fname, ftype in fields.items():
                        for am in re.finditer(r"(?:\bthis\s*\.\s*|(?<![\w.]))" + re.escape(fname) +
                                              r"\s*=\s*new\s+" + re.escape(ftype) + r"\s*\(", code):
                            end = balanced_end(code, am.end() - 1)
                            built[ftype].add(_norm(code[am.end():end - 1]))
            field_types = {t: n for n, t in fields.items()}
            for m in ce.methods:
                if m.is_constructor or not m.body:
                    continue
                code = code_only(m.body)
                seen: dict[tuple[str, str], int] = {}
                for name, args, off in _constructions(code, pages, wildcard):
                    before = code[:off]
                    line_idx = before.count("\n")
                    stmt_start = max(before.rfind(";"), before.rfind("{"), before.rfind("}")) + 1
                    stmt_head = before[stmt_start:]
                    issue = ""
                    if name in field_types and args in built.get(name, set()):
                        fname = field_types[name]
                        if not re.search(r"(?:\bthis\s*\.\s*|(?<![\w.]))" + re.escape(fname) + r"\s*=\s*$", stmt_head):
                            issue = (f"new {name}(...) although the step already holds it in the field {fname}: "
                                     f"use {fname} instead of building a second copy of the same page")
                    if not issue and (name, args) in seen:
                        issue = (f"new {name}(...) is built again in the same method (first at line "
                                 f"{body_line(f, m, seen[(name, args)])}): build it once into a variable")
                    seen.setdefault((name, args), line_idx)
                    if issue:
                        raw = m.body.splitlines()
                        result.rows.append([display, m.name, snippet(raw[line_idx] if line_idx < len(raw) else ""),
                                            issue, location(f, body_line(f, m, line_idx), config)])
    if result.rows:
        result.summary = f"{len(result.rows)} page object(s) re-created inside steps"
    return result


# ---------------------------------------------------------------------------
# 17007
# ---------------------------------------------------------------------------

_INVOCATION_RE = re.compile(r"\.\s*getInvocationContext\s*\(\s*\"")
_LOGIN_CALL = re.compile(r"\b\w*[Ll]ogin\w*\s*\(")


@rule(id="17007", description="Step logs in as another user behind the test's back", category=CATEGORY)
def step_logs_in_as_other_user(commits: CommitsDict, config) -> RuleResult:
    """A step (not a test, not a helper) that fetches an invocation context for a role
    (`getScenarioContext().getInvocationContext("underwriter")`) and logs in with it
    (`PC.loginToPC(underwriter)`): the test body never shows that a second user acts, so a reader (and
    the environment's user list) cannot tell from the test which roles it needs.

    ScenarioContext.getInvocationContext(key) creates the context on first use (centertest-core), so
    the role silently becomes part of the scenario. Detection: a variable assigned from
    `getInvocationContext("...")` that is then passed to a call whose name contains `login`, or a login
    call whose argument is the getInvocationContext(...) expression itself. Test classes (inner steps
    included) are skipped: there the login is visible in the test file."""
    result = _result("17007", "Step logs in as another user behind the test's back")
    idx = ProjectIndex(latest_files(commits))
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        if _is_test(f):
            continue
        for display, ce in scanned_classes(f):
            if ce.kind != "class" or not idx.is_step(ce):
                continue
            for m in ce.methods:
                if not m.body or "getInvocationContext" not in m.body:
                    continue
                # strings kept (the role name), comments dropped; line structure preserved
                text = strip_comments(m.body)
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    im = _INVOCATION_RE.search(line)
                    if not im:
                        continue
                    role = re.match(r'"((?:[^"\\]|\\.)*)"', line[im.end() - 1:])
                    role = role.group(1) if role else "?"
                    var = (_DECL_RE.match(line) or _ASSIGN_RE.match(line))
                    logged_in = False
                    if _LOGIN_CALL.search(line[: im.start()]):
                        logged_in = True
                    elif var:
                        name = var.group(1)
                        rest = "\n".join(lines[i + 1:])
                        logged_in = bool(re.search(r"\b\w*[Ll]ogin\w*\s*\(\s*" + re.escape(name) + r"\b", rest))
                    if not logged_in:
                        continue
                    raw = m.body.splitlines()
                    result.rows.append([display, m.name, snippet(raw[i] if i < len(raw) else line),
                                        f"The step logs in as \"{role}\" on its own: the test never shows that "
                                        "a second user acts, so its roles and users cannot be read from the test; "
                                        "make it a step the test calls (or one named helper)",
                                        location(f, body_line(f, m, i), config)])
                    break
    if result.rows:
        result.summary = f"{len(result.rows)} step(s) log in as another role the test does not show"
    return result


# ---------------------------------------------------------------------------
# 17008
# ---------------------------------------------------------------------------

_MIN_STATEMENTS = 10


def _statements(code: str) -> list[str]:
    """Statements of code_only text, whitespace collapsed (split on ; { })."""
    return [s for s in (re.sub(r"\s+", " ", p).strip() for p in re.split(r"[;{}]", code)) if s]


_JAVA_WORDS = set("""abstract assert boolean break byte case catch char class continue default do double else
enum extends final finally float for if implements import instanceof int interface long native new null package
private protected public return short static super switch synchronized this throw throws transient true false try
var void volatile while""".split())
_LOCAL_NAME = re.compile(r"(?<![\w.$])([a-z_]\w*)\b(?!\s*\()")


def _canon(stmt: str) -> str:
    """Variable names neutralised: a lower-case identifier that is not a member (`.x`), not a call
    (`x(`) and not a keyword becomes `v`, so `dataDC.getPerson()` and `data.getPerson()` compare equal.
    Types, method names and member names are kept."""
    return _LOCAL_NAME.sub(lambda m: m.group(1) if m.group(1) in _JAVA_WORDS else "v", stmt)


def _class_statements(f: SourceCodeFile) -> list[str]:
    code = code_only(f.source)
    code = re.sub(r"^\s*(?:package|import)\s[^;]*;", "", code, flags=re.M)
    name = f.main_class.class_name
    code = re.sub(r"\b" + re.escape(name) + r"\b", "ThisTest", code)
    return [_canon(s) for s in _statements(code) if not s.startswith("@")]


def _datasources(f: SourceCodeFile) -> tuple[str, ...]:
    out = set()
    for _, ce in scanned_classes(f):
        for args in [ce.annotation_args.get("DataDriven", {})] + [m.annotation_args.get("DataDriven", {}) for m in ce.methods]:
            if args.get("datasource"):
                out.add(str(args["datasource"]))
    return tuple(sorted(out))


@rule(id="17008", description="Near-duplicate test classes", category=CATEGORY)
def near_duplicate_tests(commits: CommitsDict, config) -> RuleResult:
    """Pairs of @CenterTest classes that run the same flow on the same data and differ by a line or
    two -- the difference belongs in a DC row, not in a second class (TC_UI_003Test = PA_SubmissionTest
    plus one `.withVin(...)` line).

    Normalisation: comments removed, literal contents blanked, the class's own name neutralised,
    variable names neutralised (types, method and member names kept), whitespace collapsed, split into
    statements. A pair is reported when (1) both read the same @DataDriven workbook(s), (2) both run
    the same ordered sequence of `.execute(` step calls, and (3) the statement sequences are at least
    the threshold similar (17008, default 80 percent; difflib ratio, order-aware). Condition (2) keeps
    out the templated tests that share a skeleton but run a different step (PA_AddVehicleTest vs
    PA_SubstituteVehicleTest): those are different flows. Classes with fewer than 10 statements are
    skipped. One row per pair, with the similarity."""
    result = _result("17008", "Near-duplicate test classes",
                     ["Class", "Similar to", "Similarity", "Issue", "Location"])
    limit = _threshold(config, "17008", 80)
    groups: dict[tuple, list] = defaultdict(list)
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        if not _is_test(f) or "CenterTest" not in f.main_class.annotations:
            continue
        st = _class_statements(f)
        if len(st) < _MIN_STATEMENTS:
            continue
        steps = tuple(s for s in st if ".execute(" in s)
        if not steps:
            continue
        groups[(_datasources(f), steps)].append((f, st))
    for members in groups.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                (fa, sa), (fb, sb) = members[i], members[j]
                pct = int(difflib.SequenceMatcher(None, sa, sb, autojunk=False).ratio() * 100)
                if pct < limit:
                    continue
                a, b = fa.main_class.class_name, fb.main_class.class_name
                result.rows.append([a, b, f"{pct}%",
                                    f"{a} and {b} run the same steps on the same data and are {pct}% the same "
                                    "code: keep one test and make the difference a DC row, or every fix has to "
                                    "be made twice", location(fa, fa.main_class.line, config)])
    result.rows.sort(key=lambda r: (-int(r[2].rstrip("%")), r[0], r[1]))
    if result.rows:
        result.summary = f"{len(result.rows)} pair(s) of near-duplicate test classes"
    return result


# ---------------------------------------------------------------------------
# 17009
# ---------------------------------------------------------------------------

_MIN_STATEMENT_CHARS = 60


def _mask_literals(text: str) -> str:
    """Same length, literal contents replaced by x, so ; { } inside strings do not split statements."""
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"', lambda m: '"' + "x" * (len(m.group(0)) - 2) + '"', text)
    return re.sub(r"'(?:[^'\\\n]|\\.)'", lambda m: "'" + "x" * (len(m.group(0)) - 2) + "'", text)


_TRIVIAL_START = re.compile(r"^(?:return\b|throw\b|else\b|try\b|finally\b|catch\b|case\b|default\b)")


def _helper_statements(m: Method) -> list[tuple[str, int]]:
    """(normalized statement, 0-based body line) for each statement of a method body (literals kept)."""
    text = strip_comments(m.body)
    masked = _mask_literals(text)
    out = []
    for part in re.finditer(r"[^;{}]+", masked):
        raw = text[part.start():part.end()]
        norm = re.sub(r"\s+", " ", raw).strip()
        if not norm:
            continue
        lead = len(raw) - len(raw.lstrip())
        out.append((norm, text.count("\n", 0, part.start() + lead)))
    return out


def _non_trivial(stmt: str) -> bool:
    """Worth sharing: long, and more than one plain call -- it chains calls or carries a condition."""
    if len(stmt) < _MIN_STATEMENT_CHARS or _TRIVIAL_START.match(stmt):
        return False
    if re.match(r"^(?:if|while|for)\b", stmt) and not re.search(r"\)\s*\S", stmt[stmt.find("("):]):
        return False  # a bare condition header `if (...)` without its statement
    calls = len(re.findall(r"\w\s*\(", stmt))
    return calls >= 3 or bool(re.search(r"&&|\|\||\?", stmt))


@rule(id="17009", description="Same private helper line in many tests", category=CATEGORY)
def same_helper_line_in_many_tests(commits: CommitsDict, config) -> RuleResult:
    """The same non-trivial statement copied into the helper methods (not @CenterTestCase, not
    public) of at least N test classes (17009, default 3) -- e.g. the driver-list line
    `if (dc.getPerson() != null && !dc.getVehicle().getDriverList().isEmpty()) ...` in 27 tests. It
    should be one utility method: a change to it today means editing every copy.

    Statements are compared exactly (comments removed, whitespace collapsed, literals and identifiers
    kept). Non-trivial: at least 60 characters and either three or more calls or a condition
    (&&, ||, ?:); return/throw/else and bare `if (...)` headers are ignored. One row per statement, at its
    first class, with the number of test classes and their names."""
    result = _result("17009", "Same private helper line in many tests",
                     ["Class", "Method", "Line", "Tests", "Issue", "Location"])
    limit = _threshold(config, "17009", 3)
    where: dict[str, dict[str, tuple]] = defaultdict(dict)
    for f in sorted(_project_files(commits), key=lambda x: x.key):
        if not _is_test(f):
            continue
        ce = f.main_class
        for m in ce.methods:
            if not m.body or m.is_constructor or "public" in m.modifiers or "CenterTestCase" in m.annotations:
                continue
            for stmt, li in _helper_statements(m):
                key = _canon(stmt)
                if _non_trivial(stmt) and ce.class_name not in where[key]:
                    where[key][ce.class_name] = (f, m, li, stmt)
    for stmt, owners in where.items():
        if len(owners) < limit:
            continue
        names = sorted(owners)
        f, m, li, stmt = owners[names[0]]
        others = ", ".join(names[1:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
        result.rows.append([names[0], m.name, snippet(stmt), len(names),
                            f"The same line is copied into helper methods of {len(names)} test classes "
                            f"(also {others}): make it one utility method so a change is made once",
                            location(f, body_line(f, m, li), config)])
    result.rows.sort(key=lambda r: (-r[3], r[0], r[2]))
    if result.rows:
        result.summary = f"{len(result.rows)} statement(s) copied into the helpers of {limit}+ test classes"
    return result
