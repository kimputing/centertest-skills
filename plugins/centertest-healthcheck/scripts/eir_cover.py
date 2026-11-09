"""
--cover: the fewest scenarios that keep the breadth of the full regression.

A breadth item is something the full run exercises: every test method (each flow once), every product
coverage the scenarios select (per line, from the generated product model, as eir_products counts
them) and every jurisdiction each line's scenarios run in (eir_states). Only scenarios a test runs
count: an enabled DataCombination row of a test method's @DataDriven datasource. A greedy set cover
picks, again and again, the scenario that adds the most items not covered yet (ties: the first in
name order), until every item is covered. The picks come back as suite entries (vendored
suite-builder) and one command -- a smoke or pre-release run that still touches every flow, coverage
and jurisdiction.

With a suite (--cover Smoke): what that suite leaves out of the breadth, and the fewest scenarios to
add to close it. --of Regression measures against another suite instead of everything that runs
(a PolicyCenter smoke suite against the PolicyCenter regression, not against BillingCenter's flows).
"""

from __future__ import annotations

import json
import os


def breadth_items(repo_dir: str, source_root: str, cssids_dir: str | None):
    """(scenarios, items): scenarios = {(class, method, code): set of items it covers}, items = every
    ("test", "Class.method"), ("coverage", line, name) and ("jurisdiction", line, state) the full run reaches."""
    import suite as suites
    from eir_uses import rows_by_value
    tests = suites.scan(repo_dir, source_root)
    datasource = {(t["class"], m["name"]): m["datasource"] for t in tests for m in t["methods"]}
    scenarios = {s: {("test", f"{s[0]}.{s[1]}")} for s in suites.scenarios_of(tests) if s[2]}
    row_items: dict[tuple, set] = {}
    from eir_products import structure_files
    by_value = rows_by_value(repo_dir, coverage_only=True) if structure_files(cssids_dir) else {}
    for path in structure_files(cssids_dir):
        line = os.path.basename(path)[:-len("_coverage_structure.json")]
        try:
            with open(path, encoding="utf-8") as fh:
                coverages = json.load(fh)
        except (OSError, ValueError):
            continue
        for c in coverages if isinstance(coverages, list) else []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            for k in ("name", "codeIdentifier"):
                for row in by_value.get(str(c.get(k) or "").strip().lower(), ()):
                    row_items.setdefault(row, set()).add(("coverage", line, c["name"].strip()))
    from eir_states import rows_by_state
    for (line, state), rows in (rows_by_state(repo_dir, cssids_dir) or {}).items():
        for row in rows:
            row_items.setdefault(row, set()).add(("jurisdiction", line, state))
    for s, items in scenarios.items():
        items |= row_items.get(("dc", datasource.get((s[0], s[1])), s[2].lower()), set())
    every = set().union(*scenarios.values()) if scenarios else set()
    return scenarios, every


def _suite_scenarios(repo_dir: str, source_root: str, name: str) -> set | None:
    """The scenarios a suite of CenterTestSuiteList.json runs (as CenterTest resolves it); None if no such suite."""
    import suite as suites
    path = suites.find_suite_file(repo_dir)
    if not os.path.isfile(path):
        return None
    doc, _text = suites.load_suites(path)
    if not any(str(s.get("Name", "")).lower() == name.lower() for s in doc["CenterTestSuites"]):
        return None
    name = next(str(s["Name"]) for s in doc["CenterTestSuites"] if str(s.get("Name", "")).lower() == name.lower())
    return set(suites.resolve_suite(doc, name, suites.scan(repo_dir, source_root))["scenarios"])


