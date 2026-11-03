#!/usr/bin/env python3
"""Client profiles: Kimputing-wide defaults overridden by the repo's .claude/client-profile.md."""
import argparse
import datetime
import json
import os
import re
import sys

PROFILE_PATH = os.path.join(".claude", "client-profile.md")
DEFAULTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profile", "defaults.md")
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profile", "template.md")
STALE_DAYS = 90
VERIFIED = re.compile(r"\(verified (\d{4}-\d{2}-\d{2})\)")

# switch -> allowed values; None = free text
SWITCHES = {
    "sharedValues": ("dataKey", "setCustom", "auto"),
    "recordedValues": ("data", "constants"),
    "comments": ("none", "notes", "javadoc", "auto"),
    "standardsSkill": None,
    "negativeProtocol": ("framework", "project", "auto"),
    "workbookWriter": ("openpyxl", "excel", "manual"),
    "gate": ("phases", "plan", "single"),
    "defaultEnvironment": None,
    "contextNaming": ("role", "centerRoleContext", "auto"),
    "runCommand": None,
}


class ProfileError(Exception):
    pass


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_front_matter(text: str):
    """(flat key/value dict, body). A text without a leading '---' block has no front matter."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    values = {}
    for number, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return values, "\n".join(lines[number:])
        stripped = re.sub(r"(^|\s)#.*$", "", line).strip()
        if not stripped:
            continue
        if line[0] in " \t" or line.startswith("- ") or ":" not in stripped:
            raise ProfileError(f"nested YAML is not supported: line {number}")
        key, _, value = stripped.partition(":")
        value = value.strip()
        if value.endswith(":"):
            raise ProfileError(f"nested YAML is not supported: line {number}")
        values[key.strip()] = _unquote(value)
    raise ProfileError("front matter is not closed with ---")


NO_FRONT_MATTER = "no front matter: switches use the defaults"


def has_front_matter(text: str) -> bool:
    return text.split("\n", 1)[0].strip() == "---"


def _read(path: str) -> str:
    """The file's text; utf-8-sig, because Windows editors save UTF-8 with a BOM."""
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _scan_value(project, key):
    """The switch value the scan supports for an 'auto' switch, else None."""
    if not project:
        return None
    if key == "sharedValues":
        usage = (project.get("sharedValuesUsage") or {}).get("value")
        if usage and (usage.get("dataKey", 0) or usage.get("setCustom", 0)):
            return "dataKey" if usage["dataKey"] > usage["setCustom"] else "setCustom"
    if key == "negativeProtocol":
        usage = (project.get("negativeProtocol") or {}).get("value")
        if usage and (usage.get("projectException", 0) or usage.get("framework", 0)):
            return "project" if usage["projectException"] > usage["framework"] else "framework"
    return None


def stale_facts(body: str, today: datetime.date):
    """(stale facts, malformed verified dates as invalid entries)."""
    stale, bad = [], []
    for line in body.split("\n"):
        match = VERIFIED.search(line)
        if not match:
            continue
        try:
            verified = datetime.date.fromisoformat(match.group(1))
        except ValueError:
            bad.append({"key": "verified", "value": match.group(1), "allowed": "YYYY-MM-DD"})
            continue
        if (today - verified).days > STALE_DAYS:
            stale.append({"line": line.strip(), "verified": match.group(1)})
    return stale, bad


