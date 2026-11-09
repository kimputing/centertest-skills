#!/usr/bin/env python3
"""How much of a recorded business flow the project's automation already performs, field by field.

A CenterTest Recorder session is what a person does in the app; the project's step classes are what
the automation does. For every recorded field and action this resolves the widget the way the wizard
does (parse_recording.build_plan) and looks for it in the project's own Java (generated code excluded):

- data-driven: a step sets the widget from test data (`.set(address.getCity())`), or a coverage /
  coverage term the recording changed is named in a test data workbook;
- hardcoded:   a step sets it to a literal (`.set("Standard")`), or the coverage is named only in Java;
- automated:   a step uses the widget (a click, a table row pick, a widget id written out, an entry picked by its label);
- partial:     the steps set coverages from test data, but no data row names this coverage yet;
- missing:     no step uses it;
- not counted: wizard Next/Back, tab-bar menus (a step may open the screen another way; the next
  screen's fields show whether it got there), and the login (the framework's).

A step "knows" a page when its file, or a class it extends, names the page class: the getter chain
alone is not enough, since `getPolicyInfoStep().getOrganizationType()` exists on every LOB's wizard.
`--only REGEX` keeps the files whose path matches (e.g. one LOB's folder), for a flow-specific answer.

Output: a summary per screen on stdout, and an HTML report (--html, default
~/.centertest/reports/recording-coverage-<recording id>.html). The project is only read.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_recording  # noqa: E402
import xlsx_read  # noqa: E402

PAGE_NEW = re.compile(r"new\s+(\w+)\(getContext\(\)\)")
GETTER = re.compile(r"\.(get\w*)\(")
ROW_START = {"getFirstRow", "getRow", "getLastRow", "getRows", "getRowByIndex"}
EXTENDS = re.compile(r"\bclass\s+(\w+)(?:<[^{]*?>)?\s+extends\s+(\w+)")
TYPE_TOKEN = re.compile(r"\b[A-Z]\w*\b")
LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
SETTER = re.compile(r"(?:set|select|check)\w*")
SKIP_DIRS = {"build", "out", ".gradle", ".git", "node_modules", "bin", "target"}
NAV_GETTERS = {"getNext", "getBack", "getPrevious", "getCancel"}

COUNTED = ("data", "hardcoded", "automated", "partial", "missing")
HANDLED = ("data", "hardcoded", "automated")
LABEL = {"data": "Data-driven", "hardcoded": "Hardcoded", "automated": "Automated", "partial": "Partial",
         "missing": "Missing", "skip": "Not counted"}
COVERAGE_MECHANISM = re.compile(r"\b(?:CoverageUtil|CoverageRoutes|coverageUtil)\b")


def _generated(rel: str) -> bool:
    parts = rel.replace("\\", "/").lower().split("/")
    return "generated" in parts or "datadriven" in parts


def java_index(project: str, only: str | None = None) -> dict:
    """{relative path: {"text", "lines", "types", "parent"}} for the project's hand-written Java."""
    pattern = re.compile(only) if only else None
    index = {}
    for root, dirs, files in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if not name.endswith(".java"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, project).replace("\\", "/")
            if _generated(rel):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            m = EXTENDS.search(text)
            index[rel] = {"text": text, "lines": text.splitlines(), "types": set(TYPE_TOKEN.findall(text)),
                          "parent": m.group(2) if m else None, "in_scope": not pattern or bool(pattern.search(rel))}
    return index


def _by_class(index: dict) -> dict:
    return {os.path.splitext(os.path.basename(rel))[0]: rel for rel in index}


def knows_page(rel: str, page: str, index: dict, classes: dict) -> bool:
    """The file, or a class it extends (in the project), names the page class."""
    seen = set()
    while rel and rel not in seen:
        seen.add(rel)
        entry = index[rel]
        if page in entry["types"]:
            return True
        rel = classes.get(entry["parent"] or "")
    return False


