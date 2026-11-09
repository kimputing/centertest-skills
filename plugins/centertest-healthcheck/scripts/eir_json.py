"""
Machine-readable results (`--output json`, and the JSON beside every --review PR comment), so other
tools -- the CenterTest MCP server first -- run this implementation instead of keeping their own.

--review writes {schema, tool, generated, verdict, exit_code, changes, meta} beside its PR comment.

Health check schema (additive only: new keys may appear, existing keys keep their meaning; "schema" bumps on a break):
  {schema, tool, generated, project, score, files,
   trust: {blockers: [{rule_id, title, consequence, count, samples: [label], locations: [path:line], dormant}],
           not_checked: [rule id], dormant: <findings in data no test runs>},
   rules: [{id, description, category, severity, error, headers, rows}],
   data, screens, products, since}
"""

from __future__ import annotations

import json
import os
from datetime import datetime

SCHEMA = 1


def _plain(value):
    """JSON-safe copy: sets become sorted lists, tuples lists, anything else str()."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, set):
        return sorted(_plain(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def health_json(results, project: str, files: int, data=None, screens=None, products=None, since=None) -> dict:
    from eir_report import health_score, severity_of, trust_blockers
    blockers, not_checked, dormant = trust_blockers(results)
    return {
        "schema": SCHEMA, "tool": "centertest-healthcheck", "generated": datetime.now().isoformat(timespec="seconds"),
        "project": project, "score": health_score(results, files), "files": files,
        "trust": {"blockers": _plain(blockers), "not_checked": _plain(not_checked), "dormant": _plain(dormant)},
        "rules": [{"id": r.rule_id, "description": r.description, "category": r.category,
                   "severity": severity_of(r), "error": r.error, "headers": _plain(r.headers),
                   "rows": _plain(r.rows)} for r in results],
        "data": _plain(data), "screens": _plain(screens), "products": _plain(products), "since": _plain(since),
    }


def review_json(changes, meta) -> dict:
    from eir_review import verdict
    line, code = verdict(changes)
    return {"schema": SCHEMA, "tool": "centertest-healthcheck --review",
            "generated": datetime.now().isoformat(timespec="seconds"),
            "verdict": line, "exit_code": code, "changes": _plain(changes), "meta": _plain(meta)}


def write(doc: dict, output_dir: str, stem: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    return path
