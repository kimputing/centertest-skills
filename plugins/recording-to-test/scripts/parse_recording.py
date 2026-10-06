#!/usr/bin/env python3
"""
CenterTest Recorder recording -> plan JSON for the recording-to-test skill.

Usage:
  python3 parse_recording.py <recording.zip|folder> --cssids <resources dir> [--out plan.json]

Reads only session.json. <resources dir> holds cssids/<app>/<Page>.properties (or the legacy
<app>.cssids), e.g. the cssids/ that scan_project.py extracted from the project's *-generated jar.
Widget ids are resolved with find_getter.py, an unchanged copy of cssid-finder's script; ids it
cannot resolve go through the fallback rules in resolve_fallback().
"""

import argparse
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find_getter  # noqa: E402  vendored: byte-identical to plugins/cssid-finder/scripts/find_getter.py

APPS = {"PolicyCenter": "pc", "BillingCenter": "bc", "ClaimCenter": "cc", "ContactManager": "ab"}
REDACTED = "[redacted]"


class RecordingError(Exception):
    """The recording cannot be read."""


def jstr(value) -> str:
    """A Java string literal for a recorded value."""
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def load_session(path: str) -> dict:
    """session.json from a recording folder, or from the zip the recorder writes
    (<id>_<slug>/session.json under one top-level folder)."""
    if os.path.isdir(path):
        session_file = os.path.join(path, "session.json")
        if not os.path.isfile(session_file):
            raise RecordingError(f"no session.json in {path}")
        with open(session_file, encoding="utf-8") as f:
            return json.load(f)
    if os.path.isfile(path) and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist()
                           if n.split("/")[-1] == "session.json" and n.count("/") <= 1)
            if not names:
                raise RecordingError(f"no session.json in {path}")
            return json.loads(z.read(names[0]).decode("utf-8"))
    raise RecordingError(f"not a recording folder or zip: {path}")


def messages(step: dict) -> list:
    """Page messages as {text, level}; recordings before 1.0.9 store plain strings."""
    return [{"text": m, "level": ""} if isinstance(m, str)
            else {"text": m.get("text", ""), "level": m.get("level", "")}
            for m in step.get("messages") or []]


def wait_title(title) -> str:
    """The stable part of a page title ('Account Summary: Duncan Test' -> 'Account Summary').
    waitForPageTitle matches a substring, so the prefix before ':' is enough."""
    return (title or "").split(":")[0].strip()


ROW_SELECT = ".getFirstRow().select()"
SEGMENT = re.compile(r"[-:]")


def fill_iterators(getter: str, widget_id: str, form: str) -> str:
    """Put the recorded index back where the generator kept a '#' iterator placeholder."""
    ids, keys = SEGMENT.split(widget_id), SEGMENT.split(form)
    if "#" not in getter or len(ids) != len(keys):
        return getter
    for key, part in zip(keys, ids):
        if key == "#":
            getter = getter.replace("#", part, 1)
    return getter


def lookup(cssids_dir: str, app: str, widget_id: str):
    """find_getter's search: an exact key across all normalized forms first, then a partial one.
    Returns ('resolved' | 'partial', [getter, ...]) or (None, [])."""
    layout, path = find_getter.detect_layout(cssids_dir, find_getter.APP_MAP[app][0])
    if layout is None:
        return None, []
    forms = find_getter.normalize_css_id(widget_id)
    for exact_only in ([True, False] if layout == "properties" else [True]):
        for form in forms:
            if layout == "properties":
                found = find_getter.search_properties(path, form, exact_only=exact_only)
            else:
                found = find_getter.search_legacy(path, form)
            if found:
                getters = list(dict.fromkeys(fill_iterators(g, widget_id, form) for g in found))
                return ("resolved" if exact_only else "partial"), getters
    return None, []


def with_row(getter: str, action: dict) -> str:
    """Select a list row by its contents, as the recording identified it, instead of the first row."""
    keys = action.get("rowKey") or []
    if not keys or ROW_SELECT not in getter:
        return getter
    page = action.get("page") or 1
    pages = f".forMaximumPages({page})" if page > 1 else ""
    filters = "".join(f'.with({jstr(k.get("header"))}, {jstr(k.get("text"))}, "TextCell")' for k in keys)
    return getter.replace(ROW_SELECT, f".getFirstRow(){pages}{filters}.select()", 1)


def resolve(cssids_dir: str, app, action: dict) -> dict:
    """{'resolution', 'getter'?, 'candidates'?, 'rule'?, 'reason'?} for one recorded action."""
    widget_id = action.get("widgetId")
    if not widget_id:
        return {"resolution": "unresolved", "reason": "no widget id"}
    if app is None:
        return {"resolution": "unresolved", "reason": "unknown application"}
    resolution, getters = lookup(cssids_dir, app, widget_id)
    if getters:
        result = {"resolution": resolution, "getter": with_row(getters[0], action)}
        if len(getters) > 1:
            result["candidates"] = [with_row(g, action) for g in getters]
        return result
    result = resolve_fallback(cssids_dir, app, action)
    result["getter"] = with_row(result["getter"], action)
    return result


