#!/usr/bin/env python3
"""
Detect a CenterTest project's conventions -> project JSON for the recording-to-test skill.

Usage:
  python3 scan_project.py [<project root>] [--cssids <resources dir>] [--out project.json]

Read-only: nothing in the project or in ~/.centertest/ is written; cssids taken from the
generated jar are extracted once per jar into <system temp>/recording-to-test-cssids/. Every fact is
{"value": ..., "evidence": "..."} or {"value": null, "reason": "..."}.
Credentials are never read: only the property keys and file names below.
"""

import argparse
import collections
import glob
import hashlib
import json
import os
import re
import shutil
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
    """Step base classes per center, with the @FlowTags annotation their steps carry most often
    (as written: OOTB uses both @FlowTags("…") and @FlowTags({"…"})) and how many carry one."""
    bases = {}
    for text in steps.values():
        base = re.search(r"\bextends\s+(BaseScenario\w*)", text)
        if not base:
            continue
        entry = bases.setdefault(base.group(1), {"base": base.group(1), "center": CENTERS.get(base.group(1)),
                                                 "tags": collections.Counter(), "count": 0})
        entry["count"] += 1
        tags = re.search(r"@FlowTags\([^)]*\)", text)
        if tags:
            entry["tags"][tags.group(0)] += 1
    if not bases:
        return missing(f"no step classes extending BaseScenario* under {rel(root, reusable_dir)}")
    found = []
    for entry in sorted(bases.values(), key=lambda e: -e["count"]):
        tags = entry.pop("tags")
        found.append({**entry, "flowTags": tags.most_common(1)[0][0] if tags else None,
                      "withFlowTags": sum(tags.values())})
    return fact({"root": rel(root, reusable_dir), "bases": found}, f"{sum(e['count'] for e in found)} step classes")


FACADE_METHOD = re.compile(r"static\s+(\w+)\s+(\w+)\(([^)]*)\)")
GENERATED_PAGE = re.compile(r"import\s+[\w.]+\.generated\.pages\.[\w.]+?\.(\w+);")


def facades(root, java, steps):
    """Static methods of the facade interfaces under reusable/ that return a step class. A
    context-only one also lists the generated pages its step uses and the titles it waits for."""
    classes = {os.path.splitext(os.path.basename(path))[0]: path for path in java}
    methods = []
    for path, text in sorted(steps.items()):
        interface = re.search(r"\binterface\s+(\w+)", text)
        if not interface:
            continue
        for returns, method, params in FACADE_METHOD.findall(text):
            if returns not in classes:
                continue
            entry = {"facade": interface.group(1), "method": method, "params": " ".join(params.split()),
                     "returns": returns,
                     "contextOnly": bool(re.fullmatch(r"\s*InvocationContext\s+\w+\s*", params))}
            if entry["contextOnly"]:
                step_text = java[classes[returns]]
                entry.update(step=rel(root, classes[returns]),
                             pages=sorted(set(GENERATED_PAGE.findall(step_text))),
                             titles=re.findall(r'waitForPageTitle\("([^"]+)"\)', step_text))
            methods.append(entry)
    if not methods:
        return missing("no facade interfaces with static step methods under reusable/")
    context_only = sum(m["contextOnly"] for m in methods)
    return fact(methods, f"{len(methods)} facade methods, {context_only} context-only")


