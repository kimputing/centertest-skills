#!/usr/bin/env python3
"""
CenterTest Recorder recording -> plan JSON for the recording-to-test skill.

Usage:
  python3 parse_recording.py <recording.zip|folder|session.json> --cssids <resources dir> [--out plan.json]

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
    (<id>_<slug>/session.json under one top-level folder). Recorders after 1.0.10 keep a
    recording as <rec>/<rec>/session.json beside <rec>/<rec>.zip, so the outer folder works too.
    A path to session.json itself is read as it is."""
    if os.path.isfile(path) and os.path.basename(path) == "session.json":
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if os.path.isdir(path):
        session_file = os.path.join(path, "session.json")
        if not os.path.isfile(session_file):
            session_file = os.path.join(path, os.path.basename(os.path.normpath(path)), "session.json")
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
    raise RecordingError(f"not a recording folder, zip or session.json: {path}")


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
    "date": "WidgetDateInput",
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

    # tabBar: TabBar-AccountTab -> getAccountTab(); a menu item TabBar-AccountTab-AccountTab_NewAccount
    # -> getAccount().getNewAccount(), where getAccount() expands the tab's submenu
    if parts[0] == "TabBar" and len(parts) >= 2:
        tab = parts[1]
        if len(parts) == 2:
            return {"resolution": "rule", "rule": "tabBar", "getter": f"new TabBar(getContext()).get{cap(tab)}()"}
        item = parts[-1][len(tab) + 1:] if parts[-1].startswith(tab + "_") else parts[-1]
        menu = tab[:-3] if tab.endswith("Tab") else tab
        return {"resolution": "rule", "rule": "tabBar",
                "getter": f"new TabBar(getContext()).get{cap(menu)}().get{cap(item)}()"}

    # rowColumn: <...LV>-<n>-<column>: the table's row chain plus the column's getter
    if len(parts) >= 3 and parts[-2].isdigit():
        resolution, getters = lookup(cssids_dir, app, join_id(parts[:-2], seps[:-2]))
        if resolution == "resolved" and getters[0].endswith(ROW_SELECT):
            column = parts[-1]
            # the live id of a cell ends in _Cell; the generated row getter does not (Description_Cell -> getDescription)
            name = column[:-len("_Cell")] if column.endswith("_Cell") else column
            getter = ROW_COLUMNS.get(column, f"get{cap(name)}")
            return {"resolution": "rule", "rule": "rowColumn", "column": column,
                    "getter": f"{getters[0]}.{getter}()"}

    widget = RAW_WIDGET.get(kind) or ("WidgetCheckBoxInput" if action.get("inputType") == "checkbox" else "WidgetLabel")
    return {"resolution": "raw", "rule": "raw", "widget": widget,
            "getter": f"{widget}.get({jstr(widget_id)}, getContext())"}


GEN = "Utilities.DataGenerator.getGenerator()"
# recorder assert -> AbstractWidget method (each has a ...Soft variant)
VALUE_CHECKS = {"isEqualTo": "assertEquals", "isNotEqualTo": "assertNotEquals",
                "isEqualToNumeric": "assertEqualsNumeric", "isNotEqualToNumeric": "assertNotEqualsNumeric",
                "contains": "assertContains", "notContains": "assertNotContains", "isLabelEqualTo": "assertLabel"}
STATE_CHECKS = {"isEmpty": "assertEmpty", "isNotEmpty": "assertNotEmpty", "isEnabled": "assertEnabled",
                "isDisabled": "assertDisabled", "isEditable": "assertEditable", "isReadonly": "assertReadOnly"}
FLAG_CHECKS = {"isVisible": "assertVisible", "isChecked": "assertChecked", "isRequired": "assertRequired"}
LIST_CHECKS = {"isIn": "assertIsIn", "optionsContains": "assertOptionsContain", "optionsEquals": "assertOptionsEqual"}
UNIQUE_GENERATOR = {"company": ".company().name()", "firstName": ".name().firstName()",
                    "lastName": ".name().lastName()", "email": ".internet().emailAddress()",
                    "phone": ".phoneNumber().cellPhone()", "vin": ".vehicle().vin()"}
NO_ERRORS = "Assertions.assertThat(MessagesUtil.getErrorMessages(getContext())).isEmpty()"


