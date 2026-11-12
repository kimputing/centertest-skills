"""
Rules 26001-26004: suite hygiene in CenterTestSuiteList.json.

Suites are read the way CenterTest reads them, through suite.py (a vendored copy of
plugins/suite-builder/scripts/suite.py: each List entry part is a case-insensitive regex on the whole
class, method or code; disabled DataCombination rows are not scenarios). Rule 14005 already reports
entries that run nothing and child suites that do not exist; these rules report what is left:

26001  an entry that repeats another, or selects only scenarios the suite already runs
26002  a "full run" composite suite (RegressionSuite, Nightly, ...) that leaves out tests other suites run
26003  a suite name that does not say what it runs (Regression1/Regression2, or "Regression" on one line of business)
26004  a suite that reaches itself through "Suites"

How CenterTest behaves (centertest-platform, centertest-core, read for these rules):
- TestDataProvider.readFilterList matches a "Suites" child to a suite Name with List.contains -- exact
  case -- and readInnerSuite recurses with no visited set, so A -> B -> A never ends (StackOverflowError).
- TestDataProvider.hasMatch credits a scenario to the FIRST entry of a suite whose pattern matches it
  (findFirst + FilterMatchTracker.recordMatch); FilterEntry.classify compiles "Class" and "Class method"
  as ".* <entry> .*", so they also match the not-yet-expanded "Class method .*" descriptor.
  DataDrivenScenariosExtractor.appendPhantomsForUnmatchedFilters then reports every entry that was never
  credited as a failed (phantom) scenario.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eir_models import CommitsDict, RuleResult
from eir_rules import rule

CATEGORY = "Suites"

# Words that name a whole run, and words that add nothing to such a name.
_FULL_RUN = {"regression", "full", "all", "nightly", "complete", "everything", "entire"}
_FILLER = {"suite", "suites", "test", "tests", "run", "runs", "set", "pack"}
_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_NUMBERED = re.compile(r"(.*?[A-Za-z])[\s_\-]*(\d+)")
_LOB = re.compile(r"([A-Za-z]{2,})_")


# ---------------------------------------------------------------------------
# Loading and locating
# ---------------------------------------------------------------------------

class _Suites:
    """The suite file, the project's tests and where each suite and entry is written."""

    def __init__(self, config):
        import suite as suites
        self.engine = suites
        self.config = config
        self.repo = config.repository_dir
        self.path = suites.find_suite_file(self.repo)
        self.ok = os.path.isfile(self.path)
        self.doc, self.text, self.error = {"CenterTestSuites": []}, "", None
        if self.ok:
            try:
                self.doc, self.text = suites.load_suites(self.path)
            except (OSError, ValueError) as e:
                self.ok, self.error = False, f"Cannot read {os.path.relpath(self.path, self.repo)}: {e}"
        self.list = [s for s in self.doc.get("CenterTestSuites", []) if isinstance(s, dict)]
        self.rel = os.path.relpath(self.path, self.repo).replace("\\", "/") if self.repo else self.path
        self._tests = None
        self._starts = self._suite_starts()

    @property
    def tests(self):
        if self._tests is None:
            self._tests = self.engine.scan(self.repo, getattr(self.config, "source_root", "src/main/java") or "src/main/java")
        return self._tests

    def _suite_starts(self) -> list[int]:
        """Offset of each suite's "Name" in the file, in suite order (-1 when not found)."""
        found = []
        for m in re.finditer(r'"Name"\s*:\s*("(?:[^"\\]|\\.)*")', self.text):
            try:
                found.append((json.loads(m.group(1)), m.start()))
            except ValueError:
                continue
        out, cursor = [], 0
        for s in self.list:
            name = str(s.get("Name", ""))
            hit = next((i for i in range(cursor, len(found)) if found[i][0] == name), None)
            if hit is None:
                out.append(-1)
            else:
                out.append(found[hit][1])
                cursor = hit + 1
        return out

    def line(self, offset: int) -> int:
        return self.text.count("\n", 0, offset) + 1 if offset >= 0 else 1

    def location(self, line: int) -> str:
        return f"{self.rel}:{line or 1}"

    def suite_line(self, index: int) -> int:
        return self.line(self._starts[index])

    def entry_lines(self, index: int, key: str = "List") -> list[int]:
        """Line of each value of suite `index`'s `key` array, found in order (a repeated entry gets
        its own line, not the first copy's)."""
        start = self._starts[index]
        values = self.list[index].get(key, []) or []
        if start < 0:
            return [1] * len(values)
        later = [o for o in self._starts if o > start]
        end = min(later) if later else len(self.text)
        k = re.compile(r'"%s"\s*:\s*\[' % re.escape(key)).search(self.text, start, end)
        cursor = k.end() if k else start
        lines = []
        for value in values:
            i = self.text.find(json.dumps(str(value), ensure_ascii=False), cursor, end)
            if i < 0:
                lines.append(self.line(start))
            else:
                lines.append(self.line(i))
                cursor = i + 1
        return lines

    def by_exact_name(self) -> dict[str, list[int]]:
        """{Name: [suite indexes]}: CenterTest finds a child suite by its exact Name."""
        out: dict[str, list[int]] = {}
        for i, s in enumerate(self.list):
            out.setdefault(str(s.get("Name", "")), []).append(i)
        return out


