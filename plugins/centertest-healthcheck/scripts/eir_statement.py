"""
--statement: a one-page coverage statement for the client - what the regression exercises, without the
code findings. Built from the same measures as the health check: flows that run and scenarios per full
run (suite engine), product coverages and term options the scenarios select (eir_products), the
jurisdictions each line runs in (eir_states), how much each suite reaches (eir_cover) and the known gaps
(coverages no scenario selects, flows in no suite, values that are not an option). Read only; the page
goes to healthcheck/Coverage_Statement_<timestamp>.html.
"""

from __future__ import annotations

import html
import os
import subprocess
from datetime import datetime

esc = html.escape


def gather(repo_dir: str, source_root: str, cssids_dir: str | None) -> dict:
    from eir_cover import suite_breadth
    from eir_products import product_coverage
    from eir_since import flows_running
    from eir_states import state_coverage
    import suite as suites
    tests = suites.scan(repo_dir, source_root)
    head = subprocess.run(["git", "-C", repo_dir, "log", "-1", "--format=%h %ad", "--date=short"],
                          capture_output=True, text=True).stdout.strip()
    return {"project": os.path.basename(os.path.abspath(repo_dir)), "commit": head,
            "flows": flows_running(repo_dir, source_root) or [],
            "scenarios": len(suites.scenarios_of(tests)),
            "products": product_coverage(repo_dir, cssids_dir, source_root) if cssids_dir else None,
            "states": state_coverage(repo_dir, cssids_dir) if cssids_dir else None,
            "suites": suite_breadth(repo_dir, source_root, cssids_dir)}


def _options(line: dict) -> str:
    """'4 of 19' option values set on a line's selected coverages; '–' for a line without option terms."""
    return f'{line.get("options_chosen", 0)} of {line["options_total"]}' if line.get("options_total") else "–"


def render(s: dict) -> str:
    products = s["products"] or []
    named = sum(len(l["named"]) for l in products)
    in_model = sum(l["coverages"] for l in products)
    options = sum(l.get("options_chosen", 0) for l in products)
    option_total = sum(l.get("options_total", 0) for l in products)
    every_state = sorted(set().union(*(l["states"] for l in s["states"] or [])))
    figures = [(len(s["flows"]), "flows (test methods) run in a full regression"),
               (s["scenarios"], "distinct scenarios (a row a Multiplier repeats counts once)")]
    if s["products"] is not None:
        figures.append((f"{named} of {in_model}", "product coverages the scenarios select"))
        if option_total:
            figures.append((f"{options} of {option_total}", "limit and deductible options set, on those coverages"))
    if s["states"] is not None:
        figures.append((len(every_state), "jurisdictions the scenarios run in"))
    fig_html = "".join(f'<div class="fig"><b>{esc(str(v))}</b><span>{esc(k)}</span></div>' for v, k in figures)

    line_rows = "".join(
        f'<tr><td>{esc(l["line"])}</td><td class="n">{len(l["named"])} of {l["coverages"]}</td>'
        f'<td class="n">{_options(l)}</td>'
        f'<td>{esc(", ".join(c["name"] for c in l["named"][:8]))}{" …" if len(l["named"]) > 8 else ""}</td></tr>'
        for l in sorted(products, key=lambda l: -len(l["named"])) if l["named"])
    lines_html = (f'<h2>Product coverages by line</h2><table><thead><tr><th>Line</th><th class="n">Coverages selected</th>'
                  f'<th class="n">Options set</th><th>Selected (first eight)</th></tr></thead><tbody>{line_rows}</tbody>'
                  f'</table>') if line_rows else ""

    state_rows = "".join(f'<tr><td>{esc(l["line"])}</td><td class="n">{len(l["states"])}</td>'
                         f'<td>{esc(", ".join(l["states"]))}</td></tr>' for l in s["states"] or [])
    states_html = (f'<h2>Jurisdictions by line</h2><table><thead><tr><th>Line</th><th class="n">Count</th>'
                   f'<th>Jurisdictions</th></tr></thead><tbody>{state_rows}</tbody></table>') if state_rows else ""

    suites_html = ""
    if s["suites"] and len(s["suites"]) > 1:
        full = s["suites"][0]
        ranked = sorted((r for r in s["suites"][1:] if r["scenarios"]), key=lambda r: (-r["test"], -r["coverage"]))[:6]
        pct = lambda r, k: f'{r[k] * 100 // full[k]}%' if full[k] else "–"
        rows = "".join(f'<tr><td>{esc(r["suite"])}</td><td class="n">{r["scenarios"]}</td><td class="n">{pct(r, "test")}</td>'
                       f'<td class="n">{pct(r, "coverage")}</td><td class="n">{pct(r, "jurisdiction")}</td></tr>' for r in ranked)
        suites_html = (f'<h2>Suites</h2><p>The suites that run most of it, as a share of the full regression.</p>'
                       f'<table><thead><tr><th>Suite</th><th class="n">Scenarios</th><th class="n">Flows</th>'
                       f'<th class="n">Coverages</th><th class="n">Jurisdictions</th></tr></thead><tbody>{rows}</tbody></table>')

    gaps = []
    if s["products"] is not None and in_model:
        # a line no scenario touches is a different statement from coverages missing on a line that is tested
        tested = [l for l in products if l["named"]]
        untested = sorted((l for l in products if not l["named"]), key=lambda l: -l["coverages"])
        on_tested = sum(l["coverages"] for l in tested)
        if tested:
            gaps.append(f"On the {len(tested)} line(s) the scenarios test, {on_tested - named} of {on_tested} coverages "
                        "are not selected by any scenario.")
        if untested:
            gaps.append(f"{len(untested)} line(s) of the product model no scenario tests: "
                        + ", ".join(f'{l["line"]} ({l["coverages"]} coverages)' for l in untested[:6])
                        + (", …" if len(untested) > 6 else "."))
    not_offered = [n for l in products for n in l.get("not_offered", [])]
    if not_offered:
        gaps.append(f"{len(not_offered)} limit or deductible value(s) in the test data are not an option in the product: "
                    + "; ".join(f'{n["coverage"]} / {n["term"]} = {n["value"]}' for n in not_offered[:4]) + ".")
    if s["suites"]:
        flows = [i[1] for i in s["suites"][0].get("no_suite") or [] if i[0] == "test"]
        if flows:
            gaps.append(f"{len(flows)} flow(s) run only in a full regression, in no suite: {', '.join(flows[:6])}"
                        + (", …" if len(flows) > 6 else "."))
    gaps_html = ('<h2>Known gaps</h2><ul>' + "".join(f"<li>{esc(g)}</li>" for g in gaps) + '</ul>') if gaps else ""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Regression coverage — {esc(s["project"])}</title>
