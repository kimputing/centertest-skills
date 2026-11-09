"""
Trend: how the suite's health moved month by month.

Takes the last mainline commit (first parent of HEAD) of each of the last N months, exports it
with ``git archive`` (nothing is checked out), runs the active rules exactly as a local run
would, and records the health score, trust blockers, test classes and cases, and findings.
The result is an HTML page of small multiples (one chart per measure; they never share an
axis) with the table beneath, and the same table in the terminal.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime

from eir_report import _count_items, _html_escape, health_score, trust_blockers
from eir_review import analyze_tree, export_tree


def monthly_commits(repo_dir: str, months: int, rev: str = "HEAD") -> list[tuple[str, str, int]]:
    """[(YYYY-MM, sha, epoch)] for the last first-parent commit of each of the last `months` months
    that have commits, oldest first. The current month ends at rev itself."""
    r = subprocess.run(["git", "log", "--first-parent", rev, "--format=%H|%ct"],
                       cwd=repo_dir, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    by_month: dict[str, tuple[str, int]] = {}
    for line in r.stdout.split():
        sha, _, epoch = line.partition("|")
        if not epoch.isdigit():
            continue
        month = datetime.fromtimestamp(int(epoch)).strftime("%Y-%m")
        by_month.setdefault(month, (sha, int(epoch)))  # log is newest first: first seen = month's last
    chosen = sorted(by_month.items())[-months:]
    return [(month, sha, epoch) for month, (sha, epoch) in chosen]


def snapshot_metrics(results, files: int) -> dict:
    """The measures one snapshot contributes to the trend."""
    blockers, not_checked, dormant = trust_blockers(results)
    stats = next((r for r in results if r.rule_id == "0001" and r.rows), None)
    tests = cases = None
    if stats:
        row = dict(zip(stats.headers, stats.rows[-1]))
        tests, cases = row.get("Test Classes"), row.get("Test Cases")
    return {
        "score": health_score(results, files),
        "blockers": sum(b["count"] for b in blockers),
        "dormant": dormant,
        "findings": sum(_count_items(r) for r in results if r.category != "Statistics" and not r.error),
        "tests": tests, "cases": cases, "files": files,
        "not_checked": not_checked,
    }


def collect(config, months: int, suppressions, product_dir: str | None = None) -> list[dict]:
    """One point per month; with a generated product model, also the coverages its scenarios select
    (that month's test data against today's product model)."""
    points = []
    with tempfile.TemporaryDirectory(prefix="ct-trend-") as tmp:
        for month, sha, epoch in monthly_commits(config.repository_dir, months):
            tree = os.path.join(tmp, sha[:12])
            os.makedirs(tree)
            export_tree(config.repository_dir, sha, tree, [config.source_root, "testdata"])
            print(f"  {month}  {sha[:8]}  analyzing...")
            results, files = analyze_tree(tree, config, suppressions)
            point = snapshot_metrics(results, files)
            point.update(month=month, sha=sha[:8], date=datetime.fromtimestamp(epoch).strftime("%Y-%m-%d"))
            point["coverages"] = None
            if product_dir:
                from eir_products import product_coverage
                lines = product_coverage(tree, product_dir, config.source_root)
                point["coverages"] = sum(len(l["named"]) for l in lines) if lines else None
            points.append(point)
    return points


# --- Rendering --------------------------------------------------------------------

_W, _H, _PAD_L, _PAD_R, _PAD_T, _PAD_B = 340, 170, 40, 44, 14, 26


def _nice_max(value: float) -> float:
    """Axis top for gridlines at thirds: 3 x the smallest 1/2/3/5 x 10^k step that covers value."""
    magnitude = 1
    while True:
        for base in (1, 2, 3, 5):
            if 3 * base * magnitude >= value:
                return 3 * base * magnitude
        magnitude *= 10


def _chart(title: str, unit: str, points: list[dict], key: str, fixed_max: float | None = None,
           divisions: int = 3) -> str:
    """One single-series line chart as inline SVG: recessive grid, 2px line, ringed markers,
    the last value labelled, a hover tooltip per point."""
    values = [p[key] for p in points]
    known = [v for v in values if v is not None]
    if not known:
        return f'<figure class="chart"><figcaption>{_html_escape(title)}</figcaption><p class="none">Not measured in this run.</p></figure>'
    top = fixed_max if fixed_max is not None else _nice_max(max(known))
    plot_w, plot_h = _W - _PAD_L - _PAD_R, _H - _PAD_T - _PAD_B
    n = len(points)

    def x(i):
        return _PAD_L + (plot_w / 2 if n == 1 else plot_w * i / (n - 1))

    def y(v):
        return _PAD_T + plot_h - plot_h * (v / top if top else 0)

    parts = [f'<svg viewBox="0 0 {_W} {_H}" role="img" aria-label="{_html_escape(title)} by month">']
    for k in range(divisions + 1):  # gridlines from 0 to top
        v = top * k / divisions
        gy = y(v)
        label = f"{v:.0f}" if top >= 3 else f"{v:.1f}"
        parts.append(f'<line class="grid" x1="{_PAD_L}" x2="{_W - _PAD_R}" y1="{gy:.1f}" y2="{gy:.1f}"/>'
                     f'<text class="tick" x="{_PAD_L - 6}" y="{gy + 4:.1f}" text-anchor="end">{label}</text>')
    for i, p in enumerate(points):
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{_H - 8}" text-anchor="middle">{p["month"][2:]}</text>')
    path = " ".join(f'{"M" if j == 0 else "L"}{x(i):.1f},{y(v):.1f}'
                    for j, (i, v) in enumerate((i, v) for i, v in enumerate(values) if v is not None))
    parts.append(f'<path class="line" d="{path}"/>')
    for i, (p, v) in enumerate(zip(points, values)):
        if v is None:
            continue
        tip = f'{p["month"]} ({p["sha"]}): {v}{unit}'
        parts.append(f'<g class="pt"><title>{_html_escape(tip)}</title>'
                     f'<circle class="hit" cx="{x(i):.1f}" cy="{y(v):.1f}" r="12"/>'
                     f'<circle class="dot" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4"/></g>')
    last_i = max(i for i, v in enumerate(values) if v is not None)
    parts.append(f'<text class="end" x="{x(last_i) + 8:.1f}" y="{y(values[last_i]) + 4:.1f}">{values[last_i]}</text>')
    parts.append("</svg>")
    return f'<figure class="chart"><figcaption>{_html_escape(title)}</figcaption>{"".join(parts)}</figure>'


def render_html(points: list[dict], project: str) -> str:
    first, last = points[0], points[-1]
    rows = "".join(
        f'<tr><td>{p["month"]}</td><td class="mono">{p["sha"]}</td><td>{p["score"]}</td>'
        f'<td class="{"bad" if p["blockers"] else ""}">{p["blockers"]}</td><td>{p["dormant"]}</td>'
        f'<td>{p["tests"] if p["tests"] is not None else "–"}</td><td>{p["cases"] if p["cases"] is not None else "–"}</td>'
        f'<td>{"–" if p.get("coverages") is None else p["coverages"]}</td>'
        f'<td>{p["findings"]}</td><td>{p["files"]}</td></tr>' for p in points)
    unchecked = sorted({r for p in points for r in p["not_checked"]})
    note = (f'<p class="note">Trust rules not in this ruleset, so not counted: {", ".join(unchecked)}. '
            'Use --ruleset CenterTestFull for complete blockers.</p>') if unchecked else ""
    headline = (f'Score {first["score"]} → {last["score"]}, trust blockers {first["blockers"]} → {last["blockers"]}'
                + (f', test cases {first["cases"]} → {last["cases"]}' if last["cases"] is not None else "")
                + (f', coverages selected {first["coverages"]} → {last["coverages"]}'
                   if first.get("coverages") is not None and last.get("coverages") is not None else "")
                + f' between {first["month"]} and {last["month"]}.')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CenterTest Health Trend — {_html_escape(project)}</title>
<style>
  :root {{ --bg:#0f172a; --surface:#1e293b; --line:#334155; --text:#e2e8f0; --muted:#94a3b8;
    --accent:#60a5fa; --red:#f87171; color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; line-height:1.5; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:32px 16px 48px; }}
  h1 {{ font-size:24px; margin:0 0 4px; }} h1 span {{ color:var(--accent); }}
  .lede {{ color:var(--muted); margin:0 0 24px; }}
  .grid3 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }}
  .chart {{ margin:0; background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:14px 16px 8px; min-width:0; }}
  figcaption {{ font-weight:600; font-size:15px; margin-bottom:4px; }}
  svg {{ width:100%; height:auto; display:block; }}
  .grid {{ stroke:var(--line); stroke-width:1; }}
  .tick {{ fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }}
  .end {{ fill:var(--text); font-size:12px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .line {{ fill:none; stroke:var(--accent); stroke-width:2; stroke-linejoin:round; }}
  .dot {{ fill:var(--accent); stroke:var(--surface); stroke-width:2; }}
  .hit {{ fill:transparent; }}
  .pt:hover .dot {{ r:6; }}
  .none {{ color:var(--muted); font-size:14px; }}
  .table {{ overflow-x:auto; margin-top:24px; background:var(--surface); border:1px solid var(--line); border-radius:12px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }}
  th, td {{ text-align:right; padding:8px 14px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align:left; }}
  th {{ color:var(--muted); font-weight:500; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  td.bad {{ color:var(--red); font-weight:600; }} .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .note {{ color:var(--muted); font-size:13px; }}
</style></head><body><div class="wrap">
<h1><span>CenterTest</span> Health Trend</h1>
<p class="lede">{_html_escape(project)} · {_html_escape(headline)} One mainline commit per month, analysed with the same rules.</p>
<div class="grid3">
{_chart("Health score", "", points, "score", fixed_max=100, divisions=4)}
{_chart("Trust blockers", "", points, "blockers")}
{_chart("Test cases", "", points, "cases")}
{_chart("Product coverages selected", "", points, "coverages") if any(p.get("coverages") is not None for p in points) else ""}
</div>
<div class="table"><table>
<thead><tr><th>Month</th><th>Commit</th><th>Score</th><th>Trust blockers</th><th>Not run</th><th>Test classes</th><th>Test cases</th><th>Coverages selected</th><th>Findings</th><th>Java files</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{note}
<p class="note">Generated {datetime.now().strftime("%Y-%m-%d %H:%M")} by centertest-healthcheck --trend.</p>
</div></body></html>
"""


