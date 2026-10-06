#!/usr/bin/env python3
"""
CenterTest CSS ID Getter Finder

Searches cssid resources for a given CSS ID and returns the hierarchyPath (getter chain).

Usage:
  python3 find_getter.py <app> "<css_id>"         # search (prompts for path on first run)
  python3 find_getter.py --set-path "<path>"       # set/override the resources path
  python3 find_getter.py --show-path               # show current configured path

Apps: pc, cc, bc, ab (or cm)

Supports two layouts (auto-detected):
  1. New: cssids/<app>/<Page>.properties  (key=value per line, java.util.Properties escaping)
  2. Legacy: <app>.cssids single file     (JSON-like "cssId"/"hierarchyPath" pairs)

CSS IDs separate their segments with '-' (Guidewire 10) or ':' (Guidewire 9).

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/cssid-finder/scripts/find_getter.py
"""

import sys
import re
import subprocess
import os
import json
import itertools

CONFIG_DIR = os.path.expanduser("~/.centertest")
CONFIG_FILE = os.path.join(CONFIG_DIR, "cssid-finder.json")

APP_MAP = {
    "pc": ("pc", "PolicyCenter"),
    "cc": ("cc", "ClaimCenter"),
    "bc": ("bc", "BillingCenter"),
    "ab": ("ab", "ContactManager/AgencyCenter"),
    "cm": ("ab", "ContactManager/AgencyCenter"),
}