def chain_of(getter: str) -> tuple[str | None, list[str]]:
    """(page class, getter names up to a table's row) of a resolved getter expression."""
    m = PAGE_NEW.search(getter or "")
    if not m:
        return None, []
    names = []
    for name in GETTER.findall(getter[m.end():]):
        if name in ROW_START:
            break
        if name != "get":
            names.append(name)
    return m.group(1), names


def last_call(line: str):
    """(name, argument text) of the statement's final call (`a.b().set(x);` -> ("set", "x")), else None."""
    code = line.split("//")[0].rstrip()
    if not code.endswith(");"):
        return None
    depth, i = 0, len(code) - 2
    while i >= 0:
        depth += code[i] == ")"
        depth -= code[i] == "("
        if depth == 0:
            break
        i -= 1
    m = re.search(r"\.(\w+)$", code[:i])
    return (m.group(1), code[i + 1:-2].strip()) if m else None


def _sets(line: str) -> bool:
    call = last_call(line)
    return bool(call and SETTER.fullmatch(call[0]) and call[1])


def _set_status(line: str) -> str:
    if not _sets(line):
        return "automated"
    arg = last_call(line)[1]
    return "hardcoded" if arg.startswith('"') or arg in ("true", "false") or re.fullmatch(r"-?\d[\d.]*", arg) \
        else "data"


def find_chain(page: str, names: list, index: dict, classes: dict, change: bool):
    """(status, "path:line", other files) for the first in-scope step using the chain, else None."""
    last = names[-1]
    call = re.compile(r"\." + re.escape(last) + r"\(")
    hits = []
    for rel, entry in index.items():
        if not entry["in_scope"] or not call.search(entry["text"]):
            continue
        if not all(("." + n + "(") in entry["text"] for n in names[:-1]):
            continue
        if not knows_page(rel, page, index, classes):
            continue
        for no, line in enumerate(entry["lines"], 1):
            if call.search(line) and not line.lstrip().startswith("//"):
                hits.append((rel, no, line))
                break
    if not hits:
        return None
    # a step that sets the widget beats one that only reads it
    best = next((h for h in hits if change and _sets(h[2])), hits[0])
    status = _set_status(best[2]) if change else "automated"
    return status, f"{best[0]}:{best[1]}", len(hits) - 1


def data_strings(project: str) -> dict:
    """{cell text: workbook} for every header and value in the project's testdata workbooks."""
    found = {}
    base = os.path.join(project, "testdata")
    for root, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".xlsx") or name.startswith("~$"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, project).replace("\\", "/")
            try:
                sheets = xlsx_read.read_workbook(path)
            except (xlsx_read.WorkbookError, OSError, KeyError, ValueError):
                continue
            for rows in sheets.values():
                for row in rows:
                    for key, value in row.items():
                        for text in (key, value):
                            if isinstance(text, str) and text.strip():
                                found.setdefault(text.strip(), rel)
    return found


def by_label(page: str, label: str, index: dict, classes: dict):
    """(line status, "path:line") of the first in-scope step that knows the page and names the label."""
    needle = '"' + label + '"'
    for rel, entry in index.items():
        if entry["in_scope"] and needle in entry["text"] and knows_page(rel, page, index, classes):
            for no, line in enumerate(entry["lines"], 1):
                if needle in line and not line.lstrip().startswith("//"):
                    return line, f"{rel}:{no}"
    return None


def coverage_mechanism(page: str, index: dict, classes: dict):
    """"path:line" of an in-scope step on the page that sets coverages through CoverageUtil."""
    for rel, entry in index.items():
        if entry["in_scope"] and COVERAGE_MECHANISM.search(entry["text"]) and knows_page(rel, page, index, classes):
            for no, line in enumerate(entry["lines"], 1):
                if COVERAGE_MECHANISM.search(line) and not line.lstrip().startswith(("import", "//")):
                    return f"{rel}:{no}"
    return None


