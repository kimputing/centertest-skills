#!/usr/bin/env python3
"""Scrub a CenterTest Recorder recording into a session.json copy (plus scrubbed narration transcripts) for
private test fixtures.

Replaced in every string except structural keys (widget ids, kinds, roles, screens, headers ...): URL hosts
(gw.example.test); typed and posted form values and any --also strings (V<n>); digit strings of 8+ digits
(N<n>); issue-tracker keys (KEY-<n>); meta testId/featureIds/defectIds (session id, name and recorder name are
reset); dates (shifted by --day-shift days, relations kept). Step timestamps are only date-shifted.
Narration: audio/<stem>.transcript.json is written with every segment's text scrubbed; audio files are never
copied, so an audio entry without a transcript is dropped and its narration lost (local whisper output is not
written back). Media/dom/net references are dropped.
NOT replaced: text the application displayed but nobody typed (titles, messages, checked and displayed values,
row keys, context, dialogs) -- listed in the report's needsReview, with `leftovers`: any original typed value,
--also word, meta id, recorder name or host still found anywhere (case-insensitive).
Review needsReview and the files before storing them, and keep fixtures in a private repo.
Usage: ct.py scrub <recording> --out DIR [--day-shift N] [--also WORD ...]
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import narration  # noqa: E402
import parse_recording  # noqa: E402

PLACEHOLDER_HOST = "gw.example.test"
REDACTED = "[redacted]"
RECORDER_NAME = "Recorder"
TOP_LEVEL_DROPPED = ("video",)
STEP_DROPPED = ("screenshot", "before", "full", "dom", "net", "marks", "beforeMarks")
# structural keys: widget ids, kinds, roles, enumerations ... are not client data and must stay exact;
# `name` is a posted field's widget id (the session's own name is reset)
STRUCTURAL = frozenset({"type", "kind", "widgetId", "inputType", "role", "rule", "app", "screen", "header",
                        "column", "toolVersion", "method", "source", "f", "t",
                        "name", "assert", "region", "part", "level", "key", "tab", "browser", "os"})
# RFC 3339 timestamps: dates shift, but their 9-digit fractions are not long numbers
TIME_KEYS = frozenset({"time", "startedAt", "endedAt"})
URL_HOST = re.compile(r"(https?://)([^/\s:?#\"'<>]+)(:\d+)?", re.IGNORECASE)
US_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
NUMBER = re.compile(r"[-+]?[\d,]*\.?\d+")
WORD = r"\w"
LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")
MID_NUMBER = re.compile(r"(?<!\d)\d{6,7}(?!\d)")
ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


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
            if key in STRUCTURAL:
                return URL_HOST.sub(self.host, node)
            if key in TIME_KEYS:
                return self.light(node)
            return self.text(node)
        return node


def notes_text(node) -> list:
    """Every text a note or message carries, as plain strings."""
    found = []
    for item in node or []:
        found.append(item.get("text") if isinstance(item, dict) else item)
    return found


def surviving(before: dict, after: dict) -> dict:
    """What the scrubber could not know to replace: displayed text left unchanged, and kept 6-7 digit numbers."""
    found = {k: [] for k in ("titles", "checks", "messages", "displayed", "rowKeys", "context", "dialogs")}

    def add(bucket, old, new):
        if isinstance(new, str) and new.strip() and old == new and new not in found[bucket]:
            found[bucket].append(new)

    def pairs(old, new, key):
        old_items, new_items = old.get(key), new.get(key)
        if isinstance(old_items, list) and isinstance(new_items, list):
            return zip(old_items, new_items)
        return []

    for old_step, step in zip(before.get("steps") or [], after.get("steps") or []):
        add("titles", old_step.get("title"), step.get("title"))
        for old_action, action in pairs(old_step, step, "actions"):
            if not isinstance(action, dict) or not isinstance(old_action, dict):
                continue
            for key in ("seen", "expected"):
                add("checks", old_action.get(key), action.get(key))
            add("displayed", old_action.get("display"), action.get("display"))
            if action.get("type") == "dialog":
                add("dialogs", old_action.get("label"), action.get("label"))
            for old_text, text in pairs(old_action, action, "context"):
                add("context", old_text, text)
            for old_key, row_key in pairs(old_action, action, "rowKey"):
                if isinstance(old_key, dict) and isinstance(row_key, dict):
                    add("rowKeys", old_key.get("text"), row_key.get("text"))
        for old_message, message in pairs(old_step, step, "messages"):
            if isinstance(message, dict) and isinstance(old_message, dict):
                add("messages", old_message.get("text"), message.get("text"))
            else:
                add("messages", old_message, message)
    numbers = []

    def scan(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                scan(v, k)
        elif isinstance(node, list):
            for v in node:
                scan(v, key)
        elif isinstance(node, str) and key not in STRUCTURAL and key not in TIME_KEYS:
            for number in MID_NUMBER.findall(node):
                if number not in numbers:
                    numbers.append(number)
    scan(after)
    found["numbers"] = numbers
    return found


def leftovers(originals, *docs) -> list:
    """Originals (typed values, --also words, meta ids, hosts ...) still found in the scrubbed documents,
    case-insensitively and not inside a longer word or number: the safety net after scrubbing."""
    text = "\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs)
    hits = []
    for original in originals:
        needle = json.dumps(original, ensure_ascii=False)[1:-1]
        if original in hits or not needle.strip():
            continue
        if re.search(rf"(?<![^\W_]){re.escape(needle)}(?![^\W_])", text, re.IGNORECASE):
            hits.append(original)
    return hits


def scrub_all(session: dict, transcripts=None, day_shift: int = 100, also=()) -> tuple:
    """(scrubbed session, scrubbed transcripts, report); the input is not modified. `transcripts` maps an audio
    entry's file to its segments [{start, end, text}]; audio entries without one are dropped."""
    transcripts = transcripts or {}
    scrubber = Scrubber(day_shift, also)
    scrubber.collect(session)
    out = scrubber.walk(session)
    for key in TOP_LEVEL_DROPPED:
        out.pop(key, None)
    for step in out.get("steps") or []:
        for key in STEP_DROPPED:
            step.pop(key, None)
    kept_audio, dropped, written = [], [], {}
    for entry in out.get("audio") if isinstance(out.get("audio"), list) else []:
        rel = entry.get("f") if isinstance(entry, dict) else None
        if isinstance(rel, str) and rel in transcripts:
            kept_audio.append(entry)
            written[rel] = [dict(s, text=scrubber.text(s["text"])) for s in transcripts[rel]]
        else:
            dropped.append(rel if isinstance(rel, str) else repr(entry))
    if kept_audio:
        out["audio"] = kept_audio
    else:
        out.pop("audio", None)
    meta = out.get("meta")
    original_meta = session.get("meta") if isinstance(session.get("meta"), dict) else {}
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
    originals = list(scrubber.values) + list(scrubber.fixed) + [h.split(":")[0] for h in scrubber.hosts]
    recorder = original_meta.get("recorderName")
    if isinstance(recorder, str) and recorder.strip() and recorder.strip() != RECORDER_NAME:
        originals.append(recorder.strip())
    review = surviving(session, out)
    review["leftovers"] = leftovers(originals, out, written)
    report = {"hosts": sorted(scrubber.hosts), "values": len(scrubber.values),
              "notesChanged": changed, "datesShifted": scrubber.dates,
              "numbers": len(scrubber.numbers), "issueKeys": len(scrubber.keys),
              "narration": {"transcripts": [transcript_name(rel) for rel in written], "dropped": dropped},
              "needsReview": review}
    return out, written, report