def print_trend(points: list[dict]) -> None:
    print("\n" + "=" * 72)
    print("  HEALTH TREND (last mainline commit of each month)")
    print("=" * 72)
    print(f"  {'Month':<8} {'Commit':<9} {'Score':>5} {'Blockers':>8} {'Tests':>6} {'Cases':>6} {'Covs':>5} {'Findings':>8}")
    for p in points:
        print(f"  {p['month']:<8} {p['sha']:<9} {p['score']:>5} {p['blockers']:>8} "
              f"{p['tests'] if p['tests'] is not None else '-':>6} {p['cases'] if p['cases'] is not None else '-':>6} "
              f"{'-' if p.get('coverages') is None else p['coverages']:>5} {p['findings']:>8}")
    print("=" * 72)


def run_trend(config, months: int, suppressions, cssids: str | None = None) -> int:
    from eir_screens import find_cssids_dir
    points = collect(config, months, suppressions, find_cssids_dir(config.repository_dir, cssids))
    if not points:
        print("  No commits found: --trend needs a git repository with history.")
        return 2
    out_dir = os.path.join(config.repository_dir, "healthcheck")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"Trend_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(points, os.path.basename(os.path.abspath(config.repository_dir))))
    print_trend(points)
    print(f"  Trend page: {path}\n")
    return 0
