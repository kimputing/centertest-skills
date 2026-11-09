"""
Branch review: what a branch introduces and fixes, compared with where it started.

The merge-base of BASE and HEAD and the HEAD commit are exported with ``git archive`` into
temporary folders (no checkout, no worktree: the repository is only read), every active rule
runs on both, and findings are diffed. A finding is the same finding when its rule and its row
(minus workbook row numbers, which shift when rows are inserted) match, so a branch is only
held responsible for what it changed.

The verdict is written as Markdown, ready to paste into the pull request, and printed. The
exit code is 1 when the branch introduces a trust blocker (see eir_report.TRUST_RULES), so the
review can gate a pipeline.
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from datetime import datetime

from eir_models import LOCAL_COMMIT, RuleResult
from eir_parser import parse_directory
from eir_report import TRUST_RULES, _finding_label, is_dormant
from eir_rules import run_rules
from eir_suppressions import apply_suppressions

# Columns that locate a finding or describe its context; they change without the finding changing.
_POSITION_COLUMNS = {"Row", "Line No", "Line Number", "Runs in", "Location"}

# Categories whose rows describe the project rather than problems in it.
_INFORMATIONAL = {"Statistics"}


def _git(repo_dir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_dir, capture_output=True)


def resolve_rev(repo_dir: str, rev: str) -> str | None:
    """Full SHA for rev; tries origin/<rev> when rev is not a local name."""
    for candidate in (rev, f"origin/{rev}"):
        r = _git(repo_dir, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
        if r.returncode == 0:
            return r.stdout.decode().strip()
    return None


def merge_base(repo_dir: str, base_sha: str, head_sha: str) -> str | None:
    r = _git(repo_dir, "merge-base", base_sha, head_sha)
    return r.stdout.decode().strip() if r.returncode == 0 else None


def export_tree(repo_dir: str, sha: str, dest: str, paths: list[str]) -> list[str]:
    """Extract the given paths of commit sha into dest. Returns the paths that existed."""
    present = [p for p in paths
               if _git(repo_dir, "cat-file", "-e", f"{sha}:{p}").returncode == 0]
    if not present:
        return []
    r = _git(repo_dir, "archive", "--format=tar", sha, "--", *present)
    if r.returncode != 0:
        raise RuntimeError(f"git archive {sha[:8]} failed: {r.stderr.decode().strip()}")
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:  # Python < 3.12 has no extraction filters
            tar.extractall(dest)
    return present


def analyze_tree(tree_dir: str, config, suppressions) -> tuple[list[RuleResult], int]:
    """Run the active rules on an exported tree, as local mode would. Returns (results, files)."""
    cfg = copy.copy(config)
    cfg.repository_dir = tree_dir
    files = parse_directory(tree_dir, cfg.source_root, cfg.exclude_packages,
                            cfg.exclude_files, cfg.compat_comment_lines, None)
    results = run_rules({LOCAL_COMMIT: files}, cfg)
    from eir_locate import annotate_locations
    annotate_locations(results, {LOCAL_COMMIT: files}, tree_dir)
    if suppressions:
        results, _ = apply_suppressions(results, suppressions)
    return results, len(files)


def _findings(result: RuleResult):
    """Yield (key, label) for each finding of a result.

    Row keys drop position columns. Grouped items (rules 1004, 4001, ...) embed counts such as
    "13/14 (93%)" or "6x"; those are replaced by "#" in the key, so adding one more use of an
    existing pattern is not reported as one finding fixed and another introduced.
    """
    keep = [i for i, h in enumerate(result.headers) if str(h) not in _POSITION_COLUMNS]
    for row in result.rows:
        yield (("row", tuple(str(row[i]) for i in keep if i < len(row))),
               _finding_label(result.headers, row) + (" (not run)" if is_dormant(result.headers, row) else ""))
    for section in result.sections:
        # Snapshot rules title their single section after the commit ("Commit local"): no information.
        prefix = "" if section.title.startswith("Commit ") else f"{section.title}: "
        for item in section.items:
            yield ("item", section.title, _DIGITS.sub("#", str(item))), f"{prefix}{item}"
        for sub in section.subsections:
            for item in sub.items:
                yield (("item", section.title, sub.title, _DIGITS.sub("#", str(item))),
                       f"{prefix}{sub.title}: {item}")
        for row in section.rows:
            yield ("row", section.title, tuple(str(v) for v in row)), prefix + ", ".join(str(v) for v in row)


_DIGITS = re.compile(r"\d+")


def finding_keys(result: RuleResult) -> Counter:
    """Counter of finding identities for a rule's result."""
    return Counter(key for key, _ in _findings(result))


