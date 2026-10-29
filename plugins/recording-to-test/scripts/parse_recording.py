#!/usr/bin/env python3
"""
CenterTest Recorder recording -> plan JSON for the recording-to-test skill.

Usage:
  python3 parse_recording.py <recording.zip|folder|session.json> --cssids <resources dir>
                             [--project project.json] [--out plan.json]

Reads only session.json. <resources dir> holds cssids/<app>/<Page>.properties (or the legacy
<app>.cssids), e.g. the cssids/ that scan_project.py extracted from the project's *-generated jar.
Widget ids are resolved with find_getter.py, an unchanged copy of cssid-finder's script; ids it
cannot resolve go through the fallback rules in resolve_fallback().
"""

import argparse
import datetime
import html.parser
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


def file_reader(path: str):
    """read(rel) -> text of another file in the recording (e.g. a step's dom/0001.html), or None.
    Finds the folder or zip entry session.json came from, as load_session does."""
    if os.path.isfile(path) and os.path.basename(path) == "session.json":
        path = os.path.dirname(path)
    if os.path.isdir(path):
        base = path if os.path.isfile(os.path.join(path, "session.json")) else \
            os.path.join(path, os.path.basename(os.path.normpath(path)))

        def read_dir(rel):
            target = os.path.normpath(os.path.join(base, rel))
            if not target.startswith(os.path.normpath(base) + os.sep) or not os.path.isfile(target):
                return None
            with open(target, encoding="utf-8", errors="replace") as f:
                return f.read()
        return read_dir
    if os.path.isfile(path) and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist()
                           if n.split("/")[-1] == "session.json" and n.count("/") <= 1)
        prefix = names[0][:-len("session.json")] if names else ""

        def read_zip(rel):
            if ".." in rel.split("/"):
                return None
            with zipfile.ZipFile(path) as z:
                try:
                    return z.read(prefix + rel).decode("utf-8", errors="replace")
                except KeyError:
                    return None
        return read_zip
    return lambda rel: None


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
LAST_ROW_SELECT = ".getLastRow().select()"
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
    resolution, getters, _ = lookup_keyed(cssids_dir, app, widget_id)
    return resolution, getters


def lookup_keyed(cssids_dir: str, app: str, widget_id: str):
    """lookup() plus whether the id the getters resolve to at runtime differs from the recorded one."""
    layout, path = find_getter.detect_layout(cssids_dir, find_getter.APP_MAP[app][0])
    if layout is None:
        return None, [], False
    forms = find_getter.normalize_css_id(widget_id)
    for exact_only in ([True, False] if layout == "properties" else [True]):
        for form in forms:
            if layout == "properties":
                found = find_getter.search_properties(path, form, exact_only=exact_only)
            else:
                found = find_getter.search_legacy(path, form)
            if found:
                getters = list(dict.fromkeys(fill_iterators(g, widget_id, form) for g in found))
                differs = not exact_only or not key_matches(form, widget_id, "#" in found[0])
                return ("resolved" if exact_only else "partial"), getters, differs
    return None, [], False


def key_matches(form: str, widget_id: str, takes_index: bool) -> bool:
    """Whether the cssids key a getter came from is the recorded id. '[ROW]' stands for any row (the
    row API picks it); '#' for any index only when the getter takes that index. A bracketed or
    dropped '_tb' segment, or a '#' the getter doesn't fill, is a different id at runtime."""
    keys, ids = SEGMENT.split(form), SEGMENT.split(widget_id)
    return len(keys) == len(ids) and all(
        key == part or (part.isdigit() and (key == "[ROW]" or (key == "#" and takes_index)))
        for key, part in zip(keys, ids))


TOOLBAR_CALL = re.compile(r"\.get\[([^\[\]]*_tb)\](\w+)\(\)")


def unbracket(getter: str):
    """The generator writes a conditional toolbar segment into the method name
    ('.get[DriverLV_tb]AddDriver()'), which isn't Java; the page object's method is getAddDriver().
    Returns (getter, changed)."""
    fixed = TOOLBAR_CALL.sub(lambda m: f".get{m.group(2)}()", getter or "")
    return fixed, fixed != (getter or "")


def pinned(getter: str, widget_id: str) -> str:
    """The getter with the recorded id pinned by withCssId(), unless it picks a list row (the row
    API finds the row; pinning would fix it to the recorded one)."""
    if ".getFirstRow()" in getter or ".withCssId(" in getter:
        return getter
    return f"{getter}.withCssId({jstr(widget_id)})"


PINNED = ("the getter's cssids key is not the recorded id (a bracketed or different _tb segment, an iterator "
          "the getter doesn't fill, or a partial match), so it fails at runtime; pinned with "
          ".withCssId(recorded id). If its widget class has no withCssId, use Widget<Type>.get(recorded id)")


def with_row(getter: str, action: dict) -> str:
    """Select a list row by its contents, as the recording identified it, instead of the first row.
    A row the recording added (newRow) is the table's last row."""
    if action.get("newRow") and ROW_SELECT in getter:
        return getter.replace(ROW_SELECT, LAST_ROW_SELECT, 1)
    keys = action.get("rowKey") or []
    if not keys or ROW_SELECT not in getter:
        return getter
    page = action.get("page") or 1
    pages = f".forMaximumPages({page})" if page > 1 else ""
    filters = "".join(f'.with({jstr(k.get("header"))}, {jstr(k.get("text"))}, '
                      f'"{"DateCell" if is_date(k.get("text")) else "TextCell"}")' for k in keys)
    return getter.replace(ROW_SELECT, f".getFirstRow(){pages}{filters}.select()", 1)


def resolve(cssids_dir: str, app, action: dict) -> dict:
    """{'resolution', 'getter'?, 'candidates'?, 'rule'?, 'reason'?} for one recorded action."""
    widget_id = action.get("widgetId")
    if not widget_id:
        return {"resolution": "unresolved", "reason": "no widget id"}
    if app is None:
        return {"resolution": "unresolved", "reason": "unknown application"}
    resolution, getters, differs = lookup_keyed(cssids_dir, app, widget_id)
    menu = picker_item(action) or ((menu_item(cssids_dir, app, action) or wizard_toolbar(cssids_dir, app, action))
                                   if resolution != "resolved" else None)
    if getters and not menu:
        fixed = [unbracket(g) for g in getters]
        pin = differs or any(changed for _, changed in fixed)
        getters = list(dict.fromkeys(pinned(g, widget_id) if pin else g for g, _ in fixed))
        result = {"resolution": resolution, "getter": with_row(getters[0], action)}
        if len(getters) > 1:
            result["candidates"] = [with_row(g, action) for g in getters]
        if pin and ".withCssId(" in result["getter"]:
            result["warning"] = PINNED
        return result
    result = menu or without_suffix(cssids_dir, app, action) or resolve_fallback(cssids_dir, app, action)
    result["getter"] = with_row(result["getter"], action)
    return result


# parts of a live id the generated getter's id doesn't have: a cell, a button or link inside the
# widget, a calendar icon, a radio option
ID_SUFFIX = re.compile(r"_(Cell|button|link|dateIcon|\d+)$")


def without_suffix(cssids_dir: str, app: str, action: dict):
    """The getter of the widget a suffixed id is part of ('…-Number_button' -> getNumber(), never
    getNumber_button()), when cssids has an exact key for the id without the suffix."""
    widget_id = action.get("widgetId") or ""
    stripped = ID_SUFFIX.sub("", widget_id)
    if stripped == widget_id:
        return None
    resolution, getters, differs = lookup_keyed(cssids_dir, app, stripped)
    if resolution != "resolved":
        return None
    getter, changed = unbracket(getters[0])
    return {"resolution": "rule", "rule": "suffix", "stripped": widget_id[len(stripped):],
            "getter": pinned(getter, stripped) if differs or changed else getter}


