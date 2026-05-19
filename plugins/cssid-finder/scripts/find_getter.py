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
  1. New: cssids/<app>/<Page>.properties  (key=value per line)
  2. Legacy: <app>.cssids single file     (JSON-like "cssId"/"hierarchyPath" pairs)

Latest version: https://github.com/Kimputing/centertest-skills/blob/main/skills/cssid-finder/scripts/find_getter.py
"""

import sys
import re
import subprocess
import os
import json

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


def normalize_css_id(css_id: str) -> list[str]:
    """Replace purely numeric segments with row placeholders and strip trailing '_Input' suffix.

    Returns list of normalized forms to try (both [ROW] and # are used in properties files).
    """
    if css_id.endswith("_Input"):
        css_id = css_id[:-6]
    parts = css_id.split("-")
    has_numeric = any(part.isdigit() for part in parts)

    row_form = "-".join("[ROW]" if part.isdigit() else part for part in parts)
    hash_form = "-".join("#" if part.isdigit() else part for part in parts)

    if not has_numeric:
        return [row_form]

    # Both forms may exist — try both
    forms = []
    if row_form not in forms:
        forms.append(row_form)
    if hash_form not in forms:
        forms.append(hash_form)
    return forms


def get_page_name(css_id: str) -> str:
    """Extract page name (first segment before '-') from a CSS ID."""
    return css_id.split("-")[0]


def detect_layout(cssids_dir: str, app_key: str):
    """Detect which layout is present. Returns ('properties', path) or ('legacy', path)."""
    props_dir = os.path.join(cssids_dir, "cssids", app_key)
    if os.path.isdir(props_dir):
        return "properties", props_dir

    legacy_file = os.path.join(cssids_dir, f"{app_key}.cssids")
    if os.path.isfile(legacy_file):
        return "legacy", legacy_file

    return None, None


def search_properties(props_dir: str, normalized: str) -> list[str]:
    """Search in properties layout: cssids/<app>/<Page>.properties files."""
    page = get_page_name(normalized)

    # Try exact page file first
    page_file = os.path.join(props_dir, f"{page}.properties")
    if os.path.isfile(page_file):
        return _grep_properties_file(page_file, normalized)

    # Fall back to _misc.properties (for entries starting with #)
    misc_file = os.path.join(props_dir, "_misc.properties")
    if os.path.isfile(misc_file):
        return _grep_properties_file(misc_file, normalized)

    # Last resort: grep all .properties files in the directory
    result = subprocess.run(
        ["grep", "-h", "-F", normalized, props_dir],
        capture_output=True, text=True,
    )
    return _parse_properties_output(result.stdout, normalized)


def _grep_properties_file(filepath: str, normalized: str) -> list[str]:
    """Grep a single properties file for the normalized CSS ID."""
    result = subprocess.run(
        ["grep", "-F", normalized, filepath],
        capture_output=True, text=True,
    )
    return _parse_properties_output(result.stdout, normalized)


def _parse_properties_output(output: str, normalized: str) -> list[str]:
    """Parse properties format lines: cssId=getterChain.

    Tries exact match first, then contains match for partial CSS IDs.
    """
    exact = []
    contains = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            if key == normalized:
                exact.append(value.strip())
            elif normalized in key:
                contains.append(value.strip())
    return exact if exact else contains


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
        print(f"Normalized to: {', '.join(normalized_forms)}")

    layout, path = detect_layout(cssids_dir, app_key)
    if layout is None:
        print(f"\nError: no cssid data found for {app.upper()}")
        print(f"  Checked: {cssids_dir}/cssids/{app_key}/  (properties layout)")
        print(f"  Checked: {cssids_dir}/{app_key}.cssids   (legacy layout)")
        print(f"\nRun with --set-path to update the resources path.")
        sys.exit(1)

    print(f"Layout: {layout} ({path})")
    print()

    # Try each normalized form until we find results
    found = []
    matched_form = None
    for form in normalized_forms:
        if layout == "properties":
            found = search_properties(path, form)
        else:
            found = search_legacy(path, form)
        if found:
            matched_form = form
            break

    if not found:
        print(f"Not found: {normalized_forms[0]}")
        if was_normalized:
            print(f"(searched forms: {', '.join(normalized_forms)})")
        sys.exit(0)

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
