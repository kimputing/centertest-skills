"""
"Since your last check": each local health check saves a small summary next to its reports
(healthcheck/last-run.json) and compares itself with the previous one: score, live trust blockers,
scenarios per run, product coverages selected, flows that run, jurisdictions, and the findings added
and fixed -- keyed the way --review keys them (eir_review._findings), so a moved row or a grown count is
not "new". Flows and line/jurisdiction pairs are kept by name, so the ones that left are named.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

FILE = "last-run.json"


def flows_running(repo_dir: str, source_root: str) -> list[str] | None:
    """'Class.method' of every test method that runs at least one scenario (vendored suite engine)."""
    try:
        import suite as suites
        return sorted({f"{c}.{m}" for c, m, _code in suites.scenarios_of(suites.scan(repo_dir, source_root))})
    except Exception:
        return None


def snapshot(results, files: int, data=None, products=None, states=None, flows=None) -> dict:
    from eir_report import TRUST_RULES, health_score, trust_blockers
    from eir_review import _INFORMATIONAL, _findings
    blockers, _not_checked, _dormant = trust_blockers(results)
    findings, labels = {}, {}
    for r in results:
        if r.error or r.category in _INFORMATIONAL:  # statistics are not findings, as in --review
            continue
        keys: dict[str, int] = {}
        for key, label in _findings(r):
            k = json.dumps(key, default=str)
            keys[k] = keys.get(k, 0) + 1
            labels.setdefault(r.rule_id, {}).setdefault(k, label)
        findings[r.rule_id] = keys
    return {
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "score": health_score(results, files),
        "blockers": sum(b["count"] for b in blockers),
        "scenarios": (data or {}).get("scenarios"),
        "coverages": sum(len(l["named"]) for l in products) if products else None,
        "flows": flows,
        "jurisdictions": sorted(f"{l['line']} {s}" for l in states for s in l["states"]) if states else None,
        "findings": findings, "labels": labels,
        "titles": {r.rule_id: (TRUST_RULES.get(r.rule_id, (None,))[0] or r.description) for r in results},
        "trust": sorted(rid for rid in findings if rid in TRUST_RULES),
    }


def compare(prev: dict, now: dict) -> dict:
    """What changed from the previous snapshot: [(rule, title, label, trust)] added and fixed."""
    added, fixed = [], []
    for rid in sorted(set(prev.get("findings", {})) & set(now["findings"])):  # a rule absent on one side: unknown
        a, b = prev["findings"][rid], now["findings"][rid]
        trust = rid in now.get("trust", [])
        for k, n in b.items():
            for _ in range(max(0, n - a.get(k, 0))):
                added.append((rid, now["titles"].get(rid, rid), now["labels"].get(rid, {}).get(k, k), trust))
        for k, n in a.items():
            for _ in range(max(0, n - b.get(k, 0))):
                fixed.append((rid, prev.get("titles", {}).get(rid, rid), prev.get("labels", {}).get(rid, {}).get(k, k), trust))
    # the same finding whose details changed (a count, a call list) is neither added nor fixed
    for item in [a for a in added if (a[0], a[2]) in {(f[0], f[2]) for f in fixed}]:
        added.remove(item)
        fixed.remove(next(f for f in fixed if (f[0], f[2]) == (item[0], item[2])))
    added.sort(key=lambda x: (not x[3], x[0]))
    fixed.sort(key=lambda x: (not x[3], x[0]))
    count = lambda snap, k: None if snap.get(k) is None else len({j.rsplit(" ", 1)[-1] for j in snap[k]}
                                                                  if k == "jurisdictions" else snap[k])
    lost = [("flow", f) for f in sorted(set(prev.get("flows") or []) - set(now.get("flows") or []))
            if now.get("flows") is not None]
    lost += [("jurisdiction", j) for j in sorted(set(prev.get("jurisdictions") or []) - set(now.get("jurisdictions") or []))
             if now.get("jurisdictions") is not None]
    return {"when": prev.get("when"), "score": (prev.get("score"), now["score"]),
            "blockers": (prev.get("blockers"), now["blockers"]),
            "scenarios": (prev.get("scenarios"), now["scenarios"]),
            "coverages": (prev.get("coverages"), now["coverages"]),
            "flows": (count(prev, "flows"), count(now, "flows")),
            "jurisdictions": (count(prev, "jurisdictions"), count(now, "jurisdictions")),
            "lost": lost, "added": added, "fixed": fixed}


def since_last(output_dir: str, now: dict) -> dict | None:
    """Compare with the previous run's summary (None on a first run), then save this one."""
    path = os.path.join(output_dir, FILE)
    prev = None
    try:
        with open(path, encoding="utf-8") as fh:
            prev = json.load(fh)
    except (OSError, ValueError):
        pass
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(now, fh)
    return compare(prev, now) if prev else None