# Recorder widget kind -> CenterTest widget class for the raw Widget<Type>.get(id, getContext()) form
RAW_WIDGET = {
    "text": "WidgetTextInput",
    "select": "WidgetRangeInput",
    "checkbox": "WidgetCheckBoxInput",
    "LinkWidget": "WidgetLink",
    "TabWidget": "WidgetMenuItem",
    "MenuItemWidget": "WidgetMenuItem",
    "MenuActionsWidget": "WidgetMenuItem",
    "ToolbarButtonWidget": "WidgetToolbarButton",
    "PickerToolbarButtonWidget": "WidgetToolbarButton",
    "WizardButtonWidget": "WidgetToolbarButton",
    "CheckedValuesToolbarButtonWidget": "WidgetCheckedValuesToolbarButton",
    "ButtonValueWidget": "WidgetButtonInput",
    "ImageButtonWidget": "WidgetButton",
    "button": "WidgetButton",
}
# Generated row getters for Guidewire's built-in list columns
ROW_COLUMNS = {"_Select": "getSelect", "_Checkbox": "get_CHECKBOX"}


def cap(name: str) -> str:
    return name[:1].upper() + name[1:]


def split_id(widget_id: str):
    """Segments of a widget id and the separators between them ('-' in GW10, ':' in GW9)."""
    tokens = re.split(r"([-:])", widget_id)
    return tokens[0::2], tokens[1::2]


def join_id(parts: list, seps: list) -> str:
    return "".join(part + sep for part, sep in zip(parts, list(seps) + [""]))


def page_instance(cssids_dir: str, app: str, page: str):
    """'new XPage(getContext())' for a PCF page, read from any getter in its cssids page file."""
    layout, path = find_getter.detect_layout(cssids_dir, find_getter.APP_MAP[app][0])
    page_file = os.path.join(path, f"{page}.properties") if layout == "properties" else None
    if not page_file or not os.path.isfile(page_file):
        return None
    with open(page_file, encoding="utf-8", errors="replace") as lines:
        for line in lines:
            entry = find_getter.parse_properties_line(line.rstrip("\r\n"))
            match = entry and re.match(r"new \w+\(getContext\(\)\)", entry[1].strip())
            if match:
                return match.group(0)
    return None


def resolve_fallback(cssids_dir: str, app: str, action: dict) -> dict:
    """Ids cssids has no entry for, built in the project's own idioms. Always returns a result:
    the last rule writes the raw Widget<Type>.get(id, getContext()) form."""
    widget_id, kind = action["widgetId"], action.get("kind") or ""
    parts, seps = split_id(widget_id)

    # toolbar: cssids keeps '[X_tb]' bracketed (or drops it); the live id has it bare
    if any(p.endswith("_tb") for p in parts):
        bracketed = [f"[{p}]" if p.endswith("_tb") else p for p in parts]
        resolution, getters = lookup(cssids_dir, app, join_id(bracketed, seps))
        if resolution == "resolved":
            return {"resolution": "rule", "rule": "toolbar", "getter": getters[0]}

    # wizardButton: <Wizard>-Next -> new XWizardPage(getContext()).getWizardButtons().getNext()
    if kind == "WizardButtonWidget" and len(parts) == 2:
        page = page_instance(cssids_dir, app, parts[0])
        if page:
            return {"resolution": "rule", "rule": "wizardButton",
                    "getter": f"{page}.getWizardButtons().get{cap(parts[1])}()"}

    # tabBar: the TabBar page object has a getter per tab and per tab menu item
    if parts[0] == "TabBar" and len(parts) >= 2:
        last = parts[-1]
        if len(parts) > 2 and last.startswith(parts[-2] + "_"):
            last = last[len(parts[-2]) + 1:]
        return {"resolution": "rule", "rule": "tabBar", "getter": f"new TabBar(getContext()).get{cap(last)}()"}

    # rowColumn: <...LV>-<n>-<column>: the table's row chain plus the column's getter
    if len(parts) >= 3 and parts[-2].isdigit():
        resolution, getters = lookup(cssids_dir, app, join_id(parts[:-2], seps[:-2]))
        if resolution == "resolved" and getters[0].endswith(ROW_SELECT):
            column = parts[-1]
            getter = ROW_COLUMNS.get(column, f"get{cap(column)}")
            return {"resolution": "rule", "rule": "rowColumn", "column": column,
                    "getter": f"{getters[0]}.{getter}()"}

    widget = RAW_WIDGET.get(kind) or ("WidgetCheckBoxInput" if action.get("inputType") == "checkbox" else "WidgetLabel")
    return {"resolution": "raw", "rule": "raw", "widget": widget,
            "getter": f"{widget}.get({jstr(widget_id)}, getContext())"}