def cover_report(repo_dir: str, source_root: str, cssids_dir: str | None, suite: str | None = None,
                 of: str | None = None) -> dict:
    """The greedy cover: picks in order with what each adds, as suite entries. With `suite`: what it misses
    of the breadth of `of` (default: every scenario that runs) and the fewest scenarios of `of` to add."""
    import suite as suites
    scenarios, every = breadth_items(repo_dir, source_root, cssids_dir)
    out = {}
    for label, name in (("suite", suite), ("of", of)):
        if name:
            found = _suite_scenarios(repo_dir, source_root, name)
            if found is None:
                return {"error": f"no suite named {name!r} in CenterTestSuiteList.json"}
            out[label] = found
    every_scenario = scenarios
    if "of" in out:
        scenarios = {s: items for s, items in scenarios.items() if s in out["of"]}
        every = set().union(*scenarios.values()) if scenarios else set()
    left, picks, misses = set(every), [], None
    if "suite" in out:
        # what the suite's own scenarios reach counts, in the reference suite or not
        has = out["suite"] & set(every_scenario)
        left -= set().union(*(every_scenario[s] for s in has)) if has else set()
        misses = sorted(left)
        scenarios = {s: items for s, items in scenarios.items() if s not in has}
    order = sorted(scenarios)
    while left:
        best = max(order, key=lambda s: len(scenarios[s] & left))  # max() keeps the first of equals
        gain = scenarios[best] & left
        if not gain:
            break
        picks.append({"scenario": list(best), "adds": sorted(gain)})
        left -= gain
    selected = {tuple(p["scenario"]) for p in picks}
    tests = [t for t in suites.scan(repo_dir, source_root) if any(c == t["class"] for c, _m, _code in selected)]
    kinds = ("test", "coverage", "jurisdiction")
    report = {"scenarios": len(selected), "of": len(scenarios),
              "items": {k: sum(1 for i in every if i[0] == k) for k in kinds},
              "picks": picks, "entries": suites.compact(selected, tests), "measured_against": of}
    if misses is not None:
        report.update(suite=suite, suite_scenarios=len(out["suite"]), misses=misses,
                      missing={k: sum(1 for i in misses if i[0] == k) for k in kinds})
    return report


def _label(item: tuple) -> str:
    return item[1] if item[0] == "test" else f"{item[1]} {item[2]}"


def print_cover(report: dict, name: str, command: str | None) -> None:
    if report.get("error"):
        print(f"  {report['error']}")
        return
    items = report["items"]
    against = f"suite {report['measured_against']}" if report.get("measured_against") else "the full run"
    breadth = (f"{items['test']} test methods, {items['coverage']} product coverages, "
               f"{items['jurisdiction']} line/jurisdiction pairs")
    if "misses" in report:
        miss = report["missing"]
        print(f"  {report['suite']} ({report['suite_scenarios']} scenarios) against {against} ({breadth}):")
        if not report["misses"]:
            print("  it misses nothing: every flow, coverage and line/jurisdiction is in it.")
            return
        print(f"  MISSES {miss['test']} test methods, {miss['coverage']} product coverages, "
              f"{miss['jurisdiction']} line/jurisdiction pairs")
        for kind in ("test", "coverage", "jurisdiction"):
            names = [_label(i) for i in report["misses"] if i[0] == kind]
            if names:
                print(f"    {kind}: {', '.join(names[:10])}{', ...' if len(names) > 10 else ''}")
        print(f"\n  Adding {report['scenarios']} scenario(s) closes it:")
    else:
        print(f"  COVERING SUITE: {report['scenarios']} of {report['of']} scenarios keep the breadth of {against}: {breadth}")
    for p in report["picks"][:15]:
        cls, method, code = p["scenario"]
        kinds = {k: [_label(i) for i in p["adds"] if i[0] == k] for k in ("test", "coverage", "jurisdiction")}
        adds = "; ".join(f"{len(v)} {k}{'s' if len(v) != 1 else ''}" + (f" ({', '.join(v[:3])}{', ...' if len(v) > 3 else ''})"
                                                                         if k != "test" else "")
                         for k, v in kinds.items() if v)
        print(f"    {cls} {code}: {adds}")
    if len(report["picks"]) > 15:
        print(f"    ... {len(report['picks']) - 15} more, each adding less")
    print("\n  As a suite for CenterTestSuiteList.json" + (" (or add these entries to it)" if "misses" in report else "")
          + ":\n")
    print("\n".join("    " + line for line in json.dumps({"Name": name, "List": report["entries"]}, indent=2).splitlines()))
    if command:
        print(f"\n  Then: {command}")


