"""
Portfolio: every client suite on one page.

Runs the active rules on each project's working tree (read-only: nothing is written into the
projects) and compares what a QA architect looks at first: the health score, trust blockers by
kind, the scenarios a full run executes, the wizards the suite opens per application, the product
coverages its scenarios select (from the generated product model), broken
data that tests run, and when the suite last changed. The page goes to
~/.centertest/reports/Portfolio_<timestamp>.html.
"""

from __future__ import annotations

import copy
import os
import subprocess
from datetime import datetime

from eir_models import LOCAL_COMMIT
from eir_parser import parse_directory
from eir_report import _html_escape, health_score, trust_blockers
from eir_rules import run_rules


def _last_change(path: str) -> str:
    r = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=path, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _clean_head(repo: str, source_root: str) -> str | None:
    """HEAD's sha when the tree's source and test data match it (nothing modified or untracked), else None."""
    import subprocess
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    head = run("rev-parse", "HEAD")
    if head.returncode != 0:
        return None
    status = run("status", "--porcelain", "--", source_root, "testdata")
    return head.stdout.strip() if status.returncode == 0 and not status.stdout.strip() else None


def analyze_project(path: str, config) -> dict:
    """Summary of one project, or {'path', 'error'} when it cannot be analysed."""
    from eir_data import data_overview
    from eir_locate import annotate_locations
    from eir_screens import find_cssids_dir, screen_coverage
    cfg = copy.copy(config)
    cfg.repository_dir = os.path.abspath(path)
    try:
        head = _clean_head(cfg.repository_dir, cfg.source_root)
        if head:  # committed content: the per-commit analysis cache applies (dirty trees are analysed fresh)
            from eir_review import analyze_commit
            results, n_files = analyze_commit(cfg.repository_dir, head, cfg.repository_dir, cfg, None)
            files = [None] * n_files
        else:
            files = parse_directory(cfg.repository_dir, cfg.source_root, cfg.exclude_packages,
                                    cfg.exclude_files, cfg.compat_comment_lines, None)
            if not files:
                return {"path": cfg.repository_dir, "error": f"no Java files under {cfg.source_root}"}
            results = run_rules({LOCAL_COMMIT: files}, cfg)
            annotate_locations(results, {LOCAL_COMMIT: files}, cfg.repository_dir)
        if not files:
            return {"path": cfg.repository_dir, "error": f"no Java files under {cfg.source_root}"}
        blockers, not_checked, dormant = trust_blockers(results)
        data = data_overview(cfg.repository_dir, cfg.source_root, results)
        cssids = find_cssids_dir(cfg.repository_dir)
        screens = screen_coverage(cfg.repository_dir, cfg.source_root, cssids) if cssids else []
        from eir_products import product_coverage
        products = product_coverage(cfg.repository_dir, cssids, cfg.source_root) if cssids else None
        from eir_cover import suite_breadth
        from eir_states import state_coverage
        states = state_coverage(cfg.repository_dir, cssids) if cssids else None
        reach = suite_breadth(cfg.repository_dir, cfg.source_root, cssids)
    except Exception as e:  # one broken project must not hide the others
        return {"path": cfg.repository_dir, "error": f"{type(e).__name__}: {e}"}
    return {
        "path": cfg.repository_dir, "name": suite_name(cfg.repository_dir),
        "score": health_score(results, len(files)), "files": len(files),
        "blockers": blockers, "not_checked": not_checked,
        "data": data, "screens": screens, "products": products, "changed": _last_change(cfg.repository_dir),
        "jurisdictions": sorted(set().union(*(l["states"] for l in states))) if states else None,
        "jurisdiction_lines": [(l["line"], len(l["states"])) for l in states] if states else [],
        "widest": _widest(reach),
    }


def _widest(rows) -> dict | None:
    """The suite reaching most of the full run (flows, then coverages), and the flows no suite runs."""
    if not rows or len(rows) < 2:
        return None
    full = rows[0]
    best = max(rows[1:], key=lambda r: (r["test"], r["coverage"], r["jurisdiction"]))
    share = lambda k: best[k] * 100 // full[k] if full[k] else None
    return {"suite": best["suite"], "flows": share("test"), "coverages": share("coverage"),
            "jurisdictions": share("jurisdiction"),
            "no_suite_flows": sum(1 for i in full.get("no_suite") or [] if i[0] == "test")}