def _labels(result: RuleResult) -> dict:
    """key -> readable labels, one per occurrence (rows keep their own row number)."""
    labels: dict = {}
    for key, label in _findings(result):
        labels.setdefault(key, []).append(label)
    return labels


def diff_results(base: list[RuleResult], head: list[RuleResult]) -> list[dict]:
    """Per rule: {rule_id, description, category, trust, introduced: [label], fixed: [label]}.

    Only rules with a change are returned, trust rules first. Rules that errored on either
    side are skipped (their findings are unknown, not changed).
    """
    base_by_id = {r.rule_id: r for r in base}
    changes = []
    for h in head:
        b = base_by_id.get(h.rule_id)
        if h.category in _INFORMATIONAL:
            continue
        if h.error or b is None or b.error:
            changes.append({"rule_id": h.rule_id, "description": h.description, "category": h.category,
                            "trust": TRUST_RULES.get(h.rule_id, (None,))[0], "introduced": [], "fixed": [], "blocking": 0,
                            "error": h.error or (b.error if b else "not run on the base")})
            continue
        hk, bk = finding_keys(h), finding_keys(b)
        added, removed = hk - bk, bk - hk
        if not added and not removed:
            continue
        hl, bl = _labels(h), _labels(b)
        changes.append({
            "rule_id": h.rule_id, "description": h.description, "category": h.category,
            "trust": TRUST_RULES.get(h.rule_id, (None,))[0],
            "introduced": [label for k in added for label in hl[k][-added[k]:]],
            "blocking": 0 if h.rule_id not in TRUST_RULES else
            sum(1 for k in added for label in hl[k][-added[k]:] if not label.endswith(" (not run)")),
            "fixed": [label for k in removed for label in bl[k][-removed[k]:]],
            "error": None,
        })
    changes.sort(key=lambda c: (c["trust"] is None, c["rule_id"]))
    return changes


def verdict(changes: list[dict]) -> tuple[str, int]:
    """(one-line verdict, exit code)."""
    blockers = sum(c.get("blocking", 0) for c in changes)
    introduced = sum(len(c["introduced"]) for c in changes)
    fixed = sum(len(c["fixed"]) for c in changes)
    unknown = [c["rule_id"] for c in changes if c.get("error") and c["trust"]]
    if blockers:
        return (f"Changes requested: this branch introduces {blockers} trust blocker"
                f"{'s' if blockers != 1 else ''} (tests that cannot fail or data that cannot load).", 1)
    if unknown:
        return (f"Not verified: trust rule{'s' if len(unknown) != 1 else ''} {', '.join(unknown)} could not run "
                "on both sides, so this branch may hide blockers.", 1)
    if introduced:
        return (f"Mergeable with follow-ups: {introduced} new finding{'s' if introduced != 1 else ''}, "
                f"no trust blockers; {fixed} fixed.", 0)
    return f"Clean: no new findings; {fixed} fixed.", 0


GROUP_FROM = 10  # above this many tests the plan is read by cause, not test by test


