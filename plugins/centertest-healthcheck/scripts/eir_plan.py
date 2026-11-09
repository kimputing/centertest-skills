"""
--plan FILE: one rerun suite for a release's change list.

The file lists what the release changes, one item per line ("#" starts a comment):
    coverage: Sewer Back-Up          a coverage, term value or any data value (whole-cell regex, as --uses)
    value: ON|Ontario                the same, for a state, a product, a class code ...
    page: SubmissionWizardPage       a screen: regex over the generated page classes (as --touches);
                                     a wizard step is Page.getStep (SubmissionWizardPage.getPolicyInfoStep)
    widget: SubmissionWizard-...-X   a widget id, or Page.getX (as --touches)
Each item is answered as --uses or --touches answers it; the scenarios of all items together (resolved
through each answer's suite entries by the vendored suite engine, as CenterTest would run them) become
one suite. Items that select nothing are listed: a misspelled coverage must not pass silently.
"""

from __future__ import annotations

import json
import os
import re

_ITEM = re.compile(r"^\s*(coverage|value|page|widget)\s*:\s*(.+?)\s*$", re.I)


def read_plan(path: str) -> tuple[list[tuple[str, str]], list[str]]:
    """([(kind, pattern)], [lines that are not an item])."""
    items, bad = [], []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip() if not raw.lstrip().startswith("#") else ""
            if not line:
                continue
            m = _ITEM.match(line)
            if m:
                items.append((m.group(1).lower(), m.group(2)))
            else:
                bad.append(line)
    return items, bad


def plan_report(repo_dir: str, source_root: str, path: str, cssids_dir: str | None = None) -> dict:
    import suite as suites
    from eir_uses import suites_running, touches_report, uses_report
    items, bad = read_plan(path)
    tests = suites.scan(repo_dir, source_root)
    every, per_item = set(), []
    for kind, pattern in items:
        report = (uses_report(repo_dir, source_root, pattern) if kind in ("coverage", "value")
                  else touches_report(repo_dir, source_root, pattern, cssids_dir))
        doc = {"CenterTestSuites": [{"Name": "item", "List": report.get("entries") or []}]}
        chosen = set(suites.resolve_suite(doc, "item", tests)["scenarios"]) if report.get("entries") else set()
        per_item.append({"kind": kind, "pattern": pattern, "scenarios": len(chosen), "new": len(chosen - every)})
        every |= chosen
    used = [t for t in tests if any(c == t["class"] for c, _m, _code in every)]
    return {"plan": os.path.basename(path), "items": per_item, "not_understood": bad, "scenarios": len(every),
            "of": len(suites.scenarios_of(tests)), "entries": suites.compact(every, used),
            "in_suites": suites_running(repo_dir, tests, every)}


def plan_name(path: str) -> str:
    return "Plan-" + (re.sub(r"[^A-Za-z0-9]+", "", os.path.splitext(os.path.basename(path))[0].title()) or "Release")[:40]


def print_plan(report: dict, name: str, command: str | None) -> None:
    print(f"  RELEASE PLAN {report['plan']}: {report['scenarios']} of {report['of']} scenarios")
    for it in report["items"]:
        mark = "!!" if not it["scenarios"] else "  "
        print(f"  {mark} {it['kind']:<8} {it['pattern'][:60]:<60} {it['scenarios']:>4} scenario(s)"
              + (f", {it['new']} not in an item above" if it["scenarios"] and it["new"] != it["scenarios"] else ""))
    empty = [it for it in report["items"] if not it["scenarios"]]
    if empty:
        print(f"  !! {len(empty)} item(s) select nothing: check the spelling, or no scenario exercises it yet")
    for line in report["not_understood"]:
        print(f"  ?? not an item (coverage:/value:/page:/widget:): {line}")
    if not report["entries"]:
        return
    print("\n  As a suite for CenterTestSuiteList.json:\n")
    print("\n".join("    " + l for l in json.dumps({"Name": name, "List": report["entries"]}, indent=2).splitlines()))
    if command:
        print(f"\n  Then: {command}")