def java_literals(index: dict) -> dict:
    """{string literal: "path:line"} across the in-scope Java."""
    found = {}
    for rel, entry in index.items():
        if not entry["in_scope"]:
            continue
        for no, line in enumerate(entry["lines"], 1):
            for lit in LITERAL.findall(line):
                found.setdefault(lit, f"{rel}:{no}")
    return found


def classify(step: dict, action: dict, index: dict, classes: dict, literals: dict, cells: dict) -> dict:
    """The coverage row of one recorded action."""
    row = {"seq": step.get("seq"), "screen": step.get("waitTitle") or step.get("title") or step.get("screen"),
           "label": action.get("label") or action.get("text") or action.get("widgetId"),
           "action": action.get("type"), "value": action.get("value"), "where": "", "status": "missing", "why": ""}
    getter = action.get("getter") or ""
    change = action.get("type") == "change"
    if step.get("login"):
        row.update(status="skip", why="login: done by the framework")
        return row
    if action.get("navigationOnly") or action.get("rule") in ("wizardButton",):
        row.update(status="skip", why="wizard navigation")
        return row
    if action.get("rule") == "tabBar":
        row.update(status="skip", why="menu navigation: a step may open the screen another way")
        return row
    coverage = action.get("coverage")
    if coverage:
        names = [n for n in (coverage.get("coverage"), coverage.get("covterm")) if n]
        if all(n in cells for n in names):
            row.update(status="data", where=cells[names[-1]], why="named in test data")
        elif all(n in cells or n in literals for n in names):
            row.update(status="hardcoded", where=literals.get(names[-1]) or literals.get(names[0]) or "",
                       why="named in Java")
        else:
            named = " / ".join(f"'{n}'" for n in names)
            mechanism = coverage_mechanism(action.get("page", "") + "Page", index, classes) or \
                coverage_mechanism(action.get("page", ""), index, classes)
            if mechanism:
                row.update(status="partial", where=mechanism,
                           why=f"coverages come from test data; no row names {named} yet")
            else:
                row["why"] = f"coverage {named} not in test data or Java"
        return row
    if action.get("resolution") == "raw" or getter.startswith("Widget"):
        wid = action.get("widgetId") or ""
        if wid in literals:
            row.update(status="automated", where=literals[wid], why="widget id written out")
        else:
            row["why"] = "widget id not in Java"
        return row
    page, names = chain_of(getter)
    if not page or not names:
        row["why"] = action.get("reason") or "widget not resolved from the recording"
        return row
    if names[-1] in NAV_GETTERS:
        row.update(status="skip", why="wizard navigation")
        return row
    hit = find_chain(page, names, index, classes, change)
    label = action.get("label")
    labelled = None if hit or not label else by_label(page, label, index, classes)
    if hit:
        status, where, others = hit
        row.update(status=status, where=where, why=f"+{others} more" if others else "")
    elif labelled:
        line, where = labelled
        row.update(status=_set_status(line) if change else "automated", where=where, why="picked by its label")
    else:
        row["why"] = f"no step calls {page}…{'().'.join(names[-2:])}()"
    return row


_PROJECT_CACHE: dict = {}


def _project_facts(project: str, only: str | None):
    """(java index, classes, literals, data cells), read once per project and scope."""
    key = (os.path.abspath(project), only)
    if key not in _PROJECT_CACHE:
        index = java_index(project, only)
        _PROJECT_CACHE[key] = (index, _by_class(index), java_literals(index), data_strings(project))
    return _PROJECT_CACHE[key]


def coverage(plan: dict, project: str, only: str | None = None) -> dict:
    index, classes, literals, cells = _project_facts(project, only)
    rows = [classify(step, action, index, classes, literals, cells)
            for step in plan.get("steps") or [] for action in step.get("actions") or []]
    screens = {}
    for row in rows:
        s = screens.setdefault(row["screen"], {s: 0 for s in COUNTED + ("skip",)})
        s[row["status"]] += 1
    totals = {s: sum(1 for r in rows if r["status"] == s) for s in COUNTED + ("skip",)}
    counted = sum(totals[s] for s in COUNTED)
    handled = sum(totals[s] for s in HANDLED)
    return {"recording": [r.get("id") for r in (plan.get("parts") or [plan]) for r in [r.get("recording") or {}]],
            "name": (plan.get("test") or {}).get("name") or (plan.get("recording") or {}).get("name"),
            "only": only, "rows": rows, "screens": screens, "totals": totals,
            "counted": counted, "handled": handled,
            "percent": round(100 * handled / counted) if counted else None}


