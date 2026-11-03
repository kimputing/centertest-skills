#!/usr/bin/env python3
"""Scrub a CenterTest Recorder recording into a session.json-only copy for private test fixtures.

Replaced: URL hosts (gw.example.test); typed and posted form values and any --also strings (V<n>); digit
strings of 8+ digits (N<n>); issue-tracker keys (KEY-<n>); meta testId/featureIds/defectIds, session id and
name; dates (shifted by --day-shift days, relations kept); media/dom/net references are dropped.
NOT replaced: text the application displayed but nobody typed (page titles, messages, checked values).
Review the report's needsReview list and the file before storing it, and keep fixtures in a private repo.
Usage: ct.py scrub <recording> --out DIR [--day-shift N] [--also WORD ...]
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
LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")
MID_NUMBER = re.compile(r"(?<!\d)\d{6,7}(?!\d)")
ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
# keys whose strings can carry client text; every other key (ids, selectors, labels, kinds) is left alone
TEXT_KEYS = frozenset({"title", "text", "description", "prerequisites", "expectedOutcome", "expected", "seen",
                       "value", "display", "values", "messages", "url", "startUrl"})


def is_date(text: str) -> bool:
    return bool(US_DATE.fullmatch(text) or ISO_DATE.fullmatch(text))


def is_typed_value(value) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and text != REDACTED and not is_date(text) and not NUMBER.fullmatch(text)


class Scrubber:
    def __init__(self, day_shift: int, also=()):
        self.delta = datetime.timedelta(days=day_shift)
        self.values = {}      # original -> placeholder
        self.fixed = {}       # meta ids -> neutral placeholder
        self.numbers = {}
        self.keys = {}
        self.also = [a for a in also if isinstance(a, str) and a.strip()]
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
        for word in self.also:
            word = word.strip()
            if word not in self.values:
                self.values[word] = f"V{len(self.values) + 1}"
        meta = session.get("meta") if isinstance(session.get("meta"), dict) else {}
        if isinstance(meta.get("testId"), str) and meta["testId"].strip():
            self.fixed[meta["testId"].strip()] = "T1"
        for field, prefix in (("featureIds", "F"), ("defectIds", "D")):
            for n, item in enumerate(meta.get(field) or [], 1):
                if isinstance(item, str) and item.strip():
                    self.fixed[item.strip()] = f"{prefix}{n}"
        for step in session.get("steps") or []:
            for action in step.get("actions") or []:
                if action.get("type") == "change":
                    self.register(action.get("value"))
            for request in step.get("requests") or []:
                for field in request.get("fields") or []:
                    if isinstance(field, dict):
                        self.register(field.get("value"))
        self.lookup = dict(self.fixed, **self.values)
        ordered = sorted(self.lookup, key=len, reverse=True)
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

    def number(self, match):
        return self.numbers.setdefault(match.group(0), f"N{len(self.numbers) + 1}")

    def issue_key(self, match):
        return self.keys.setdefault(match.group(0), f"KEY-{len(self.keys) + 1}")

    def light(self, value: str) -> str:
        value = URL_HOST.sub(self.host, value)
        value = US_DATE.sub(self.shift_us, value)
        return ISO_DATE.sub(self.shift_iso, value)

    def text(self, value: str) -> str:
        value = URL_HOST.sub(self.host, value)
        if self.pattern:
            value = self.pattern.sub(lambda m: self.lookup[m.group(0)], value)
        value = LONG_NUMBER.sub(self.number, value)
        value = ISSUE_KEY.sub(self.issue_key, value)
        value = US_DATE.sub(self.shift_us, value)
        return ISO_DATE.sub(self.shift_iso, value)

    def walk(self, node, key=None):
        if isinstance(node, dict):
            return {k: self.walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [self.walk(v, key) for v in node]
        if isinstance(node, str):
            if key in TEXT_KEYS:
                return self.text(node)
            if key in STRUCTURAL:
                return URL_HOST.sub(self.host, node)
            return self.light(node)
        return node


def notes_text(node) -> list:
    """Every text a note or message carries, as plain strings."""
    found = []
    for item in node or []:
        found.append(item.get("text") if isinstance(item, dict) else item)
    return found


def surviving(before: dict, after: dict) -> dict:
    """What the scrubber could not know to replace: displayed text left unchanged, and kept 6-7 digit numbers."""
    titles, checks, messages, numbers = [], [], [], []

    def add(bucket, old, new):
        if isinstance(new, str) and new.strip() and old == new and new not in bucket:
            bucket.append(new)

    for old_step, step in zip(before.get("steps") or [], after.get("steps") or []):
        add(titles, old_step.get("title"), step.get("title"))
        for old_action, action in zip(old_step.get("actions") or [], step.get("actions") or []):
            for key in ("seen", "expected"):
                add(checks, old_action.get(key), action.get(key))
        for old_message, message in zip(old_step.get("messages") or [], step.get("messages") or []):
            if isinstance(message, dict):
                add(messages, old_message.get("text"), message.get("text"))
            else:
                add(messages, old_message, message)

    def scan(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                scan(v, k)
        elif isinstance(node, list):
            for v in node:
                scan(v, key)
        elif isinstance(node, str) and key in TEXT_KEYS:
            for found in MID_NUMBER.findall(node):
                if found not in numbers:
                    numbers.append(found)
    scan(after)
    return {"titles": titles, "checks": checks, "messages": messages, "numbers": numbers}


def scrub(session: dict, day_shift: int = 100, also=()) -> tuple:
    """(scrubbed copy, report); the input is not modified. `also` are extra strings replaced like typed values."""
    scrubber = Scrubber(day_shift, also)
    scrubber.collect(session)
    out = scrubber.walk(session)
    for key in TOP_LEVEL_DROPPED:
        out.pop(key, None)
    for step in out.get("steps") or []:
        for key in STEP_DROPPED:
            step.pop(key, None)
    meta = out.get("meta")
    if isinstance(meta, dict):
        if meta.get("recorderName"):
            meta["recorderName"] = RECORDER_NAME
        if meta.get("testId"):
            meta["testId"] = "T1"
        for field, prefix in (("featureIds", "F"), ("defectIds", "D")):
            if isinstance(meta.get(field), list):
                meta[field] = [f"{prefix}{n}" for n in range(1, len(meta[field]) + 1)]
    if "id" in out:
        out["id"] = "rec-1"
    if "name" in out:
        out["name"] = "recording"
    changed = []
    if notes_text(out.get("notes")) != notes_text(session.get("notes")):
        changed.append(0)
    for before, after in zip(session.get("steps") or [], out.get("steps") or []):
        if notes_text(after.get("notes")) != notes_text(before.get("notes")):
            changed.append(before.get("seq"))
    report = {"hosts": sorted(scrubber.hosts), "values": len(scrubber.values),
              "notesChanged": changed, "datesShifted": scrubber.dates,
              "numbers": len(scrubber.numbers), "issueKeys": len(scrubber.keys),
              "needsReview": surviving(session, out)}
    return out, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ct.py scrub", description="session.json-only copy of a recording "
                                     "with hosts, typed values and dates replaced")
    parser.add_argument("recording", help="recording folder, zip or session.json")
    parser.add_argument("--out", required=True, help="directory to write session.json into")
    parser.add_argument("--also", action="append", default=[], metavar="WORD",
                        help="extra string to replace like a typed value, e.g. a name seen on screen (repeatable)")
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
    scrubbed, report = scrub(session, args.day_shift, args.also)
    os.makedirs(args.out, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(scrubbed, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(report, indent=2))
    if any(report["needsReview"].values()):
        print("Warning: displayed text may remain (see needsReview); review the file before storing it, "
              "and keep it in a private repo", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
