#!/usr/bin/env python3
"""Engine gap report: a small markdown file the user sends to Kimputing when the parser got a plan field wrong.

Only recording ids, tool versions and the schema version are copied from the plan - never startUrl, name
or any recorded value, so the report carries no client data.
"""
import argparse
import datetime
import json
import os
import re
import sys

DEFAULT_OUT_DIR = os.path.join(".claude", "wizard", "gaps")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(field: str) -> str:
    """File-name-safe slug of a field path, e.g. 'steps[3].getter' -> 'steps-3-getter'."""
    return SLUG_RE.sub("-", field.lower()).strip("-") or "field"


def recordings(plan: dict) -> list:
    """(id, toolVersion) of the recording, or of every part of a combined plan."""
    plans = plan.get("parts") or [plan]
    result = []
    for part in plans:
        recording = part.get("recording") or {}
        result.append((recording.get("id", "unknown"), recording.get("toolVersion", "unknown")))
    return result


def one_line(text) -> str:
    """Collapse a value to a single line so it cannot break the report structure."""
    return " ".join(str(text).split())


def render(plan: dict, field: str, expected: str, got: str) -> str:
    lines = ["# Recording-to-test engine gap report", "", "## Recording", ""]
    for rec_id, tool_version in recordings(plan):
        lines.append(f"- recording.id: {rec_id}")
        lines.append(f"  recording.toolVersion: {tool_version}")
    lines += ["", "## Plan", "", f"- schemaVersion: {plan.get('schemaVersion', 'unknown')}",
              "", "## Field", "", one_line(field),
              "", "## Expected", "", one_line(expected),
              "", "## Got", "", one_line(got),
              "", "## Send this file to Kimputing (recording-to-test engine)", "",
              "Do not patch the engine locally. Please check that the file holds no client data before sending.", ""]
    return "\n".join(lines)


def write(plan: dict, field: str, expected: str, got: str, out_dir: str, today: datetime.date) -> str:
    """Write the report as <out_dir>/<YYYY-MM-DD>-<field-slug>[-N].md and return its path."""
    os.makedirs(out_dir, exist_ok=True)
    base = f"{today.isoformat()}-{slug(field)}"
    path = os.path.join(out_dir, base + ".md")
    number = 1
    while os.path.exists(path):
        number += 1
        path = os.path.join(out_dir, f"{base}-{number}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(plan, field, expected, got))
    return path


def main(argv=None) -> int:
    """gap-report: write a gap report for Kimputing and print its path."""
    parser = argparse.ArgumentParser(prog="ct.py gap-report", description=main.__doc__)
    parser.add_argument("--plan", required=True, help="plan JSON (single or combined)")
    parser.add_argument("--field", required=True, help="plan field that is wrong or missing")
    parser.add_argument("--expected", required=True)
    parser.add_argument("--got", required=True)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError) as error:
        print(f"Error: cannot read plan: {error}", file=sys.stderr)
        return 2
    print(write(plan, args.field, args.expected, args.got, args.out_dir, datetime.date.today()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
