#!/usr/bin/env python3
"""Scrub a CenterTest Recorder recording into a shareable, session.json-only copy.

Hosts, typed values and dates are replaced so a client recording can serve as a (private) test fixture:
  * every URL host becomes gw.example.test;
  * every typed value (and every posted form value) becomes V<n>, the same value the same placeholder,
    in actions, row cells, requests, notes, messages, titles and meta text;
  * every MM/DD/YYYY or YYYY-MM-DD date (also inside timestamps) moves by the same number of days, so the
    relations between dates survive;
  * media, DOM and network references are dropped (only session.json is written).
Usage: ct.py scrub <recording> --out DIR [--day-shift N]
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_recording  # noqa: E402

PLACEHOLDER_HOST = "gw.example.test"
REDACTED = "[redacted]"
RECORDER_NAME = "Recorder"
TOP_LEVEL_DROPPED = ("video", "audio")
STEP_DROPPED = ("screenshot", "before", "full", "dom", "net", "marks", "beforeMarks")
# structural keys: widget ids, kinds, roles ... are not client data and must stay exact
STRUCTURAL = frozenset({"type", "widgetId", "kind", "label", "inputType", "column", "assert", "region", "role",
                        "part", "level", "screen", "app", "rule", "tab", "browser", "os", "toolVersion",
                        "name", "header", "method", "source"})
URL_HOST = re.compile(r"(https?://)([^/\s:?#\"'<>]+)(:\d+)?", re.IGNORECASE)
US_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
NUMBER = re.compile(r"[-+]?[\d,]*\.?\d+")
WORD = r"\w"


def is_date(text: str) -> bool:
    return bool(US_DATE.fullmatch(text) or ISO_DATE.fullmatch(text))


def is_typed_value(value) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and text != REDACTED and not is_date(text) and not NUMBER.fullmatch(text)


class Scrubber:
    def __init__(self, day_shift: int):
        self.delta = datetime.timedelta(days=day_shift)
        self.values = {}      # original -> placeholder
        self.hosts = []
        self.dates = 0
        self.pattern = None

    # -- collecting ---------------------------------------------------------------------------------
    def register(self, value):
        if is_typed_value(value):
            value = value.strip()
            if value not in self.values:
                self.values[value] = f"V{len(self.values) + 1}"

    def collect(self, session: dict):
        for step in session.get("steps") or []:
            for action in step.get("actions") or []:
                if action.get("type") == "change":
                    self.register(action.get("value"))
            for request in step.get("requests") or []:
                for field in request.get("fields") or []:
                    if isinstance(field, dict):
                        self.register(field.get("value"))
        ordered = sorted(self.values, key=len, reverse=True)
        if ordered:
            alternatives = "|".join(re.escape(v) for v in ordered)
            self.pattern = re.compile(rf"(?<!{WORD})(?:{alternatives})(?!{WORD})")

    # -- replacing ----------------------------------------------------------------------------------
    def host(self, match):
        found = match.group(2) + (match.group(3) or "")
        if found not in self.hosts:
            self.hosts.append(found)
        return match.group(1) + PLACEHOLDER_HOST

    def shift_us(self, match):
        month, day, year = match.group(1), match.group(2), match.group(3)
        try:
            moved = datetime.date(int(year), int(month), int(day)) + self.delta
        except (ValueError, OverflowError):
            return match.group(0)
        self.dates += 1
        return (f"{moved.month:0{len(month)}d}/{moved.day:0{len(day)}d}/{moved.year:04d}")

    def shift_iso(self, match):
        try:
            moved = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3))) + self.delta
        except (ValueError, OverflowError):
            return match.group(0)
        self.dates += 1
        return moved.isoformat()

    def text(self, value: str) -> str:
        value = URL_HOST.sub(self.host, value)
        if self.pattern:
            value = self.pattern.sub(lambda m: self.values[m.group(0)], value)
        value = US_DATE.sub(self.shift_us, value)
        return ISO_DATE.sub(self.shift_iso, value)

    def walk(self, node, key=None):
        if isinstance(node, dict):
            return {k: self.walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [self.walk(v, key) for v in node]
        if isinstance(node, str):
            if key in STRUCTURAL:
                return URL_HOST.sub(self.host, node)
            return self.text(node)
        return node


def notes_text(node) -> list:
    """Every text a note or message carries, as plain strings."""
    found = []
    for item in node or []:
        found.append(item.get("text") if isinstance(item, dict) else item)
    return found


def scrub(session: dict, day_shift: int = 100) -> tuple:
    """(scrubbed copy, report); the input is not modified."""
    scrubber = Scrubber(day_shift)
    scrubber.collect(session)
    out = scrubber.walk(session)
    for key in TOP_LEVEL_DROPPED:
        out.pop(key, None)
    for step in out.get("steps") or []:
        for key in STEP_DROPPED:
            step.pop(key, None)
    if isinstance(out.get("meta"), dict) and out["meta"].get("recorderName"):
        out["meta"]["recorderName"] = RECORDER_NAME
    changed = []
    if notes_text(out.get("notes")) != notes_text(session.get("notes")):
        changed.append(0)
    for before, after in zip(session.get("steps") or [], out.get("steps") or []):
        if notes_text(after.get("notes")) != notes_text(before.get("notes")):
            changed.append(before.get("seq"))
    report = {"hosts": sorted(scrubber.hosts), "values": len(scrubber.values),
              "notesChanged": changed, "datesShifted": scrubber.dates}
    return out, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ct.py scrub", description="session.json-only copy of a recording "
                                     "with hosts, typed values and dates replaced")
    parser.add_argument("recording", help="recording folder, zip or session.json")
    parser.add_argument("--out", required=True, help="directory to write session.json into")
    parser.add_argument("--day-shift", type=int, default=100, help="days every date moves by (default 100)")
    args = parser.parse_args(argv)
    target = os.path.join(args.out, "session.json")
    if os.path.exists(target):
        print(f"Error: {target} already exists; not overwriting", file=sys.stderr)
        return 2
    try:
        session = parse_recording.load_session(args.recording)
    except (parse_recording.RecordingError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    scrubbed, report = scrub(session, args.day_shift)
    os.makedirs(args.out, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(scrubbed, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