def _result(rule_id: str, description: str, headers: list[str]) -> RuleResult:
    return RuleResult(rule_id=rule_id, description=description, category=CATEGORY, headers=headers)


def _tokens(name: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(name)]


def _is_full_run_name(name: str) -> bool:
    """RegressionSuite, FullRegression, Nightly, AllTests: only whole-run words (no qualifier such as
    PC_, Smoke or a number, which would make the suite a deliberate part)."""
    tokens = _tokens(name)
    return bool(tokens) and any(t in _FULL_RUN for t in tokens) and all(t in _FULL_RUN or t in _FILLER for t in tokens)


def _classes(scenarios) -> list[str]:
    return sorted({c for c, _m, _code in scenarios})


def _short_list(items: list[str], limit: int = 8) -> str:
    return ", ".join(items[:limit]) + (f" +{len(items) - limit} more" if len(items) > limit else "")


# ---------------------------------------------------------------------------
# 26001
# ---------------------------------------------------------------------------

@rule(id="26001", description="Suite entry repeated or already covered", category=CATEGORY)
def suite_entry_repeated_or_covered(commits: CommitsDict, config) -> RuleResult:
    """A List entry that repeats another entry of the same suite (compared case-insensitively, as
    CenterTest compares), or whose scenarios are all selected by another entry, by a Packages pattern
    of the suite or by one of its child suites.

    Heuristic: entries resolve to (class, method, code) scenarios with suite.resolve_entry (enabled rows
    only); entry i is reported when its set is a subset of entry j's, and for equal sets only the later
    entry is reported. Entries that resolve to nothing are 14005's. The Issue says when CenterTest will
    also report the entry as a failed scenario: an entry credited to nobody (an earlier entry matches all
    of its scenarios, and the not-yet-expanded "Class method .*" descriptor too) becomes a phantom failure.
    """
    result = _result("26001", "Suite entry repeated or already covered", ["Suite", "Entry", "Issue", "Location"])
    s = _Suites(config)
    if s.error:
        result.error = s.error
    if not s.ok:
        return result
    eng = s.engine
    scenarios = eng.scenarios_of(s.tests)
    by_class = {t["class"]: t["package"] for t in s.tests}
    names = s.by_exact_name()
    for si, suite in enumerate(s.list):
        name = str(suite.get("Name", ""))
        entries = [str(e) for e in (suite.get("List", []) or [])]
        if not entries:
            continue
        lines = s.entry_lines(si)
        resolved = [set(eng.resolve_entry(e, scenarios)) for e in entries]
        # what the suite runs besides its List: Packages patterns and child suites
        others = []
        for pattern in suite.get("Packages", []) or []:
            hit = {sc for sc in scenarios
                   if eng._full(pattern, by_class.get(sc[0], "")) or eng._full(pattern, f"{by_class.get(sc[0], '')}.{sc[0]}")}
            others.append((f"package pattern '{pattern}'", hit))
        for child in suite.get("Suites", []) or []:
            if str(child) in names and str(child) != name:
                others.append((f"child suite '{child}'", set(eng.resolve_suite(s.doc, str(child), s.tests)["scenarios"])))
        for i, entry in enumerate(entries):
            mine = resolved[i]
            if not mine:
                continue  # runs nothing: rule 14005
            norm = " ".join(entry.split()).lower()
            issue = None
            for j in range(i):
                if " ".join(entries[j].split()).lower() == norm:
                    issue = (f"repeats entry '{entries[j]}' (line {lines[j]}); CenterTest credits each scenario to the "
                             f"first entry that matches it, so this copy is reported as a failed scenario")
                    break
            if issue is None:
                for j, theirs in enumerate(resolved):
                    if j == i or not theirs or not mine <= theirs or (mine == theirs and j > i):
                        continue
                    if j < i and (len(entries[j].split()) < 3 or len(entry.split()) >= 3):
                        issue = (f"selects only scenarios entry '{entries[j]}' (line {lines[j]}) already selects; CenterTest "
                                 f"credits each scenario to the first matching entry, so this one is reported as a failed scenario")
                    else:
                        issue = f"selects only scenarios entry '{entries[j]}' (line {lines[j]}) also selects: it adds nothing to the suite"
                    break
            if issue is None:
                for label, theirs in others:
                    if mine <= theirs:
                        issue = f"every scenario it selects already runs through {label} of this suite: it adds nothing"
                        break
            if issue:
                result.rows.append([name, entry, issue, s.location(lines[i])])
    return result