# Recorder widget kind -> CenterTest widget class for the raw Widget<Type>.get(id, getContext()) form
RAW_WIDGET = {
    "text": "WidgetTextInput",
    "date": "WidgetDateInput",
    "select": "WidgetRangeInput",
    "checkbox": "WidgetCheckBoxInput",
    "LinkWidget": "WidgetLink",
    "TabWidget": "WidgetMenuItem",
    "MenuItemWidget": "WidgetMenuItem",
    "MenuIconWidget": "WidgetMenuItem",
    "PickerMenuItemWidget": "WidgetMenuItem",
    "MenuActionsWidget": "WidgetMenuItem",
    "ToolbarButtonWidget": "WidgetToolbarButton",
    "PickerToolbarButtonWidget": "WidgetToolbarButton",
    "WizardButtonWidget": "WidgetToolbarButton",
    "CheckedValuesToolbarButtonWidget": "WidgetCheckedValuesToolbarButton",
    "ButtonValueWidget": "WidgetButtonInput",
    "ImageButtonWidget": "WidgetButton",
    "button": "WidgetButton",
}
# an input recorded without a widget kind, by its type (a radio's value says boolean or range)
RAW_INPUT = {"checkbox": "WidgetCheckBoxInput", "radio": "WidgetBooleanRadioInput"}
BOOLEAN_VALUES = ("true", "false")
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


def menu_item(cssids_dir: str, app: str, action: dict):
    """A menu item cssids has no exact key for, picked by its label on the button that opens the
    menu: getAddDriver().withCssId("…").get("New Person") (WidgetMenuItem.get(label)). None when
    the button has no exact key either."""
    label = action.get("text") or action.get("label")
    parts, seps = split_id(action.get("widgetId") or "")
    if action.get("kind") != "MenuItemWidget" or not label or len(parts) < 3 or parts[0] == "TabBar":
        return None
    opener = join_id(parts[:-1], seps[:-1])
    resolution, getters, differs = lookup_keyed(cssids_dir, app, opener)
    if resolution != "resolved":
        return None
    getter, changed = unbracket(getters[0])
    return {"resolution": "rule", "rule": "menuItem",
            "getter": f"{pinned(getter, opener) if differs or changed else getter}.get({jstr(label)})"}


def picker_item(action: dict):
    """A pick from a picker's menu, clicked right after its menu icon (menuIcon, set by fold_openers):
    WidgetMenuItem.get(icon id).get(label) opens the menu itself, as projects write it."""
    icon, label = action.get("menuIcon"), action.get("text") or action.get("label")
    if not icon or not label:
        return None
    return {"resolution": "rule", "rule": "menuItem", "widget": "WidgetMenuItem",
            "getter": f"WidgetMenuItem.get({jstr(icon)}, getContext()).get({jstr(label)})"}


# labels of the wizard toolbar buttons WizardButtons has a getter for (it finds the button by label)
WIZARD_LABELS = ["Back", "Bind Options", "Cancel", "Cancel Now", "Cancel/Rewrite", "Close Options", "Decline",
                 "Delete", "Edit", "Edit Policy Transaction", "Finish", "Finish Quote", "Full App", "Issue Now",
                 "Issue Policy", "Next", "Non-Renew", "Not-Taken", "OK", "Print Quote", "Quote", "Rate",
                 "Refer to Agent for Issue", "Reinstate", "Release Lock", "Renew", "Save Draft",
                 "Schedule Cancellation", "Start Cancellation", "Submit", "Update", "Versions", "Withdraw",
                 "Withdraw Transaction"]
WIZARD_GETTERS = {label.lower(): "get" + "".join(cap(w) for w in re.split(r"\W+", label) if w) for label in WIZARD_LABELS}
WIZARD_STAGES = {"getQuote": "quote", "getIssuePolicy": "issue", "getIssueNow": "issue"}


def wizard_toolbar(cssids_dir: str, app: str, action: dict):
    """A button in a wizard screen's toolbar (…-JobWizardToolbarButtonSet-QuoteTypeToolbarButtonSet-Quote,
    …-JobWizardToolbarButtonSet-BindPolicyChange): <wizard page>.getWizardButtons().get<Label>(), picked
    by the label the recording shows. Quote and Issue carry wizardAction, which the base may handle."""
    parts, _ = split_id(action.get("widgetId") or "")
    label = (action.get("text") or action.get("label") or "").strip().lower()
    if not any(p.endswith("WizardToolbarButtonSet") for p in parts) or label not in WIZARD_GETTERS:
        return None
    page = page_instance(cssids_dir, app, parts[0])
    if not page:
        return None
    method = WIZARD_GETTERS[label]
    result = {"resolution": "rule", "rule": "wizardButton", "getter": f"{page}.getWizardButtons().{method}()"}
    if method in WIZARD_STAGES:
        result["wizardAction"] = WIZARD_STAGES[method]
    return result


def resolve_fallback(cssids_dir: str, app: str, action: dict) -> dict:
    """Ids cssids has no entry for, built in the project's own idioms. Always returns a result:
    the last rule writes the raw Widget<Type>.get(id, getContext()) form."""
    widget_id, kind = action["widgetId"], action.get("kind") or ""
    parts, seps = split_id(widget_id)

    # toolbar: cssids keeps '[X_tb]' bracketed (or drops it); the live id has it bare
    if any(p.endswith("_tb") for p in parts):
        bracketed = [f"[{p}]" if p.endswith("_tb") else p for p in parts]
        resolution, getters = lookup(cssids_dir, app, join_id(bracketed, seps))
        if resolution == "resolved":  # the key has the segment bracketed or dropped: not the live id
            return {"resolution": "rule", "rule": "toolbar", "getter": pinned(unbracket(getters[0])[0], widget_id),
                    "warning": PINNED}

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
            # the live id of a cell ends in _Cell, a button in it in _button; the generated row getter has
            # neither (Description_Cell -> getDescription, Number_button -> getNumber)
            name = ID_SUFFIX.sub("", column)
            getter = ROW_COLUMNS.get(column, f"get{cap(name)}")
            result = {"resolution": "rule", "rule": "rowColumn", "column": column,
                      "getter": f"{getters[0]}.{getter}()"}
            if column not in ROW_COLUMNS:
                result["warning"] = (f"no cssids key for column {name}: {getter}() is built from the id; "
                                     "check the row class has it before writing it")
            return result

    widget = RAW_WIDGET.get(kind) or RAW_INPUT.get(action.get("inputType")) or "WidgetLabel"
    if widget == "WidgetBooleanRadioInput" and str(action.get("value")).lower() not in BOOLEAN_VALUES:
        widget = "WidgetRangeRadioInput"
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
    if action.get("inputType") == "radio" and str(value).lower() in BOOLEAN_VALUES:
        return f'.set("{str(value).lower()}")'  # a Yes/No radio: set("true") whatever the options are labelled
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
    found |= {WIDGET_PACKAGE + name for name in re.findall(r"\b(Widget\w+)\.get\(", text)}
    if widget:
        found.add(WIDGET_PACKAGE + widget)
    return found


CELL_SUFFIX = re.compile(r"_(Cell|IC|button|link|Input)$")
# a debug tooltip Guidewire shows in development mode ("See PolicyChangeWizard.pcf StackopenForEditInit: …")
JUNK_LABEL = re.compile(r"\.pcf\b|Stack\w*Init|\bat [\w.$]+\(")


def item_label(action: dict) -> str:
    """The recorded label; for a list cell without one, its column. A form input's name is its
    widget id in Guidewire, never a label."""
    name = action.get("name")
    if name and name in (action.get("widgetId"), f"{action.get('widgetId')}_checkbox"):
        name = None
    label = next((l for l in (action.get("label"), action.get("text"), name) if l and not JUNK_LABEL.search(l)), "")
    if not label and (action.get("widgetId") or "").endswith("__crumb__"):
        label = "Return to previous page"
    if not label and action.get("column"):
        label = CELL_SUFFIX.sub("", action["column"]).lstrip("_")
    if not label and action.get("widgetId"):
        label = split_id(action["widgetId"])[0][-1].strip("_")
    return label


def warn(item: dict, text: str):
    """Add a reason for review; an item can have several."""
    item["warning"] = f"{item['warning']}; {text}" if item.get("warning") else text


def positional_index(widget_id) -> str:
    """The iterator or list index in a widget id ('…-0-UnassignedDriver' -> '0'), else ''."""
    parts, _ = split_id(widget_id or "")
    return next((p for p in parts[1:-1] if p.isdigit()), "")


