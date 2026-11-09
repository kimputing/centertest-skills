"""
--model-diff OLD [NEW]: what a regenerated product model changes for this suite.

The generated project keeps the product model in git (<Line>_coverage_structure.json beside the
cssids). Between two of its revisions (NEW: the files on disk when omitted) this compares, per line,
coverages (matched by codeIdentifier first, so a coverage whose display name changed is "renamed",
not removed and added) and the options of their terms. For the suite it says what breaks and what
nobody tests:
- scenarios that select a removed coverage or a renamed one by its old name, and scenarios that set a
  removed option (the screen no longer offers it: the step fails),
- added coverages and options no scenario selects yet.
The affected scenarios come back as suite entries to rerun after regenerating (vendored suite-builder).
"""

from __future__ import annotations

import json
import os
import subprocess


def _git(repo: str, *args: str) -> str:
    run = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return run.stdout if run.returncode == 0 else ""


def _resources(cssids_dir: str) -> str:
    path = os.path.realpath(cssids_dir)  # git names the real top level: a symlinked path must match it
    return os.path.dirname(path) if os.path.basename(path) == "cssids" else path


def load_models(cssids_dir: str, rev: str | None) -> dict[str, list] | None:
    """{line: coverages} of the product model at a git revision of the generated project (None: on disk)."""
    resources = _resources(cssids_dir)
    if rev is None:
        from eir_products import structure_files
        out = {}
        for path in structure_files(cssids_dir):
            with open(path, encoding="utf-8") as fh:
                out[os.path.basename(path)[:-len("_coverage_structure.json")]] = json.load(fh)
        return out
    top = _git(resources, "rev-parse", "--show-toplevel").strip()
    if not top or not _git(top, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip():
        return None
    rel = os.path.relpath(resources, top).replace("\\", "/")
    out = {}
    for name in _git(top, "ls-tree", "--name-only", rev, rel + "/").split():
        if name.endswith("_coverage_structure.json"):
            try:
                out[name.rsplit("/", 1)[-1][:-len("_coverage_structure.json")]] = json.loads(_git(top, "show", f"{rev}:{name}") or "[]")
            except ValueError:
                continue
    return out or None  # a revision without any model file is not "an empty model"


def _catalog(models: dict[str, list]) -> tuple[dict, dict]:
    """(coverages {(line, key): name} keyed by codeIdentifier or name, options {(line, coverage, term, option)})."""
    coverages, options = {}, set()
    for line, items in models.items():
        for c in items if isinstance(items, list) else []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            name = c["name"].strip()
            coverages[(line, c.get("codeIdentifier") or name)] = name
            for t in c.get("covTerms") or []:
                for ch in t.get("covTermChoices") or []:
                    if ch.get("name") and t.get("name"):
                        options.add((line, name, t["name"].strip(), ch["name"].strip()))
    return coverages, options


def model_diff(repo_dir: str, source_root: str, cssids_dir: str, old: str, new: str | None = None) -> dict:
    import suite as suites
    from eir_products import _keys_of, _squeeze
    from eir_uses import rows_by_value
    before, after = load_models(cssids_dir, old), load_models(cssids_dir, new)
    if before is None or after is None:
        return {"error": f"no product model at {old if before is None else new} in the generated project's git"}
    cov_a, opt_a = _catalog(before)
    cov_b, opt_b = _catalog(after)
    removed = {k: n for k, n in cov_a.items() if k not in cov_b}
    added = {k: n for k, n in cov_b.items() if k not in cov_a}
    renamed = {k: (cov_a[k], cov_b[k]) for k in set(cov_a) & set(cov_b) if cov_a[k] != cov_b[k]}
    still = {n.lower() for n in cov_b.values()}

    tests = suites.scan(repo_dir, source_root)
    runnable = set(suites.scenarios_of(tests))
    datasource = {(t["class"], m["name"]): m["datasource"] for t in tests for m in t["methods"]}
    by_row = {}
    for s in runnable:
        if s[2]:
            by_row.setdefault(("dc", datasource.get((s[0], s[1])), s[2].lower()), set()).add(s)
    by_value = rows_by_value(repo_dir, coverage_only=True)

    def scenarios_naming(name: str) -> set:
        return set().union(*(by_row.get(r, set()) for r in by_value.get(name.lower(), ())))

    breaks: dict[str, set] = {}
    for (line, _k), name in removed.items():
        if name.lower() not in still:  # the same name on another sub-line still exists: nothing to fix
            for s in scenarios_naming(name):
                breaks.setdefault(f"{line}: coverage removed - {name}", set()).add(s)
    for (line, _k), (was, now) in renamed.items():
        if was.lower() not in still:
            for s in scenarios_naming(was):
                breaks.setdefault(f"{line}: coverage renamed - {was} -> {now}", set()).add(s)
    # options a scenario sets that the new model no longer offers for that coverage and term
    from eir_cover import _option_items_with
    old_options = _option_items_with(repo_dir, before)
    new_keys = {(line, cov.lower(), term.lower(), _squeeze(opt)) for line, cov, term, opt in opt_b}
    for row, items in old_options.items():
        for _kind, line, label in items:
            cov, rest = label.split(" / ", 1)
            term, opt = rest.split(" = ", 1)
            if not any((line, cov.lower(), term.lower(), k) in new_keys for k in _keys_of(opt)):
                for s in by_row.get(row, ()):
                    breaks.setdefault(f"{line}: option removed - {label}", set()).add(s)

    selected_now = set(by_value)
    untested_added = sorted(f"{line}: {n}" for (line, _k), n in added.items() if n.lower() not in selected_now)
    affected = set().union(*breaks.values()) if breaks else set()
    used = [t for t in tests if any(c == t["class"] for c, _m, _code in affected)]
    return {
        "old": old, "new": new or "working tree",
        "coverages": {"removed": len(removed), "added": len(added), "renamed": len(renamed)},
        "options": {"removed": len(opt_a - opt_b), "added": len(opt_b - opt_a)},
        "breaks": {k: sorted(v) for k, v in sorted(breaks.items())},
        "scenarios": len(affected), "entries": suites.compact(affected, used),
        "untested_added": untested_added,
    }


def print_model_diff(d: dict, name: str, command: str | None) -> None:
    if d.get("error"):
        print(f"  {d['error']}")
        return
    c, o = d["coverages"], d["options"]
    print(f"  PRODUCT MODEL {d['old']} -> {d['new']}: coverages -{c['removed']} +{c['added']} ({c['renamed']} renamed), "
          f"options -{o['removed']} +{o['added']}")
    if d["breaks"]:
        print(f"  {d['scenarios']} scenario(s) select or set something the new model no longer has (they fail at that step):")
        for what, scen in list(d["breaks"].items())[:15]:
            shown = ", ".join(f"{cl} {code}" for cl, _m, code in scen[:3]) + (" ..." if len(scen) > 3 else "")
            print(f"    {what}: {shown}")
        if len(d["breaks"]) > 15:
            print(f"    ... {len(d['breaks']) - 15} more")
        print("\n  Rerun them after regenerating:\n")
        print("\n".join("    " + l for l in json.dumps({"Name": name, "List": d["entries"]}, indent=2).splitlines()))
        if command:
            print(f"\n  Then: {command}")
    else:
        print("  No scenario selects or sets anything the new model removed.")
    if d["untested_added"]:
        print(f"\n  Added and selected by no scenario ({len(d['untested_added'])}): "
              + ", ".join(d["untested_added"][:10]) + (" ..." if len(d["untested_added"]) > 10 else ""))