def render_text(result: dict) -> str:
    t = result["totals"]
    out = [f"Recording coverage: {result['handled']}/{result['counted']} recorded fields and actions automated"
           + (f" ({result['percent']}%)" if result["percent"] is not None else ""),
           f"  data-driven {t['data']}  hardcoded {t['hardcoded']}  automated {t['automated']}"
           f"  partial {t['partial']}  missing {t['missing']}  (not counted: {t['skip']})"]
    if result["only"]:
        out.append(f"  steps searched: paths matching {result['only']}")
    out.append("")
    for screen, s in result["screens"].items():
        counted = sum(s[k] for k in COUNTED)
        if counted:
            out.append(f"  {sum(s[k] for k in HANDLED):>3}/{counted:<3} {screen}")
    missing = [r for r in result["rows"] if r["status"] in ("partial", "missing")]
    if missing:
        out += ["", "Not automated yet:"]
        out += [f"  #{r['seq']} {r['screen']} · {r['label']} ({r['action']}) — {r['why']}" for r in missing]
    out[-len(missing):] = [line.replace(" — ", " — partial: ", 1) if r["status"] == "partial" else line
                           for line, r in zip(out[-len(missing):], missing)]
    return "\n".join(out)


_CSS = """
:root{--bg:#f6f7f9;--fg:#1d2430;--mute:#5d6878;--line:#d9dee6;--card:#fff;
--data:#2f6f4f;--hard:#8a6d1c;--auto:#3b5f8f;--part:#b8642a;--miss:#a33a2c;--skip:#9aa3b0}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14181f;--fg:#e4e8ef;--mute:#9aa5b5;
--line:#2c3440;--card:#1b2029;--data:#5fbf8a;--hard:#d9b54a;--auto:#7fa6dc;--part:#e39a5c;--miss:#e07a6a;--skip:#5d6878;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px max(16px,env(safe-area-inset-left,0px))}
h1{font-size:24px;margin:0 0 4px;text-wrap:balance}h2{font-size:17px;margin:28px 0 8px}
.sub{color:var(--mute);margin:0 0 20px}
.big{font-size:44px;font-weight:600;line-height:1}.big small{font-size:16px;color:var(--mute);font-weight:400}
.bar{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--line);margin:14px 0 6px}
.bar span{display:block}.k{display:flex;gap:18px;flex-wrap:wrap;color:var(--mute);font-size:13px}
.k i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.data{background:var(--data)}.hardcoded{background:var(--hard)}.automated{background:var(--auto)}
.partial{background:var(--part)}.missing{background:var(--miss)}.skip{background:var(--skip)}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{text-align:left;padding:7px 10px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:500}
td.s b{display:inline-block;padding:1px 7px;border-radius:9px;color:#fff;font-weight:500;font-size:12px}
tr.r-skip td{color:var(--mute)}td.s{white-space:nowrap}code{font:12.5px "IBM Plex Mono",ui-monospace,monospace;word-break:break-all}
.scr td:first-child{width:60%}.mini{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--line);min-width:120px}
"""