def unique_java(unique: dict):
    """The data generator call for a value marked unique: the recorder's uniqueJava() in report.html."""
    rule = unique.get("rule")
    front = jstr(unique["prefix"]) + " + " if unique.get("prefix") else ""
    if rule in UNIQUE_GENERATOR:
        return GEN + UNIQUE_GENERATOR[rule]
    if rule == "ssn":
        return "Utilities.DataGenerator.getValidSsn()"
    if rule == "letters":
        return f"{front}Utilities.getRandomStringWithoutNumbers({unique.get('length')})"
    if rule == "alnum":
        return f"{front}Utilities.getRandomString({unique.get('length')})"
    if rule == "pattern":
        pattern = unique.get("pattern") or ""
        if "?" in pattern:
            return f"{GEN}.bothify({jstr(pattern)}{', true' if unique.get('upper') else ''})"
        return f"{GEN}.numerify({jstr(pattern)})"
    return None


def value_java(action: dict) -> str:
    """The Java value an entered value is set with: the generator call for a unique one, else the shown text."""
    expr = unique_java(action["unique"]) if action.get("unique") else None
    if expr:
        return expr
    display = action.get("display")
    return jstr(display if display not in (None, '') else action.get("value"))


def action_java(action: dict):
    """The call on the widget for a click or an entered value; None for anything else."""
    if action.get("type") == "click":
        return ".click()"
    if action.get("type") != "change" or action.get("value") == REDACTED:
        return None
    value = action.get("value")
    if isinstance(value, bool):  # a checkbox: WidgetCheckBoxInput has only set(String)
        return f'.set("{str(value).lower()}")'
    return f".set({value_java(action)})"


def check_java(check: dict):
    """The widget assertion for a recorded check; a soft check uses the ...Soft variant."""
    name, soft = check.get("assert"), "Soft" if check.get("soft") else ""
    values = check.get("values") or []
    if name in VALUE_CHECKS:
        return f".{VALUE_CHECKS[name]}{soft}({jstr(check.get('expected'))})"
    if name in STATE_CHECKS:
        return f".{STATE_CHECKS[name]}{soft}()"
    if name in FLAG_CHECKS:
        return f".{FLAG_CHECKS[name]}{soft}({'false' if check.get('flag') is False else 'true'})"
    if name in LIST_CHECKS:
        listed = ", ".join(jstr(v) for v in values)
        return f".{LIST_CHECKS[name]}{soft}(new String[]{{{listed}}})"
    if name == "optionsNotContains":
        return f".assertOptionsNotContain{soft}({jstr(values[0] if values else check.get('expected'))})"
    return None


def described(description: str, assertion: str, soft: bool) -> str:
    """An assertion inside CenterTestAssertion; softAssertThat records a failure and lets the test go on."""
    method = "softAssertThat" if soft else "assertThat"
    return (f"CenterTestAssertion.withContext(getContext()).withDescription({jstr(description)})"
            f".{method}(() -> {assertion});")


def message_check_java(check: dict):
    """A page-message check as a statement; MessagesUtil has no soft form, so a soft check wraps it."""
    name, soft, expected = check.get("assert"), bool(check.get("soft")), check.get("expected")
    if name in ("messageWith", "messageContaining"):
        method = "assertMessageWith" if name == "messageWith" else "assertMessageContaining"
        call = f"MessagesUtil.{method}(getContext(), {jstr(expected)})"
        if not soft:
            return call + ";"
        shown = "Message shown" if name == "messageWith" else "Message shown containing"
        return described(f"{shown}: {'' if expected is None else expected}", call, soft=True)
    if name == "noErrorMessages":
        return described("No error messages", NO_ERRORS, soft)
    return None


COVERAGE_UTIL = "com.ankrpt.centertest.guidewire.runtime.CoverageUtil"
# recorder assert -> CoverageUtil assertion on a coverage term; CoverageUtil has no ...Soft variants
COVTERM_CHECKS = {"isEqualTo": ("assertEquals", "equals"), "isEditable": ("assertEditable", "is editable"),
                  "isReadonly": ("assertReadOnly", "is read-only"), "isNotEmpty": ("assertNotNull", "is not empty")}