def resolve(root, project, defaults_path, today):
    path = os.path.join(root, PROFILE_PATH)
    exists = os.path.isfile(path)
    defaults, _ = parse_front_matter(_read(defaults_path))
    error, warnings = None, []
    try:
        repo, body = {}, ""
        if exists:
            text = _read(path)
            repo, body = parse_front_matter(text)
            if not has_front_matter(text):
                warnings.append(NO_FRONT_MATTER)
    except ProfileError as problem:  # a malformed repo profile falls back to the defaults
        repo, body, error = {}, "", str(problem)
    except UnicodeDecodeError as problem:
        repo, body, error = {}, "", f"{PROFILE_PATH} is not UTF-8 text ({problem}): save it as UTF-8"
    except OSError as problem:
        repo, body, error = {}, "", f"{PROFILE_PATH} is not readable: {problem}"
    switches, invalid = {}, []
    for key, allowed in SWITCHES.items():
        value, source = defaults.get(key, ""), "defaults"
        if key in repo:
            if allowed is None or repo[key] in allowed:
                value, source = repo[key], "repo"
            else:
                invalid.append({"key": key, "value": repo[key], "allowed": list(allowed)})
        if value == "auto":
            found = _scan_value(project, key)
            if found:
                value, source = found, "scan"
        switches[key] = {"value": value, "source": source}
    stale, bad_dates = stale_facts(body, today)
    result = {"path": path, "exists": exists, "switches": switches,
              "unknownKeys": sorted(set(repo) - set(SWITCHES)), "invalid": invalid + bad_dates,
              "staleFacts": stale}
    if error:
        result["error"] = error
    if warnings:
        result["warnings"] = warnings
    return result


def _bullets(items, stamp):
    return "\n".join(f"- {item} {stamp}" for item in items) if items else f"- none found {stamp}"


def init_profile(project, today, template_path):
    """Draft client-profile.md text from the scan; never writes anything."""
    defaults, _ = parse_front_matter(_read(DEFAULTS_PATH))
    stamp = f"(verified {today.isoformat()})"

    def value(name):
        return (project.get(name) or {}).get("value")

    layout, style, build = value("testLayout"), value("testStyle"), value("build")
    usage = (project.get("sharedValuesUsage") or {}).get("value") or {}
    set_custom, data_key = usage.get("setCustom", 0), usage.get("dataKey", 0)
    mixed = bool(set_custom and data_key)
    lines = []
    for key in SWITCHES:
        found = "auto" if mixed and key == "sharedValues" else _scan_value(project, key)
        lines.append(f"{key}: {found or defaults.get(key, '')}".rstrip())
    prefixes = (layout or {}).get("lobPrefixes", {})
    layout_items = [f"{lob}: test class prefix {prefix}_" for lob, prefix in prefixes.items()]
    roles = [f"invocation context role {role} ({count} uses)" for role, count in ((style or {}).get("roles") or {}).items()]
    build_items = []
    if build:
        build_items = [f"compile: {build['compile']}"]
        if build.get("run"):
            build_items.append(f"run: {build['run']}")
        if build.get("profiles"):
            build_items.append("profiles: " + ", ".join(build["profiles"]))
    template = _read(template_path)
    for name, items in (("layout", layout_items), ("roles", roles), ("build", build_items),
                        ("guidance", value("guidance") or [])):
        template = template.replace("{" + name + "}", _bullets(items, stamp))
    if mixed:
        # a saved value would hide the mix from the wizard (resolve would report source "repo")
        template = template.rstrip("\n") + "\n\n## Shared values\n" + _bullets(
            [f"setCustom used {set_custom} times, generated DataKey {data_key} times: mixed, "
             "the wizard asks per scenario"], stamp) + "\n"
    return "---\n" + "\n".join(lines) + "\n---\n" + template


def _load_project(path):
    with open(path, encoding="utf-8") as f:
        project = json.load(f)
    if not isinstance(project, dict):
        raise ProfileError(f"{path} must hold a JSON object")
    return project


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="ct.py profile", description="Client profile: resolve switches or draft a profile")
    sub = ap.add_subparsers(dest="action", required=True)
    res = sub.add_parser("resolve", help="print the resolved switches as JSON")
    res.add_argument("--root", required=True)
    res.add_argument("--project")
    ini = sub.add_parser("init", help="draft a client-profile.md from a scan")
    ini.add_argument("--project", required=True)
    ini.add_argument("--out")
    args = ap.parse_args(argv)
    today = datetime.date.today()
    try:
        project = _load_project(args.project) if args.project else None
        if args.action == "resolve":
            result = resolve(args.root, project, DEFAULTS_PATH, today)
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0
        text = init_profile(project, today, TEMPLATE_PATH)
        if args.out:
            if os.path.exists(args.out):
                print(f"Error: {args.out} exists; not overwriting", file=sys.stderr)
                return 2
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            print(text)
    except (ProfileError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