# label -> data generator rule for a field whose fixed value collides on reruns
IDENTITY_FIELDS = [(re.compile(r"\bfirst\s*name\b", re.I), "firstName"),
                   (re.compile(r"\blast\s*name\b", re.I), "lastName"),
                   (re.compile(r"\b(company|organi[sz]ation)\s*name\b", re.I), "company"),
                   (re.compile(r"\be-?mail\b", re.I), "email"),
                   (re.compile(r"\bvin\b", re.I), "vin"),
                   (re.compile(r"\b(ssn|social security)\b", re.I), "ssn"),
                   (re.compile(r"\blicen[cs]e\s*(#|no\.?|number)?\s*$", re.I), "pattern")]


def identity_value(label: str, value) -> dict:
    """{expr, recorded} with a generator for a person's or vehicle's identity value, else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    for pattern, rule in IDENTITY_FIELDS:
        if pattern.search(label or ""):
            shape = re.sub(r"[A-Za-z]", "?", re.sub(r"\d", "#", value.strip()))
            expr = unique_java({"rule": rule, "pattern": shape, "upper": value.strip().isupper()})
            return {"expr": expr, "recorded": value} if expr else None
    return None


RADIO_OPTION = re.compile(r"_\d+$")


def radio_widget(action: dict) -> dict:
    """A radio button is recorded on its option's <input> ('…_IC_0'), which has its own id; the widget,
    and its getter, is the id without the option suffix."""
    widget_id = action.get("widgetId") or ""
    if action.get("inputType") != "radio" or not RADIO_OPTION.search(widget_id):
        return action
    return dict(action, widgetId=RADIO_OPTION.sub("", widget_id), radioOption=widget_id)


def row_radio(item: dict, action: dict) -> None:
    """A radio in a list row: the cell's set() doesn't take (WidgetBooleanRadioCell.set fails with WI-005,
    WidgetBooleanRadioInput.set leaves it unchanged), so the recorded option is clicked, and a Yes/No
    radio is then checked through getBoolean()."""
    option, widget_id, value = action["radioOption"], item["widgetId"], str(action.get("value")).lower()
    item.update(resolution="rule", rule="rowRadio", widget="WidgetButton", java=".click()",
                getter=f"WidgetButton.get({jstr(option)}, getContext())")
    item.pop("candidates", None)
    if value in BOOLEAN_VALUES:
        shown = action.get("display") or ("Yes" if value == "true" else "No")
        item["then"] = described(f"{item['label']} is {shown}",
                                 f"Assertions.assertThat(WidgetBooleanRadioInput.get({jstr(widget_id)}, getContext())"
                                 f".getBoolean()).isEqualTo({value})", soft=False)
    warn(item, "a radio in a list row: its cell's set() doesn't take, so the recorded option is clicked"
               + (" and then checked (then)" if "then" in item else ""))


def closest_date(item: dict, action: dict) -> None:
    """The transaction dates set or posted before this date, and the recorded date's relation to them."""
    if action.get("transactionDates"):
        item["transactionDates"] = action["transactionDates"]
    if action.get("dateRelations"):
        item["dateRelations"] = action["dateRelations"]
        warn(item, f"closest: {action['dateRelations'][0]['text']}")


