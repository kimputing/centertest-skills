#!/usr/bin/env python3
"""
Detect a CenterTest project's conventions -> project JSON for the recording-to-test skill.

Usage:
  python3 scan_project.py [<project root>] [--cssids <resources dir>] [--out project.json]

Read-only: nothing in the project or in ~/.centertest/ is written; cssids taken from the
generated jar are extracted to a new temp directory. Every fact is
{"value": ..., "evidence": "..."} or {"value": null, "reason": "..."}.
Credentials are never read: only the property keys and file names below.
"""

import argparse
import collections
import glob
import json
import os
import re
import sys
import tempfile
import zipfile

SKIP_DIRS = {".git", ".gradle", ".idea", "build", "out", "target", "node_modules"}
CENTERS = {"BaseScenarioPC": "pc", "BaseScenarioBC": "bc", "BaseScenarioCC": "cc", "BaseScenarioAB": "ab"}
CENTERTEST_CLASS = re.compile(r"^\s*@CenterTest\s*$", re.M)
TEST_PREFIX = re.compile(r"^([A-Z][A-Z0-9]*)_")


def fact(value, evidence: str) -> dict:
    return {"value": value, "evidence": evidence}


def missing(reason: str) -> dict:
    return {"value": None, "reason": reason}


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def properties(path: str) -> dict:
    """'key=value' lines of a .properties file (enough for the plain keys read here)."""
    values = {}
    for line in read(path).splitlines():
        line = line.strip()
        if line and line[0] not in "#!" and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def first_property(paths, names, key):
    """(value, path) from the first file whose name is in `names` and that sets `key`."""
    for path in paths:
        if os.path.basename(path) in names:
            value = properties(path).get(key)
            if value:
                return value, path
    return None, None


def index(root: str):
    """Every .java source (path -> text) and the paths of the .properties files."""
    java, props = {}, []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = os.path.join(current, name)
            if name.endswith(".java"):
                java[path] = read(path)
            elif name.endswith(".properties"):
                props.append(path)
    return java, props


def files_under(java: dict, directory: str) -> dict:
    prefix = directory + os.sep
    return {path: text for path, text in java.items() if path.startswith(prefix)}


def client_package(root, props):
    value, path = first_property(props, {"customer.centertest.properties"}, "centertest.client.package")
    if value:
        return fact(value, rel(root, path))
    return missing("no centertest.client.package in customer.centertest.properties")


def tests_root(root, java):
    roots = collections.Counter()
    for path, text in java.items():
        source = CENTERTEST_CLASS.search(text) and re.search(r"^(.*?/src/[^/]+/java)/", path.replace(os.sep, "/"))
        if source:
            roots[source.group(1)] += 1
    if not roots:
        return missing("no @CenterTest classes found")
    top, count = roots.most_common(1)[0]
    return fact(rel(root, top), f"{count} @CenterTest classes")


def test_layout(tests_dir, tests):
    folders, prefixes = collections.Counter(), collections.defaultdict(collections.Counter)
    for path in tests:
        parts = os.path.relpath(os.path.dirname(path), tests_dir).split(os.sep)
        folders["/".join(parts)] += 1
        prefix = TEST_PREFIX.match(os.path.basename(path))
        if prefix and len(parts) >= 2:
            prefixes[parts[1]][prefix.group(1)] += 1
    if not folders:
        return missing(f"no @CenterTest classes under {tests_dir}")
    value = {"folders": dict(folders.most_common()),
             "lobPrefixes": {lob: counts.most_common(1)[0][0] for lob, counts in sorted(prefixes.items())}}
    return fact(value, f"{sum(folders.values())} tests")


def test_style(tests):
    methods, roles, counts = collections.Counter(), collections.Counter(), collections.Counter()
    for text in tests.values():
        methods.update(re.findall(r"public void (\w+)\(\s*ScenarioContext", text))
        roles.update(re.findall(r'getInvocationContext\("([^"]+)"\)', text))
        counts["restartPoints"] += "enum RestartPoints" in text
        counts["testCaseId"] += bool(re.search(r"@CenterTestCase\([^)]*testCaseId", text))
        counts["emptyCenterTestCase"] += "@CenterTestCase()" in text
        counts["dataDriven"] += "@DataDriven" in text
    value = {"tests": len(tests), "methods": dict(methods.most_common()), "roles": dict(roles.most_common())}
    value.update({key: counts[key] for key in ("restartPoints", "testCaseId", "emptyCenterTestCase", "dataDriven")})
    return fact(value, f"{len(tests)} tests")


def step_conventions(root, steps, reusable_dir):
    combos = collections.Counter()
    for text in steps.values():
        base = re.search(r"\bextends\s+(BaseScenario\w*)", text)
        if base:
            tags = re.search(r'@FlowTags\("([^"]+)"\)', text)
            combos[(base.group(1), tags.group(1) if tags else None)] += 1
    if not combos:
        return missing(f"no step classes extending BaseScenario* under {rel(root, reusable_dir)}")
    bases = {}
    for (base, tags), count in combos.most_common():
        entry = bases.setdefault(base, {"base": base, "center": CENTERS.get(base), "flowTags": tags, "count": 0})
        entry["count"] += count
    return fact({"root": rel(root, reusable_dir), "bases": list(bases.values())},
                f"{sum(combos.values())} step classes")


def scan(root, cssids=None, gradle_home=None, m2_home=None) -> dict:
    root = os.path.abspath(root)
    java, props = index(root)
    result = {"root": root, "clientPackage": client_package(root, props), "testsRoot": tests_root(root, java)}
    package, source = result["clientPackage"]["value"], result["testsRoot"]["value"]
    if package and source:
        base = os.path.join(root, *source.split("/"), *package.split("."))
        tests_dir, reusable_dir = os.path.join(base, "tests"), os.path.join(base, "reusable")
        tests = {p: t for p, t in files_under(java, tests_dir).items() if CENTERTEST_CLASS.search(t)}
        steps = files_under(java, reusable_dir)
        result.update(testLayout=test_layout(tests_dir, tests), testStyle=test_style(tests),
                      steps=step_conventions(root, steps, reusable_dir))
    else:
        for key in ("testLayout", "testStyle", "steps"):
            result[key] = missing("needs clientPackage and testsRoot")
    return result