def _rerun_by_cause(rerun: list[dict], limit: int) -> list[str]:
    """The plan grouped by the change that reaches it, biggest first, with the tests that only that
    change reaches (they leave the plan if it is reverted); row-level reruns listed on their own."""
    causes: dict[str, list[str]] = {}
    for e in rerun:
        for reason in e["reasons"]:
            causes.setdefault(reason, []).append(e["test"])
    ranked = sorted(causes.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    only = {reason: sum(1 for e in rerun if e["reasons"] == [reason]) for reason in causes}
    out = ["By change (a test reached by several changes is under each):", ""]
    for reason, tests in ranked[:limit]:
        names = ", ".join(tests[:8]) + (f" +{len(tests) - 8}" if len(tests) > 8 else "")
        alone = f", {only[reason]} only through it" if only[reason] else ""
        out.append(f"- **{reason}** → {len(tests)} test{'s' if len(tests) != 1 else ''}{alone}: {names}")
    if len(ranked) > limit:
        out.append(f"- … and {len(ranked) - limit} more changes")
    rows = [e for e in rerun if e["codes"]]
    if rows:
        out += ["", "Only some rows:"] + [f"- **{e['test']}** — rows {', '.join(e['codes'])}" for e in rows[:limit * 2]]
        if len(rows) > limit * 2:
            out.append(f"- … and {len(rows) - limit * 2} more")
    return out


def render_markdown(changes: list[dict], meta: dict, limit: int = 15) -> str:
    """The review as Markdown for a pull-request comment."""
    line, _ = verdict(changes)
    out = [f"## CenterTest review: `{meta['head_name']}` vs `{meta['base_name']}`", "",
           f"**{line}**", "",
           f"Compared {meta['head_short']} with the merge-base {meta['base_short']} "
           f"({meta['head_files']} vs {meta['base_files']} Java files, rules: {meta['ruleset']}). "
           "Only findings this branch added or removed are listed.", ""]
    introduced = [c for c in changes if c["introduced"]]
    fixed = [c for c in changes if c["fixed"]]
    if introduced:
        out += ["### Introduced", ""]
        for c in introduced:
            mark = "⛔ " if c.get("blocking") else ""
            title = c["trust"] or c["description"]
            out.append(f"- {mark}**{len(c['introduced'])} × {title}** ({c['rule_id']})")
            for label in c["introduced"][:limit]:
                out.append(f"  - `{label}`")
            if len(c["introduced"]) > limit:
                out.append(f"  - … and {len(c['introduced']) - limit} more")
        out.append("")
    if fixed:
        out += ["### Fixed", ""]
        for c in fixed:
            out.append(f"- **{len(c['fixed'])} × {c['trust'] or c['description']}** ({c['rule_id']})")
        out.append("")
    for sc in meta.get("suites") or []:
        if sc is (meta.get("suites") or [None])[0]:
            out += ["### Suite changes", ""]
        verb = {"new": "new suite", "deleted": "deleted", "changed": "changed"}[sc["status"]]
        out.append(f"- **{sc['suite']}** ({verb}): {sc['before']} → {sc['after']} scenarios "
                   f"(+{len(sc['added'])} −{len(sc['removed'])})")
        for label, items in (("runs now", sc["added"]), ("no longer runs", sc["removed"])):
            if items:
                shown = ", ".join(" ".join(x).strip() for x in items[:limit])
                out.append(f"  - {label}: {shown}" + (f" … +{len(items) - limit}" if len(items) > limit else ""))
        for e in sc["adds_nothing"]:
            out.append(f"  - ⚠ `{e}` adds nothing: the suite already runs it")
        for e in sc["dead"]:
            out.append(f"  - ⛔ `{e}` matches no test: CenterTest reports it as a failed scenario")
    if meta.get("suites"):
        out.append("")
    data = meta.get("data") or []
    if data:
        out += ["### Data changes", ""]
        for d in data[:limit * 2]:
            name = f"`{os.path.basename(d['file'])} › {d['sheet']}`"
            parts = []
            if d["added"]:
                parts.append("added " + ", ".join(f"**{c}**" for c in d["added"][:limit]) +
                             (f" +{len(d['added']) - limit}" if len(d["added"]) > limit else ""))
            if d["removed"]:
                parts.append("removed " + ", ".join(f"**{c}**" for c in d["removed"][:limit]) +
                             (f" +{len(d['removed']) - limit}" if len(d["removed"]) > limit else ""))
            out.append(f"- {name}: " + ("; ".join(parts) if parts else f"{len(d['changed'])} row(s) changed"))
            for code, cols in d["changed"][:limit]:
                diffs = "; ".join("{} `{}` → `{}`".format(col, *_diff_pair(old, new)) for col, old, new in cols[:6])
                out.append(f"  - **{code}**: {diffs}" + (f" (+{len(cols) - 6} columns)" if len(cols) > 6 else ""))
            if len(d["changed"]) > limit:
                out.append(f"  - … and {len(d['changed']) - limit} more changed rows")
        if len(data) > limit * 2:
            out.append(f"- … and {len(data) - limit * 2} more sheets")
        out.append("")
    rerun = meta.get("rerun") or []
    if rerun:
        from eir_impact import command_for
        out += ["### Rerun to verify", "",
                f"{len(rerun)} test{'s' if len(rerun) != 1 else ''} reach this branch's {meta.get('changed', 0)} changed "
                "files (code they call, rows they run, reference data those rows use).", ""]
        if len(rerun) > GROUP_FROM:
            out += _rerun_by_cause(rerun, limit)
        else:
            for entry in rerun:
                rows = f" — rows {', '.join(entry['codes'])}" if entry["codes"] else " — all rows"
                out.append(f"- **{entry['test']}**{rows} ({'; '.join(entry['reasons'])})")
        one = meta.get("rerun_suite")
        if one:
            body = json.dumps({"Name": one["name"], "List": one["entries"]}, indent=2)
            out += ["", f"**All of it in one run**: add this suite to `CenterTestSuiteList.json` (it runs exactly "
                        f"these scenarios: {len(one['entries'])} entr{'y' if len(one['entries']) == 1 else 'ies'}) "
                        "and start it once:", "", "```json", body, "```", "", "```bash", one["command"], "```"]
            if one.get("idle"):
                out += ["", f"Not in it: {', '.join(one['idle'])} — every row the plan names is disabled, so "
                            "the test runs nothing (rule 9011)."]
        commands = [c for c in (command_for(e, meta.get("forwards", (False, False))) for e in rerun) if c]
        if commands and (not one or len(commands) <= 3):
            out += ([""] + (["One test at a time:"] if one else []) + ["```bash"] + commands[:limit * 2] + ["```"])
        out.append("")
    scope = meta.get("scope")
    if scope and (scope["removed"] or scope["switched_off"] or scope["added"]):
        def names(items):
            shown = [f"`{c} {m}{(' ' + k) if k else ''}`" for c, m, k in items[:limit]]
            return ", ".join(shown) + (f" … +{len(items) - limit}" if len(items) > limit else "")
        out += ["### Run scope", "", f"A full run executes {scope['before']} → {scope['after']} scenarios.", ""]
        if scope["removed"]:
            out += [f"**Removed** ({len(scope['removed'])}: the test or its row is gone): {names(scope['removed'])}", ""]
        if scope["switched_off"]:
            out += [f"**Switched off** ({len(scope['switched_off'])}: the row is disabled): {names(scope['switched_off'])}", ""]
        if scope["added"]:
            out += [f"Added ({len(scope['added'])}): {names(scope['added'])}", ""]
    coverage = meta.get("coverage") or []
    if coverage:
        lost = [(c["line"], n) for c in coverage for n in c["lost"]]
        gained = [(c["line"], n) for c in coverage for n in c["gained"]]
        out += ["### Product coverage", "",
                "Coverages of the product model the scenarios select (a row an enabled scenario reaches names them), "
                "merge-base → branch tip.", ""]
        if lost:
            out.append(f"**No scenario selects these any more** ({len(lost)}):")
            out += [f"- {line}: {name}" for line, name in lost[:limit * 2]]
            if len(lost) > limit * 2:
                out.append(f"- … and {len(lost) - limit * 2} more")
            out.append("")
        if gained:
            out.append(f"Newly selected ({len(gained)}): " + "; ".join(f"{l}: {n}" for l, n in gained[:limit])
                       + (f" … +{len(gained) - limit}" if len(gained) > limit else ""))
            out.append("")
    errored = [c for c in changes if c.get("error")]
    if errored:
        out += ["### Not compared", ""]
        for c in errored:
            out.append(f"- {c['rule_id']} {c['trust'] or c['description']}: {c['error']}")
        out.append("")
    if not changes:
        out += ["No findings were added or removed.", ""]
    return "\n".join(out)


def _short(value: str, width: int = 40) -> str:
    value = str(value).replace("`", "'")
    return value if len(value) <= width else value[: width - 1] + "…"


def _diff_pair(old: str, new: str, width: int = 40, context: int = 12) -> tuple[str, str]:
    """old and new cut to the region where they differ (with a little context), so a long cell
    whose change sits past the first characters still shows the change."""
    old, new = str(old).replace("`", "'"), str(new).replace("`", "'")
    if len(old) <= width and len(new) <= width:
        return old, new
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    q = 0
    while q < min(len(old), len(new)) - p and old[-1 - q] == new[-1 - q]:
        q += 1
    start = max(0, p - context)

    def cut(v):
        end = min(len(v), len(v) - q + context)
        part = v[start:end]
        if len(part) > width:
            part = part[:width - 1] + "…"
        return ("…" if start > 0 else "") + part + ("…" if end < len(v) else "")
    return cut(old), cut(new)


def print_review(changes: list[dict], meta: dict) -> None:
    line, _ = verdict(changes)
    print("\n" + "=" * 60)
    print(f"  BRANCH REVIEW  {meta['head_name']} ({meta['head_short']}) vs {meta['base_name']}"
          f" (merge-base {meta['base_short']})")
    print("=" * 60)
    for c in changes:
        if not c["introduced"]:
            continue
        mark = "!!" if c.get("blocking") else "+ "
        print(f"  {mark} {len(c['introduced']):>3} new  {c['rule_id']}: {c['trust'] or c['description']}")
        for label in c["introduced"][:3]:
            print(f"           {label}")
    for c in changes:
        if c.get("error"):
            print(f"  ?? not compared  {c['rule_id']}: {c['error']}")
    for sc in meta.get("suites") or []:
        warn = (f", {len(sc['adds_nothing'])} entr{'y adds' if len(sc['adds_nothing']) == 1 else 'ies add'} nothing" if sc["adds_nothing"] else "") + \
               (f", {len(sc['dead'])} match no test" if sc["dead"] else "")
        print(f"  ## suite {sc['suite']}: {sc['before']} -> {sc['after']} scenarios{warn}")
    data = meta.get("data") or []
    if data:
        files = len({d["file"] for d in data})
        print(f"  ~~ data: {files} workbook(s), {sum(len(d['added']) for d in data)} rows added, "
              f"{sum(len(d['changed']) for d in data)} changed, {sum(len(d['removed']) for d in data)} removed")
    scope = meta.get("scope")
    if scope and (scope["removed"] or scope["switched_off"] or scope["added"]):
        print(f"  ## run scope {scope['before']} -> {scope['after']} scenarios: {len(scope['removed'])} removed, "
              f"{len(scope['switched_off'])} switched off, {len(scope['added'])} added")
    for c in meta.get("coverage") or []:
        if c["lost"]:
            print(f"  -- {c['line']}: no scenario selects {len(c['lost'])} coverage(s) any more: "
                  + ", ".join(c["lost"][:4]) + (" ..." if len(c["lost"]) > 4 else ""))
        if c["gained"]:
            print(f"  ++ {c['line']}: {len(c['gained'])} coverage(s) newly selected: "
                  + ", ".join(c["gained"][:4]) + (" ..." if len(c["gained"]) > 4 else ""))
    rerun = meta.get("rerun") or []
    if rerun:
        print(f"  >> rerun {len(rerun)} test(s): " + ", ".join(
            e["test"] + (f" [{len(e['codes'])} rows]" if e["codes"] else "") for e in rerun[:6])
              + (" ..." if len(rerun) > 6 else ""))
        one = meta.get("rerun_suite")
        if one:
            print(f"  >> all in one run: suite {one['name']} ({len(one['entries'])} entries, in the PR comment): "
                  f"{one['command']}")
    fixed = sum(len(c["fixed"]) for c in changes)
    if fixed:
        print(f"  -  {fixed:>3} fixed in "
              + ", ".join(c["rule_id"] for c in changes if c["fixed"]))
    print("-" * 60)
    print(f"  {line}")
    print("=" * 60)


def run_scope(base_tree: str, head_tree: str, source_root: str) -> dict:
    """What a full run executes, merge-base -> branch tip: (class, method, code) scenarios removed (the test or
    row is gone), switched off (the row is still there, disabled) and added, by the vendored suite engine."""
    import suite as suites
    base_t, head_t = suites.scan(base_tree, source_root), suites.scan(head_tree, source_root)
    on_a, on_b = set(suites.scenarios_of(base_t)), set(suites.scenarios_of(head_t))
    all_b = set(suites.scenarios_of(head_t, include_disabled=True))
    return {"before": len(on_a), "after": len(on_b), "removed": sorted(on_a - all_b),
            "switched_off": sorted((on_a - on_b) & all_b), "added": sorted(on_b - on_a)}


def coverage_delta(base_tree: str, head_tree: str, cssids: str | None) -> list[dict]:
    """Per line of business: product coverages the scenarios select on the branch tip that they did not
    at the merge-base (gained), and the other way round (lost). [] without a product model."""
    from eir_products import product_coverage
    base, head = product_coverage(base_tree, cssids), product_coverage(head_tree, cssids)
    if not base or not head:
        return []
    before = {l["line"]: {c["name"] for c in l["named"]} for l in base}
    out = []
    for l in head:
        now, was = {c["name"] for c in l["named"]}, before.get(l["line"], set())
        if now != was:
            out.append({"line": l["line"], "gained": sorted(now - was), "lost": sorted(was - now)})
    return out


def run_review(config, base_rev: str, head_rev: str, suppressions, cssids: str | None = None) -> int:
    """Run the branch review; returns the exit code (1 when a trust blocker is introduced)."""
    repo = config.repository_dir
    base_sha, head_sha = resolve_rev(repo, base_rev), resolve_rev(repo, head_rev)
    for name, sha in ((base_rev, base_sha), (head_rev, head_sha)):
        if sha is None:
            print(f"ERROR: '{name}' is not a branch, tag or commit in {repo}", file=sys.stderr)
            return 2
    start = merge_base(repo, base_sha, head_sha)
    if start is None:
        print(f"ERROR: {base_rev} and {head_rev} have no common history", file=sys.stderr)
        return 2
    changes, meta = compute_review(config, start, head_sha, base_rev, head_rev, suppressions, cssids)
    out_dir = os.path.join(repo, "healthcheck")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"Review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(changes, meta))
    print_review(changes, meta)
    print(f"  PR comment: {path}\n")
    return verdict(changes)[1]


def compute_review(config, start: str, head_sha: str, base_rev: str, head_rev: str, suppressions,
                   cssids: str | None = None) -> tuple[list[dict], dict]:
    """(finding changes, meta) between two commits; reads the repository only (git archive to a temp dir)."""
    repo = config.repository_dir
    paths = [config.source_root, "testdata"]
    import suite as suites
    suite_file = suites.find_suite_file(repo)
    suite_rel = os.path.relpath(suite_file, repo).replace("\\", "/") if os.path.isfile(suite_file) else None
    if suite_rel:
        paths.append(suite_rel)
    results = {}
    with tempfile.TemporaryDirectory(prefix="ct-review-") as tmp:
        for side, sha in (("base", start), ("head", head_sha)):
            tree = os.path.join(tmp, side)
            os.makedirs(tree)
            export_tree(repo, sha, tree, paths)
            print(f"  Analyzing {side} {sha[:8]}...")
            results[side] = analyze_tree(tree, config, suppressions)
        from eir_impact import changed_files, data_changes, rerun_plan, rerun_suite, run_commands, suite_command
        changed = changed_files(repo, start, head_sha)
        rerun = rerun_plan(os.path.join(tmp, "base"), os.path.join(tmp, "head"), changed, config.source_root)
        suite_name = f"Rerun-{head_sha[:8]}"
        # one test is one command already; a suite pays off from two
        suite_entries, idle = (rerun_suite(os.path.join(tmp, "head"), rerun, config.source_root)
                               if len(rerun) > 1 else ([], []))
        data = data_changes(os.path.join(tmp, "base"), os.path.join(tmp, "head"), changed)
        from eir_impact import suite_changes
        suites_changed = (suite_changes(os.path.join(tmp, "base"), os.path.join(tmp, "head"), suite_rel, config.source_root)
                          if suite_rel and suite_rel in changed else [])
        scope = run_scope(os.path.join(tmp, "base"), os.path.join(tmp, "head"), config.source_root)
        from eir_screens import find_cssids_dir
        product_dir = find_cssids_dir(repo, cssids)
        coverage = (coverage_delta(os.path.join(tmp, "base"), os.path.join(tmp, "head"), product_dir)
                    if product_dir and any(p.startswith("testdata/") for p in changed) else [])
    changes = diff_results(results["base"][0], results["head"][0])
    meta = {"base_name": base_rev, "head_name": head_rev,
            "base_short": start[:8], "head_short": head_sha[:8],
            "base_files": results["base"][1], "head_files": results["head"][1],
            "ruleset": ",".join(config.rules) if config.rules else config.ruleset,
            "rerun": rerun, "forwards": run_commands(repo), "changed": len(changed), "data": data,
            "suites": suites_changed, "coverage": coverage, "scope": scope,
            "rerun_suite": {"name": suite_name, "entries": suite_entries, "idle": idle,
                            "command": suite_command(repo, suite_name)} if suite_entries else None}
    return changes, meta
