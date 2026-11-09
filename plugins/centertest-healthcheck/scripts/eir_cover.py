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


def cover_report(repo_dir: str, source_root: str, cssids_dir: str | None) -> dict:
    """The greedy cover: picks in order with what each adds, as suite entries."""
    import suite as suites
    scenarios, every = breadth_items(repo_dir, source_root, cssids_dir)
    left, picks = set(every), []
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
    return {"scenarios": len(selected), "of": len(scenarios),
            "items": {k: sum(1 for i in every if i[0] == k) for k in kinds},
            "picks": picks, "entries": suites.compact(selected, tests)}


def _label(item: tuple) -> str:
    return item[1] if item[0] == "test" else f"{item[1]} {item[2]}"


def print_cover(report: dict, name: str, command: str | None) -> None:
    items = report["items"]
    print(f"  COVERING SUITE: {report['scenarios']} of {report['of']} scenarios keep the full run's breadth: "
          f"{items['test']} test methods, {items['coverage']} product coverages, "
          f"{items['jurisdiction']} line/jurisdiction pairs")
    for p in report["picks"][:15]:
        cls, method, code = p["scenario"]
        kinds = {k: [_label(i) for i in p["adds"] if i[0] == k] for k in ("test", "coverage", "jurisdiction")}
        adds = "; ".join(f"{len(v)} {k}{'s' if len(v) != 1 else ''}" + (f" ({', '.join(v[:3])}{', ...' if len(v) > 3 else ''})"
                                                                         if k != "test" else "")
                         for k, v in kinds.items() if v)
        print(f"    {cls} {code}: {adds}")
    if len(report["picks"]) > 15:
        print(f"    ... {len(report['picks']) - 15} more, each adding less")
    print("\n  As a suite for CenterTestSuiteList.json:\n")
    print("\n".join("    " + line for line in json.dumps({"Name": name, "List": report["entries"]}, indent=2).splitlines()))
    if command:
        print(f"\n  Then: {command}")