def _widest_text(p: dict) -> list[str]:
    w = p.get("widest")
    if not w:
        return []
    parts = [f"{w['flows']}% of flows"] + ([f"{w['coverages']}% of coverages"] if w["coverages"] is not None else [])
    return [w["suite"], ", ".join(parts)] + ([f"{w['no_suite_flows']} flow(s) in no suite"] if w["no_suite_flows"] else [])


_GENERIC_NAMES = {"centertest", "tests", "test", "automation", "project", "src"}


def suite_name(path: str) -> str:
    """The folder name, with its parent when the name alone says nothing ("exavalu/CenterTest")."""
    path = os.path.abspath(path)
    name = os.path.basename(path)
    return f"{os.path.basename(os.path.dirname(path))}/{name}" if name.lower() in _GENERIC_NAMES else name


def _home(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def _wizards(p: dict) -> str:
    if not p.get("screens"):
        return "not measured (generated cssids/ not found)"
    parts = []
    for c in p.get("screens") or []:
        total = len(c["wizards"]) + len(c["unused_wizards"])
        if total:
            parts.append(f'{c["app"].upper()} {len(c["wizards"])}/{total}')
    return " · ".join(parts) if parts else "–"


def _products(p: dict, lines: int = 4) -> str:
    """'35/2135 (2%) · CA7 8/568 · GL7 7/432 ...': coverages the scenarios select, overall and per biggest line."""
    if not p.get("products"):
        return "not measured (no product model in the generated project)"
    total = sum(l["coverages"] for l in p["products"])
    chosen = sum(len(l["named"]) for l in p["products"])
    biggest = sorted(p["products"], key=lambda l: -l["coverages"])[:lines]
    short = lambda name: name[:-4] if name.endswith("Line") else name
    head = f"{chosen}/{total} ({round(100 * chosen / total) if total else 0}%)"
    return " · ".join([head] + [f'{short(l["line"])} {len(l["named"])}/{l["coverages"]}' for l in biggest])


def _products_cell(p: dict) -> str:
    if not p.get("products"):
        return '<span class="err">not measured</span>'
    head, *lines = _products(p).split(" · ")
    return _html_escape(head) + "".join(f'<div class="kind">{_html_escape(l)}</div>' for l in lines)


def _jurisdictions_cell(p: dict) -> str:
    j = p.get("jurisdictions")
    if j is None:
        return '<span class="err">not measured</span>'
    lines = p.get("jurisdiction_lines") or []  # widest first
    detail = "".join(f'<div class="kind">{_html_escape(line)} {n}</div>' for line, n in lines[:3])
    return f'{len(j)}{detail}'


def _widest_cell(p: dict) -> str:
    lines = _widest_text(p)
    if not lines:
        return '<span class="err">no suite file</span>'
    return _html_escape(lines[0]) + "".join(f'<div class="kind left">{_html_escape(l)}</div>' for l in lines[1:])


def render_html(projects: list[dict]) -> str:
    rows = []
    for p in projects:
        if p.get("error"):
            rows.append(f'<tr><td class="name">{_html_escape(suite_name(p["path"]))}</td>'
                        f'<td colspan="10" class="err">Not analysed: {_html_escape(p["error"])}</td></tr>')
            continue
        total = sum(b["count"] for b in p["blockers"])
        kinds = "".join(f'<div class="kind">{b["count"]} × {_html_escape(b["title"])}</div>' for b in p["blockers"])
        d = p["data"] or {}
        rows.append(
            f'<tr><td class="name">{_html_escape(p["name"])}<div class="path">{_html_escape(_home(p["path"]))}</div></td>'
            f'<td class="num score {"bad" if total else "ok"}">{p["score"]}</td>'
            f'<td class="num {"bad" if total else "ok"}">{total}{kinds}</td>'
            f'<td class="num">{d.get("scenarios", "–")}</td>'
            f'<td class="num">{"–" if d.get("broken_live") is None else d["broken_live"]}</td>'
            f'<td class="num">{len(d.get("unread", [])) if d else "–"}</td>'
            f'<td>{_wizards(p)}</td>'
            f'<td class="num">{_products_cell(p)}</td>'
            f'<td class="num">{_jurisdictions_cell(p)}</td>'
            f'<td class="widest">{_widest_cell(p)}</td>'
            f'<td class="num">{_html_escape(p["changed"])}</td></tr>')
    analysed = [p for p in projects if not p.get("error")]
    at_risk = sum(1 for p in analysed if p["blockers"])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CenterTest Portfolio</title>
<style>
  :root {{ --bg:#0f172a; --surface:#1e293b; --line:#334155; --text:#e2e8f0; --muted:#94a3b8;
    --accent:#60a5fa; --red:#f87171; --green:#4ade80; color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; line-height:1.5; }}
  .wrap {{ max-width:1480px; margin:0 auto; padding:32px 16px 48px; }}
  h1 {{ font-size:24px; margin:0 0 4px; }} h1 span {{ color:var(--accent); }}
  .lede {{ color:var(--muted); margin:0 0 24px; }}
  .table {{ overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:12px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ padding:10px 14px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
  th {{ color:var(--muted); font-weight:500; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  th.num {{ white-space:normal; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .name {{ font-weight:600; }} .path {{ font-weight:400; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }}
  .score {{ font-size:20px; font-weight:800; }}
  .bad {{ color:var(--red); }} .ok {{ color:var(--green); }}
  .kind {{ color:var(--muted); font-size:12px; font-weight:400; text-align:right; }}
  .kind.left {{ text-align:left; }}
  td.name {{ min-width:160px; }} td.widest {{ min-width:200px; }}
  .num .kind {{ white-space:normal; min-width:120px; }}
  .err {{ color:var(--muted); }}
</style></head><body><div class="wrap">
<h1><span>CenterTest</span> Portfolio</h1>
<p class="lede">{len(analysed)} suites analysed, {at_risk} at risk (a test that can pass while the application is broken,
or cannot run). Same rules for every suite; projects were only read. Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}.</p>
<div class="table"><table>
<thead><tr><th>Suite</th><th class="num">Score</th><th class="num">Trust blockers</th><th class="num">Scenarios per run</th>
<th class="num">Broken data tests run</th><th class="num">Unread workbooks</th><th>Wizards opened</th>
<th class="num">Coverages selected</th><th class="num">Jurisdictions</th><th>Widest suite</th>
<th class="num">Last change</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
</div></body></html>
"""


def print_portfolio(projects: list[dict]) -> None:
    print("\n" + "=" * 92)
    print(f"  {'Suite':<28} {'Score':>5} {'Blockers':>8} {'Scenarios':>9} {'Data':>5}  Wizards")
    print("=" * 92)
    for p in projects:
        name = suite_name(p["path"])[:28]
        if p.get("error"):
            print(f"  {name:<28} not analysed: {p['error']}")
            continue
        d = p["data"] or {}
        print(f"  {name:<28} {p['score']:>5} {sum(b['count'] for b in p['blockers']):>8} "
              f"{d.get('scenarios', '-'):>9} {'-' if d.get('broken_live') is None else d['broken_live']:>5}  {_wizards(p)}")
        print(f"  {'':<28} coverages selected: {_products(p)}")
        if p.get("jurisdictions") is not None:
            print(f"  {'':<28} jurisdictions: {len(p['jurisdictions'])}")
        if _widest_text(p):
            print(f"  {'':<28} widest suite: " + " - ".join(_widest_text(p)))
    print("=" * 92)


def run_portfolio(config, paths: list[str]) -> int:
    projects = []
    for path in paths:
        print(f"  Analysing {path} ...")
        projects.append(analyze_project(path, config))
    out_dir = os.path.expanduser("~/.centertest/reports")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"Portfolio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(projects))
    from eir_json import emit
    emit({"projects": projects})
    print_portfolio(projects)
    print(f"  Portfolio page: {out}\n")
    return 0