def render_html(result: dict) -> str:
    esc = html.escape
    t = result["totals"]
    counted = result["counted"] or 1

    def bar(s, total, cls="bar"):
        return f'<div class="{cls}">' + "".join(
            f'<span class="{k}" style="width:{100 * s[k] / total:.2f}%" title="{LABEL[k]} {s[k]}"></span>'
            for k in COUNTED if s[k]) + "</div>"

    pct = f"{result['percent']}%" if result["percent"] is not None else "–"
    title = esc(result["name"] or "Recorded flow")
    parts = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
             f"<meta name=viewport content='width=device-width,initial-scale=1'><title>Recording coverage</title>"
             f"<style>{_CSS}</style></head><body><main>",
             f"<h1>{title}: automation coverage</h1>",
             f"<p class=sub>Recording {esc(', '.join(str(r) for r in result['recording']))}. "
             "Every recorded field and action, looked up in the project's own step classes"
             + (f" (paths matching <code>{esc(result['only'])}</code>)" if result["only"] else "") + ".</p>",
             f"<div class=big>{pct} <small>{result['handled']} of {result['counted']} recorded fields and actions "
             f"automated · {t['partial']} partial · {t['missing']} missing · {t['skip']} not counted</small></div>",
             bar(t, counted),
             '<div class=k>' + "".join(f'<span><i class="{k}"></i>{LABEL[k]} {t[k]}</span>'
                                       for k in COUNTED + ("skip",)) + "</div>",
             "<h2>By screen</h2><div class=wrap><table class=scr><tr><th>Screen</th><th>Automated</th><th></th></tr>"]
    for screen, s in result["screens"].items():
        n = sum(s[k] for k in COUNTED)
        if n:
            parts.append(f"<tr><td>{esc(str(screen))}</td><td>{sum(s[k] for k in HANDLED)}/{n}</td>"
                         f"<td>{bar(s, n, 'mini')}</td></tr>")
    parts.append("</table></div><h2>Field by field</h2><div class=wrap><table><tr><th>#</th><th>Screen</th>"
                 "<th>Field / action</th><th>Recorded value</th><th>Status</th><th>Where</th></tr>")
    for r in result["rows"]:
        value = "" if r["value"] is None else str(r["value"])
        where = f"<code>{esc(r['where'])}</code>" if r["where"] else ""
        why = f" <span style='color:var(--mute)'>{esc(r['why'])}</span>" if r["why"] else ""
        parts.append(f"<tr class=r-{r['status']}><td>{r['seq']}</td><td>{esc(str(r['screen']))}</td>"
                     f"<td>{esc(str(r['label']))} <span style='color:var(--mute)'>{esc(str(r['action']))}</span></td>"
                     f"<td>{esc(value)}</td><td class=s><b class={r['status']}>{LABEL[r['status']]}</b></td>"
                     f"<td>{where}{why}</td></tr>")
    parts.append("</table></div></main></body></html>")
    return "".join(parts)


def recordings_in(paths: list[str]) -> list[str]:
    """The recordings named, a folder of recordings expanded to the ones directly inside it."""
    out = []
    for p in paths:
        if os.path.isdir(p) and not os.path.isfile(os.path.join(p, "session.json")):
            for name in sorted(os.listdir(p)):
                sub = os.path.join(p, name)
                if os.path.isfile(os.path.join(sub, "session.json")) or name.endswith(".zip"):
                    out.append(sub)
        else:
            out.append(p)
    return out