def scrub(session: dict, day_shift: int = 100, also=()) -> tuple:
    """(scrubbed copy, report) of a session alone; its audio entries are dropped (no transcripts given)."""
    out, _, report = scrub_all(session, None, day_shift, also)
    return out, report


def transcript_name(rel: str) -> str:
    """audio/0001.webm -> audio/0001.transcript.json, as narration.py looks it up."""
    return narration.stem_of(rel) + ".transcript.json"


def inside(root: str, rel: str):
    """The path of rel under root, or None when it would land outside it."""
    target = os.path.normpath(os.path.join(root, *rel.split("/")))
    return target if target.startswith(os.path.normpath(root) + os.sep) else None


def read_transcripts(session: dict, read_bytes, out_dir: str) -> dict:
    """{audio file: segments} for each audio entry with a readable transcript that can be written under out_dir."""
    found = {}
    audio = session.get("audio")
    for number, entry in enumerate(audio if isinstance(audio, list) else [], 1):
        rel, _ = narration.audio_entry(entry, number)
        if rel is None or rel in found or inside(out_dir, transcript_name(rel)) is None:
            continue
        segments = narration.transcript_segments(read_bytes, rel)
        if segments is not None:
            found[rel] = segments
    return found


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
        f.write("\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ct.py scrub", description="session.json copy of a recording (and its "
                                     "narration transcripts) with hosts, typed values and dates replaced")
    parser.add_argument("recording", help="recording folder, zip or session.json")
    parser.add_argument("--out", required=True, help="directory to write session.json and audio/*.transcript.json into")
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
    transcripts = read_transcripts(session, parse_recording.file_bytes(args.recording), args.out)
    paths = {rel: inside(args.out, transcript_name(rel)) for rel in transcripts}
    existing = [path for path in paths.values() if os.path.exists(path)]
    if existing:
        print(f"Error: {existing[0]} already exists; not overwriting", file=sys.stderr)
        return 2
    scrubbed, written, report = scrub_all(session, transcripts, args.day_shift, args.also)
    write_json(target, scrubbed)
    for rel, segments in written.items():
        write_json(paths[rel], {"segments": segments})
    print(json.dumps(report, indent=2, ensure_ascii=True))
    review = report["needsReview"]
    if review["leftovers"]:
        print(f"Warning: {len(review['leftovers'])} original value(s) are still in the output "
              "(needsReview.leftovers); replace them with --also or edit the files", file=sys.stderr)
    if report["narration"]["dropped"]:
        print("Note: audio without a transcript was dropped, so its narration is lost: "
              + ", ".join(report["narration"]["dropped"]), file=sys.stderr)
    if any(review.values()):
        print("Warning: displayed text may remain (see needsReview); review the files before storing them, "
              "and keep them in a private repo", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