<style>
  :root {{ --bg:#fbfaf7; --text:#1d2433; --muted:#5d6678; --line:#dcd8cf; --accent:#1f5f8b; --card:#ffffff; color-scheme: light; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171d; --text:#e6e8ec; --muted:#9aa3b2; --line:#2c323d;
    --accent:#7cb4dc; --card:#1b1f27; color-scheme: dark; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.55 "Iowan Old Style","Charter",Georgia,serif; }}
  main {{ max-width:960px; margin:0 auto; padding:40px 16px 56px; }}
  h1 {{ font-size:30px; line-height:1.2; margin:0 0 6px; text-wrap:balance; }}
  h2 {{ font-size:19px; margin:36px 0 10px; color:var(--accent); }}
  .meta {{ color:var(--muted); margin:0 0 28px; font-family:system-ui,sans-serif; font-size:13px; }}
  .figs {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr)); gap:12px; }}
  .fig {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }}
  .fig b {{ display:block; font-size:26px; font-family:system-ui,sans-serif; font-variant-numeric:tabular-nums; }}
  .fig span {{ color:var(--muted); font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; font-family:system-ui,sans-serif; font-size:13px; }}
  th, td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ color:var(--muted); font-weight:600; }}
  .n {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  ul {{ padding-left:20px; }} li {{ margin:6px 0; }}
  .foot {{ color:var(--muted); font-size:12px; margin-top:40px; font-family:system-ui,sans-serif; }}
  @media (max-width:600px) {{ table {{ display:block; overflow-x:auto; }} }}
</style></head><body><main>
<h1>What the {esc(s["project"])} regression covers</h1>
<p class="meta">As of commit {esc(s["commit"] or "–")}, generated {datetime.now().strftime("%Y-%m-%d")} from the test code and test data.</p>
<div class="figs">{fig_html}</div>
{lines_html}
{states_html}
{suites_html}
{gaps_html}
<p class="foot">A coverage counts when a scenario that runs selects it (its DataCombination row or a row it references names it);
options and jurisdictions likewise. Generated by centertest-healthcheck --statement.</p>
</main></body></html>
"""


def write(repo_dir: str, source_root: str, cssids_dir: str | None) -> str:
    out_dir = os.path.join(repo_dir, "healthcheck")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"Coverage_Statement_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    data = gather(repo_dir, source_root, cssids_dir)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    from eir_json import emit
    emit(dict(data, page=path))
    return path
