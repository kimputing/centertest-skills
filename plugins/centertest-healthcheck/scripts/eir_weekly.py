"""
--weekly PROJECT...: what landed in each client suite in the last N days (--days, default 7).

Per project: the mainline (first-parent) commit N days ago against HEAD, run through the branch
review (eir_review.compute_review, read only: git archive into a temp dir): commits landed, the
verdict, new trust blockers, findings added and fixed, product coverages no scenario selects any
more, data rows changed and the tests to rerun. Quiet suites are listed as quiet. One page in
~/.centertest/reports/Weekly_<timestamp>.html; nothing is written to the projects.
"""

from __future__ import annotations

import copy
import os
import subprocess
from datetime import datetime

from eir_report import _html_escape


def _git(repo: str, *args) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _authors(who: dict) -> list[tuple[str, int]]:
    """[(author, trust blockers attributed)] most first."""
    count: dict[str, int] = {}
    for author, _when, _sha, how in who.values():
        if how != "older":  # a line written before the week did not introduce the finding
            count[author] = count.get(author, 0) + 1
    return sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))


def week_of(path: str, config, days: int, cssids: str | None = None) -> dict:
    """Summary of the last `days` days of one project, or {'path', 'error'}."""
    from eir_portfolio import suite_name
    from eir_review import compute_review, verdict
    repo = os.path.abspath(path)
    out = {"path": repo, "name": suite_name(repo)}
    head = _git(repo, "rev-parse", "HEAD")
    if not head:
        return dict(out, error="not a git repository with commits")
    since = _git(repo, "rev-list", "-1", "--first-parent", f"--before={days} days ago", "HEAD")
    out["landed"] = int(_git(repo, "rev-list", "--count", "--first-parent", f"{since}..HEAD" if since else "HEAD") or 0)
    out["last"] = _git(repo, "log", "-1", "--format=%ad", "--date=short", "HEAD")
    if not since or out["landed"] == 0:
        return out
    cfg = copy.copy(config)
    cfg.repository_dir = repo
    try:
        from eir_screens import _belongs_to
        # one --cssids for several projects: only the project it was generated for gets it (the others find
        # their own <project>-generated); another client's model would report coverages they never had
        own = cssids if cssids and _belongs_to(repo, cssids) else None
        changes, meta = compute_review(cfg, since, head, f"{days} days ago", "HEAD", None, own)
    except Exception as e:  # one broken project must not hide the others
        return dict(out, error=f"{type(e).__name__}: {e}")
    line, code = verdict(changes)
    line = line.replace("this branch introduces", "these commits introduce").replace("this branch may", "these commits may")
    out.update(
        since=since[:8], head=head[:8], verdict=line, blocked=code != 0,
        blockers=[(c["trust"] or c["description"], c["blocking"]) for c in changes if c.get("blocking")],
        added=sum(len(c["introduced"]) for c in changes), fixed=sum(len(c["fixed"]) for c in changes),
        lost=[(c["line"], n) for c in meta.get("coverage") or [] for n in c["lost"]],
        gained=sum(len(c["gained"]) for c in meta.get("coverage") or []),
        rows=sum(len(d["added"]) + len(d["changed"]) + len(d["removed"]) for d in meta.get("data") or []),
        rerun=len(meta.get("rerun") or []), changed=meta.get("changed", 0), scope=meta.get("scope"),
        authors=_authors(meta.get("blame") or {}),
        flows=[s["test"] for s in (meta.get("scope") or {}).get("flows_stopped") or []],
        states_lost=[(s["line"], j) for s in meta.get("states") or [] for j in s["lost"]],
        not_offered=[(c["line"], f'{n["coverage"]} / {n["term"]} = {n["value"]}')
                     for c in meta.get("coverage") or [] for n in c.get("not_offered") or []],
        options_lost=[(c["line"], o) for c in meta.get("coverage") or [] for o in c.get("options_lost") or []])
    return out


def _lost(w: dict) -> str:
    """'What the run lost' cell: flows that no longer run, coverages no scenario selects, jurisdictions a line
    no longer runs in, and term values the product does not offer, newest damage first."""
    parts = [("flow no longer runs", [f for f in w.get("flows", [])]),
             ("coverage no scenario selects", [f"{l}: {c}" for l, c in w.get("lost", [])]),
             ("line no longer runs in", [f"{l}: {j}" for l, j in w.get("states_lost", [])]),
             ("option no scenario sets", [f"{l}: {o}" for l, o in w.get("options_lost", [])]),
             ("not an option", [f"{l}: {v}" for l, v in w.get("not_offered", [])])]
    total = sum(len(items) for _k, items in parts)
    detail = "".join(f'<div class="kind">{_html_escape(kind)}: {_html_escape(", ".join(items[:4]))}'
                     f'{" +" + str(len(items) - 4) if len(items) > 4 else ""}</div>' for kind, items in parts if items)
    return (f'<td class="num {"bad" if total else ""}">{total} lost, {w["gained"]} coverage{"" if w["gained"] == 1 else "s"} gained{detail}</td>')


def _scope(w: dict) -> str:
    s = w.get("scope")
    if not s:
        return "–"
    gone = len(s["removed"]) + len(s["switched_off"])
    tail = f'<div class="kind {"bad" if gone else ""}">−{gone} removed or off, +{len(s["added"])}</div>'
    return f'{s["before"]} → {s["after"]}{tail}'


