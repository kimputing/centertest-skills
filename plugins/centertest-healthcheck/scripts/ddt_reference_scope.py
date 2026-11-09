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


RELATIONSHIPS_KEY = "$relationships"
IDENTIFIERS_KEY = "$identifiers"
# A leading ``token.`` where token is [A-Za-z0-9_]+ is the identifier prefix (mirror of Java RelationshipCodes).
_IDENTIFIER_PREFIX = re.compile(r"^([A-Za-z0-9_]+)\..+$")


def parse_relationships(hierarchy):
    """Parse $relationships + $identifiers (mirror of Java DataDrivenHierarchyParser.parseRelationships).

    Returns (by_relationship, identifiers):
      by_relationship: {relationship_lower: {IDENTIFIER_UPPER: target_dc_file}}
      identifiers:     [(IDENTIFIER_UPPER, [compiled_patterns])]
    """
    by_relationship, identifiers = {}, []
    if not isinstance(hierarchy, dict):
        return by_relationship, identifiers
    ids = hierarchy.get(IDENTIFIERS_KEY)
    if isinstance(ids, dict):
        for ident, patterns in ids.items():
            compiled = [re.compile(p) for p in patterns] if isinstance(patterns, list) else []
            identifiers.append((ident.upper(), compiled))
    rels = hierarchy.get(RELATIONSHIPS_KEY)
    if isinstance(rels, dict):
        for rel, targets in rels.items():
            target_map = {}
            if isinstance(targets, dict):
                for ident, target in targets.items():
                    target_map[ident.upper()] = target
            by_relationship[rel.lower()] = target_map
    return by_relationship, identifiers


def default_identifier_for(dc_path, identifiers):
    """Default identifier (UPPER) for a DC path, '' if none. Raises ValueError on >1 distinct match."""
    normalized = _normalize(dc_path)
    match = ""
    for ident, patterns in identifiers:
        for pattern in patterns:
            if pattern.fullmatch(normalized):
                if match and match != ident:
                    raise ValueError(
                        f"DC path '{dc_path}' matches multiple identifiers: {match} and {ident}")
                match = ident
    return match


def identifier_of(raw_code, default_identifier):
    """Identifier (UPPER) for a relationship code: the ``token.`` prefix, else the default."""
    if raw_code is not None:
        m = _IDENTIFIER_PREFIX.match(raw_code.strip())
        if m:
            return m.group(1).upper()
    return (default_identifier or "").strip().upper()


def strip_identifier(raw_code):
    """The bare code with any ``identifier.`` prefix removed."""
    if raw_code is None:
        return None
    trimmed = raw_code.strip()
    m = _IDENTIFIER_PREFIX.match(trimmed)
    if m:
        return trimmed[len(m.group(1)) + 1:].strip()
    return trimmed


def _relationship_self_test():
    """Inline checks for the relationship primitives (no fixture coupling)."""
    failures = 0
    checks = [
        (identifier_of("CA.FourDoorSedan", "WC"), "CA"),
        (identifier_of("ExcludeMedical_MultiLocation", "wc"), "WC"),
        (identifier_of("Default", ""), ""),
        (strip_identifier("CA.FourDoorSedan"), "FourDoorSedan"),
        (strip_identifier("ExcludeMedical_MultiLocation"), "ExcludeMedical_MultiLocation"),
    ]
    for got, exp in checks:
        if got != exp:
            failures += 1
            print(f"FAIL relationship primitive: got {got!r} exp {exp!r}")
    by_rel, idents = parse_relationships({
        "$identifiers": {"WC": ["testdata/workerscomp/.*"], "CA": ["testdata/commercialauto/.*"]},
        "$relationships": {"Submission": {"WC": "testdata/workerscomp/WC_SubmissionDC.xlsx"}},
    })
    if default_identifier_for("testdata/workerscomp/WC_ClaimDC.xlsx", idents) != "WC":
        failures += 1
        print("FAIL default_identifier_for WC")
    if by_rel.get("submission", {}).get("WC") != "testdata/workerscomp/WC_SubmissionDC.xlsx":
        failures += 1
        print("FAIL parse_relationships target")
    return failures


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
    failures += _relationship_self_test()
    total = len(fixture["cases"]) + len(fixture["collisionCases"])
    if failures:
        print(f"\n{failures} check(s) FAILED ({total} fixture cases + relationship primitives)")
        sys.exit(1)
    print(f"All {total} fixture checks + relationship primitives passed (Python mirror matches Java).")


if __name__ == "__main__":
    _self_test()