def load_config() -> dict:
    """Load config from ~/.centertest/cssid-finder.json."""
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    """Save config to ~/.centertest/cssid-finder.json."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Config saved to {CONFIG_FILE}")


def get_cssids_dir() -> str:
    """Resolve the resources path: env var > config file > prompt user."""
    # 1. Environment variable takes priority (override)
    env_val = os.environ.get("CENTERTEST_CSSIDS_DIR")
    if env_val:
        return env_val

    # 2. Saved config
    config = load_config()
    if config.get("cssids_dir"):
        return config["cssids_dir"]

    # 3. First run — ask user
    print("No cssids path configured yet.")
    print("Enter the path to the generated project's resources directory")
    print("(the folder containing 'cssids/' or '*.cssids' files):")
    print()
    path = input("> ").strip()

    if not path:
        print("Error: no path provided")
        sys.exit(1)

    path = os.path.expanduser(path)

    if not os.path.isdir(path):
        print(f"Error: directory not found: {path}")
        sys.exit(1)

    config["cssids_dir"] = path
    save_config(config)
    print()
    return path


def set_path(path: str) -> None:
    """Set or override the resources path."""
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        print(f"Error: directory not found: {path}")
        sys.exit(1)

    config = load_config()
    old = config.get("cssids_dir", "(not set)")
    config["cssids_dir"] = path
    save_config(config)
    print(f"  Old: {old}")
    print(f"  New: {path}")


def show_path() -> None:
    """Show the current configured path."""
    env_val = os.environ.get("CENTERTEST_CSSIDS_DIR")
    config = load_config()
    saved = config.get("cssids_dir")

    if env_val:
        print(f"Active path (from CENTERTEST_CSSIDS_DIR env var): {env_val}")
        if saved:
            print(f"Saved path (overridden by env var): {saved}")
    elif saved:
        print(f"Active path: {saved}")
    else:
        print("No path configured. Run a search or use --set-path to configure.")


# Placeholders used in the generated cssid keys (see GuidewireElement.getId in
# centertest-core, and the "How CSS IDs map to page-object getters" doc):
#   '#'     -> iterator index   (a numeric segment on an iterator widget)
#   '[ROW]' -> table / list-view row index
ITERATOR_PLACEHOLDER = "#"
ROW_PLACEHOLDER = "[ROW]"
# Segment separators: '-' on Guidewire 10, ':' on Guidewire 9.
SEPARATOR = re.compile(r"([-:])")
# An unescaped .properties line: key up to the first '=', ':' or whitespace, then the separator.
PLAIN_LINE = re.compile(r"([^=:\s]*)[ \t\f]*[=:]?[ \t\f]*(.*)", re.DOTALL)
# A conditional toolbar segment '[X_tb]' (never the '[ROW]' placeholder).
TOOLBAR_SEGMENT = re.compile(r"\[([^\[\]]*_tb)\]")
TOOLBAR_SEGMENT_WITH_SEPARATOR = re.compile(r"\[[^\[\]]*_tb\][-:]?")
# Cap the #/[ROW] combinations we try, to avoid explosion on pathological ids.
MAX_COMBINATORIAL_SEGMENTS = 6


def _bracket_variants(css_id: str) -> list[str]:
    """Expand conditional '[X_tb]' toolbar segments.

    Mirrors AbstractWidget.findElement / CssMapper.addWithHierarchy in centertest-core:
    a bracketed '[X_tb]' segment may or may not appear in the live DOM id, so we try
    (1) the id as-is, (2) brackets removed (table name kept), (3) the whole segment removed.
    """
    forms = [css_id]
    if "_tb]" in css_id:
        forms.append(TOOLBAR_SEGMENT.sub(r"\1", css_id))
        forms.append(TOOLBAR_SEGMENT_WITH_SEPARATOR.sub("", css_id))
    return forms


def _expand_numeric(parts: list[str]) -> list[list[str]]:
    """Replace each numeric segment independently with '#' or '[ROW]'.

    A runtime CSS id can contain BOTH an iterator index and table-row indices in the
    same id (e.g. ClauseIterator-3-...-RiskTermsLV-0-...). The stored key uses '#' for
    the iterator and '[ROW]' for the rows, so we generate every #/[ROW] combination and
    let the search find the one that matches.
    """
    numeric_idx = [i for i, p in enumerate(parts) if p.isdigit()]
    if not numeric_idx:
        return [parts]

    if len(numeric_idx) > MAX_COMBINATORIAL_SEGMENTS:
        hash_form = [ITERATOR_PLACEHOLDER if p.isdigit() else p for p in parts]
        row_form = [ROW_PLACEHOLDER if p.isdigit() else p for p in parts]
        return [hash_form, row_form]

    forms = []
    for combo in itertools.product((ITERATOR_PLACEHOLDER, ROW_PLACEHOLDER), repeat=len(numeric_idx)):
        candidate = list(parts)
        for idx, placeholder in zip(numeric_idx, combo):
            candidate[idx] = placeholder
        forms.append(candidate)
    return forms


def normalize_css_id(css_id: str) -> list[str]:
    """Normalize a runtime CSS ID into the candidate key forms stored in the cssid files.

    Handles the three generation-time transforms (see the "How CSS IDs map to
    page-object getters" doc):
      * iterator index  -> '#'
      * table-row index -> '[ROW]'
      * conditional toolbar segment '[X_tb]' (kept / brackets removed / segment removed)

    Returns an ordered, de-duplicated list of forms to try.
    """
    if css_id.endswith("_Input"):
        css_id = css_id[:-6]

    parts = SEPARATOR.split(css_id)  # keeps the separators, so each id rejoins as it was
    forms: list[str] = []
    seen: set[str] = set()
    for candidate_parts in _expand_numeric(parts):
        candidate = "".join(candidate_parts)
        for variant in _bracket_variants(candidate):
            if variant not in seen:
                seen.add(variant)
                forms.append(variant)
    return forms


def get_page_name(css_id: str) -> str:
    """Page file name for a CSS ID, as CssMapper.pageName in centertest-core writes it:
    the segment before the first '-' or ':', or '_misc' for an id that starts with '#'."""
    if css_id.startswith("#"):
        return "_misc"
    separator = SEPARATOR.search(css_id)
    return css_id[:separator.start()] if separator and separator.start() > 0 else css_id


_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}


def _unescape(text: str) -> str:
    """Undo java.util.Properties escapes: \\t \\n \\r \\f, \\uXXXX, and \\X for any other X."""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2:i + 6]):
                out.append(chr(int(text[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_properties_line(line: str):
    """Split one .properties line into (key, value) as java.util.Properties.load does.

    Returns None for blank and comment lines. A line that starts with an unescaped '#'
    but has '=' is still read as data: files generated before CenterTest 6.15 wrote
    '#'-rooted ids unescaped."""
    line = line.lstrip(" \t\f")
    if not line or (line[0] in "#!" and "=" not in line):
        return None
    if "\\" not in line:  # nothing escaped: the common case, split without the char loop
        plain = PLAIN_LINE.match(line)
        return plain.group(1), plain.group(2)
    i = 0
    while i < len(line) and line[i] not in "=: \t\f":
        i += 2 if line[i] == "\\" else 1
    key_end = min(i, len(line))
    while i < len(line) and line[i] in " \t\f":
        i += 1
    if i < len(line) and line[i] in "=:":
        i += 1
    while i < len(line) and line[i] in " \t\f":
        i += 1
    return _unescape(line[:key_end]), _unescape(line[i:])


def detect_layout(cssids_dir: str, app_key: str):
    """Detect which layout is present. Returns ('properties', path) or ('legacy', path)."""
    props_dir = os.path.join(cssids_dir, "cssids", app_key)
    if os.path.isdir(props_dir):
        return "properties", props_dir

    legacy_file = os.path.join(cssids_dir, f"{app_key}.cssids")
    if os.path.isfile(legacy_file):
        return "legacy", legacy_file

    return None, None


def search_properties(props_dir: str, normalized: str, exact_only: bool = False) -> list[str]:
    """Search in properties layout: cssids/<app>/<Page>.properties files."""
    # The page file the generator wrote this id into ('_misc' for '#'-rooted ids)
    page_file = os.path.join(props_dir, f"{get_page_name(normalized)}.properties")
    if os.path.isfile(page_file):
        found = _match_entries(_load_entries((page_file,)), normalized, exact_only)
        if found:
            return found

    # A partial id, or a file layout from an older generator: search every page file
    page_files = []
    for root, _, files in os.walk(props_dir):
        page_files += [os.path.join(root, name) for name in sorted(files) if name.endswith(".properties")]
    return _match_entries(_load_entries(tuple(page_files)), normalized, exact_only)


_entries_cache: dict[tuple[str, ...], tuple[list, dict, dict]] = {}


def _load_entries(page_files: tuple[str, ...]) -> tuple[list, dict, dict]:
    """The lines of the page files as (key, value, raw key, raw value), read once per run,
    plus an index of each key kind for exact lookups.

    key/value are what java.util.Properties.load reads, as CenterTest does at runtime.
    The raw split at the first '=' covers files written before CenterTest 6.15 without
    escaping, where a Guidewire 9 key such as 'Page:Panel:Field' kept its ':' unescaped."""
    if page_files not in _entries_cache:
        entries, by_key, by_raw_key = [], {}, {}
        for page_file in page_files:
            with open(page_file, encoding="utf-8", errors="replace") as lines:
                for line in lines:
                    line = line.rstrip("\r\n")
                    entry = parse_properties_line(line)
                    if entry is None:
                        continue
                    raw_key, _, raw_value = line.partition("=")
                    key, value, raw_key, raw_value = entry[0], entry[1].strip(), raw_key.strip(), raw_value.strip()
                    entries.append((key, value, raw_key, raw_value))
                    by_key.setdefault(key, []).append(value)
                    by_raw_key.setdefault(raw_key, []).append(raw_value)
        _entries_cache[page_files] = (entries, by_key, by_raw_key)
    return _entries_cache[page_files]


def _match_entries(loaded: tuple[list, dict, dict], normalized: str, exact_only: bool = False) -> list[str]:
    """Getter chains whose key is the CSS ID, or contains it when ``exact_only`` is False."""
    entries, by_key, by_raw_key = loaded
    exact = by_key.get(normalized) or by_raw_key.get(normalized)
    if exact or exact_only:
        return list(exact or [])
    for key_index, value_index in ((0, 1), (2, 3)):
        contains = [e[value_index] for e in entries if normalized in e[key_index]]
        if contains:
            return contains
    return []


def search_legacy(filepath: str, normalized: str) -> list[str]:
    """Search in legacy single-file layout: <app>.cssids (JSON-like)."""
    search_term = f'"cssId": "{normalized}"'
    result = subprocess.run(
        ["grep", "-A", "1", "-F", search_term, filepath],
        capture_output=True, text=True,
    )
    output = result.stdout.strip()
    if not output:
        return []

    blocks = re.split(r"\n--\n", output)
    results = []
    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        for line in lines:
            m = re.search(r'"hierarchyPath":\s*"(.+?)"', line)
            if m:
                results.append(m.group(1))
                break
    return results


def find_getter(app: str, css_id: str) -> None:
    app_lower = app.lower()
    if app_lower not in APP_MAP:
        print(f"Error: unknown app '{app}'. Valid apps: pc, cc, bc, ab, cm")
        sys.exit(1)

    cssids_dir = get_cssids_dir()
    app_key, app_name = APP_MAP[app_lower]
    normalized_forms = normalize_css_id(css_id)
    was_normalized = normalized_forms[0] != css_id

    print(f"Searching in {app.upper()} ({app_name}) for: {css_id}")
    if was_normalized:
        shown = normalized_forms[:4]
        suffix = f" (+{len(normalized_forms) - len(shown)} more)" if len(normalized_forms) > len(shown) else ""
        print(f"Normalized to: {', '.join(shown)}{suffix}")

    layout, path = detect_layout(cssids_dir, app_key)
    if layout is None:
        print(f"\nError: no cssid data found for {app.upper()}")
        print(f"  Checked: {cssids_dir}/cssids/{app_key}/  (properties layout)")
        print(f"  Checked: {cssids_dir}/{app_key}.cssids   (legacy layout)")
        print(f"\nRun with --set-path to update the resources path.")
        sys.exit(1)

    print(f"Layout: {layout} ({path})")
    print()

    # Pass 1: prefer an exact key match across all candidate forms (so a partial match
    # on an early form does not pre-empt an exact match on a later #/[ROW] combination).
    # Pass 2: fall back to partial (contains) matches.
    found, matched_form = [], None
    passes = [True, False] if layout == "properties" else [True]
    for exact_only in passes:
        for form in normalized_forms:
            if layout == "properties":
                found = search_properties(path, form, exact_only=exact_only)
            else:
                found = search_legacy(path, form)
            if found:
                matched_form = form
                break
        if found:
            break

    if not found:
        print(f"Not found: {normalized_forms[0]}")
        if was_normalized:
            print(f"(searched {len(normalized_forms)} form(s))")
        sys.exit(0)

    if matched_form and matched_form != css_id:
        print(f"Matched key: {matched_form}")
    if len(found) == 1:
        print("Found:")
        print(f"  {found[0]}")
    else:
        print(f"Found {len(found)} matches:")
        for i, h in enumerate(found, 1):
            print(f"  [{i}] {h}")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--show-path":
        show_path()
        sys.exit(0)

    if len(sys.argv) == 3 and sys.argv[1] == "--set-path":
        set_path(sys.argv[2])
        sys.exit(0)

    if len(sys.argv) != 3 or sys.argv[1].startswith("-"):
        print("Usage:")
        print("  python3 find_getter.py <app> \"<css_id>\"   # search for getter")
        print("  python3 find_getter.py --set-path <path>   # set resources path")
        print("  python3 find_getter.py --show-path          # show current path")
        print()
        print("  app: pc, cc, bc, ab, cm")
        print()
        print("On first run, you will be prompted for the resources path.")
        print("Override anytime with --set-path or CENTERTEST_CSSIDS_DIR env var.")
        sys.exit(1)

    find_getter(sys.argv[1], sys.argv[2])
