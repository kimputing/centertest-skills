#!/usr/bin/env python3
"""Eval harness for the recording-to-test engine.

Runs `ct.py scan` + `ct.py parse` for every case folder under a cases directory (kept outside this
public repo) and checks the expected values in the resulting plan/project JSON.

    python run_evals.py --cases DIR      (or set CT_EVALS_DIR)

Exit code: 0 all passed or skipped, 1 any FAIL, 2 usage error.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CT = os.path.join(os.path.dirname(HERE), "scripts", "ct.py")
SEGMENT = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def get_path(doc, path):
    """Dotted path with [i] indexes, e.g. plan.existingTests[0].path. Raises KeyError naming the bad segment."""
    current = doc
    for match in SEGMENT.finditer(path):
        name, index = match.group(1), match.group(2)
        if name is not None:
            if not isinstance(current, dict) or name not in current:
                raise KeyError(name)
            current = current[name]
        else:
            i = int(index)
            if not isinstance(current, list) or i >= len(current):
                raise KeyError(f"[{i}]")
            current = current[i]
    return current


def _expand(value, case_dir):
    """Expand ${VAR}; relative paths resolve against the case folder. Raises KeyError for an unset variable."""
    def sub(m):
        if m.group(1) not in os.environ:
            raise KeyError(m.group(1))
        return os.environ[m.group(1)]
    value = re.sub(r"\$\{([^}]+)\}", sub, value)
    return value if os.path.isabs(value) else os.path.normpath(os.path.join(case_dir, value))


def _run(args):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _check(doc, expectation):
    path, op = expectation["path"], expectation["op"]
    try:
        actual = get_path(doc, path)
    except KeyError as missing:
        if op == "absent":
            return None
        return f"{path}: missing segment {missing.args[0]}"
    if op == "exists":
        return None
    if op == "absent":
        return f"{path}: expected absent, found {actual!r}"
    want = expectation.get("value")
    if op == "equals":
        return None if actual == want else f"{path}: expected {want!r}, got {actual!r}"
    if op == "contains":
        try:
            ok = want in actual
        except TypeError:
            ok = False
        return None if ok else f"{path}: expected to contain {want!r}, got {actual!r}"
    return f"{path}: unknown op {op!r}"


def run_case(case_dir, ct):
    case = _read_json(os.path.join(case_dir, "case.json"))
    name = case.get("name") or os.path.basename(case_dir)

    def result(status, failures=(), reason=None):
        r = {"name": name, "status": status, "failures": list(failures)}
        if reason:
            r["reason"] = reason
        return r

    try:
        project = _expand(case["project"], case_dir)
        recordings = [_expand(r, case_dir) for r in case["recordings"]]
        cssids_field = _expand(case["cssids"], case_dir) if case.get("cssids") else None
    except KeyError as unset:
        return result("SKIP", reason=f"environment variable {unset.args[0]} is not set")
    if not os.path.isdir(project):
        return result("SKIP", reason=f"project not found: {project}")
    for rec in recordings:
        if not os.path.exists(rec):
            return result("SKIP", reason=f"recording not found: {rec}")

    with tempfile.TemporaryDirectory() as tmp:
        project_json = os.path.join(tmp, "project.json")
        plan_json = os.path.join(tmp, "plan.json")
        scan_args = [ct, "scan", project, "--out", project_json]
        if cssids_field:
            scan_args += ["--cssids", cssids_field]
        done = _run(scan_args)
        if done.returncode != 0:
            return result("FAIL", [f"scan exited {done.returncode}: {done.stderr.strip()[-300:]}"])
        project_doc = _read_json(project_json)
        cssids = (project_doc.get("cssids") or {}).get("value") or cssids_field
        if not cssids:
            return result("SKIP", reason="no cssids: the scan found none and the case has no \"cssids\" field")
        done = _run([ct, "parse", *recordings, "--cssids", cssids, "--project", project_json, "--out", plan_json])
        if done.returncode != 0:
            return result("FAIL", [f"parse exited {done.returncode}: {done.stderr.strip()[-300:]}"])
        doc = {"plan": _read_json(plan_json), "project": project_doc}

    failures = [f for f in (_check(doc, e) for e in case.get("expect", [])) if f]
    return result("FAIL" if failures else "PASS", failures)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run recording-to-test eval cases kept outside this repository.")
    parser.add_argument("--cases", help="directory of case folders, each with case.json (else CT_EVALS_DIR)")
    parser.add_argument("--ct", default=DEFAULT_CT, help="path to ct.py (default: this plugin's)")
    args = parser.parse_args(argv)
    cases_dir = args.cases or os.environ.get("CT_EVALS_DIR")
    if not cases_dir:
        print("Error: give --cases DIR or set CT_EVALS_DIR (cases live outside this repository)", file=sys.stderr)
        return 2
    if not os.path.isdir(cases_dir):
        print(f"Error: cases directory not found: {cases_dir}", file=sys.stderr)
        return 2
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for entry in sorted(os.listdir(cases_dir)):
        folder = os.path.join(cases_dir, entry)
        if not os.path.isfile(os.path.join(folder, "case.json")):
            continue
        try:
            res = run_case(folder, args.ct)
        except (OSError, ValueError, KeyError) as error:
            res = {"name": entry, "status": "FAIL", "failures": [f"invalid case: {error}"]}
        counts[res["status"]] += 1
        line = f"{res['status']} {res['name']}"
        if res.get("reason"):
            line += f" ({res['reason']})"
        print(line)
        for failure in res["failures"]:
            print(f"    - {failure}")
    print(f"{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