def coverage_widget(action: dict):
    """'checkbox' or 'term' for a coverage widget CoverageUtil handles by its labels, else None.
    Its id holds the coverage's place in an iterator, which moves when the product model changes."""
    if action.get("type") not in ("change", "check"):
        return None
    parts, _ = split_id(action.get("widgetId") or "")
    if "CoverageInputSet" not in parts or "CovPatternInputGroup" not in parts:
        return None
    if "CovTermInputSet" in parts:
        return "term"
    return "checkbox" if parts[-1].lower() == "_checkbox" else None


def coverage_target(action: dict, widget: str, label: str) -> dict:
    """The coverage and term a coverage widget is on. A term's label is the term and the last
    context entry its coverage; without a coverage title the label is the coverage, and a blank
    term makes CoverageUtil take the coverage's first term."""
    context = action.get("context") or []
    result = {"resolution": "rule", "rule": "coverage", "getter": "coverageUtil"}
    if widget == "checkbox":
        result["coverage"] = {"coverage": label, "covterm": None}
    elif len(context) >= 2:
        result["coverage"] = {"coverage": context[-1], "covterm": label}
    else:
        result["coverage"] = {"coverage": label, "covterm": ""}
        result["warning"] = ("the recording has no coverage title: the label is used as the coverage and "
                             "its first term is set; check both on screen")
    return result


def coverage_action_java(action: dict, target: dict):
    """setSelected for a coverage checkbox, setCoverage for a term; None for anything else."""
    value = action.get("value")
    if action.get("type") != "change" or value == REDACTED:
        return None
    coverage, covterm = jstr(target["coverage"]), target["covterm"]
    if covterm is None:
        return f".setSelected({coverage}, {str(value).lower()})" if isinstance(value, bool) else None
    return f".setCoverage({coverage}, {jstr(covterm)}, {value_java(action)})"


def coverage_check_java(check: dict, target: dict):
    """The CoverageUtil assertion for a check on a coverage term; a soft check is wrapped as a whole statement."""
    if target["covterm"] is None or check.get("assert") not in COVTERM_CHECKS:
        return None
    method, verb = COVTERM_CHECKS[check["assert"]]
    args = [target["coverage"], target["covterm"]] + ([check.get("expected")] if method == "assertEquals" else [])
    call = f"{method}({', '.join(jstr(a) for a in args)})"
    if not check.get("soft"):
        return "." + call
    expected = f" {check.get('expected') or ''}" if method == "assertEquals" else ""
    return described(f"{target['coverage']} / {target['covterm']} {verb}{expected}", "coverageUtil." + call, soft=True)


FRAMEWORK_CLASSES = {
    "MessagesUtil": "com.ankrpt.centertest.guidewire.runtime.MessagesUtil",
    "CenterTestAssertion": "com.ankrpt.centertest.assertion.CenterTestAssertion",
    "Assertions": "org.assertj.core.api.Assertions",
    "Utilities": "com.ankrpt.centertest.util.Utilities",
}
WIDGET_PACKAGE = "com.ankrpt.centertest.guidewire.widget."


def imports_for(text: str, widget) -> set:
    """Framework classes a Java fragment uses; page-object imports are left to the skill."""
    found = {fqn for name, fqn in FRAMEWORK_CLASSES.items() if re.search(rf"\b{name}\.", text)}
    if widget:
        found.add(WIDGET_PACKAGE + widget)
    return found


