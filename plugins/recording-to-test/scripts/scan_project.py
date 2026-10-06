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


def extract_cssids(jar):
    """cssids/ from the jar into a new temp directory, or None when the jar has none."""
    with zipfile.ZipFile(jar) as z:
        names = [n for n in z.namelist() if n.startswith("cssids/") and not n.endswith("/") and ".." not in n]
        if not names:
            return None
        target = tempfile.mkdtemp(prefix="recording-to-test-cssids-")
        for name in names:
            z.extract(name, target)
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


def cssids_source(root, override, gradle_home, m2_home):
    if override:
        if os.path.isdir(override):
            return fact(os.path.abspath(override), "--cssids")
        return missing(f"--cssids {override} is not a directory")
    dependency = generated_dependency(root)
    if dependency:
        jar = find_jar(*dependency, gradle_home, m2_home)
        target = extract_cssids(jar) if jar else None
        if target:
            return fact(target, f"cssids/ extracted from {jar} ({':'.join(dependency)})")
    checkout = generated_checkout(root)
    if checkout:
        return fact(checkout, "*-generated checkout next to the project")
    found = (f"no jar for {':'.join(dependency)} with cssids/ in the Gradle or Maven cache"
             if dependency else "no *-generated dependency in build.gradle")
    return missing(f"{found}, and no single *-generated checkout with cssids next to the project; "
                   "pass --cssids <generated project>/src/main/resources")


def build_info(root, props):
    build = os.path.join(root, "build.gradle")
    if not os.path.isfile(build):
        return missing("no build.gradle")
    text = read(build)
    gradle = "./gradlew" if os.path.isfile(os.path.join(root, "gradlew")) else "gradle"
    profiles = sorted({m.group(1) for m in (re.fullmatch(r"profile\.([\w-]+)\.properties", os.path.basename(p))
                                            for p in props) if m})
    run = None
    if "bootRun" in text and "MainRunner" in text:
        run = f'{gradle} bootRun --args="--spring.profiles.active={{profile}} --centerTest={{testClass}}"'
    return fact({"compile": f"{gradle} compileJava", "run": run, "profiles": profiles}, "build.gradle")


def guidewire_version(root, props):
    value, path = first_property(props, {"customer.centertest.properties", "centertest.properties"}, "gw.version")
    return fact(value, rel(root, path)) if value else missing("no gw.version property")


def scan(root, cssids=None, gradle_home=None, m2_home=None) -> dict:
    root = os.path.abspath(root)
    gradle_home = gradle_home or os.environ.get("GRADLE_USER_HOME") or os.path.expanduser("~/.gradle")
    m2_home = m2_home or os.path.expanduser("~/.m2")
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
                      exemplars=exemplars(root, tests, steps, tests_dir, reusable_dir))
    else:
        for key in ("testLayout", "testStyle", "steps", "facades", "exemplars"):
            result[key] = missing("needs clientPackage and testsRoot")
    result.update(cssids=cssids_source(root, cssids, gradle_home, m2_home),
                  build=build_info(root, props), guidewireVersion=guidewire_version(root, props))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Detect a CenterTest project's conventions")
    parser.add_argument("root", nargs="?", default=".", help="project root (default: current directory)")
    parser.add_argument("--cssids", help="resources dir holding cssids/<app>/, when it cannot be detected")
    parser.add_argument("--out", help="write the result here instead of stdout")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.root):
        print(f"Error: project root not found: {args.root}", file=sys.stderr)
        return 2
    text = json.dumps(scan(args.root, args.cssids), indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