def exemplars(root, tests, steps, tests_dir, reusable_dir):
    """Per center, a median-sized test that uses an invocation role and a median-sized step class."""
    def center_of(path, directory):
        return os.path.relpath(path, directory).split(os.sep)[0]

    picked = {}
    for center in sorted({center_of(path, tests_dir) for path in tests}):
        test_files = sorted((len(t), p) for p, t in tests.items()
                            if center_of(p, tests_dir) == center and "getInvocationContext" in t)
        step_files = sorted((len(t), p) for p, t in steps.items()
                            if center_of(p, reusable_dir) == center
                            and re.search(r"\bextends\s+BaseScenario", t) and "waitForPageTitle" in t)
        if test_files and step_files:
            picked[center] = {"test": rel(root, test_files[len(test_files) // 2][1]),
                              "step": rel(root, step_files[len(step_files) // 2][1])}
    if not picked:
        return missing("no test and step class pair found for any center")
    return fact(picked, "median-sized test and step class per center")


METHOD = re.compile(r"(?:public|protected|private)\s+(?:(?:static|final|abstract|synchronized)\s+)*"
                    r"(?:[\w<>\[\],.?]+\s+)?(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w.,\s]+)?\{")


def methods_of(text: str) -> list:
    """(name, params, body) for each method and constructor of a class, bodies by brace matching."""
    found = []
    for header in METHOD.finditer(text):
        depth, end = 0, len(text)
        for i in range(header.end() - 1, len(text)):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                end = i
                break
        found.append((header.group(1), " ".join(header.group(2).split()), text[header.end():end]))
    return found


def class_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


RECORDED = re.compile(r"/\*\*(?:(?!\*/).)*\bRecorded\b", re.S)
FOLDER_LIMIT = 8


def folders(root, tests, steps, tests_dir, reusable_dir, facade_names):
    """Per <center>/<lob>/<transaction> folder: its step classes, those generated from a recording
    first (Javadoc says "Recorded"), and its tests with the facade and step calls they make, in order."""
    step_names = {class_name(p) for p, t in steps.items() if re.search(r"\bclass\s", t)}
    calls = re.compile(r"\b(?:(" + "|".join(sorted(facade_names) or ["$^"]) + r")\.(\w+)|new\s+(\w+))\(")
    by_folder = {"tests": collections.defaultdict(list), "steps": collections.defaultdict(list)}
    for path, text in sorted(tests.items()):
        flow = [f"{f}.{m}" if f else f"new {n}" for f, m, n in calls.findall(text) if f or n in step_names]
        source = re.search(r"@DataDriven\([^)]*?datasource\s*=\s*\"([^\"]+)\"", text)
        by_folder["tests"][rel(tests_dir, os.path.dirname(path))].append(
            {"path": rel(root, path), "flow": flow, "restartPoints": "enum RestartPoints" in text,
             "dataDriven": source.group(1) if source else None})
    for path, text in sorted(steps.items()):
        base = re.search(r"\bclass\s+\w+(?:<[^>]*>)?\s+extends\s+(\w+)", text)
        if base and "interface " not in text:
            by_folder["steps"][rel(reusable_dir, os.path.dirname(path))].append(
                {"path": rel(root, path), "extends": base.group(1), "recorded": bool(RECORDED.search(text))})
    value = {kind: {folder: sorted(entries, key=lambda e: not e.get("recorded"))[:FOLDER_LIMIT]
                    for folder, entries in sorted(found.items())}
             for kind, found in by_folder.items()}
    if not value["tests"] and not value["steps"]:
        return missing("no tests or steps in folders")
    return fact(value, "tests and steps per folder; steps recorded from a recording first")


# a base's methods that quote or issue the transaction, by the wizard button or toolbar getter they click
WIZARD_ACTIONS = {"quote": re.compile(r"\.getQuote\(\)"),
                  "issue": re.compile(r"\.get(?:Issue|IssuePolicy|IssueNow|Bind\w*)\(\)")}


def transaction_bases(root, steps):
    """Each abstract Abstract* step base: its wizard-page fields, the methods that quote or issue
    (wizardActions) and, per constructor argument (other than the context), the methods that read it. An argument no method reads, or one
    read only by an optional helper, doesn't stop a new step from extending the base."""
    found = []
    for path, text in sorted(steps.items()):
        declared = re.search(r"\babstract\s+class\s+(Abstract\w+)(?:<[^>]*>)?(?:\s+extends\s+(\w+))?", text)
        if not declared:
            continue
        name, methods = declared.group(1), methods_of(text)
        constructors = []
        for method, params, body in methods:
            if method != name:
                continue
            fields = {param: field for field, param in re.findall(r"this\.(\w+)\s*=\s*(\w+)\s*;", body)}
            uses = {}
            for param in filter(None, (p.strip() for p in params.split(","))):
                kind, arg = param.rsplit(" ", 1)
                if kind.endswith("InvocationContext"):
                    continue
                field = fields.get(arg)
                uses[param] = sorted({m for m, _, b in methods if m != name and field
                                      and re.search(rf"\b{field}\b", b)})
            constructors.append({"params": params, "argUsedBy": uses})
        actions = {stage: sorted({m for m, _, b in methods if m != name and pattern.search(b)})
                   for stage, pattern in WIZARD_ACTIONS.items()}
        found.append({"class": name, "path": rel(root, path), "extends": declared.group(2),
                      "constructors": constructors,
                      "wizardFields": [f"{t} {n}" for t, n in re.findall(
                          r"(?:protected|public)\s+(?:final\s+)?(\w*WizardPage)\s+(\w+)\s*;", text)],
                      "wizardActions": {stage: found_in for stage, found_in in actions.items() if found_in}})
    if not found:
        return missing("no abstract Abstract* step bases under reusable/")
    return fact(found, f"{len(found)} abstract step bases")


TITLE_LITERAL = re.compile(r"(?:Title\w*\(\s*|Title\(\)\s*\.\s*\w+\(\s*)(?:\"([^\"]+)\"|([A-Z][A-Z0-9_]*)\b)")
PAGE_CLASS = re.compile(r"new\s+(\w+)\(\s*getContext\(\)\s*\)")
# a Guidewire widget id written as a literal (or the start of one, joined to more): "SubmissionWizard-…-ClaimsInfo_ICLV-"
ID_LITERAL = re.compile(r"\"([A-Za-z]\w*(?:[-:][\w#\[\]]+){2,}[-:]?)\"")


def screen_helpers(root, steps):
    """The steps root's methods indexed by the screen titles they wait for or compare, and by the
    generated pages they open ('…Page' dropped, so 'SubmissionWizard' is the PCF name a widget id
    starts with), and by the widget ids they write as literals (ids). A blocker screen in a recording
    (UW issues, risk approval, warnings) is looked up here, and a helper written for the same list in
    another wizard is found by its id."""
    titles, pages, ids = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(set)
    for path, text in sorted(steps.items()):
        constants = dict(re.findall(r"static\s+final\s+String\s+(\w+)\s*=\s*\"([^\"]*)\"", text))
        generated = set(GENERATED_PAGE.findall(text))
        owner = class_name(path)
        for method, _, body in methods_of(text):
            if method == owner:
                continue
            ref = f"{owner}.{method}"
            for literal, constant in TITLE_LITERAL.findall(body):
                title = literal or constants.get(constant)
                if title:
                    titles[title].add(ref)
            for page in PAGE_CLASS.findall(body):
                if page in generated:
                    pages[page[:-len("Page")] if page.endswith("Page") else page].add(ref)
            for literal in ID_LITERAL.findall(body):
                ids[literal].add(ref)
    if not titles and not pages and not ids:
        return missing("no step methods wait for a title, open a generated page or use a widget id")
    value = {"titles": {k: sorted(v) for k, v in sorted(titles.items())},
             "pages": {k: sorted(v) for k, v in sorted(pages.items())},
             "ids": {k: sorted(v) for k, v in sorted(ids.items())}}
    return fact(value, f"{len(titles)} titles, {len(pages)} pages, {len(ids)} widget ids")


WIZARD_BUTTON_CALL = re.compile(r"getWizardButtons\(\)\s*\.\s*(get\w+)\(\)")
SET_COVERAGE = re.compile(r"setCoverage\(\s*[^,()]+,\s*[^,()]+,\s*(?:\"([^\"]*)\"|([A-Z][A-Z0-9_]*)\b)")


def idioms(steps):
    """How the steps root writes what the parser would otherwise write its own way: the WizardButtons
    getters it calls (getNextV9 or getNext) and whether coverage amounts are plain (2000000) or formatted
    ($2,000,000), from setCoverage literals and the constants they name."""
    buttons, plain, formatted = collections.Counter(), 0, 0
    for text in steps.values():
        buttons.update(WIZARD_BUTTON_CALL.findall(text))
        constants = dict(re.findall(r"static\s+final\s+String\s+(\w+)\s*=\s*\"([^\"]*)\"", text))
        for literal, constant in SET_COVERAGE.findall(text):
            amount = literal or constants.get(constant) or ""
            if re.fullmatch(r"\d+(\.\d+)?", amount):
                plain += 1
            elif re.fullmatch(r"\$?\d{1,3}(,\d{3})+(\.\d+)?|\$\d+(\.\d+)?", amount):
                formatted += 1
    if not buttons and not plain and not formatted:
        return missing("no getWizardButtons() calls or setCoverage amounts under reusable/")
    style = "plain" if plain > formatted else "formatted" if formatted > plain else None
    return fact({"wizardButtons": dict(buttons.most_common()), "coverageAmounts": style},
                f"{sum(buttons.values())} wizard button calls; coverage amounts {plain} plain, {formatted} formatted")


GUIDANCE_FILES = {"CLAUDE.md", "AGENTS.md"}


def guidance(root):
    """The project's own instructions for agents; the skill reads and follows them."""
    found = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        found += [rel(root, os.path.join(current, name)) for name in sorted(files) if name in GUIDANCE_FILES]
    return fact(found, "CLAUDE.md / AGENTS.md files") if found else missing("no CLAUDE.md or AGENTS.md in the project")


GENERATED_DEPENDENCY = re.compile(r"""["']([\w.\-]+):([\w.\-]*generated[\w.\-]*):(.*)$""", re.M)


def generated_dependency(root):
    """(group, artifact, version) of the *-generated dependency declared in build.gradle(.kts)."""
    gradle_properties = os.path.join(root, "gradle.properties")
    props = properties(gradle_properties) if os.path.isfile(gradle_properties) else {}
    for name in ("build.gradle", "build.gradle.kts"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        for group, artifact, rest in GENERATED_DEPENDENCY.findall(read(path)):
            reference = (re.search(r"""property\(\s*['"]([\w.]+)['"]\s*\)""", rest)
                         or re.search(r"\$\{?([A-Za-z_][\w.]*)\}?", rest))
            literal = re.match(r"[\w.\-]+", rest)
            version = props.get(reference.group(1)) if reference else (literal.group(0) if literal else None)
            if version:
                return group, artifact, version
    return None


def find_jar(group, artifact, version, gradle_home, m2_home):
    """The dependency's jar in the Gradle or Maven cache: the declared version first, then a
    version that only adds a suffix to it (e.g. -SNAPSHOT), newest first."""
    candidates = []
    base = os.path.join(gradle_home, "caches", "modules-2", "files-2.1", group, artifact)
    if os.path.isdir(base):
        for found in sorted(os.listdir(base)):
            if found.startswith(version):
                for jar in glob.glob(os.path.join(base, found, "*", f"{artifact}-{found}.jar")):
                    candidates.append((found != version, -os.path.getmtime(jar), jar))
    maven = os.path.join(m2_home, "repository", *group.split("."), artifact, version, f"{artifact}-{version}.jar")
    if os.path.isfile(maven):
        candidates.append((False, -os.path.getmtime(maven), maven))
    return sorted(candidates)[0][2] if candidates else None


CSSIDS_ENTRY = re.compile(r"^(cssids/.*[^/]|(pc|bc|cc|ab|cm)\.cssids)$")


def extract_cssids(jar, cache_root):
    """The jar's cssids (cssids/<app>/ in GW10, <app>.cssids at the root in GW9), extracted once per
    jar version into cache_root and reused by later scans; None when the jar has none."""
    with zipfile.ZipFile(jar) as z:
        names = [n for n in z.namelist() if CSSIDS_ENTRY.match(n) and ".." not in n]
        if not names:
            return None
        key = hashlib.sha1(f"{os.path.abspath(jar)}|{os.path.getmtime(jar)}".encode()).hexdigest()[:16]
        target = os.path.join(cache_root, key)
        if os.path.isdir(target):
            return target
        os.makedirs(cache_root, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".extract-", dir=cache_root)
        for name in names:
            z.extract(name, staging)
    try:
        os.rename(staging, target)
    except OSError:  # another scan extracted the same jar first
        shutil.rmtree(staging, ignore_errors=True)
    return target


def generated_checkout(root):
    """src/main/resources of the *-generated checkout: the one build.gradle names, else the only
    sibling folder with cssids. Two candidates and no name -> None (never guessed)."""
    def resources(folder):
        found = os.path.join(folder, "src", "main", "resources")
        has_cssids = os.path.isdir(os.path.join(found, "cssids")) or glob.glob(os.path.join(found, "*.cssids"))
        return found if has_cssids else None

    build = os.path.join(root, "build.gradle")
    if os.path.isfile(build):
        for folder in re.findall(r"""dir\s*=\s*['"]([^'"]*generated[^'"]*)['"]""", read(build)):
            found = resources(os.path.normpath(os.path.join(root, folder)))
            if found:
                return found
    parent = os.path.dirname(root)
    siblings = [resources(os.path.join(parent, d)) for d in sorted(os.listdir(parent))
                if "generated" in d and os.path.join(parent, d) != root]
    siblings = [s for s in siblings if s]
    return siblings[0] if len(siblings) == 1 else None


def cssids_source(root, override, gradle_home, m2_home, cache_root):
    if override:
        if os.path.isdir(override):
            return fact(os.path.abspath(override), "--cssids")
        return missing(f"--cssids {override} is not a directory")
    dependency = generated_dependency(root)
    if dependency:
        jar = find_jar(*dependency, gradle_home, m2_home)
        target = extract_cssids(jar, cache_root) if jar else None
        if target:
            return fact(target, f"cssids/ extracted from {jar} ({':'.join(dependency)})")
    checkout = generated_checkout(root)
    if checkout:
        return fact(checkout, "*-generated checkout next to the project")
    found = (f"no jar for {':'.join(dependency)} with cssids/ in the Gradle or Maven cache"
             if dependency else "no *-generated dependency in build.gradle")
    return missing(f"{found}, and no single *-generated checkout with cssids next to the project; "
                   "pass --cssids <generated project>/src/main/resources")


def bootrun_properties(text: str) -> list:
    """The -P properties the bootRun { } block reads (project.hasProperty / findProperty)."""
    start = re.search(r"\bbootRun\s*\{", text)
    if not start:
        return []
    depth, end = 0, len(text)
    for i in range(start.end() - 1, len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            end = i
            break
    block = text[start.end():end]
    return sorted(set(re.findall(r"""(?:hasProperty|findProperty)\(\s*['"](\w+)['"]""", block)))


def build_info(root, props):
    build = os.path.join(root, "build.gradle")
    if not os.path.isfile(build):
        return missing("no build.gradle")
    text = read(build)
    gradle = "./gradlew" if os.path.isfile(os.path.join(root, "gradlew")) else "gradle"
    profiles = sorted({m.group(1) for m in (re.fullmatch(r"profile\.([\w-]+)\.properties", os.path.basename(p))
                                            for p in props) if m})
    run, read_props = None, bootrun_properties(text)
    if "bootRun" in text and "MainRunner" in text:
        if not read_props:
            run = f'{gradle} bootRun --args="--spring.profiles.active={{profile}} --centerTest={{testClass}}"'
        elif "centerTest" in read_props:  # the block passes -P values on; without centerTest ask the user
            flags = (["-Pprofile={profile}"] if "profile" in read_props else []) + ["-PcenterTest={testClass}"]
            run = f"{gradle} bootRun {' '.join(flags)}"
    return fact({"compile": f"{gradle} compileJava", "run": run, "profiles": profiles,
                 "bootRunProperties": read_props}, "build.gradle")


def guidewire_version(root, props):
    value, path = first_property(props, {"customer.centertest.properties", "centertest.properties"}, "gw.version")
    return fact(value, rel(root, path)) if value else missing("no gw.version property")


def scan(root, cssids=None, gradle_home=None, m2_home=None, cache_root=None) -> dict:
    root = os.path.abspath(root)
    gradle_home = gradle_home or os.environ.get("GRADLE_USER_HOME") or os.path.expanduser("~/.gradle")
    m2_home = m2_home or os.path.expanduser("~/.m2")
    cache_root = cache_root or os.path.join(tempfile.gettempdir(), "recording-to-test-cssids")
    java, props = index(root)
    result = {"root": root, "clientPackage": client_package(root, props), "testsRoot": tests_root(root, java)}
    package, source = result["clientPackage"]["value"], result["testsRoot"]["value"]
    if package and source:
        base = os.path.join(root, *source.split("/"), *package.split("."))
        tests_dir, reusable_dir = os.path.join(base, "tests"), os.path.join(base, "reusable")
        tests = {p: t for p, t in files_under(java, tests_dir).items() if CENTERTEST_CLASS.search(t)}
        steps = files_under(java, reusable_dir)
        result.update(testLayout=test_layout(tests_dir, tests), testStyle=test_style(tests),
                      steps=step_conventions(root, steps, reusable_dir), facades=facades(root, java, steps),
                      exemplars=exemplars(root, tests, steps, tests_dir, reusable_dir),
                      transactionBases=transaction_bases(root, steps), screenHelpers=screen_helpers(root, steps),
                      idioms=idioms(steps))
        result["folders"] = folders(root, tests, steps, tests_dir, reusable_dir,
                                    {m["facade"] for m in result["facades"]["value"] or []})
    else:
        for key in ("testLayout", "testStyle", "steps", "facades", "exemplars", "folders", "transactionBases",
                    "screenHelpers", "idioms"):
            result[key] = missing("needs clientPackage and testsRoot")
    result.update(guidance=guidance(root), cssids=cssids_source(root, cssids, gradle_home, m2_home, cache_root),
                  build=build_info(root, props), guidewireVersion=guidewire_version(root, props))
    return result


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description="Detect a CenterTest project's conventions")
    parser.add_argument("root", nargs="?", default=".", help="project root (default: current directory)")
    parser.add_argument("--cssids", help="resources dir holding cssids/<app>/, when it cannot be detected")
    parser.add_argument("--out", help="write the result here instead of stdout")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.root):
        print(f"Error: project root not found: {args.root}", file=sys.stderr)
        return 2
    # ASCII only (\u escapes): a reader that decodes the file as cp1252 on Windows still gets it right
    text = json.dumps(scan(args.root, args.cssids), indent=2, ensure_ascii=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