# ---------------------------------------------------------------------------
# 26002
# ---------------------------------------------------------------------------

@rule(id="26002", description="Aggregate suite misses sibling suites", category=CATEGORY)
def aggregate_suite_misses_siblings(commits: CommitsDict, config) -> RuleResult:
    """A composite suite (one with "Suites") named as the whole run -- RegressionSuite, FullRegression,
    Nightly, AllTests: every word of the name is a whole-run word or filler, so PC_Regression or
    Smoke_All are not -- that does not run scenarios another suite runs.

    One row per other suite with scenarios the aggregate leaves out, listing the test classes. Suites
    the aggregate reaches, and suites that reach the aggregate, are not compared. A suite whose missed
    scenarios are all listed under another reported suite is folded into it (the suite missed most
    completely wins a tie), so Regression3 is not repeated when Renewal already names its tests.
    """
    result = _result("26002", "Aggregate suite misses sibling suites",
                     ["Suite", "Missed suite", "Missed tests", "Issue", "Location"])
    s = _Suites(config)
    if s.error:
        result.error = s.error
    if not s.ok:
        return result
    eng = s.engine
    names = [str(x.get("Name", "")) for x in s.list]
    resolved = {}

    def scen(name):
        if name.lower() not in resolved:
            resolved[name.lower()] = set(eng.resolve_suite(s.doc, name, s.tests)["scenarios"])
        return resolved[name.lower()]

    def reach(name, seen=None):
        """Lower-cased names of the suites `name` includes, directly or through children."""
        seen = set() if seen is None else seen
        for x in s.list:
            if str(x.get("Name", "")).lower() != name.lower():
                continue
            for child in x.get("Suites", []) or []:
                c = str(child).lower()
                if c not in seen:
                    seen.add(c)
                    reach(str(child), seen)
        return seen

    for ai, agg in enumerate(s.list):
        name = names[ai]
        if not (agg.get("Suites") and _is_full_run_name(name)):
            continue
        mine = scen(name)
        inside = reach(name) | {name.lower()}
        candidates = []
        for oi, other in enumerate(names):
            if other.lower() in inside or name.lower() in reach(other):
                continue
            theirs = scen(other)
            missed = theirs - mine
            if missed:
                candidates.append((oi, other, missed, len(missed) / len(theirs)))
        kept = []
        for oi, other, missed, share in candidates:
            folded = any(o2 != oi and missed <= m2 and (missed != m2 or (s2, -o2) > (share, -oi))
                         for o2, _o, m2, s2 in candidates)
            if not folded:
                kept.append((oi, other, missed, share))
        for oi, other, missed, share in kept:
            classes = _classes(missed)
            partly = {c for c in classes if any(sc[0] == c for sc in mine)}
            shown = [f"{c} (some rows)" if c in partly else c for c in classes]
            whole = "every scenario" if share == 1 else f"{len(missed)} of the {len(scen(other))} scenarios"
            result.rows.append([
                name, other, _short_list(shown),
                f"'{name}' is named as the whole run but leaves out {whole} of suite '{other}' "
                f"({len(classes)} test class{'es' if len(classes) != 1 else ''}): a full run never runs them",
                s.location(s.suite_line(ai)),
            ])
    return result


# ---------------------------------------------------------------------------
# 26003
# ---------------------------------------------------------------------------