def translate(cssids_dir: str, app, action: dict) -> dict:
    """One recorded action or check as plan data with its Java fragment."""
    widget_id = action.get("widgetId")
    item = {"type": action.get("type"), "widgetId": widget_id,
            "page": find_getter.get_page_name(widget_id) if widget_id else None,
            "label": action.get("label") or action.get("text") or action.get("name") or ""}
    if action.get("kind") == "message":  # page-message checks have no widget
        item.update(resolution="resolved", java=message_check_java(action),
                    soft=bool(action.get("soft")), expected=action.get("expected"))
        return item
    coverage = coverage_widget(action)
    item.update(coverage_target(action, coverage, item["label"]) if coverage else resolve(cssids_dir, app, action))
    if action.get("type") == "check":
        java = coverage_check_java(action, item["coverage"]) if coverage else check_java(action)
        item.update(java=java, soft=bool(action.get("soft")), expected=action.get("expected"))
    else:
        item["java"] = coverage_action_java(action, item["coverage"]) if coverage else action_java(action)
    if coverage and item["java"] is None:
        item["warning"] = (f"CoverageUtil has no call for this {action.get('assert') or action.get('type')} "
                           f"on a coverage {coverage}; write it by hand on coverageUtil")
    elif coverage and item.get("soft"):
        item["getter"] = None  # a soft coverage check is a whole statement already
    if action.get("type") == "check":
        return item
    if item.get("column") == "_Checkbox" and item["java"]:
        item["java"] = ".click()"  # the project ticks a list row with get_CHECKBOX().click()
    if action.get("type") == "change" and action.get("value") != REDACTED:
        item["value"] = action.get("display") or action.get("value")
    if action.get("unique"):
        item["unique"] = {"expr": unique_java(action["unique"]), "recorded": action.get("value")}
    if action.get("key"):
        item["key"] = action["key"]
    if (action.get("row") or 0) > 1 and not action.get("rowKey") and ".getFirstRow()" in (item.get("getter") or ""):
        item["warning"] = f"row {action['row']} picked by position; getFirstRow() selects the first row"
    if action.get("source") == "request":
        clicks = action.get("calendarClicks", 1)
        item.update(source="request", postedDates=action.get("postedDates") or {})
        item["warning"] = (f"date picked from the calendar: value taken from the form the step posted "
                           f"(replaces {clicks} calendar click{'s' if clicks > 1 else ''}); check it")
        if item["postedDates"]:
            dates = ", ".join(f"{name} = {value}" for name, value in item["postedDates"].items())
            item["warning"] += f"; dates also posted: {dates}. Ask how the recorded date relates to them"
    if action.get("part") == "expand":
        item["java"] = None
        item["warning"] = ("expand click not translated: the next menu getter opens it (TabBar.get<Tab>() "
                           "expands its submenu); a tree node may need a hand-written expand")
    elif action.get("part") == "sort":
        item["java"] = None
        item["warning"] = "sort click not translated: sort the list by hand if the test depends on its order"
    return item


def needs_review(item: dict) -> bool:
    if item.get("page") == "Login":
        return False  # the login facade replaces whatever was typed on the login page
    if item.get("rule") == "coverage":
        return item["java"] is None or "warning" in item  # CoverageUtil always compiles; only doubtful labels
    return (item["resolution"] != "resolved" or item["java"] is None
            or "warning" in item or "candidates" in item)


def review_reason(item: dict) -> str:
    """Why an item is in the review list, for the confirmation table."""
    if item.get("warning") or item.get("reason"):
        return item.get("warning") or item["reason"]
    if item["java"] is None:
        return "not translated"
    if "candidates" in item:
        return f"{len(item['candidates'])} getters match; pick one"
    if item["resolution"] == "partial":
        return "no exact cssids key; partial match"
    if item["resolution"] == "rule":
        return f"no cssids key; built by the {item['rule']} rule, verify at compile"
    return "no cssids key or rule; raw Widget<Type>.get(id) form"


DATE_VALUE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
CALENDAR_ICON = "_dateIcon"


def is_date(value) -> bool:
    return isinstance(value, str) and bool(DATE_VALUE.fullmatch(value.strip()))


def with_picked_dates(actions: list, step: dict) -> list:
    """A date picked from the calendar fires no change event: the recorder logs only clicks on the
    field and its <id>_dateIcon. The value is in the form the step posted (requests[].fields), so the
    first such click becomes that change ("source": "request") and the field's other calendar clicks
    are folded into it. The other dates the step posted go with it, as context for the review."""
    posted = {}
    for request in step.get("requests") or []:
        for field in request.get("fields") or []:
            posted.setdefault(field.get("name"), field.get("value"))
    changed = {a.get("widgetId") for a in actions if a.get("type") == "change"}
    picked, result = {}, []
    for action in actions:
        widget_id = action.get("widgetId") or ""
        field = widget_id[:-len(CALENDAR_ICON)] if widget_id.endswith(CALENDAR_ICON) else widget_id
        value = posted.get(field) if field else None
        if (action.get("type") != "click" or field in changed or not isinstance(value, str)
                or not (action.get("kind") == "date" or is_date(value))):
            result.append(action)
        elif field in picked:
            picked[field]["calendarClicks"] += 1
        else:
            picked[field] = dict(action, type="change", widgetId=field, kind="date", value=value,
                                 source="request", calendarClicks=1,
                                 postedDates={n: v for n, v in posted.items() if n != field and is_date(v)})
            result.append(picked[field])
    return result


