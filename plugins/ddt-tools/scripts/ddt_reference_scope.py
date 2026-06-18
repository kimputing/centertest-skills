#!/usr/bin/env python3
"""Python mirror of the Java DdtReferenceScopeResolver / DataDrivenHierarchyParser.

Reference-centric model: each reference file lists, by regex, the DC paths that consume it,
under the reserved ``$references`` key of DataDrivenHierarchy.json. A DC's effective scope:

  - local References sheet present  -> used verbatim (the map is ignored for that DC)
  - sheet absent                    -> every reference file whose pattern matches the DC path,
                                       in model order, de-duplicated

Patterns are matched (full match) against forward-slash DC paths and should target the
``*DC.xlsx`` naming. This must stay in lockstep with the Java resolver and the shared fixture
``reference-scope-fixture.json``; run this module directly to self-check against it.
"""
import json
import os
import re
import sys

REFERENCES_KEY = "$references"


def parse_references(hierarchy):
    """Parse the $references map into [(reference_file, [compiled_patterns])]."""
    entries = []
    if not isinstance(hierarchy, dict):
        return entries
    refs = hierarchy.get(REFERENCES_KEY)
    if not isinstance(refs, dict):
        return entries
    for ref_file, patterns in refs.items():
        compiled = [re.compile(p) for p in patterns] if isinstance(patterns, list) else []
        entries.append((ref_file, compiled))
    return entries


def _normalize(path):
    return path.replace("\\", "/").strip()


def resolve(dc_location, local_sheet_references, entries):
    """Return (locations, origin). origin is 'LOCAL_SHEET' or 'REFERENCE_MAP'."""
    if local_sheet_references is not None:
        return list(local_sheet_references), "LOCAL_SHEET"
    matched, seen = [], set()
    dc = _normalize(dc_location)
    for ref_file, patterns in entries:
        for pattern in patterns:
            if pattern.fullmatch(dc):
                key = _normalize(ref_file)
                if key not in seen:
                    seen.add(key)
                    matched.append(ref_file)
                break
    return matched, "REFERENCE_MAP"


def find_scope_collisions(scope_locations, sheet_names_by_location):
    """Return sheet names (lower-cased) owned by >1 file in the scope (collision-free => [])."""
    counts, collisions = {}, []
    for location in scope_locations or []:
        for sheet in sheet_names_by_location.get(location, []) or []:
            key = sheet.lower()
            counts[key] = counts.get(key, 0) + 1
            if counts[key] == 2:
                collisions.append(key)
    return collisions


def _self_test():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference-scope-fixture.json")
    with open(path) as fh:
        fixture = json.load(fh)
    entries = parse_references(fixture["model"])
    failures = 0
    for case in fixture["cases"]:
        locations, origin = resolve(case["dcLocation"], case.get("localSheetReferences"), entries)
        exp = case["expect"]
        if origin != exp["origin"] or locations != exp["locations"]:
            failures += 1
            print(f"FAIL resolve: {case['name']}\n  got ({origin}, {locations})\n  exp ({exp['origin']}, {exp['locations']})")
    for case in fixture["collisionCases"]:
        got = find_scope_collisions(case["scopeLocations"], case["sheetNamesByLocation"])
        if got != case["expectCollisions"]:
            failures += 1
            print(f"FAIL collision: {case['name']}\n  got {got}\n  exp {case['expectCollisions']}")
    total = len(fixture["cases"]) + len(fixture["collisionCases"])
    if failures:
        print(f"\n{failures}/{total} fixture checks FAILED")
        sys.exit(1)
    print(f"All {total} fixture checks passed (Python mirror matches the shared fixture).")


if __name__ == "__main__":
    _self_test()