def translate(cssids_dir: str, app, action: dict) -> dict:
    """One recorded action or check as plan data with its Java fragment."""
    action = radio_widget(action)
    widget_id = action.get("widgetId")
    item = {"type": action.get("type"), "widgetId": widget_id,
            "page": find_getter.get_page_name(widget_id) if widget_id else None,
            "label": item_label(action)}
    if action.get("radioOption"):
        item["radioOption"] = action["radioOption"]
    if action.get("menuOpener"):
        item["menuOpener"] = action["menuOpener"]
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
        if action.get("newRow"):
            item["newRow"] = True
        return item
    if action.get("radioOption") and positional_index(widget_id) and item["java"]:
        row_radio(item, action)
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
    if action.get("newRow"):
        item["newRow"] = action["newRow"]
    if BLOCKER_ID.search(widget_id or ""):
        item["blocker"] = True
        warn(item, "handles a UW issue / approval screen: use the project's blocker helper (plan.blockers) "
                   "instead of raw clicks")
    elif action.get("newRow"):
        pass  # the row this recording added: getLastRow(), no data question
    elif action.get("rowKey"):
        item["dependsOnData"] = True
        filters = ", ".join(f'{k.get("header")} = {k.get("text")}' for k in action["rowKey"])
        dates = [f'{k.get("header")} = {k.get("text")}' for k in action["rowKey"] if is_date(k.get("text"))]
        warn(item, f"row picked by its recorded values ({filters}): it only matches the recorded data; ask "
                   "whether to filter by the test's own data")
        if dates:
            warn(item, f"{', '.join(dates)} is a date literal: make it relative or drop that filter")
    elif (item.get("resolution") in ("raw", "partial") or item.get("rule") == "rowRadio") and positional_index(widget_id):
        item["dependsOnData"] = True
        warn(item, f"picks entry {positional_index(widget_id)} of a list or iterator by its position "
                   "(e.g. an existing or unassigned contact): it only works if the account or policy "
                   "already has that data; ask how the test gets it")
    if action.get("type") == "change" and action.get("source") != "request" and is_date(action.get("value")):
        item.update(typedDate=True, postedDates=action.get("postedDates") or {})
        warn(item, "date typed: write it relative to today or to the policy's effective/change date "
                   "(e.g. date of birth = effective date - 30 years) unless the test needs this day; ask")
        closest_date(item, action)
    identity = None if action.get("unique") else identity_value(item["label"], item.get("value"))
    if identity:
        item["uniqueSuggested"] = identity
        warn(item, f"identity field: a fixed value collides on reruns; suggested {identity['expr']} "
                   "(or the project's own generator, e.g. PersonNameUtil)")
    if action.get("source") == "request":
        clicks = action.get("calendarClicks", 1)
        item.update(source="request", postedDates=action.get("postedDates") or {})
        item["warning"] = (f"date picked from the calendar: value taken from the form the step posted "
                           f"(replaces {clicks} calendar click{'s' if clicks > 1 else ''}); check it")
        if item["postedDates"]:
            dates = ", ".join(f"{name} = {value}" for name, value in item["postedDates"].items())
            item["warning"] += f"; dates also posted: {dates}. Ask how the recorded date relates to them"
        closest_date(item, action)
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
        if action.get("type") == "change" and is_date(action.get("value")):
            result.append(dict(action, postedDates={n: v for n, v in posted.items() if n != field and is_date(v)}))
        elif (action.get("type") != "click" or field in changed or not isinstance(value, str)
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


class HeaderText(html.parser.HTMLParser):
    """The text of the elements with the given ids in a DOM snapshot."""

    def __init__(self, ids):
        super().__init__()
        self.ids, self.texts, self.open = set(ids), {}, []

    def handle_starttag(self, tag, attrs):
        if self.open:
            self.open[-1][1] += 1
        elif dict(attrs).get("id") in self.ids:
            self.open.append([dict(attrs)["id"], 1])
            self.texts[dict(attrs)["id"]] = ""

    def handle_endtag(self, tag):
        if self.open:
            self.open[-1][1] -= 1
            if self.open[-1][1] == 0:
                self.open.pop()

    def handle_data(self, data):
        if self.open:
            self.texts[self.open[-1][0]] += data


def with_headers(actions: list, dom) -> list:
    """A list cell recorded without a label gets its column header from the step's DOM snapshot:
    the header of '<list>-<row>-<column>' is '<list>-<column>Header' (Rated_IC -> RatedHeader)."""
    wanted = {}
    for action in actions:
        parts, seps = split_id(action.get("widgetId") or "")
        if action.get("label") or len(parts) < 3 or not parts[-2].isdigit():
            continue
        lv, column = join_id(parts[:-2], seps[:-2]), parts[-1]
        sep = seps[-1]
        wanted[action["widgetId"]] = [f"{lv}{sep}{name}Header" for name in
                                      dict.fromkeys([column, CELL_SUFFIX.sub("", column)])]
    if not wanted or not dom:
        return actions
    reader = HeaderText({i for ids in wanted.values() for i in ids})
    reader.feed(dom)
    headers = {widget_id: next((" ".join(reader.texts[i].split()) for i in ids
                                if " ".join(reader.texts.get(i, "").split())), "")
               for widget_id, ids in wanted.items()}
    return [dict(a, label=headers[a["widgetId"]]) if headers.get(a.get("widgetId")) else a for a in actions]


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class FieldValues(html.parser.HTMLParser):
    """What a DOM snapshot shows in each value widget (an element with class gw-ValueWidget): the text of
    a read-only value, an input's value, a select's selected option, a checked radio's label. And each
    input's label, from '<id>_Input' > .gw-label. The recorder copies live values into the attributes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.labels, self.stack, self.text, self.groups = {}, {}, [], [], {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes, element_id = (a.get("class") or "").split(), a.get("id")
        ctx = dict(self.stack[-1]) if self.stack else {"value": None, "input": None, "label": None, "skip": False,
                                                       "notext": False, "option": None}
        if element_id and "gw-ValueWidget" in classes and not any("HeaderCell" in c for c in classes):
            ctx.update(value=element_id, skip=False, notext=False)
            self.parts.setdefault(element_id, [])
        if element_id and element_id.endswith("CovPatternInputGroup") and a.get("aria-label"):
            self.groups[element_id] = a["aria-label"]  # the coverage's title
        if element_id and element_id.endswith("_Input"):
            ctx["input"] = element_id[:-len("_Input")]
        if "gw-label" in classes and ctx["input"] and not ctx["value"]:
            ctx["label"] = ctx["input"]
            self.labels.setdefault(ctx["input"], "")
        if "gw-vw--children" in classes:
            ctx["skip"] = True
        if any(c.endswith("--input-group") for c in classes):
            ctx["notext"] = True  # a radio group's option labels: only the checked one counts
        if tag == "option":
            ctx["option"] = "selected" in a
        value_id = ctx["value"] if not ctx["skip"] else None
        if value_id and tag == "input":
            kind = (a.get("type") or "text").lower()
            if kind == "radio" and "checked" in a:
                self.parts[value_id].append(a.get("aria-label") or a.get("value") or "")
            elif kind == "checkbox":
                self.parts[value_id].append("true" if "checked" in a else "false")
            elif kind not in ("radio", "hidden", "button", "submit"):
                self.parts[value_id].append(a.get("value") or "")
        elif value_id and tag == "br":
            self.parts[value_id].append(" ")
        if tag not in VOID_TAGS:
            self.stack.append(ctx)

    def handle_endtag(self, tag):
        if tag not in VOID_TAGS and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)
        ctx = self.stack[-1] if self.stack else None
        if not ctx:
            return
        if ctx["label"]:
            self.labels[ctx["label"]] += data
        if ctx["value"] and not ctx["skip"] and not ctx["notext"] and ctx["option"] is not False:
            self.parts[ctx["value"]].append(data)

    def values(self) -> dict:
        return {k: " ".join("".join(v).split()) for k, v in self.parts.items()}


def posted_fields(step: dict) -> dict:
    """The form fields the step posted, the last post's value for each (the form when the step ended)."""
    fields = {}
    for request in step.get("requests") or []:
        for field in request.get("fields") or []:
            if field.get("name"):
                fields[field["name"]] = field.get("value")
    return fields


def snapshot(step: dict, read_file) -> dict:
    """What a step shows: its DOM snapshot's value widgets over the fields it posted (a posted select value
    is a code; the snapshot has the text shown), the labels, the coverage titles (groups) and the page text."""
    found = {"values": {k: str(v) for k, v in posted_fields(step).items() if v not in (None, "") and k != "QuickJump"},
             "labels": {}, "groups": {}, "text": None}
    dom = step.get("dom")
    html_text = read_file(dom) if dom and read_file else None
    if html_text:
        reader = FieldValues()
        reader.feed(html_text)
        found["values"].update({k: v for k, v in reader.values().items() if v})
        found["labels"] = {k: " ".join(v.split()) for k, v in reader.labels.items() if v.strip()}
        found["groups"] = reader.groups
        found["text"] = " ".join("".join(reader.text).split())
    return found


def coverage_of(widget_id: str, groups: dict):
    """The title of the coverage a widget is in ('…-CovPatternInputGroup-…'), or None."""
    return next((title for group, title in groups.items()
                 if widget_id.startswith(group) and widget_id[len(group):len(group) + 1] in ("-", ":")), None)


ASKS_CHECK = re.compile(r"\b(verify|verified|confirm|ensure|check|make sure|validate|assert)\b", re.I)
CONDITIONAL = re.compile(r"\b(if|unless|in case|only when|whenever)\b", re.I)
NOTE_STOPWORDS = {
    "verify", "verified", "confirm", "ensure", "check", "make", "sure", "validate", "assert", "that", "this",
    "these", "those", "there", "their", "they", "them", "then", "than", "with", "without", "from", "into", "onto",
    "after", "before", "have", "been", "were", "will", "would", "should", "could", "must", "also", "both",
    "each", "every", "when", "where", "which", "what", "while", "only", "just", "still", "same", "other",
    "changed", "change", "changes", "updated", "update", "updates", "correct", "correctly", "properly", "shown",
    "show", "shows", "displayed", "display", "screen", "page", "field", "fields", "value", "values", "the",
    "and", "are", "for", "new", "old", "is", "was", "has", "not", "all", "any", "set", "now", "here", "again",
    "click", "clicked", "select", "selected", "enter", "entered", "test", "policy", "unless", "case"}
# words too common in ids to match a field on their own
GENERIC_STEMS = {"code", "name", "number", "type", "date", "status", "info", "detail", "description"}
NOTE_FIELD_LIMIT = 12


def stem(word: str) -> str:
    """A crude stem, so a note's word matches the id: territories / territory -> territor, codes -> code."""
    word = word.lower()
    for suffix in ("ies", "es", "s", "ed", "ing"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[:-len(suffix)]
            break
    return word[:-1] if len(word) > 4 and word.endswith("y") else word


def note_stems(text: str) -> list:
    words = re.findall(r"[A-Za-z]{3,}", text or "")
    return list(dict.fromkeys(stem(w) for w in words if w.lower() not in NOTE_STOPWORDS))


def field_words(widget_id: str, label: str) -> str:
    """What a note's words are matched against: the id's last segment, a list's name when the id is a
    list cell, and the label the screen shows."""
    parts, _ = split_id(widget_id)
    words = [parts[-1]] + [p for p, after in zip(parts, parts[1:]) if after.isdigit()] + [label or ""]
    return " ".join(words).lower()


AMOUNT_FIELD = re.compile(r"Premium|TotalCost|Cost$|Surcharge|Discount|Modifier", re.I)
SCREEN_AMOUNTS = 10


def note_field_java(widget_id: str, label: str, coverage, value: str) -> str:
    """The check on a field's last value: on coverageUtil for a coverage (a whole statement), else the call on
    the field's getter."""
    if not coverage:
        return f".assertEquals({jstr(value)})"
    if widget_id.endswith("_checkbox"):
        return f"Assertions.assertThat(coverageUtil.isSelected({jstr(coverage)})).isEqualTo({value == 'true'});"
    return f"coverageUtil.assertEquals({jstr(coverage)}, {jstr(label)}, {jstr(value)});"


def note_checks(plan: dict, snapshots: list) -> list:
    """For each note that asks for a check (verify, confirm, ensure…), the fields whose label or id has the
    note's words, with the values the recording shows for them, in order (before → after), the last step
    that showed them (lastSeq) and a check on the last value (on coverageUtil for a coverage term, with its
    coverage title). Changed fields matched by their label come first, id-only matches last. The note's
    screen comes with it: which words it shows (a "no surcharge" note on a screen without the word
    surcharge is a question) and its premium / cost / surcharge amounts."""
    found = []
    labels, groups = {}, {}
    for shot in snapshots:
        labels.update(shot["labels"])
        groups.update(shot["groups"])
    seqs = [entry["seq"] for entry in plan["steps"]]
    for note in plan["notes"]:
        if not note.get("asksCheck"):
            continue
        stems = note_stems(note["text"])
        specific = [s for s in stems if s not in GENERIC_STEMS]
        if not specific:
            continue
        observed, last_seen = {}, {}
        for entry, shot in zip(plan["steps"], snapshots):
            for widget_id, value in shot["values"].items():
                observed.setdefault(widget_id, [])
                last_seen[widget_id] = entry["seq"]
                if not observed[widget_id] or observed[widget_id][-1]["value"] != value:
                    observed[widget_id].append({"seq": entry["seq"], "value": value})
        fields = []
        for widget_id, seen in observed.items():
            label = labels.get(widget_id) or item_label({"widgetId": widget_id})
            coverage = coverage_of(widget_id, groups)
            if coverage and widget_id.endswith("_checkbox"):
                label = coverage
            by_label = [s for s in stems if s in f"{coverage or ''} {labels.get(widget_id, '')}".lower()]
            matched = list(dict.fromkeys(by_label + [s for s in stems if s in field_words(widget_id, "")]))
            if not any(s in specific for s in matched):
                continue
            field = {"widgetId": widget_id, "label": label, "matched": matched,
                     "byLabel": any(s in specific for s in by_label), "values": seen, "changed": len(seen) > 1,
                     "lastSeq": last_seen[widget_id],
                     "java": note_field_java(widget_id, label, coverage, seen[-1]["value"])}
            if coverage:
                field["coverage"] = {"coverage": coverage, "covterm": None if widget_id.endswith("_checkbox") else label}
            fields.append(field)
        at_note = note["seq"] or 0
        fields.sort(key=lambda f: (not (f["changed"] and f["byLabel"]), not f["byLabel"], not f["changed"],
                                   -len(f["matched"]), f["lastSeq"] < at_note, f["widgetId"]))
        result = {"seq": note["seq"], "text": note["text"], "words": specific,
                  "fields": fields[:NOTE_FIELD_LIMIT], "more": max(0, len(fields) - NOTE_FIELD_LIMIT)}
        shot = snapshots[seqs.index(note["seq"])] if note["seq"] in seqs else None
        if shot and shot["text"] is not None:
            text = shot["text"].lower()
            amounts = [{"widgetId": w, "label": labels.get(w) or item_label({"widgetId": w}), "value": v}
                       for w, v in shot["values"].items() if AMOUNT_FIELD.search(split_id(w)[0][-1])]
            result["screen"] = {"seq": note["seq"], "shows": {s: s in text for s in specific},
                                "amounts": amounts[:SCREEN_AMOUNTS]}
        found.append(result)
    return found


WEAK_CHECKS = {"isVisible", "isNotEmpty"}


def stronger_check(item: dict, check: dict, values: dict, entered: list) -> None:
    """A visibility / not-empty check on a field that shows a value: propose a check on the value, contains
    the longest value entered earlier that it shows (e.g. the address just added), else equals it."""
    shown = values.get(item.get("widgetId") or "")
    if check.get("assert") not in WEAK_CHECKS or check.get("flag") is False or not shown:
        return
    hits = [v for v in entered if len(v) >= 4 and v.lower() in shown.lower()]
    soft = "Soft" if check.get("soft") else ""
    if hits:
        java = f".assertContains{soft}({jstr(max(hits, key=len))})"
    else:
        java = f".assertEquals{soft}({jstr(shown)})"
    item["valueSuggested"] = {"java": java, "shown": shown}
    warn(item, f"only checks that the field is there, which always passes; the screen shows {shown!r}: "
               f"suggested {java}")


NEXT = re.compile(r"^next\b", re.I)


def navigation(steps: list) -> list:
    """Runs of steps whose only action is the wizard's Next: screens passed without changing anything.
    The project may move between wizard screens another way (e.g. the left-hand menu)."""
    runs, run, before = [], [], None
    for entry in steps + [None]:
        if entry is not None and not entry["actions"]:
            continue  # a note or check-only step changes nothing
        nexts = entry is not None and len(entry["actions"]) == 1 and entry["actions"][0]["type"] == "click" \
            and bool(NEXT.match(entry["actions"][0]["label"].strip()))
        if nexts:
            run.append(entry)
            continue
        if run:
            for step_entry in run:
                step_entry["actions"][0]["navigationOnly"] = True
            runs.append({"seqs": [e["seq"] for e in run], "clicks": len(run),
                         "from": before and before["waitTitle"], "to": run[-1]["waitTitle"]})
            run = []
        before = entry
    return runs


def base_methods(item: dict, bases: list) -> None:
    """The transaction base's methods for a Quote / Issue click (wizardAction), found by the wizard page
    the base holds (transactionBases.wizardFields) and the button its methods click (wizardActions)."""
    action, page = item.get("wizardAction"), (item.get("page") or "") + "Page"
    found = [f"{base['class']}.{method}" for base in bases
             if any(field.split()[0] == page for field in base.get("wizardFields") or [])
             for method in (base.get("wizardActions") or {}).get(action, [])]
    if found:
        item["baseMethods"] = found
        warn(item, f"the transaction base handles {action} in {', '.join(found)}: call it instead of the click")


def opens_menu(action: dict, following) -> bool:
    """A click that opens the menu whose item the next action clicks."""
    opener = action.get("widgetId") or ""
    return bool(following and opener and action.get("type") == "click" and following.get("type") == "click"
                and following.get("kind") == "MenuItemWidget" and action.get("part") != "expand"
                and re.match(re.escape(opener) + r"[-:]", following.get("widgetId") or ""))


def fold_menu_openers(items: list) -> list:
    """An item with a getter opens its menu itself (WidgetMenuItem.get(label) clicks the button), so
    the click that opened it is dropped. A raw item only moves to its element: the opener stays,
    written in the raw form instead of a list of partial matches."""
    result = []
    for item, following in zip(items, items[1:] + [None]):
        opens = item.pop("opensMenu", False)
        kind = item.pop("kind", None)
        if not opens or not following:
            result.append(item)
        elif following["resolution"] in ("resolved", "rule"):
            following["menuOpener"] = item["label"]
        else:
            if item["resolution"] == "partial":
                widget = RAW_WIDGET.get(kind, "WidgetMenuItem")
                item.pop("candidates", None)
                item.update(resolution="raw", rule="raw", widget=widget,
                            getter=f"{widget}.get({jstr(item['widgetId'])}, getContext())")
            result.append(item)
    return result


PICKER_ITEMS = ("PickerMenuItemWidget", "MenuItemWidget")


def fold_openers(steps_actions: list) -> None:
    """Clicks that only open something for a later action, across step boundaries (a click can end a
    step): a calendar icon whose field is set (the change replaces it; a picked date counts it in
    calendarClicks), and a picker's menu icon right before its item (the item gets menuIcon and
    menuOpener; WidgetMenuItem.get(icon).get(label) opens the menu itself). Edits the lists in place."""
    flat = [(n, k, a) for n, actions in enumerate(steps_actions) for k, a in enumerate(actions)]
    drop = set()
    for i, (n, _, action) in enumerate(flat):
        widget_id = action.get("widgetId") or ""
        if action.get("type") != "click":
            continue
        if widget_id.endswith(CALENDAR_ICON):
            field = widget_id[:-len(CALENDAR_ICON)]
            sets = [a for _, _, a in flat[i + 1:] if a.get("type") == "change" and a.get("widgetId") == field]
            sets = sets or [a for m, _, a in flat if m == n and a.get("type") == "change" and a.get("widgetId") == field]
            if sets:
                drop.add((n, flat[i][1]))
                if sets[0].get("source") == "request":  # a dict with_picked_dates made, not the session's
                    sets[0]["calendarClicks"] = sets[0].get("calendarClicks", 1) + 1
        elif action.get("kind") == "MenuIconWidget" and i + 1 < len(flat):
            m, k, item = flat[i + 1]
            if item.get("type") == "click" and item.get("kind") in PICKER_ITEMS and (item.get("text") or item.get("label")):
                steps_actions[m][k] = dict(item, menuIcon=widget_id, menuOpener=item_label(action))
                drop.add((n, flat[i][1]))
    for n, actions in enumerate(steps_actions):
        actions[:] = [a for k, a in enumerate(actions) if (n, k) not in drop]


ADD_CLICK = re.compile(r"^add\b", re.I)


def row_table(widget_id: str):
    """(id prefix, table segment, row index position) of a list-row id ('…-ConvictionsDV-0-Col'), or None."""
    parts, _ = split_id(widget_id or "")
    position = next((i for i in range(2, len(parts) - 1) if parts[i].isdigit()), None)
    return (parts[:position - 1], parts[position - 1], position) if position else None


def adds_to(click: dict, table, row_id: str) -> bool:
    """Whether a click is the Add of that table: an Add (by label or id) whose id starts with the
    table's container and whose next segment is the table or its toolbar (ConvictionsDV, ConvictionsLV_tb).
    An Add menu the row is inside ('…-AddDriver-AddExistingContact-0-UnassignedDriver') lists existing
    contacts: picking one of its entries is not a new row."""
    prefix, segment, _ = table
    click_id = click.get("widgetId") or ""
    if re.match(re.escape(click_id) + r"[-:]", row_id):
        return False
    parts, _ = split_id(click_id)
    label = click.get("text") or click.get("label") or ""
    stem = re.sub(r"_?(LV|DV)$", "", segment)
    return bool(click.get("type") == "click" and (ADD_CLICK.match(label.strip()) or parts[-1].startswith("Add"))
                and len(parts) > len(prefix) and parts[:len(prefix)] == prefix
                and parts[len(prefix)].startswith(stem))


def mark_new_rows(steps_actions: list) -> None:
    """A row item of a table the recording clicked Add on earlier is that new row (newRow), not the
    account's data: getLastRow() selects it. Edits the lists in place."""
    adds = []
    for actions in steps_actions:
        for k, action in enumerate(actions):
            table = row_table(action.get("widgetId"))
            if table and any(adds_to(add, table, action["widgetId"]) for add in adds):
                actions[k] = dict(action, newRow=True)
            if action.get("type") == "click":
                adds.append(action)


TRANSACTION_DATE = re.compile(r"Effective|EffDate|PeriodStart|ChangeDate|Cancel\w*Date|Reinstat\w*Date|RenewalDate",
                              re.I)


def parse_date(value):
    """A recorded MM/DD/YYYY (or MM/DD/YY) date, else None."""
    if not is_date(value):
        return None
    month, day, year = (int(p) for p in value.strip().split("/"))
    try:
        return datetime.date(year + 2000 if year < 100 else year, month, day)
    except ValueError:
        return None


def date_name(field: str) -> str:
    """'…-StartPolicyChangeDV-EffectiveDate' -> 'EffectiveDate', 'PolicyPeriodEffDateID_Arg' -> 'PolicyPeriodEffDateID'."""
    return re.sub(r"_Arg$", "", split_id(field)[0][-1])


def relation(day, anchor, name: str) -> str:
    """'EffectiveDate + 1 day', 'EffectiveDate - 35 years' (same day and month), else days (≈ years)."""
    days = (day - anchor).days
    if days == 0:
        return f"= {name}"
    sign = "+" if days > 0 else "-"
    if (day.month, day.day) == (anchor.month, anchor.day):
        years = abs(day.year - anchor.year)
        return f"{name} {sign} {years} year{'s' if years != 1 else ''}"
    about = f" (≈ {round(abs(days) / 365.25)} years)" if abs(days) >= 365 else ""
    return f"{name} {sign} {abs(days)} day{'s' if abs(days) != 1 else ''}{about}"


def date_relations(value: str, anchors: list) -> list:
    """The recorded date against each anchor (transaction dates first, then the other posted dates, then
    the day it was recorded), closest first within each kind."""
    day = parse_date(value)
    found = []
    for kind in ("transaction", "posted", "recorded on"):
        same = []
        for name, anchor_value, seq in [(n, v, s) for k, n, v, s in anchors if k == kind]:
            anchor = parse_date(anchor_value)
            if day and anchor:
                same.append({"anchor": name, "value": anchor_value, "seq": seq, "days": (day - anchor).days,
                             "text": relation(day, anchor, "today" if kind == "recorded on" else name)})
        found += sorted(same, key=lambda r: abs(r["days"]))
    return found


def with_transaction_dates(recorded_steps: list, steps_actions: list, recorded_on) -> list:
    """The transaction's own dates (a policy change's effective date, the period's start), whether the
    analyst set them or kept the default the step posted. Every later date action gets them
    (transactionDates) and its relations to them, its posted dates and the recording day
    (dateRelations): a conviction must fall after the change date, not just before today. Edits the
    lists in place; returns the dates as [{field, name, value, seq, source}]."""
    known = {}
    for step, actions in zip(recorded_steps, steps_actions):
        seq = step.get("seq")
        for k, action in enumerate(actions):
            if action.get("type") != "change" or not is_date(action.get("value")):
                continue
            field = action.get("widgetId")
            dates = [d for f, d in known.items() if f != field]
            anchors = ([("transaction", d["name"], d["value"], d["seq"]) for d in dates]
                       + [("posted", date_name(n), v, seq) for n, v in (action.get("postedDates") or {}).items()
                          if n not in known]
                       + ([("recorded on", "today", recorded_on.strftime("%m/%d/%Y"), None)] if recorded_on else []))
            actions[k] = dict(action, transactionDates={d["name"]: d["value"] for d in dates},
                              dateRelations=date_relations(action["value"], anchors))
        for action in actions:
            field = action.get("widgetId") or ""
            if action.get("type") == "change" and is_date(action.get("value")) and TRANSACTION_DATE.search(field):
                known[field] = {"field": field, "name": date_name(field), "value": action["value"], "seq": seq,
                                "source": "set"}
        for field, value in posted_fields(step).items():
            if is_date(value) and TRANSACTION_DATE.search(field) and field not in known:
                known[field] = {"field": field, "name": date_name(field), "value": value, "seq": seq,
                                "source": "posted"}
    return list(known.values())


def recording_day(session: dict):
    """The day the recording was made (its startedAt), for relations to "today"."""
    try:
        return datetime.date.fromisoformat((session.get("startedAt") or "")[:10])
    except ValueError:
        return None


BLOCKER_ID =re.compile(r"UWBlockProgress|RiskEvaluation|UWIssue|RiskApproval|SpecialApprove")
BLOCKER_TEXT = re.compile(r"issues? that block|risk approval|uw issue|underwriter|approval required|"
                          r"facility|rsp pool", re.I)


def step_pages(entry: dict) -> list:
    """The PCF pages a step's screen and items are on, as screenHelpers.pages keys them."""
    pages = [entry.get("screen")] + [i.get("page") for i in entry["actions"] + entry["checks"]]
    return sorted({p for p in pages if p and p != "_misc"})


HELPER_LIMIT = 6


def id_tail(widget_id: str):
    """The two segments that name a list's container ('…-PAClaimsInfo-ClaimsInfo_ICLV-0-Col' ->
    'PAClaimsInfo-ClaimsInfo_ICLV'), the same in every wizard that shows the list; None for other ids."""
    table = row_table(widget_id)
    if not table or len(table[0]) < 1:
        return None
    parts, seps = split_id(widget_id)
    position = table[2]
    return join_id(parts[position - 2:position], seps[position - 2:position - 1])


def helpers_for(entry: dict, screen_helpers: dict, plan_bases=()) -> list:
    """The project's methods that use this step's lists (an id literal with the same container, from any
    wizard), wait for its title or open one of its pages. Methods of the transaction's base come first;
    the rest is cut at HELPER_LIMIT (helpersMore counts them)."""
    found = {}
    for item in entry["actions"] + entry["checks"]:
        tail = id_tail(item.get("widgetId"))
        for literal, refs in (screen_helpers.get("ids") or {}).items() if tail else []:
            if tail in literal:
                page = split_id(literal)[0][0]
                other = f" (written for {page}: reuse or generalise?)" if page not in entry["pages"] else ""
                for ref in refs:
                    found.setdefault(ref, f"id …{tail}{other}")
    title = entry.get("title") or ""
    for key, refs in (screen_helpers.get("titles") or {}).items():
        stem = key.rstrip(": ").strip()
        if len(stem) > 3 and (title.startswith(stem) or (entry["waitTitle"] and stem.startswith(entry["waitTitle"]))):
            for ref in refs:
                found.setdefault(ref, f"title {key!r}")
    for page in entry["pages"]:
        for ref in (screen_helpers.get("pages") or {}).get(page, []):
            found.setdefault(ref, f"page {page}")
    ranked = sorted(found.items(), key=lambda kv: (kv[0].split(".")[0] not in plan_bases,
                                                   not kv[1].startswith("id ")))
    if len(ranked) > HELPER_LIMIT:
        entry["helpersMore"] = len(ranked) - HELPER_LIMIT
    return [{"method": ref, "matched": why} for ref, why in ranked[:HELPER_LIMIT]]


def blockers(steps: list) -> list:
    """Steps on a UW-issue or approval screen (by title, page message or widget), with the helpers
    that handle that screen. UW rules depend on data and environment, so a block seen at Issue can
    also come at Quote."""
    found = []
    for entry in steps:
        texts = [m["text"] for m in entry["messages"] if BLOCKER_TEXT.search(m["text"])]
        items = [i for i in entry["actions"] if i.get("blocker")]
        if not (texts or items or BLOCKER_TEXT.search(entry.get("title") or "")
                or any(BLOCKER_ID.search(p) for p in entry["pages"])):
            continue
        found.append({"seq": entry["seq"], "title": entry.get("title"), "pages": entry["pages"], "messages": texts,
                      "items": [i["label"] for i in items], "helpers": entry.get("helpers")})
    return found


def refused(steps: list) -> list:
    """A Next / Quote / Issue the application refused: the step it ended stayed on the same screen,
    and the same button was clicked again later (usually after a field was fixed)."""
    flat = [(entry, action) for entry in steps for action in entry["actions"]]
    found = []
    for index, entry in enumerate(steps[1:], 1):
        if not entry["actions"]:
            continue
        click = entry["actions"][-1]
        if (click["type"] != "click" or not RESUME.match(click["label"].strip())
                or entry["waitTitle"] != steps[index - 1]["waitTitle"]):
            continue
        start = next(n for n, (_, a) in enumerate(flat) if a is click) + 1
        again = next((n for n in range(start, len(flat)) if flat[n][1].get("widgetId") == click.get("widgetId")
                      and flat[n][1]["type"] == "click"), None)
        if again is None:
            continue
        between = flat[start:again]
        found.append({"kind": "refused", "seq": entry["seq"], "action": click["label"], "title": entry["waitTitle"],
                      "errors": [m["text"] for m in entry["messages"] if m["level"] in ("error", "warning")],
                      "fixes": [{"seq": e["seq"], "label": a["label"], "value": a.get("value")}
                                for e, a in between if a["type"] == "change"],
                      "between": [{"seq": e["seq"], "label": a["label"]} for e, a in between if a["type"] != "change"],
                      "retrySeq": flat[again][0]["seq"]})
    return found


EDIT_AGAIN = re.compile(r"^(Clear|Edit Policy Transaction|Edit Transaction|Edit Policy)$", re.I)
RESUME = re.compile(r"^(Quote|Issue Policy|Issue|Bind Options|Bind Only|Submit|Next)$", re.I)


def retries(steps: list) -> list:
    """Values the analyst corrected later, and validation-fix loops: errors shown, then Clear / Edit
    Policy Transaction, fields fixed, and the transaction quoted or issued again."""
    flat = [(index, entry, action) for index, entry in enumerate(steps) for action in entry["actions"]]
    first_quote = next((entry["seq"] for _, entry, a in flat
                        if a["type"] == "click" and a["label"].strip().lower() == "quote"), None)
    found, last_set, loop_end = [], {}, -1
    for position, (index, entry, action) in enumerate(flat):
        widget_id, value = action.get("widgetId"), action.get("value")
        if action["type"] == "change" and widget_id and value is not None:
            before = last_set.get(widget_id)
            if before and before[0] != entry["seq"] and before[1] != value:
                action["corrects"] = {"seq": before[0], "value": before[1]}
                found.append({"kind": "corrected", "label": action["label"], "widgetId": widget_id,
                              "seq": before[0], "fixedSeq": entry["seq"], "from": before[1], "to": value})
            last_set[widget_id] = (entry["seq"], value)
        if action["type"] != "click" or not (EDIT_AGAIN.match(action["label"].strip())
                                             or "WebMessageWorksheet" in (widget_id or "")):
            continue
        loop = found[-1] if found and found[-1]["kind"] == "validationLoop" else None
        if loop and position < loop_end and not any(f["position"] < position for f in loop["fixes"]):
            loop["edit"] += f" → {action['label']}"  # Clear, then Edit Policy Transaction: one loop
            continue
        shown = next((s for s in reversed(steps[max(0, index - 3):index + 1])
                      if any(m["level"] in ("error", "warning") for m in s["messages"])), None)
        loop = {"kind": "validationLoop", "editSeq": entry["seq"], "edit": action["label"],
                "errorSeq": shown and shown["seq"],
                "errors": [m["text"] for m in shown["messages"] if m["level"] in ("error", "warning")] if shown else [],
                "fixes": [], "resumeSeq": None, "firstQuoteSeq": first_quote}
        loop_end = len(flat)
        for later, (_, fix_entry, fix) in enumerate(flat[position + 1:], position + 1):
            if fix["type"] == "click" and RESUME.match(fix["label"].strip()):
                loop["resumeSeq"], loop_end = fix_entry["seq"], later
                break
            if fix["type"] == "change":
                loop["fixes"].append({"seq": fix_entry["seq"], "label": fix["label"], "value": fix.get("value"),
                                      "position": later})
        found.append(loop)
    for loop in found:
        for fix in loop.get("fixes", []):
            fix.pop("position")
    return found


def build_plan(session: dict, cssids_dir: str, read_file=None, project=None) -> dict:
    meta = session.get("meta") or {}
    plan = {
        "recording": {key: session.get(key) for key in ("id", "name", "toolVersion", "startUrl")},
        "test": {"name": session.get("name"), "testId": meta.get("testId"),
                 "description": meta.get("description"), "prerequisites": meta.get("prerequisites"),
                 "expectedOutcome": meta.get("expectedOutcome"), "features": meta.get("featureIds") or [],
                 "defects": meta.get("defectIds") or [], "tags": meta.get("tags") or [],
                 "recordedBy": meta.get("recorderName")},
        # recordings before 1.1 kept notes on the session; 1.1 keeps them on the steps only
        "notes": [note_entry(None, n.get("text", "")) for n in session.get("notes") or []],
        "apps": [], "steps": [], "review": [], "retries": [], "blockers": [], "navigation": [], "noteChecks": [],
        "transactionDates": [], "imports": [],
    }
    recorded_steps = session.get("steps") or []
    # checks marked "Remove check" in the recorder's review stay in session.json with removed: true
    steps_actions = [with_picked_dates([a for a in s.get("actions") or [] if not a.get("removed")], s)
                     for s in recorded_steps]
    fold_openers(steps_actions)
    mark_new_rows(steps_actions)
    plan["transactionDates"] = with_transaction_dates(recorded_steps, steps_actions, recording_day(session))
    imports, uniques, previous_app, reviewed, kept_steps = set(), {}, None, [], []
    for recorded_step, recorded in zip(recorded_steps, steps_actions):
        dom = recorded_step.get("dom")
        recorded = with_headers(recorded, read_file(dom) if dom and read_file else None)
        notes = [n.get("text", "") for n in recorded_step.get("notes") or []]
        plan["notes"] += [note_entry(recorded_step.get("seq"), text) for text in notes]
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
                 "messages": messages(recorded_step),
                 "dom": recorded_step.get("dom")}
        translated_items = []
        for action, following in zip(recorded, recorded[1:] + [None]):
            translated = translate(cssids_dir, app, action)
            if opens_menu(action, following):
                translated.update(opensMenu=True, kind=action.get("kind"))
            translated_items.append(translated)
        kept = {id(item) for item in fold_menu_openers(translated_items)}
        for action, translated in zip(recorded, translated_items):
            if id(translated) not in kept:
                continue
            if action.get("type") == "check":
                translated["recordedCheck"] = action
                if translated.get("expected") in uniques:
                    translated["uniqueFrom"] = uniques[translated["expected"]]
                entry["checks"].append(translated)
            else:
                if "unique" in translated:
                    uniques[str(action.get("value"))] = {"seq": entry["seq"], "label": translated["label"]}
                entry["actions"].append(translated)
            reviewed.append((entry["seq"], translated))
        if recorded:  # a step with only notes opens no application
            if app and app not in plan["apps"]:
                plan["apps"].append(app)
            previous_app = app or previous_app
        plan["steps"].append(entry)
        kept_steps.append(recorded_step)
    analyse(plan, kept_steps, read_file, project or {})
    if plan.get("outcomeMismatch"):
        plan["review"].append({"seq": None, "label": "Expected outcome", "widgetId": None, "resolution": "rule",
                               "rule": "outcome", "reason": plan["outcomeMismatch"]["reason"]})
    for seq, translated in reviewed:
        imports |= imports_for(" ".join(translated.get(k) or "" for k in ("getter", "java", "then", "cellById")),
                               translated.get("widget"))
        if translated.get("rule") == "coverage":
            imports.add(COVERAGE_UTIL)
        if needs_review(translated):
            plan["review"].append({
                "seq": seq, "label": translated["label"], "widgetId": translated.get("widgetId"),
                "resolution": translated["resolution"], "rule": translated.get("rule"),
                "reason": review_reason(translated)})
    plan["imports"] = sorted(imports)
    return plan


def note_entry(seq, text: str) -> dict:
    """A note, flagged when it asks for a check (verify, confirm, ensure…) or states a condition
    ("If there's an error…, override"): the gate lists the condition instead of doing it always."""
    note = {"seq": seq, "text": text}
    if ASKS_CHECK.search(text):
        note["asksCheck"] = True
    if CONDITIONAL.search(text):
        note["conditional"] = True
    return note


def analyse(plan: dict, recorded_steps: list, read_file, project: dict) -> None:
    """What needs the whole plan: helpers and blockers per step, retries, navigation-only Next clicks,
    the base's Quote / Issue methods, stronger checks and the values for notes that ask for a check."""
    screen_helpers = (project.get("screenHelpers") or {}).get("value")
    bases = (project.get("transactionBases") or {}).get("value") or []
    for entry in plan["steps"]:
        entry["pages"] = step_pages(entry)
    pages = {page for entry in plan["steps"] for page in entry["pages"]}
    plan_bases = {base["class"] for base in bases
                  if any(field.split()[0][:-len("Page")] in pages for field in base.get("wizardFields") or [])}
    for entry in plan["steps"]:
        if screen_helpers:
            entry["helpers"] = helpers_for(entry, screen_helpers, plan_bases)
        for item in entry["actions"]:
            if item.get("wizardAction"):
                base_methods(item, bases)
    plan["retries"] = retries(plan["steps"]) + refused(plan["steps"])
    plan["blockers"] = blockers(plan["steps"])
    plan["navigation"] = navigation(plan["steps"])
    cache = {}

    def snapshot_of(index):
        if index not in cache:
            cache[index] = snapshot(recorded_steps[index], read_file)
        return cache[index]

    entered, issued = [], False
    for index, entry in enumerate(plan["steps"]):
        entered += [str(a.get("value")) for a in entry["actions"]
                    if a["type"] == "change" and isinstance(a.get("value"), str) and a.get("value") != REDACTED]
        issued = issued or any(issues(a) for a in entry["actions"])
        for item in entry["checks"]:
            check = item.pop("recordedCheck")
            if check.get("assert") in WEAK_CHECKS and item.get("widgetId"):
                stronger_check(item, check, snapshot_of(index)["values"], entered)
            if issued and row_table(item.get("widgetId")) and item.get("getter") and item["java"]:
                bound_row(item)
    if any(n.get("asksCheck") for n in plan["notes"]):
        plan["noteChecks"] = note_checks(plan, [snapshot_of(i) for i in range(len(plan["steps"]))])
    outcome_mismatch(plan)
    starts_logged_in = bool(plan["steps"]) and plan["steps"][0]["login"]
    if read_file and plan["steps"] and not starts_logged_in:
        plan["startValues"] = start_values(plan, [snapshot_of(i) for i in range(len(plan["steps"]))])


ISSUE_LABEL = re.compile(r"^(issue policy|issue now|issue|bind only|bind policy change)$", re.I)


def issues(action: dict) -> bool:
    """A click that issues or binds the transaction."""
    return action["type"] == "click" and (action.get("wizardAction") == "issue"
                                          or bool(ISSUE_LABEL.match(action["label"].strip())))


def bound_row(item: dict) -> None:
    """A check on a list row after the transaction was issued, i.e. on the reopened, read-only job:
    there the row API returned only the header row, while the cell read by its id worked."""
    item["cellById"] = f"WidgetLabel.get({jstr(item['widgetId'])}, getContext())"
    warn(item, f"a row of a bound, read-only job: getFirstRow() / getRows() may return only the header "
               f"row there; read the cell by its id ({item['cellById']}{item['java']})")


OUTCOME_BINDS = re.compile(r"\b(bind|binds|bound|issue|issued)\b", re.I)


def outcome_mismatch(plan: dict) -> None:
    """The expected outcome mentions more binds / issues than the recording makes (e.g. "an increase
    bound, then a decrease bound" against one change with both): a question for the gate."""
    mentioned = len(OUTCOME_BINDS.findall(plan["test"].get("expectedOutcome") or ""))
    refused_seqs = {r["seq"] for r in plan["retries"] if r["kind"] == "refused"}
    made = [entry["seq"] for entry in plan["steps"] if entry["seq"] not in refused_seqs
            and any(issues(a) for a in entry["actions"])]
    if mentioned > len(made):
        plan["outcomeMismatch"] = {
            "mentioned": mentioned, "recorded": len(made), "issueSeqs": made,
            "reason": f"the expected outcome mentions {mentioned} binds / issues, the recording makes {len(made)}"
                      f"{' (seq ' + ', '.join(map(str, made)) + ')' if made else ''}: ask whether the test "
                      "follows the recording or the expected outcome"}


START_VALUES = 40


def start_values(plan: dict, snapshots: list) -> list:
    """The coverages as the recording first shows them, before it changes them: the state the policy was
    in when the recording started. Compared with the folder's recorded steps' end state, it shows which
    step this recording continues ("chain after X")."""
    groups, found = {}, {}
    for shot in snapshots:
        groups.update(shot["groups"])
    for entry, shot in zip(plan["steps"], snapshots):
        for widget_id, value in shot["values"].items():
            coverage = coverage_of(widget_id, groups)
            if coverage and widget_id not in found:
                term = None if widget_id.endswith("_checkbox") else (shot["labels"].get(widget_id) or "")
                found[widget_id] = {"coverage": coverage, "covterm": term, "value": value, "seq": entry["seq"]}
    return list(found.values())[:START_VALUES]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CenterTest Recorder recording -> plan JSON")
    parser.add_argument("recording", help="the recording .zip, its folder, or its session.json")
    parser.add_argument("--cssids", required=True, help="resources dir holding cssids/<app>/ (or <app>.cssids)")
    parser.add_argument("--project", help="project.json from scan_project.py: match screens to the project's helpers")
    parser.add_argument("--out", help="write the plan here instead of stdout")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.cssids):
        print(f"Error: cssids directory not found: {args.cssids}", file=sys.stderr)
        return 2
    try:
        session = load_session(args.recording)
        project = None
        if args.project:
            with open(args.project, encoding="utf-8") as f:
                project = json.load(f)
    except (RecordingError, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    plan = build_plan(session, args.cssids, file_reader(args.recording), project)
    text = json.dumps(plan, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
