"""
States (jurisdictions) the scenarios run in, per line of business.

A state counts for a line when a row that an enabled DataCombination row of the line reaches (the row
itself and what it references: #Ref, joins, @Rel, as eir_uses follows them) names it in a State,
Jurisdiction or GoverningLaw column, by the code or the name of the generated Jurisdiction typelist
(TC_Jurisdiction: "AZ" or "Arizona"). The line is the DataCombination workbook's prefix
(CA_SubmissionDC.xlsx -> CA). Addresses count too: a state here is one the scenarios' data uses, not
necessarily a policy's base state.

Each line also lists the states the suite uses on other lines but never on this one: where a
state-specific rule or form of this line is never exercised although the company writes there.
"""

from __future__ import annotations

import glob
import os
import re

_STATE_COLUMN = re.compile(r"state|jurisdiction|governinglaw", re.I)
_TYPECODE = re.compile(r'new TC_Jurisdiction\("((?:[^"\\]|\\.)*)", "((?:[^"\\]|\\.)*)", (?:true|false)\)')


def jurisdictions(cssids_dir: str | None) -> dict[str, str]:
    """{lower-cased code or name: code} from the generated TC_Jurisdiction (PolicyCenter's first)."""
    if not cssids_dir:
        return {}
    resources = os.path.abspath(cssids_dir)
    if os.path.basename(resources) == "cssids":
        resources = os.path.dirname(resources)
    java = os.path.join(os.path.dirname(resources), "java")
    found = sorted(glob.glob(os.path.join(java, "**", "typelist", "*", "TC_Jurisdiction.java"), recursive=True),
                   key=lambda p: (os.path.basename(os.path.dirname(p)) != "pc", p))
    if not found:
        return {}
    try:
        with open(found[0], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return {}
    codes = {}
    for code, name in _TYPECODE.findall(text):
        codes[name.strip().lower()] = code
        codes[code.strip().lower()] = code
    return codes


def line_of(rel_path: str) -> str | None:
    """'testdata/ca/CA_SubmissionDC.xlsx' -> 'CA'; None for a workbook without a line prefix."""
    base = os.path.basename(rel_path)
    return base.split("_")[0] if "_" in base else None


def state_coverage(repo_dir: str, cssids_dir: str | None) -> list[dict] | None:
    """[{line, states: {code: scenarios}, elsewhere: [codes]}] for lines whose scenarios name a state;
    None without a Jurisdiction typelist."""
    codes = jurisdictions(cssids_dir)
    if not codes:
        return None
    from eir_uses import _DISABLED, _graph, _key
    tables, links = _graph(repo_dir)
    out_of = dict(links)
    named = {}  # row key -> state codes its State/Jurisdiction cells name
    for t in tables:
        cols = [i for i, h in enumerate(t["headers"]) if h and h[0] not in "#@" and _STATE_COLUMN.search(h)]
        if not cols:
            continue
        for code, cells in t["rows"]:
            states = {codes[cells[i].strip().lower()] for i in cols
                      if i < len(cells) and cells[i].strip().lower() in codes}
            if states:
                named[_key(t, code)] = states
    per_line: dict[str, dict[str, int]] = {}
    for t in tables:
        line = line_of(t["rel"]) if t["dc"] else None
        if not line:
            continue
        di = next((i for i, h in enumerate(t["headers"]) if h.lower() == "disabled"), None)
        for code, cells in t["rows"]:
            if di is not None and di < len(cells) and cells[di].strip().lower() in _DISABLED:
                continue
            start = _key(t, code)
            seen, frontier = {start}, [start]
            while frontier:
                for nxt in out_of.get(frontier.pop(), ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
            states = set().union(*(named.get(k, set()) for k in seen))
            counts = per_line.setdefault(line, {})
            for s in states:
                counts[s] = counts.get(s, 0) + 1
    everywhere = set().union(*per_line.values()) if per_line else set()
    return [{"line": line, "states": dict(sorted(states.items())), "elsewhere": sorted(everywhere - set(states))}
            for line, states in sorted(per_line.items(), key=lambda kv: (-len(kv[1]), kv[0])) if states]


def state_delta(base_tree: str, head_tree: str, cssids_dir: str | None) -> list[dict]:
    """[{line, lost, gained}]: jurisdictions a line's scenarios ran in at the merge-base and no longer do on the
    branch tip (a row removed or switched off, an address changed), and the other way round."""
    base, head = state_coverage(base_tree, cssids_dir), state_coverage(head_tree, cssids_dir)
    if base is None or head is None:
        return []
    was = {l["line"]: set(l["states"]) for l in base}
    now = {l["line"]: set(l["states"]) for l in head}
    out = []
    for line in sorted(set(was) | set(now)):
        lost, gained = was.get(line, set()) - now.get(line, set()), now.get(line, set()) - was.get(line, set())
        if lost or gained:
            out.append({"line": line, "lost": sorted(lost), "gained": sorted(gained)})
    return out


def print_states(lines: list[dict]) -> None:
    every = set().union(*(l["states"] for l in lines))
    print(f"  JURISDICTIONS THE SCENARIOS RUN IN ({len(every)} in all; a State/Jurisdiction cell of a row they reach)")
    for l in lines:
        shown = ", ".join(l["states"]) if len(l["states"]) <= 12 else ", ".join(list(l["states"])[:12]) + ", ..."
        missing = (f"   not here, on other lines: {len(l['elsewhere'])}"
                   + (f" ({', '.join(l['elsewhere'][:8])}{', ...' if len(l['elsewhere']) > 8 else ''})")
                   if l["elsewhere"] else "")
        print(f"  {l['line']:<12} {len(l['states']):>3}: {shown}{missing}")


def excel_rows(lines: list[dict]) -> list[list]:
    """Line, state, scenarios (0 for a state the suite uses on other lines only)."""
    rows = []
    for l in lines:
        rows += [[l["line"], s, n] for s, n in l["states"].items()]
        rows += [[l["line"], s, 0] for s in l["elsewhere"]]
    return rows