def suite_breadth(repo_dir: str, source_root: str, cssids_dir: str | None) -> list[dict] | None:
    """[{suite, scenarios, test, coverage, jurisdiction}] for every suite of CenterTestSuiteList.json, plus a
    first row "(full run)": how much of the full run's breadth each suite reaches. None without a suite file."""
    import suite as suites
    path = suites.find_suite_file(repo_dir)
    if not os.path.isfile(path):
        return None
    try:
        doc, _text = suites.load_suites(path)
    except (OSError, ValueError):
        return None
    scenarios, every = breadth_items(repo_dir, source_root, cssids_dir)
    tests = suites.scan(repo_dir, source_root)
    kinds = ("test", "coverage", "jurisdiction")

    def row(name, chosen):
        reached = set().union(*(scenarios[s] for s in chosen)) if chosen else set()
        return dict({"suite": name, "scenarios": len(chosen)}, **{k: sum(1 for i in reached if i[0] == k) for k in kinds})

    rows, union = [row("(full run)", set(scenarios))], set()
    for s in doc["CenterTestSuites"]:
        name = str(s.get("Name", ""))
        try:
            chosen = set(suites.resolve_suite(doc, name, tests)["scenarios"]) & set(scenarios)
        except Exception:  # a broken suite (rule 14005 names it) reaches nothing
            chosen = set()
        union |= chosen
        rows.append(row(name, chosen))
    # what the full run reaches that no suite does: it runs only when someone runs everything
    reached = set().union(*(scenarios[s] for s in union)) if union else set()
    rows[0]["no_suite"] = sorted(every - reached)
    rows[0]["any_suite"] = {k: sum(1 for i in reached if i[0] == k) for k in kinds}
    return rows


def print_suite_breadth(rows: list[dict]) -> None:
    full = rows[0]
    print(f"  SUITES: share of the full run each reaches ({full['scenarios']} scenarios, {full['test']} test methods, "
          f"{full['coverage']} coverages, {full['jurisdiction']} line/jurisdiction pairs)")
    pct = lambda r, k: f"{r[k] * 100 // full[k]:>3}%" if full[k] else "   -"
    ranked = sorted(rows[1:], key=lambda r: (-r["test"], -r["coverage"], r["suite"].lower()))
    running = [r for r in ranked if r["scenarios"]]
    for r in running[:10]:
        print(f"  {r['suite'][:34]:<34} {r['scenarios']:>5} scen.  flows {pct(r, 'test')}  coverages {pct(r, 'coverage')}"
              f"  jurisdictions {pct(r, 'jurisdiction')}")
    if len(running) > 10:
        print(f"  ... {len(running) - 10} more (Excel sheet \"Suites\")")
    idle = [r["suite"] for r in ranked if not r["scenarios"]]
    if idle:
        print(f"  Run nothing ({len(idle)}): {', '.join(idle)}")
    missing = full.get("no_suite") or []
    if missing:
        flows = [i[1] for i in missing if i[0] == "test"]
        others = len(missing) - len(flows)
        print(f"  In no suite: {len(flows)} flow(s)" + (f" ({', '.join(flows[:6])}{', ...' if len(flows) > 6 else ''})" if flows else "")
              + (f", {others} coverage or line/jurisdiction item(s)" if others else "")
              + " - they run only in a full run")


def suite_breadth_rows(rows: list[dict]) -> list[list]:
    """Excel: suite, scenarios, then per kind reached / full run and the share."""
    full = rows[0]
    out = []
    for r in rows:
        line = [r["suite"], r["scenarios"]]
        for k in ("test", "coverage", "jurisdiction"):
            line += [r[k], round(r[k] / full[k], 3) if full[k] else None]
        out.append(line)
    return out