def render_index(results: list[dict], only: str | None) -> str:
    esc = html.escape
    rows = []
    for r in sorted(results, key=lambda r: (r["percent"] is None, r["percent"] or 0, r["file"])):
        t = r["totals"]
        pct = "–" if r["percent"] is None else f"{r['percent']}%"
        rows.append(f"<tr><td><a href='{esc(r['file'])}'>{esc(str(r['name'] or r['recording'][0]))}</a>"
                    f"<div style='color:var(--mute);font-size:12px'>{esc(str(r['recording'][0]))}</div></td>"
                    f"<td>{len([s for s in r['screens'].values() if sum(s[k] for k in COUNTED)])}</td>"
                    f"<td>{r['handled']}/{r['counted']}</td><td><b>{pct}</b></td>"
                    f"<td>{t['missing']}</td><td>{t['partial']}</td><td>{t['hardcoded']}</td></tr>")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>Recording coverage</title><style>{_CSS}</style></head><body><main>"
            f"<h1>Recorded flows: how much is automated</h1><p class=sub>{len(results)} recordings, each looked up in the "
            "project's own step classes" + (f" (paths matching <code>{esc(only)}</code>)" if only else "")
            + ". Biggest gaps first; open one for its field-by-field report.</p><div class=wrap><table><tr><th>Recording</th>"
            "<th>Screens</th><th>Automated</th><th>%</th><th>Missing</th><th>Partial</th><th>Hardcoded</th></tr>"
            + "".join(rows) + "</table></div></main></body></html>")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="How much of a recorded flow the project's automation performs")
    ap.add_argument("recording", nargs="+", help="the recording .zip, folder or session.json (several = one flow)")
    ap.add_argument("--cssids", required=True, help="resources dir holding cssids/<app>/ (or <app>.cssids)")
    ap.add_argument("--project", required=True, help="the CenterTest project to look in (only read)")
    ap.add_argument("--only", help="regex: search only step files whose path matches (e.g. one LOB folder)")
    ap.add_argument("--html", help="HTML report path (default ~/.centertest/reports/recording-coverage-<id>.html)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON instead of text")
    ap.add_argument("--each", action="store_true",
                    help="each recording (or each one in a folder) is its own flow: one report each and an index; "
                         "--html is then a folder (default ~/.centertest/reports/recording-coverage/)")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.cssids) or not os.path.isdir(args.project):
        print("Error: --cssids and --project must be directories", file=sys.stderr)
        return 2
    if args.each:
        return _each(args)
    try:
        sessions = [parse_recording.load_session(p) for p in args.recording]
    except (parse_recording.RecordingError, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    plans = [parse_recording.build_plan(s, args.cssids, parse_recording.file_reader(p), None,
                                        parse_recording.file_bytes(p)) for s, p in zip(sessions, args.recording)]
    plan = plans[0] if len(plans) == 1 else parse_recording.combine(plans)
    result = coverage(plan, args.project, args.only)
    out = args.html or os.path.join(os.path.expanduser("~"), ".centertest", "reports",
                                    f"recording-coverage-{result['recording'][0] or 'session'}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(result))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_text(result))
        print(f"\nReport: {out}")
    return 0


def _each(args) -> int:
    out_dir = args.html or os.path.join(os.path.expanduser("~"), ".centertest", "reports", "recording-coverage")
    os.makedirs(out_dir, exist_ok=True)
    results, skipped, seen = [], [], set()
    for path in recordings_in(args.recording):
        try:
            session = parse_recording.load_session(path)
        except (parse_recording.RecordingError, ValueError, OSError) as error:
            skipped.append((path, str(error)))
            continue
        if session.get("id") and session["id"] in seen:  # a recording kept as its folder and its .zip
            continue
        seen.add(session.get("id"))
        plan = parse_recording.build_plan(session, args.cssids, parse_recording.file_reader(path), None,
                                          parse_recording.file_bytes(path))
        result = coverage(plan, args.project, args.only)
        result["file"] = re.sub(r"[^\w.-]+", "_", str(result["recording"][0] or os.path.basename(path))) + ".html"
        with open(os.path.join(out_dir, result["file"]), "w", encoding="utf-8") as fh:
            fh.write(render_html(result))
        results.append(result)
    index = os.path.join(out_dir, "index.html")
    with open(index, "w", encoding="utf-8") as fh:
        fh.write(render_index(results, args.only))
    if args.json:
        print(json.dumps([{k: r[k] for k in ("recording", "name", "handled", "counted", "percent", "totals", "file")}
                          for r in results], indent=2))
    else:
        for r in sorted(results, key=lambda r: (r["percent"] is None, r["percent"] or 0)):
            pct = "  -" if r["percent"] is None else f"{r['percent']:>3}%"
            print(f"  {pct}  {r['handled']:>3}/{r['counted']:<3} missing {r['totals']['missing']:<3} "
                  f"{r['name'] or r['recording'][0]}")
        for path, error in skipped:
            print(f"  skipped {path}: {error}")
        print(f"\nIndex: {index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