def _arrow(pair) -> str:
    a, b = pair
    if a is None or b is None:
        return "–"
    return f"{a} → {b}" if a != b else f"{b} (same)"


def print_since(d: dict) -> None:
    print(f"  SINCE YOUR LAST CHECK ({d['when']}): score {_arrow(d['score'])}, trust blockers {_arrow(d['blockers'])}, "
          f"{len(d['added'])} finding(s) added, {len(d['fixed'])} fixed")
    for rid, title, label, trust in d["added"][:6]:
        print(f"      {'!!' if trust else '+ '} {rid} {title}: {label}")
    if d.get("flows", (None, None)) != (None, None) or d.get("jurisdictions", (None, None)) != (None, None):
        print(f"      flows that run {_arrow(d.get('flows', (None, None)))}, "
              f"jurisdictions {_arrow(d.get('jurisdictions', (None, None)))}")
    for kind, name in (d.get("lost") or [])[:8]:
        print(f"      -- {'no longer runs' if kind == 'flow' else 'line no longer runs in'}: {name}")


def panel_html(d: dict | None, esc) -> str:
    if not d:
        return ""
    tiles = [("Score", _arrow(d["score"])), ("Trust blockers", _arrow(d["blockers"])),
             ("Scenarios per run", _arrow(d["scenarios"])), ("Coverages selected", _arrow(d["coverages"]))]
    tiles += [(label, _arrow(d[k])) for k, label in (("flows", "Flows that run"), ("jurisdictions", "Jurisdictions"))
              if d.get(k, (None, None)) != (None, None)]
    cells = "".join(f'<div class="data-tile"><div class="data-big" style="font-size:22px">{esc(v)}</div>'
                    f'<div class="data-label">{esc(k)}</div></div>' for k, v in tiles)

    def items(rows, mark):
        shown = "".join(f'<li>{"⛔ " if trust else ""}<b>{esc(rid)}</b> {esc(title)}: <code>{esc(str(label))}</code></li>'
                        for rid, title, label, trust in rows[:8])
        more = f"<li>… and {len(rows) - 8} more</li>" if len(rows) > 8 else ""
        return f'<div class="data-sub">{mark} {len(rows)}</div><ul class="since">{shown}{more}</ul>' if rows else ""

    return (f'  <div class="data"><h2>Since your last check</h2><p class="screens-note">Compared with the health check '
            f'of {esc(d["when"] or "–")} (healthcheck/{FILE}).</p><div class="data-grid">{cells}</div>'
            f'{_lost_html(d.get("lost") or [], esc)}{items(d["added"], "Added")}{items(d["fixed"], "Fixed")}</div>\n')


def _lost_html(lost: list, esc) -> str:
    if not lost:
        return ""
    shown = "".join(f'<li>{"No longer runs" if kind == "flow" else "Line no longer runs in"}: <code>{esc(name)}</code></li>'
                    for kind, name in lost[:8])
    more = f"<li>… and {len(lost) - 8} more</li>" if len(lost) > 8 else ""
    return f'<div class="data-sub">Left the run {len(lost)}</div><ul class="since">{shown}{more}</ul>'