@rule(id="26003", description="Suite name that doesn't say what it runs", category=CATEGORY)
def suite_name_says_nothing(commits: CommitsDict, config) -> RuleResult:
    """Suite names a reader cannot map to their content.

    - Numbered: Regression1, Regression2 -- a name of the form <word><number> where at least two
      suites share the word (a sequence, not a version such as Release2024 on its own).
    - Broad but narrow: a name made only of whole-run words (Regression, FullRegression, AllTests) on
      a suite whose test classes (two or more) all carry one line-of-business prefix (HO_, PA_), when
      the project has at least two prefixes -- "Regression" that runs only the HO tests.
    Composite suites are judged by what they resolve to. Low severity: the suite still runs.
    """
    result = _result("26003", "Suite name that doesn't say what it runs", ["Suite", "Runs", "Issue", "Location"])
    s = _Suites(config)
    if s.error:
        result.error = s.error
    if not s.ok:
        return result
    eng = s.engine
    names = [str(x.get("Name", "")) for x in s.list]
    bases: dict[str, set] = {}
    for name in names:
        m = _NUMBERED.fullmatch(name.strip())
        if m:
            bases.setdefault(m.group(1).lower(), set()).add(m.group(2))
    prefixes = {m.group(1).lower() for t in s.tests for m in [_LOB.match(t["class"])] if m}
    for i, name in enumerate(names):
        reasons = []
        m = _NUMBERED.fullmatch(name.strip())
        numbered = bool(m and len(bases.get(m.group(1).lower(), ())) >= 2)
        if numbered:
            reasons.append("a numbered name says nothing about which tests it runs")
        classes = _classes(eng.resolve_suite(s.doc, name, s.tests)["scenarios"])
        tokens = [t for t in _tokens(name) if not t.isdigit()]
        broad = bool(tokens) and any(t in _FULL_RUN for t in tokens) and all(t in _FULL_RUN or t in _FILLER for t in tokens)
        lobs = {mm.group(1).lower() if mm else None for c in classes for mm in [_LOB.match(c)]}
        if broad and len(prefixes) >= 2 and len(classes) >= 2 and len(lobs) == 1 and None not in lobs:
            prefix = _LOB.match(classes[0]).group(1)
            reasons.append(f"the name reads as the whole run, but every test it runs is a {prefix}_ test")
        if reasons:
            runs = _short_list(classes, 6) if classes else "nothing"
            result.rows.append([name, runs, "; ".join(reasons) + ": name it after what it runs",
                                s.location(s.suite_line(i))])
    return result


# ---------------------------------------------------------------------------
# 26004
# ---------------------------------------------------------------------------

@rule(id="26004", description="Suite includes itself", category=CATEGORY)
def suite_includes_itself(commits: CommitsDict, config) -> RuleResult:
    """A suite that reaches itself through "Suites" (A -> A, or A -> B -> A).

    CenterTest follows a child by its exact Name (TestDataProvider.readFilterList: List.contains) and
    recurses without remembering where it has been (readInnerSuite), so a cycle never ends: running any
    suite on it fails with a StackOverflowError before a test starts. Names are therefore compared
    exactly, as CenterTest compares them; one row per cycle (per strongly connected group of suites).
    """
    result = _result("26004", "Suite includes itself", ["Suite", "Cycle", "Issue", "Location"])
    s = _Suites(config)
    if s.error:
        result.error = s.error
    if not s.ok:
        return result
    names = s.by_exact_name()
    order = list(names)
    graph = {n: [] for n in order}
    for i, x in enumerate(s.list):
        n = str(x.get("Name", ""))
        for child in x.get("Suites", []) or []:
            if str(child) in names and str(child) not in graph[n]:
                graph[n].append(str(child))

    # Tarjan's strongly connected components (iterative)
    index, low, stack, on, comps, counter = {}, {}, [], set(), [], [0]
    for root in order:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, pi = work.pop()
            if pi == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                on.add(v)
            recurse = False
            for k in range(pi, len(graph[v])):
                w = graph[v][k]
                if w not in index:
                    work.append((v, k + 1))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                comps.append(comp)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])

    for comp in comps:
        if len(comp) == 1 and comp[0] not in graph[comp[0]]:
            continue
        members = set(comp)
        first = min(comp, key=order.index)
        # shortest way back to `first` inside the group
        paths, queue, cycle = {first: [first]}, [first], None
        while queue and cycle is None:
            v = queue.pop(0)
            for w in graph[v]:
                if w == first:
                    cycle = paths[v] + [first]
                    break
                if w in members and w not in paths:
                    paths[w] = paths[v] + [w]
                    queue.append(w)
        cycle = cycle or [first, first]
        result.rows.append([
            first, " -> ".join(cycle),
            "the suite reaches itself through \"Suites\"; CenterTest follows children without remembering "
            "where it has been, so running it never ends (StackOverflowError) and no test starts",
            s.location(s.suite_line(names[first][0])),
        ])
    result.rows.sort(key=lambda r: int(r[3].rsplit(":", 1)[1]))
    return result