def render_html(weeks: list[dict], days: int) -> str:
    rows = []
    for w in weeks:
        name = (f'<td class="name">{_html_escape(w["name"])}'
                f'<div class="path">last commit {_html_escape(w.get("last") or "–")}</div></td>')
        if w.get("error"):
            rows.append(f'<tr>{name}<td colspan="7" class="muted">Not analysed: {_html_escape(w["error"])}</td></tr>')
            continue
        if not w.get("verdict"):
            rows.append(f'<tr>{name}<td colspan="7" class="muted">Quiet: nothing landed in {days} days</td></tr>')
            continue
        blockers = "".join(f'<div class="kind">{n} × {_html_escape(t)}</div>' for t, n in w["blockers"])
        if w.get("authors"):
            blockers += '<div class="kind">introduced by ' + ", ".join(
                f"{_html_escape(a)} ({n})" for a, n in w["authors"]) + "</div>"
        rows.append(
            f'<tr>{name}<td class="num">{w["landed"]}<div class="kind">{w["since"]}..{w["head"]}</div></td>'
            f'<td class="{"bad" if w["blocked"] else "ok"}">{_html_escape(w["verdict"])}{blockers}</td>'
            f'<td class="num">+{w["added"]} / −{w["fixed"]}</td>'
            f'{_lost(w)}'
            f'<td class="num">{w["rows"]}</td><td class="num">{_scope(w)}</td><td class="num">{w["rerun"]}</td></tr>')
    busy = [w for w in weeks if w.get("verdict")]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CenterTest Weekly</title>
<style>
  :root {{ --bg:#0f172a; --surface:#1e293b; --line:#334155; --text:#e2e8f0; --muted:#94a3b8;
    --accent:#60a5fa; --red:#f87171; --green:#4ade80; color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; line-height:1.5; }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:32px 16px 48px; }}
  h1 {{ font-size:24px; margin:0 0 4px; }} h1 span {{ color:var(--accent); }}
  .lede {{ color:var(--muted); margin:0 0 24px; }}
  .table {{ overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:12px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ padding:10px 14px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
  th {{ color:var(--muted); font-weight:500; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .name {{ font-weight:600; }} .path {{ font-weight:400; color:var(--muted); font-size:12px; }}
  .bad {{ color:var(--red); }} .ok {{ color:var(--green); }} .muted {{ color:var(--muted); }}
  .kind {{ color:var(--muted); font-size:12px; font-weight:400; }}
</style></head><body><div class="wrap">
<h1><span>CenterTest</span> Weekly</h1>
<p class="lede">The last {days} days of {len(weeks)} suites: {len(busy)} with changes. Each is the mainline commit {days} days
ago against HEAD, run through the branch review; projects were only read. Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}.</p>
<div class="table"><table>
<thead><tr><th>Suite</th><th class="num">Commits</th><th>Verdict</th><th class="num">Findings added / fixed</th>
<th class="num">What the run lost</th><th class="num">Data rows changed</th><th class="num">Scenarios per run</th>
<th class="num">Tests to rerun</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
</div></body></html>
"""


def print_weekly(weeks: list[dict], days: int) -> None:
    print("\n" + "=" * 92)
    print(f"  WEEKLY: last {days} days")
    print("=" * 92)
    for w in weeks:
        if w.get("error"):
            print(f"  {w['name']:<28} not analysed: {w['error']}")
        elif not w.get("verdict"):
            print(f"  {w['name']:<28} quiet (last commit {w.get('last') or '-'})")
        else:
            print(f"  {w['name']:<28} {w['landed']} commit(s)  {w['verdict']}")
            for t, n in w["blockers"]:
                print(f"  {'':<28} !! {n} x {t}")
            if w.get("authors"):
                print(f"  {'':<28}    introduced by " + ", ".join(f"{a} ({n})" for a, n in w["authors"]))
            for label, items in (("flows that no longer run", w.get("flows", [])),
                                 ("coverages no scenario selects any more", [f"{l}: {c}" for l, c in w["lost"]]),
                                 ("lines no longer run in", [f"{l}: {j}" for l, j in w.get("states_lost", [])]),
                                 ("options no scenario sets", [f"{l}: {o}" for l, o in w.get("options_lost", [])]),
                                 ("values not an option", [f"{l}: {v}" for l, v in w.get("not_offered", [])])):
                if items:
                    print(f"  {'':<28} -- {label}: " + ", ".join(items[:4]) + (" ..." if len(items) > 4 else ""))
            s = w.get("scope") or {}
            print(f"  {'':<28} findings +{w['added']}/-{w['fixed']}, data rows {w['rows']}, rerun {w['rerun']} test(s)"
                  + (f", scenarios {s['before']} -> {s['after']} ({len(s['removed'])} removed, "
                     f"{len(s['switched_off'])} switched off)" if s else ""))
    print("=" * 92)


def run_weekly(config, paths: list[str], days: int, cssids: str | None = None) -> int:
    weeks = []
    for path in paths:
        print(f"  {path} ...")
        weeks.append(week_of(path, config, days, cssids))
    out_dir = os.path.join(os.path.expanduser("~"), ".centertest", "reports")
    os.makedirs(out_dir, exist_ok=True)
    page = os.path.join(out_dir, f"Weekly_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(render_html(weeks, days))
    from eir_json import emit
    emit({"days": days, "page": page, "suites": weeks})
    print_weekly(weeks, days)
    print(f"  Weekly page: {page}\n")
    return 0