def build_plan(session: dict, cssids_dir: str) -> dict:
    meta = session.get("meta") or {}
    plan = {
        "recording": {key: session.get(key) for key in ("id", "name", "toolVersion", "startUrl")},
        "test": {"name": session.get("name"), "testId": meta.get("testId"),
                 "description": meta.get("description"), "prerequisites": meta.get("prerequisites"),
                 "expectedOutcome": meta.get("expectedOutcome"), "features": meta.get("featureIds") or [],
                 "defects": meta.get("defectIds") or [], "tags": meta.get("tags") or [],
                 "recordedBy": meta.get("recorderName")},
        # recordings before 1.1 kept notes on the session; 1.1 keeps them on the steps only
        "notes": [{"seq": None, "text": n.get("text", "")} for n in session.get("notes") or []],
        "apps": [], "steps": [], "review": [], "imports": [],
    }
    imports, uniques, previous_app = set(), {}, None
    for recorded_step in session.get("steps") or []:
        # checks marked "Remove check" in the recorder's review stay in session.json with removed: true
        recorded = with_picked_dates([a for a in recorded_step.get("actions") or [] if not a.get("removed")],
                                     recorded_step)
        notes = [n.get("text", "") for n in recorded_step.get("notes") or []]
        plan["notes"] += [{"seq": recorded_step.get("seq"), "text": text} for text in notes]
        if not recorded and not notes:
            continue
        app = APPS.get(recorded_step.get("app"))
        entry = {"seq": recorded_step.get("seq"), "app": app, "appName": recorded_step.get("app"),
                 "appSwitch": bool(recorded) and previous_app is not None and app is not None and app != previous_app,
                 "screen": recorded_step.get("screen"), "title": recorded_step.get("title"),
                 "waitTitle": wait_title(recorded_step.get("title")),
                 "login": any(a.get("value") == REDACTED for a in recorded),
                 "actions": [], "checks": [],
                 "notes": notes,
                 "messages": messages(recorded_step)}
        for action in recorded:
            translated = translate(cssids_dir, app, action)
            imports |= imports_for((translated.get("getter") or "") + (translated.get("java") or ""),
                                   translated.get("widget"))
            if translated.get("rule") == "coverage":
                imports.add(COVERAGE_UTIL)
            if action.get("type") == "check":
                if translated.get("expected") in uniques:
                    translated["uniqueFrom"] = uniques[translated["expected"]]
                entry["checks"].append(translated)
            else:
                if "unique" in translated:
                    uniques[str(action.get("value"))] = {"seq": entry["seq"], "label": translated["label"]}
                entry["actions"].append(translated)
            if needs_review(translated):
                plan["review"].append({
                    "seq": entry["seq"], "label": translated["label"], "widgetId": translated.get("widgetId"),
                    "resolution": translated["resolution"], "rule": translated.get("rule"),
                    "reason": review_reason(translated)})
        if recorded:  # a step with only notes opens no application
            if app and app not in plan["apps"]:
                plan["apps"].append(app)
            previous_app = app or previous_app
        plan["steps"].append(entry)
    plan["imports"] = sorted(imports)
    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CenterTest Recorder recording -> plan JSON")
    parser.add_argument("recording", help="the recording .zip, its folder, or its session.json")
    parser.add_argument("--cssids", required=True, help="resources dir holding cssids/<app>/ (or <app>.cssids)")
    parser.add_argument("--out", help="write the plan here instead of stdout")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.cssids):
        print(f"Error: cssids directory not found: {args.cssids}", file=sys.stderr)
        return 2
    try:
        session = load_session(args.recording)
    except (RecordingError, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    text = json.dumps(build_plan(session, args.cssids), indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
