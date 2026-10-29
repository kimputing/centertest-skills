import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import parse_recording as pr  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
RECORDINGS = os.path.join(FIXTURES, "recordings")
CSSIDS = os.path.join(FIXTURES, "cssids")


def load(name):
    return pr.load_session(os.path.join(RECORDINGS, name))


class LoadSessionTest(unittest.TestCase):
    def test_loads_folder(self):
        self.assertEqual(load("real-180418")["id"], "2026-10-01_180418")

    def test_loads_zip_with_one_top_level_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rec.zip")
            with zipfile.ZipFile(path, "w") as z:
                z.write(os.path.join(RECORDINGS, "real-180418", "session.json"),
                        "2026-10-01_180418_test1/session.json")
            self.assertEqual(pr.load_session(path)["id"], "2026-10-01_180418")

    def test_loads_zip_ignoring_macosx_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rec.zip")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("__MACOSX/2026-10-01_180418_test1/._session.json", b"\x00\x05binary")
                z.write(os.path.join(RECORDINGS, "real-180418", "session.json"),
                        "2026-10-01_180418_test1/session.json")
            self.assertEqual(pr.load_session(path)["id"], "2026-10-01_180418")

    def test_loads_outer_folder_of_the_recorder_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = os.path.join(tmp, "2026-10-01_180418_test1")
            os.makedirs(os.path.join(outer, "2026-10-01_180418_test1"))
            with open(os.path.join(RECORDINGS, "real-180418", "session.json"), encoding="utf-8") as src, \
                    open(os.path.join(outer, "2026-10-01_180418_test1", "session.json"), "w", encoding="utf-8") as dst:
                dst.write(src.read())
            self.assertEqual(pr.load_session(outer)["id"], "2026-10-01_180418")

    def test_loads_session_json_path(self):
        self.assertEqual(pr.load_session(os.path.join(RECORDINGS, "real-180418", "session.json"))["id"],
                         "2026-10-01_180418")

    def test_folder_without_session_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(pr.RecordingError, "no session.json"):
                pr.load_session(tmp)

    def test_not_a_recording(self):
        with self.assertRaisesRegex(pr.RecordingError, "not a recording"):
            pr.load_session(os.path.join(RECORDINGS, "does-not-exist"))


class HelpersTest(unittest.TestCase):
    def test_messages_accept_plain_strings_and_objects(self):
        step = {"messages": ["old style", {"text": "new style", "level": "error"}]}
        self.assertEqual(pr.messages(step), [{"text": "old style", "level": ""},
                                             {"text": "new style", "level": "error"}])

    def test_wait_title_keeps_the_part_before_the_colon(self):
        self.assertEqual(pr.wait_title("Account Summary: Duncan Test"), "Account Summary")
        self.assertEqual(pr.wait_title("Offerings"), "Offerings")
        self.assertEqual(pr.wait_title(None), "")


class LookupTest(unittest.TestCase):
    def test_exact_key(self):
        self.assertEqual(pr.lookup(CSSIDS, "pc", "Login-LoginScreen-LoginDV-username"),
                         ("resolved", ["new LoginPage(getContext()).getUsername()"]))

    def test_iterator_index_is_put_back(self):
        result = pr.resolve(CSSIDS, "pc", {"widgetId": "SubmissionWizard-LOBWizardStepGroup-ClauseIterator-2-Limit"})
        self.assertEqual(result, {"resolution": "resolved",
                                  "getter": "new SubmissionWizardPage(getContext()).getClauseIterator(2).getLimit()"})

    def test_unknown_application(self):
        self.assertEqual(pr.resolve(CSSIDS, None, {"widgetId": "X-Y"}),
                         {"resolution": "unresolved", "reason": "unknown application"})

    def test_no_widget_id(self):
        self.assertEqual(pr.resolve(CSSIDS, "pc", {"type": "dialog"}),
                         {"resolution": "unresolved", "reason": "no widget id"})

    def test_row_filters_and_later_page(self):
        getter = "new P(getContext()).getTable().getFirstRow().select().getSelect()"
        action = {"page": 2, "rowKey": [{"header": "Name", "text": "Acme"}, {"header": "City", "text": "Ulm"}]}
        self.assertEqual(pr.with_row(getter, action),
                         'new P(getContext()).getTable().getFirstRow().forMaximumPages(2)'
                         '.with("Name", "Acme", "TextCell").with("City", "Ulm", "TextCell").select().getSelect()')

    def test_row_without_key_is_unchanged(self):
        getter = "new P(getContext()).getTable().getFirstRow().select().getSelect()"
        self.assertEqual(pr.with_row(getter, {"row": 2}), getter)

    def test_jstr_escapes(self):
        self.assertEqual(pr.jstr('say "hi" \\ now\nnext'), '"say \\"hi\\" \\\\ now\\nnext"')
        self.assertEqual(pr.jstr(None), '""')
        self.assertEqual(pr.jstr("Zürich"), '"Zürich"')


class FallbackRulesTest(unittest.TestCase):
    def resolve(self, app, **action):
        return pr.resolve(CSSIDS, app, action)

    def test_toolbar_segment_is_bracketed(self):
        result = self.resolve("pc", widgetId="SubmissionWizard-LOBWizardStepGroup-LineWizardStepSet-GeneralLiabilityScreen"
                                             "-AdditionalCoveragesPanelSet-AdditionalCoveragesDV_tb-Add",
                              kind="ToolbarButtonWidget")
        self.assertEqual(result["rule"], "toolbar")
        self.assertEqual(result["getter"], "new SubmissionWizardPage(getContext()).getLineWizardStepSet()"
                                           ".getLineWizardStepSetGLLineStep().getAdditionalCoveragesCard().getAdd()"
                                           '.withCssId("SubmissionWizard-LOBWizardStepGroup-LineWizardStepSet'
                                           '-GeneralLiabilityScreen-AdditionalCoveragesPanelSet-AdditionalCoveragesDV_tb-Add")')

    def test_wizard_button(self):
        result = self.resolve("pc", widgetId="SubmissionWizard-Next", kind="WizardButtonWidget")
        self.assertEqual(result, {"resolution": "rule", "rule": "wizardButton",
                                  "getter": "new SubmissionWizardPage(getContext()).getWizardButtons().getNext()"})

    def test_tab_and_tab_menu_item(self):
        self.assertEqual(self.resolve("pc", widgetId="TabBar-AccountTab", kind="TabWidget")["getter"],
                         "new TabBar(getContext()).getAccountTab()")
        self.assertEqual(self.resolve("pc", widgetId="TabBar-AccountTab-AccountTab_NewAccount",
                                      kind="MenuItemWidget")["getter"],
                         "new TabBar(getContext()).getAccount().getNewAccount()")

    def test_row_select_column_with_row_key(self):
        result = self.resolve("pc", widgetId="OrganizationSearchPopup-OrganizationSearchPopupScreen-OrganizationSearchResultsLV-0-_Select",
                              kind="SelectorCellValueWidget", rowKey=[{"header": "Organization Name", "text": "ACV"}])
        self.assertEqual(result["rule"], "rowColumn")
        self.assertEqual(result["getter"], 'new OrganizationSearchPopup(getContext()).getOrganizationSearchResultsTable()'
                                           '.getFirstRow().with("Organization Name", "ACV", "TextCell").select().getSelect()')

    def test_row_named_and_checkbox_columns(self):
        link = self.resolve("pc", widgetId="NewSubmission-NewSubmissionScreen-ProductOffersDV-ProductSelectionLV-4-addSubmission",
                            kind="LinkWidget")
        self.assertTrue(link["getter"].endswith(".getProductSelectionTable().getFirstRow().select().getAddSubmission()"))
        box = self.resolve("pc", widgetId="CoveragePatternSearchPopup-CoveragePatternSearchScreen-CoveragePatternSearchResultsLV-0-_Checkbox",
                           kind="checkbox", inputType="checkbox")
        self.assertEqual((box["rule"], box["column"]), ("rowColumn", "_Checkbox"))
        self.assertTrue(box["getter"].endswith(".select().get_CHECKBOX()"))

    def test_row_cell_column_drops_the_cell_suffix(self):
        cell = self.resolve("pc", widgetId="NewSubmission-NewSubmissionScreen-ProductOffersDV-ProductSelectionLV-4-Description_Cell",
                            kind="text")
        self.assertEqual(cell["column"], "Description_Cell")
        self.assertTrue(cell["getter"].endswith(".getProductSelectionTable().getFirstRow().select().getDescription()"))

    def test_row_column_gw9_separators(self):
        result = self.resolve("cc", widgetId="ClaimSearch:ClaimSearchScreen:ClaimSearchResultsLV:2:_Select",
                              kind="SelectorCellValueWidget")
        self.assertEqual(result["getter"], "new ClaimSearchPage(getContext()).getClaimSearchResultsTable()"
                                           ".getFirstRow().select().getSelect()")

    def test_iterator_widget_falls_back_to_raw_form(self):
        widget_id = ("SubmissionWizard-LOBWizardStepGroup-LineWizardStepSet-GeneralLiabilityScreen-PolicyLineDV"
                     "-GLGroupIterator-0-CoverageInputSet-CovPatternInputGroup-1-CovTermInputSet-OptionTermInput")
        result = self.resolve("pc", widgetId=widget_id, kind="select")
        self.assertEqual(result, {"resolution": "raw", "rule": "raw", "widget": "WidgetRangeInput",
                                  "getter": f'WidgetRangeInput.get("{widget_id}", getContext())'})

    def test_raw_widget_class_from_kind(self):
        self.assertEqual(self.resolve("pc", widgetId="X-Y-_checkbox", kind="checkbox", inputType="checkbox")["widget"],
                         "WidgetCheckBoxInput")
        self.assertEqual(self.resolve("pc", widgetId="X-Y-Header_inner", kind="div")["widget"], "WidgetLabel")
        self.assertEqual(self.resolve("pc", widgetId="X-Y-EffectiveDate", kind="date", inputType="text")["widget"],
                         "WidgetDateInput")

    def test_app_without_cssids_falls_back_to_raw(self):
        result = self.resolve("ab", widgetId="ABContactDetailPopup-Name", kind="text")
        self.assertEqual((result["resolution"], result["widget"]), ("raw", "WidgetTextInput"))


class JavaFragmentsTest(unittest.TestCase):
    def test_checks(self):
        cases = [
            ({"assert": "isEqualTo", "expected": "Active"}, '.assertEquals("Active")'),
            ({"assert": "isEqualTo", "expected": "<blank>"}, '.assertEquals("<blank>")'),
            ({"assert": "isNotEqualTo", "expected": "X", "soft": True}, '.assertNotEqualsSoft("X")'),
            ({"assert": "isEqualToNumeric", "expected": "1,250.00", "soft": True}, '.assertEqualsNumericSoft("1,250.00")'),
            ({"assert": "isNotEqualToNumeric", "expected": "0"}, '.assertNotEqualsNumeric("0")'),
            ({"assert": "contains", "expected": "Ac"}, '.assertContains("Ac")'),
            ({"assert": "notContains", "expected": "Z"}, '.assertNotContains("Z")'),
            ({"assert": "isLabelEqualTo", "expected": "Name"}, '.assertLabel("Name")'),
            ({"assert": "isEmpty"}, ".assertEmpty()"),
            ({"assert": "isNotEmpty", "soft": True}, ".assertNotEmptySoft()"),
            ({"assert": "isEnabled"}, ".assertEnabled()"),
            ({"assert": "isDisabled"}, ".assertDisabled()"),
            ({"assert": "isEditable"}, ".assertEditable()"),
            ({"assert": "isReadonly"}, ".assertReadOnly()"),
            ({"assert": "isVisible", "flag": True}, ".assertVisible(true)"),
            ({"assert": "isVisible", "flag": False, "seen": "gone"}, ".assertVisible(false)"),
            ({"assert": "isChecked", "flag": False}, ".assertChecked(false)"),
            ({"assert": "isRequired"}, ".assertRequired(true)"),
            ({"assert": "isIn", "values": ["A", 'B "q"']}, '.assertIsIn(new String[]{"A", "B \\"q\\""})'),
            ({"assert": "optionsContains", "values": ["A", "B"]}, '.assertOptionsContain(new String[]{"A", "B"})'),
            ({"assert": "optionsEquals", "values": ["A"], "soft": True}, '.assertOptionsEqualSoft(new String[]{"A"})'),
            ({"assert": "optionsNotContains", "values": ["Z"]}, '.assertOptionsNotContain("Z")'),
            ({"assert": "isSomethingNew"}, None),
        ]
        for check, expected in cases:
            with self.subTest(check=check):
                self.assertEqual(pr.check_java(check), expected)

    def test_message_checks(self):
        self.assertEqual(pr.message_check_java({"assert": "messageWith", "expected": "Exact"}),
                         'MessagesUtil.assertMessageWith(getContext(), "Exact");')
        self.assertEqual(pr.message_check_java({"assert": "messageContaining", "expected": "Quote"}),
                         'MessagesUtil.assertMessageContaining(getContext(), "Quote");')
        self.assertEqual(pr.message_check_java({"assert": "noErrorMessages"}),
                         'CenterTestAssertion.withContext(getContext()).withDescription("No error messages")'
                         '.assertThat(() -> Assertions.assertThat(MessagesUtil.getErrorMessages(getContext())).isEmpty());')

    def test_soft_message_checks_let_the_test_go_on(self):
        self.assertEqual(pr.message_check_java({"assert": "messageWith", "expected": "Exact", "soft": True}),
                         'CenterTestAssertion.withContext(getContext()).withDescription("Message shown: Exact")'
                         '.softAssertThat(() -> MessagesUtil.assertMessageWith(getContext(), "Exact"));')
        self.assertIn('.softAssertThat(() -> Assertions.assertThat(MessagesUtil.getErrorMessages(getContext()))',
                      pr.message_check_java({"assert": "noErrorMessages", "soft": True}))

    def test_actions(self):
        self.assertEqual(pr.action_java({"type": "click"}), ".click()")
        self.assertEqual(pr.action_java({"type": "change", "value": "su"}), '.set("su")')
        self.assertEqual(pr.action_java({"type": "change", "value": "1000", "display": "1,000"}), '.set("1,000")')
        # WidgetCheckBoxInput has only set(String); set(Boolean) is on the boolean radio/dropdown widgets
        self.assertEqual(pr.action_java({"type": "change", "value": True}), '.set("true")')
        self.assertEqual(pr.action_java({"type": "change", "value": False}), '.set("false")')
        self.assertIsNone(pr.action_java({"type": "change", "value": "[redacted]"}))
        self.assertIsNone(pr.action_java({"type": "key", "key": "Enter"}))
        self.assertEqual(pr.action_java({"type": "change", "value": "Acme", "unique": {"rule": "company"}}),
                         ".set(Utilities.DataGenerator.getGenerator().company().name())")

    def test_unique_values(self):
        gen = "Utilities.DataGenerator.getGenerator()"
        cases = [
            ({"rule": "email"}, gen + ".internet().emailAddress()"),
            ({"rule": "ssn"}, "Utilities.DataGenerator.getValidSsn()"),
            ({"rule": "letters", "prefix": "Acme ", "length": 6}, '"Acme " + Utilities.getRandomStringWithoutNumbers(6)'),
            ({"rule": "alnum", "length": 8}, "Utilities.getRandomString(8)"),
            ({"rule": "pattern", "pattern": "??-####", "upper": True}, gen + '.bothify("??-####", true)'),
            ({"rule": "pattern", "pattern": "###-##"}, gen + '.numerify("###-##")'),
            ({"rule": "unknown"}, None),
        ]
        for unique, expected in cases:
            with self.subTest(unique=unique):
                self.assertEqual(pr.unique_java(unique), expected)


class ReviewFixesTest(unittest.TestCase):
    def test_expand_click_is_not_translated_and_says_why(self):
        item = pr.translate(CSSIDS, "pc", {"type": "click", "widgetId": "TabBar-AccountTab", "kind": "TabWidget",
                                           "part": "expand", "text": "Account"})
        self.assertIsNone(item["java"])
        self.assertIn("expand", item["warning"])
        self.assertTrue(pr.needs_review(item))

    def test_sort_click_is_not_translated(self):
        item = pr.translate(CSSIDS, "pc", {"type": "click", "widgetId": "X-Y-NameHeader", "kind": "div", "part": "sort"})
        self.assertIsNone(item["java"])
        self.assertIn("sort", item["warning"])

    def test_several_matching_getters_are_reviewed(self):
        self.assertTrue(pr.needs_review({"resolution": "resolved", "java": ".click()", "candidates": ["a", "b"]}))

    def test_every_review_row_has_a_reason(self):
        review = pr.build_plan(load("real-174907"), CSSIDS)["review"]
        self.assertTrue(review)
        self.assertEqual([r for r in review if not r["reason"]], [])


GL = "SubmissionWizard-LOBWizardStepGroup-LineWizardStepSet-GeneralLiabilityScreen-"
OCCURRENCE = GL + "PolicyLineDV-GLGroupIterator-0-CoverageInputSet-CovPatternInputGroup-0-CovTermInputSet-OptionTermInput"
DEDUCTIBLE = GL + "PolicyLineDV-GLGroupIterator-1-CoverageInputSet-CovPatternInputGroup-_checkbox"
POLLUTANTS = (GL + "AdditionalCoveragesPanelSet-AdditionalCoveragesDV-0-CoverageInputSet-CovPatternInputGroup-0"
              "-CovTermInputSet-StringTermInput")


class CoverageUtilTest(unittest.TestCase):
    """Coverage checkboxes and terms go through CoverageUtil, found by their labels, not by iterator position."""

    def translate(self, **action):
        return pr.translate(CSSIDS, "pc", action)

    def test_coverage_checkbox_is_selected_by_its_label(self):
        item = self.translate(type="change", widgetId=DEDUCTIBLE, kind="checkbox", label="GL Deductible",
                              value=True, context=["Standard Coverages"])
        self.assertEqual((item["resolution"], item["rule"], item["getter"], item["java"]),
                         ("rule", "coverage", "coverageUtil", '.setSelected("GL Deductible", true)'))
        self.assertEqual(item["coverage"], {"coverage": "GL Deductible", "covterm": None})
        self.assertFalse(pr.needs_review(item))

    def test_coverage_term_takes_its_coverage_from_the_context(self):
        item = self.translate(type="change", widgetId=OCCURRENCE, kind="select", label="Occurrence Limit",
                              value="500000", display="500,000", context=["Standard Coverages", "General Liability"])
        self.assertEqual(item["java"], '.setCoverage("General Liability", "Occurrence Limit", "500,000")')
        self.assertEqual(item["value"], "500,000")
        self.assertFalse(pr.needs_review(item))

    def test_coverage_term_without_a_coverage_title_is_reviewed(self):
        item = self.translate(type="change", widgetId=POLLUTANTS, kind="text", label="Designated Pollutants",
                              value="333", context=["Additional Coverages"])
        self.assertEqual(item["java"], '.setCoverage("Designated Pollutants", "", "333")')
        self.assertIn("no coverage title", item["warning"])
        self.assertTrue(pr.needs_review(item))

    def test_coverage_term_with_a_unique_value(self):
        item = self.translate(type="change", widgetId=POLLUTANTS, kind="text", label="Limit", value="AB12",
                              context=["Additional Coverages", "Designated Pollutants"],
                              unique={"rule": "alnum", "length": 4})
        self.assertEqual(item["java"], '.setCoverage("Designated Pollutants", "Limit", Utilities.getRandomString(4))')

    def test_gw9_separators(self):
        widget_id = OCCURRENCE.replace("-", ":")
        item = self.translate(type="change", widgetId=widget_id, kind="select", label="Occurrence Limit",
                              value="500,000", context=["General Liability"] * 2)
        self.assertEqual(item["rule"], "coverage")

    def test_coverage_term_checks(self):
        context = ["Standard Coverages", "General Liability"]
        cases = [
            ({"assert": "isEqualTo", "expected": "500,000"},
             '.assertEquals("General Liability", "Occurrence Limit", "500,000")'),
            ({"assert": "isEditable"}, '.assertEditable("General Liability", "Occurrence Limit")'),
            ({"assert": "isReadonly"}, '.assertReadOnly("General Liability", "Occurrence Limit")'),
            ({"assert": "isNotEmpty"}, '.assertNotNull("General Liability", "Occurrence Limit")'),
        ]
        for check, expected in cases:
            with self.subTest(check=check):
                item = self.translate(type="check", widgetId=OCCURRENCE, kind="select", label="Occurrence Limit",
                                      context=context, **check)
                self.assertEqual((item["getter"], item["java"]), ("coverageUtil", expected))

    def test_soft_coverage_check_is_a_whole_statement(self):
        item = self.translate(type="check", widgetId=OCCURRENCE, kind="select", label="Occurrence Limit",
                              context=["Standard Coverages", "General Liability"],
                              **{"assert": "isEqualTo", "expected": "500,000", "soft": True})
        self.assertIsNone(item["getter"])
        self.assertEqual(item["java"],
                         'CenterTestAssertion.withContext(getContext())'
                         '.withDescription("General Liability / Occurrence Limit equals 500,000")'
                         '.softAssertThat(() -> coverageUtil.assertEquals("General Liability", "Occurrence Limit", '
                         '"500,000"));')

    def test_check_coverage_util_cannot_make_is_reviewed(self):
        item = self.translate(type="check", widgetId=DEDUCTIBLE, kind="checkbox", label="GL Deductible",
                              context=["Standard Coverages"], **{"assert": "isChecked", "flag": True})
        self.assertIsNone(item["java"])
        self.assertIn("CoverageUtil", item["warning"])
        self.assertTrue(pr.needs_review(item))

    def test_click_on_a_coverage_widget_is_left_to_the_getters(self):
        item = self.translate(type="click", widgetId=DEDUCTIBLE, kind="checkbox", label="GL Deductible")
        self.assertNotEqual(item.get("rule"), "coverage")

    def test_recording_uses_coverage_util_for_every_coverage(self):
        plan = plan_for("real-174907")
        items = [i for s in plan["steps"] for i in s["actions"] + s["checks"]
                 if "CoverageInputSet" in (i.get("widgetId") or "")]
        self.assertTrue(items)
        self.assertEqual([i["widgetId"] for i in items if i.get("rule") != "coverage"], [])
        self.assertEqual(item(items, OCCURRENCE)["java"],
                         '.setCoverage("General Liability", "Occurrence Limit", "500,000")')
        self.assertEqual(item(items, DEDUCTIBLE)["java"], '.setSelected("GL Deductible", true)')
        self.assertIn("com.ankrpt.centertest.guidewire.runtime.CoverageUtil", plan["imports"])
        reviewed = {r["widgetId"] for r in plan["review"]}
        self.assertIn(POLLUTANTS, reviewed)
        self.assertNotIn(OCCURRENCE, reviewed)


EFFECTIVE = "PolicyChangeWizard-PolicyChangeWizard_StartPolicyChangeScreen-StartPolicyChangeDV-EffectiveDate"


class PickedDateTest(unittest.TestCase):
    """A date picked with the calendar fires no change event: its value is only in the form the step posted."""

    def plan(self, actions, fields):
        session = {"steps": [{"seq": 2, "app": "PolicyCenter", "title": "Policy Change", "actions": actions,
                              "requests": [{"method": "POST", "fields": fields}]}]}
        return pr.build_plan(session, CSSIDS)

    def test_calendar_clicks_become_one_set_of_the_posted_value(self):
        # as recorded: the calendar icon, then the field; the value is only in the POST that followed
        plan = self.plan([{"type": "click", "widgetId": EFFECTIVE + "_dateIcon", "kind": ""},
                          {"type": "click", "widgetId": EFFECTIVE, "kind": "date", "label": "Effective Date"},
                          {"type": "click", "widgetId": "PolicyChangeWizard-Next", "kind": "WizardButtonWidget"}],
                         [{"name": "QuickJump", "value": ""}, {"name": EFFECTIVE, "value": "12/31/2027"},
                          {"name": "PolicyPeriodEffDateID_Arg", "value": "01/01/2028"}])
        actions = plan["steps"][0]["actions"]
        self.assertEqual([a["widgetId"] for a in actions], [EFFECTIVE, "PolicyChangeWizard-Next"])
        date = actions[0]
        self.assertEqual((date["type"], date["java"], date["value"], date["source"]),
                         ("change", '.set("12/31/2027")', "12/31/2027", "request"))
        self.assertEqual(date["postedDates"], {"PolicyPeriodEffDateID_Arg": "01/01/2028"})
        reason = next(r["reason"] for r in plan["review"] if r["widgetId"] == EFFECTIVE)
        self.assertIn("calendar", reason)
        self.assertIn("2 calendar clicks", reason)
        self.assertIn("PolicyPeriodEffDateID_Arg = 01/01/2028", reason)

    def test_raw_calendar_date_is_a_date_input(self):
        plan = self.plan([{"type": "click", "widgetId": "X-Y-StartDate_dateIcon"}], [{"name": "X-Y-StartDate", "value": "1/2/2027"}])
        date = plan["steps"][0]["actions"][0]
        self.assertEqual((date["widgetId"], date["widget"], date["java"]), ("X-Y-StartDate", "WidgetDateInput", '.set("1/2/2027")'))
        self.assertEqual(date["postedDates"], {})

    def test_typed_date_is_left_alone(self):
        plan = self.plan([{"type": "click", "widgetId": EFFECTIVE, "kind": "date"},
                          {"type": "change", "widgetId": EFFECTIVE, "kind": "date", "value": "01/15/2027"}],
                         [{"name": EFFECTIVE, "value": "01/15/2027"}])
        self.assertEqual([a["type"] for a in plan["steps"][0]["actions"]], ["click", "change"])

    def test_click_on_a_field_that_posted_no_date_stays_a_click(self):
        plan = self.plan([{"type": "click", "widgetId": "X-Y-Name", "kind": "text"}], [{"name": "X-Y-Name", "value": "Acme"}])
        self.assertEqual(plan["steps"][0]["actions"][0]["java"], ".click()")


def plan_for(name):
    return pr.build_plan(load(name), CSSIDS)


def step(plan, seq):
    return next(s for s in plan["steps"] if s["seq"] == seq)


def item(items, widget_id):
    return next(i for i in items if i.get("widgetId") == widget_id)


class PlanFromRealRecordingsTest(unittest.TestCase):
    def test_metadata_and_kept_steps(self):
        plan = plan_for("real-180418")
        self.assertEqual(plan["test"]["testId"], "tc123")
        self.assertEqual(plan["test"]["features"], ["AD-123"])
        self.assertEqual(plan["test"]["defects"], ["JIRA-321"])
        self.assertEqual([s["seq"] for s in plan["steps"]], [2, 3])
        self.assertEqual(plan["apps"], ["pc"])

    def test_login_step(self):
        login = step(plan_for("real-180418"), 2)
        self.assertTrue(login["login"])
        self.assertEqual(item(login["actions"], "Login-LoginScreen-LoginDV-username")["java"], '.set("su")')
        self.assertIsNone(item(login["actions"], "Login-LoginScreen-LoginDV-password")["java"])

    def test_account_summary_checks(self):
        summary = step(plan_for("real-180418"), 3)
        self.assertEqual(summary["waitTitle"], "Account Summary")
        prefix = "AccountFile_Summary-AccountSummaryDashboard-AccountDetailsDetailViewTile-AccountDetailsDetailViewTile_DV-"
        self.assertEqual(item(summary["checks"], prefix + "AccountStatus")["java"], '.assertEquals("Active")')
        self.assertEqual(item(summary["checks"], prefix + "AccountNumber")["java"], ".assertVisible(true)")
        header = item(summary["checks"], "AccountFile_Summary-AccountSummaryDashboard-CurrentActivitiesAccountListViewTile"
                                         "-CurrentActivitiesAccountListViewTile_LV-PriorityHeader_inner")
        self.assertEqual((header["resolution"], header["widget"], header["java"]), ("raw", "WidgetLabel", ".assertEnabled()"))
        self.assertEqual(item(summary["actions"], "TabBar-AccountTab")["getter"], "new TabBar(getContext()).getAccountTab()")

    def test_submission_recording(self):
        plan = plan_for("real-174907")
        self.assertIn("MessagesUtil.getErrorMessages(getContext())", step(plan, 5)["checks"][0]["java"])
        select = item(step(plan, 13)["actions"],
                      "OrganizationSearchPopup-OrganizationSearchPopupScreen-OrganizationSearchResultsLV-0-_Select")
        self.assertIn('.with("Organization Name", "ACV Property Insurance", "TextCell")', select["getter"])
        self.assertEqual(item(step(plan, 18)["actions"], "SubmissionWizard-Next")["rule"], "wizardButton")
        tick = item(step(plan, 26)["actions"],
                    "CoveragePatternSearchPopup-CoveragePatternSearchScreen-CoveragePatternSearchResultsLV-0-_Checkbox")
        self.assertEqual(tick["java"], ".click()")
        self.assertIn("com.ankrpt.centertest.guidewire.runtime.MessagesUtil", plan["imports"])
        self.assertIn("com.ankrpt.centertest.guidewire.widget.WidgetRangeInput", plan["imports"])
        self.assertTrue(any(r["seq"] == 18 and r["rule"] == "wizardButton" for r in plan["review"]))
        self.assertFalse(any(r["widgetId"] and r["widgetId"].startswith("Login-") for r in plan["review"]))


class PlanFromSyntheticRecordingTest(unittest.TestCase):
    def setUp(self):
        self.plan = plan_for("synthetic")

    def test_notes_messages_and_unique_value(self):
        search = step(self.plan, 2)
        self.assertEqual(self.plan["notes"], [{"seq": None, "text": "before the first step"},
                                              {"seq": 2, "text": "pick the organization on page 2"}])
        self.assertEqual(search["notes"], ["pick the organization on page 2"])
        self.assertEqual(search["messages"], [{"text": "Legacy plain message", "level": ""}])
        name = search["actions"][0]
        self.assertEqual(name["unique"], {"expr": "Utilities.DataGenerator.getGenerator().company().name()",
                                          "recorded": "Acme"})
        self.assertIn("com.ankrpt.centertest.util.Utilities", self.plan["imports"])

    def test_rows(self):
        first, second = step(self.plan, 2)["actions"][1:3]
        self.assertIn('.getFirstRow().forMaximumPages(2).with("Name", "Acme", "TextCell").select().getSelect()',
                      first["getter"])
        self.assertTrue(second["warning"].startswith("row 2 picked by position"))

    def test_untranslated_and_unknown_items_are_reviewed(self):
        reasons = {(r["seq"], r["label"]): r for r in self.plan["review"]}
        self.assertEqual(reasons[(2, "Name")]["reason"], "not translated")  # the Enter key
        self.assertEqual(reasons[(3, "Offering")]["reason"], "not translated")  # isSomethingNew
        self.assertEqual(reasons[(3, "Are you sure?")]["resolution"], "unresolved")
        self.assertEqual(reasons[(5, "Widget")]["reason"], "unknown application")  # labelled from its id

    def test_soft_message_check_is_soft(self):
        message = step(self.plan, 3)["checks"][3]
        self.assertEqual(message["java"],
                         'CenterTestAssertion.withContext(getContext()).withDescription("Message shown containing: Quote")'
                         '.softAssertThat(() -> MessagesUtil.assertMessageContaining(getContext(), "Quote"));')
        self.assertNotIn("warning", message)
        self.assertIn("com.ankrpt.centertest.assertion.CenterTestAssertion", self.plan["imports"])

    def test_app_switch_links_check_to_unique_value(self):
        billing = step(self.plan, 4)
        self.assertEqual((billing["app"], billing["appSwitch"]), ("bc", True))
        self.assertEqual(billing["checks"][0]["uniqueFrom"], {"seq": 2, "label": "Name"})
        self.assertEqual(self.plan["apps"], ["pc", "bc"])


class StepNotesTest(unittest.TestCase):
    """Recorder 1.1 keeps notes on the steps; a note step has no actions."""

    def setUp(self):
        session = {"steps": [
            {"seq": 1, "kind": "start", "app": "PolicyCenter", "actions": []},
            {"seq": 2, "app": "PolicyCenter", "screen": "AccountFile_Summary", "title": "Account Summary",
             "actions": [{"type": "click", "widgetId": "TabBar-AccountTab", "label": "Account"}],
             "notes": [{"time": 1, "text": "The account number is new on every run.", "source": "panel"}]},
            {"seq": 3, "kind": "note", "app": "BillingCenter", "actions": [],
             "notes": [{"time": 2, "text": "A quoted submission is not billed yet.", "source": "panel"}]}]}
        self.plan = pr.build_plan(session, CSSIDS)

    def test_step_with_only_a_note_is_kept(self):
        self.assertEqual([s["seq"] for s in self.plan["steps"]], [2, 3])
        note = step(self.plan, 3)
        self.assertEqual((note["actions"], note["checks"]), ([], []))
        self.assertEqual(note["notes"], ["A quoted submission is not billed yet."])

    def test_plan_notes_collect_step_notes_in_order(self):
        self.assertEqual(self.plan["notes"], [{"seq": 2, "text": "The account number is new on every run."},
                                              {"seq": 3, "text": "A quoted submission is not billed yet."}])

    def test_note_step_opens_no_application(self):
        self.assertEqual(self.plan["apps"], ["pc"])
        self.assertFalse(step(self.plan, 3)["appSwitch"])


class RemovedChecksTest(unittest.TestCase):
    def test_checks_removed_in_review_are_skipped(self):
        session = {"steps": [{"seq": 2, "app": "PolicyCenter", "screen": "SubmissionWizard", "title": "Offerings",
                              "actions": [
                                  {"type": "click", "widgetId": "SubmissionWizard-Next", "label": "Next"},
                                  {"type": "check", "widgetId": "SubmissionWizard-OfferingScreen-OfferingSelection",
                                   "kind": "select", "label": "Offering", "assert": "isSomethingNew", "removed": True},
                                  {"type": "check", "kind": "message", "assert": "noErrorMessages", "removed": True}]}]}
        plan = pr.build_plan(session, CSSIDS)
        self.assertEqual(step(plan, 2)["checks"], [])
        self.assertFalse(any(r["label"] == "Offering" or r["label"] == "" for r in plan["review"]))


DRIVERS = ("PolicyChangeWizard-LOBWizardStepGroup-LineWizardStepSet-PAVehiclesScreen-PAVehiclesPanelSet"
           "-VehiclesListDetailPanel-VehiclesDetailsCV-PersonalAuto_AssignDriversDV")
ADD_DRIVER = DRIVERS + "-DriverLV_tb-AddDriver"
VEHICLE_CARD = ("new PolicyChangeWizardPage(getContext()).getLineWizardStepSet().getPersonalVehiclesStep()"
                ".getVehiclesDetailsCV().getVehicleDetailCard()")


class ToolbarAndMenuTest(unittest.TestCase):
    def test_bracketed_call_is_renamed(self):
        self.assertEqual(pr.unbracket("new P(getContext()).getCard().get[DriverLV_tb]AddDriver()"),
                         ("new P(getContext()).getCard().getAddDriver()", True))
        self.assertEqual(pr.unbracket("new P(getContext()).get[DriverLV_tb]DriverTable().getFirstRow().select()"),
                         ("new P(getContext()).getDriverTable().getFirstRow().select()", True))
        self.assertEqual(pr.unbracket("new P(getContext()).getAdd()"), ("new P(getContext()).getAdd()", False))

    def test_cssids_getter_with_bracketed_segment_is_valid_java(self):
        result = pr.resolve(CSSIDS, "pc", {"widgetId": ADD_DRIVER, "kind": "ToolbarButtonWidget"})
        self.assertEqual(result["getter"], f'{VEHICLE_CARD}.getAddDriver().withCssId("{ADD_DRIVER}")')
        self.assertEqual(result["warning"], pr.PINNED)

    def test_key_matches_the_recorded_id(self):
        self.assertTrue(pr.key_matches("P-LV-[ROW]-Name", "P-LV-3-Name", takes_index=False))
        self.assertTrue(pr.key_matches("P-It-#-Limit", "P-It-2-Limit", takes_index=True))
        self.assertFalse(pr.key_matches("P-It-#-Limit", "P-It-2-Limit", takes_index=False))
        self.assertFalse(pr.key_matches("P-[VehiclesLV_tb]-Sub", "P-VehiclesListDetailPanel_tb-Sub", takes_index=False))
        self.assertFalse(pr.key_matches("P-Sub", "P-X_tb-Sub", takes_index=False))

    def test_toolbar_segment_dropped_from_the_key_is_pinned(self):
        live = ("PolicyChangeWizard-LOBWizardStepGroup-LineWizardStepSet-PAVehiclesScreen-PAVehiclesPanelSet"
                "-VehiclesListDetailPanel_tb-SubstituteVeh_Ext")
        result = pr.resolve(CSSIDS, "pc", {"widgetId": live, "kind": "ToolbarButtonWidget"})
        self.assertEqual(result["rule"], "toolbar")
        self.assertTrue(result["getter"].endswith(f'.getSubstituteVeh_Ext().withCssId("{live}")'))

    def test_iterator_the_getter_does_not_fill_is_pinned(self):
        live = "PolicyChangeWizard-ViewQuoteScreen-RatingCumulDetailsPanelSet-0-OverrideRating"
        result = pr.resolve(CSSIDS, "pc", {"widgetId": live, "kind": "LinkWidget"})
        self.assertEqual(result["getter"], "new PolicyChangeWizardPage(getContext()).getViewQuoteStep()"
                                           f'.getRatingCumulDetails().getOverrideRating().withCssId("{live}")')
        self.assertEqual(result["warning"], pr.PINNED)

    def test_partial_match_is_pinned(self):
        result = pr.resolve(CSSIDS, "pc", {"widgetId": "PolicyChangeWizard-ViewQuoteScreen", "kind": "div"})
        self.assertEqual(result["resolution"], "partial")
        for getter in result.get("candidates", [result["getter"]]):
            self.assertTrue(getter.endswith('.withCssId("PolicyChangeWizard-ViewQuoteScreen")'), getter)

    def test_exact_key_and_rows_are_not_pinned(self):
        self.assertNotIn("withCssId", pr.resolve(CSSIDS, "pc", {"widgetId": "Login-LoginScreen-LoginDV-username"})["getter"])
        row = pr.resolve(CSSIDS, "pc", {"widgetId": "OrganizationSearchPopup-OrganizationSearchPopupScreen"
                                                    "-OrganizationSearchResultsLV-0-ContactCity"})
        self.assertNotIn("withCssId", row["getter"])

    def test_menu_item_is_picked_by_label_on_its_button(self):
        result = pr.resolve(CSSIDS, "pc", {"widgetId": ADD_DRIVER + "-AddNewPerson", "kind": "MenuItemWidget",
                                           "text": "New Person"})
        self.assertEqual((result["resolution"], result["rule"]), ("rule", "menuItem"))
        self.assertEqual(result["getter"], f'{VEHICLE_CARD}.getAddDriver().withCssId("{ADD_DRIVER}").get("New Person")')

    def test_menu_item_without_a_known_button_stays_raw(self):
        result = pr.resolve(CSSIDS, "pc", {"widgetId": "AccountFile-AccountFileMenuActions-X-NewSubmission",
                                           "kind": "MenuItemWidget", "text": "New Submission"})
        self.assertEqual(result["rule"], "raw")

    def plan(self, actions):
        return pr.build_plan({"steps": [{"seq": 4, "app": "PolicyCenter", "title": "Vehicles", "actions": actions}]},
                             CSSIDS)

    def test_opener_is_dropped_when_the_item_opens_its_menu(self):
        plan = self.plan([{"type": "click", "widgetId": ADD_DRIVER, "kind": "ToolbarButtonWidget", "text": "Add"},
                          {"type": "click", "widgetId": ADD_DRIVER + "-AddNewPerson", "kind": "MenuItemWidget",
                           "text": "New Person"}])
        actions = step(plan, 4)["actions"]
        self.assertEqual([a["widgetId"] for a in actions], [ADD_DRIVER + "-AddNewPerson"])
        self.assertEqual(actions[0]["menuOpener"], "Add")

    def test_opener_stays_raw_when_the_item_is_raw(self):
        plan = self.plan([{"type": "click", "widgetId": "SubmissionWizard-OfferingScreen", "kind": "MenuActionsWidget",
                           "text": "Actions"},
                          {"type": "click", "widgetId": "SubmissionWizard-OfferingScreen-X-Y", "kind": "MenuItemWidget",
                           "text": "Y"}])
        opener, menu_item = step(plan, 4)["actions"]
        self.assertEqual(opener["getter"], 'WidgetMenuItem.get("SubmissionWizard-OfferingScreen", getContext())')
        self.assertNotIn("candidates", opener)
        self.assertEqual(menu_item["rule"], "raw")


class LabelsAndDataTest(unittest.TestCase):
    def translate(self, **action):
        return pr.translate(CSSIDS, "pc", action)

    def test_input_name_is_not_a_label(self):
        cell = DRIVERS + "-DriverLV-1-Rated_IC"
        self.assertEqual(pr.item_label({"widgetId": cell, "name": cell, "column": "Rated_IC"}), "Rated")
        self.assertEqual(pr.item_label({"widgetId": cell, "name": cell + "_checkbox"}), "Rated_IC")
        self.assertEqual(pr.item_label({"widgetId": cell, "label": "Premium applied", "name": cell}), "Premium applied")

    def test_cell_label_comes_from_the_column_header_in_the_dom(self):
        cell = DRIVERS + "-DriverLV-1-Rated_IC"
        dom = (f'<div id="{DRIVERS}-DriverLV-RatedHeader"><div class="gw-label"> Premium\n applied </div>'
               f'<span></span></div><input id="{cell}">')
        actions = pr.with_headers([{"type": "change", "widgetId": cell, "value": True}], dom)
        self.assertEqual(actions[0]["label"], "Premium applied")

    def test_pick_by_position_depends_on_data(self):
        item = self.translate(type="click", widgetId="NewDriverPopup-ContactsLV-0-UnassignedDriver", kind="LinkWidget")
        self.assertTrue(item["dependsOnData"])
        self.assertIn("picks entry 0", item["warning"])

    def test_typed_date_is_questioned(self):
        session = {"steps": [{"seq": 3, "app": "PolicyCenter", "title": "Driver", "actions": [
            {"type": "change", "widgetId": "NewDriverPopup-DateOfBirth", "kind": "text", "label": "Date of Birth",
             "value": "05/04/1980"}],
            "requests": [{"fields": [{"name": "PolicyChangeWizard-EffDate", "value": "01/01/2028"}]}]}]}
        typed = pr.build_plan(session, CSSIDS)["steps"][0]["actions"][0]
        self.assertTrue(typed["typedDate"])
        self.assertEqual(typed["postedDates"], {"PolicyChangeWizard-EffDate": "01/01/2028"})
        self.assertIn("date typed", typed["warning"])

    def test_identity_fields_get_a_generator(self):
        licence = self.translate(type="change", widgetId="X-LicenseNumber", kind="text", label="License #",
                                 value="2569874")
        self.assertEqual(licence["uniqueSuggested"],
                         {"expr": 'Utilities.DataGenerator.getGenerator().numerify("#######")', "recorded": "2569874"})
        vin = self.translate(type="change", widgetId="X-Vin", kind="text", label="VIN", value="1HGCM82633A004352")
        self.assertEqual(vin["uniqueSuggested"]["expr"], "Utilities.DataGenerator.getGenerator().vehicle().vin()")
        self.assertIsNone(pr.identity_value("License State", "CA"))
        marked = self.translate(type="change", widgetId="X-FirstName", kind="text", label="First name", value="Ann",
                                unique={"rule": "firstName"})
        self.assertNotIn("uniqueSuggested", marked)


class RetriesTest(unittest.TestCase):
    def test_value_corrected_after_next(self):
        session = {"steps": [
            {"seq": 2, "app": "PolicyCenter", "title": "Driver", "actions": [
                {"type": "change", "widgetId": "X-Licence", "kind": "text", "label": "Licence", "value": "2569874"},
                {"type": "click", "widgetId": "PolicyChangeWizard-Next", "kind": "WizardButtonWidget", "label": "Next"}]},
            {"seq": 3, "app": "PolicyCenter", "title": "Driver", "actions": [
                {"type": "change", "widgetId": "X-Licence", "kind": "text", "label": "Licence", "value": "256987"}]}]}
        plan = pr.build_plan(session, CSSIDS)
        self.assertEqual(plan["retries"], [{"kind": "corrected", "label": "Licence", "widgetId": "X-Licence",
                                            "seq": 2, "fixedSeq": 3, "from": "2569874", "to": "256987"}])
        self.assertEqual(step(plan, 3)["actions"][0]["corrects"], {"seq": 2, "value": "2569874"})

    def test_validation_fix_loop(self):
        click = lambda seq, label: {"type": "click", "widgetId": f"PolicyChangeWizard-{label.replace(' ', '')}",
                                    "kind": "ToolbarButtonWidget", "text": label}
        session = {"steps": [
            {"seq": 5, "app": "PolicyCenter", "title": "Policy Review", "actions": [click(5, "Quote")]},
            {"seq": 6, "app": "PolicyCenter", "title": "Quote", "actions": [click(6, "Issue Policy")],
             "messages": [{"text": "MVR Status is required", "level": "error"}]},
            {"seq": 7, "app": "PolicyCenter", "title": "Quote", "actions": [click(7, "Clear"),
                                                                            click(7, "Edit Policy Transaction")]},
            {"seq": 8, "app": "PolicyCenter", "title": "Drivers", "actions": [
                {"type": "change", "widgetId": "X-MVRStatus", "kind": "select", "label": "MVR Status",
                 "value": "Ordered"}, click(8, "Quote")]},
            {"seq": 9, "app": "PolicyCenter", "title": "Quote", "actions": [click(9, "Issue Policy")]}]}
        loops = [r for r in pr.build_plan(session, CSSIDS)["retries"] if r["kind"] == "validationLoop"]
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0], {"kind": "validationLoop", "editSeq": 7, "edit": "Clear → Edit Policy Transaction",
                                    "errorSeq": 6,
                                    "errors": ["MVR Status is required"],
                                    "fixes": [{"seq": 8, "label": "MVR Status", "value": "Ordered"}],
                                    "resumeSeq": 8, "firstQuoteSeq": 5})


UW_APPROVE = "UWBlockProgressIssuesPopup-UWBlockProgressIssuesScreen-RiskEvaluationPanelSet-1-UWIssueRowSet-SpecialApprove"
PROJECT = {"screenHelpers": {"value": {
    "titles": {"Risk Approval Details": ["ApproveUWIssuesAndIssuePolicy.clearUWIssues"]},
    "pages": {"UWBlockProgressIssuesPopup": ["AbstractPolicyChange.issueStep"]}}}}


def click(seq_label, widget_id=None, kind="ToolbarButtonWidget"):
    return {"type": "click", "widgetId": widget_id or f"PolicyChangeWizard-{seq_label.replace(' ', '')}",
            "kind": kind, "text": seq_label}


class BlockersAndRefusalsTest(unittest.TestCase):
    def test_uw_issue_row_is_a_blocker_not_account_data(self):
        item = pr.translate(CSSIDS, "pc", {"type": "click", "widgetId": UW_APPROVE, "kind": "button", "text": "Special Approve"})
        self.assertTrue(item["blocker"])
        self.assertNotIn("dependsOnData", item)

    def test_blocker_screen_is_matched_to_helpers_by_page(self):
        session = {"steps": [
            {"seq": 18, "app": "PolicyCenter", "screen": "PolicyChangeWizard", "title": "Quote",
             "actions": [click("Issue Policy")]},
            {"seq": 19, "app": "PolicyCenter", "screen": "UWBlockProgressIssuesPopup",
             "title": "Issues that block Issuance",
             "actions": [click("Special Approve", UW_APPROVE, "button")]}]}
        plan = pr.build_plan(session, CSSIDS, project=PROJECT)
        blocker, = plan["blockers"]
        self.assertEqual((blocker["seq"], blocker["items"]), (19, ["Special Approve"]))
        self.assertEqual(blocker["helpers"], [{"method": "AbstractPolicyChange.issueStep",
                                               "matched": "page UWBlockProgressIssuesPopup"}])
        self.assertEqual(step(plan, 19)["pages"], ["UWBlockProgressIssuesPopup"])
        self.assertNotIn("helpers", step(pr.build_plan(session, CSSIDS), 19))  # no project.json: no lookup

    def test_helper_matched_by_title_and_blocker_by_message(self):
        session = {"steps": [{"seq": 3, "app": "PolicyCenter", "title": "Risk Approval Details: 123",
                              "actions": [click("Quote")],
                              "messages": [{"text": "Policy placed in the facility (RSP) pool", "level": "warning"}]}]}
        blocker, = pr.build_plan(session, CSSIDS, project=PROJECT)["blockers"]
        self.assertEqual(blocker["messages"], ["Policy placed in the facility (RSP) pool"])
        self.assertEqual(blocker["helpers"][0]["method"], "ApproveUWIssuesAndIssuePolicy.clearUWIssues")

    def test_refused_next_then_fix_then_next_again(self):
        next_button = click("Next", "PolicyChangeWizard-Next", "WizardButtonWidget")
        ownership = {"type": "change", "widgetId": "X-Ownership", "kind": "select", "label": "Ownership", "value": "Owned"}
        session = {"steps": [
            {"seq": 13, "app": "PolicyCenter", "title": "Vehicles", "actions": [click("Edit")]},
            {"seq": 14, "app": "PolicyCenter", "title": "Vehicles", "actions": [next_button],
             "messages": [{"text": "Ownership : Missing required field", "level": "error"}]},
            {"seq": 15, "app": "PolicyCenter", "title": "Drivers", "actions": [ownership, dict(next_button)]}]}
        refused = [r for r in pr.build_plan(session, CSSIDS)["retries"] if r["kind"] == "refused"]
        self.assertEqual(refused, [{"kind": "refused", "seq": 14, "action": "Next", "title": "Vehicles",
                                    "errors": ["Ownership : Missing required field"],
                                    "fixes": [{"seq": 15, "label": "Ownership", "value": "Owned"}],
                                    "between": [], "retrySeq": 15}])

    def test_issue_clicked_twice(self):
        issue = click("Issue Policy")
        session = {"steps": [
            {"seq": 17, "app": "PolicyCenter", "title": "Quote", "actions": [click("Quote")]},
            {"seq": 18, "app": "PolicyCenter", "title": "Quote", "actions": [issue]},
            {"seq": 19, "app": "PolicyCenter", "title": "Policy Change Bound", "actions": [dict(issue)]}]}
        refused, = [r for r in pr.build_plan(session, CSSIDS)["retries"] if r["kind"] == "refused"]
        self.assertEqual((refused["seq"], refused["retrySeq"], refused["fixes"]), (18, 19, []))

    def test_row_filters_from_recorded_values_depend_on_data(self):
        item = pr.translate(CSSIDS, "pc", {
            "type": "click", "widgetId": "OrganizationSearchPopup-OrganizationSearchPopupScreen"
                                         "-OrganizationSearchResultsLV-0-_Select", "kind": "SelectorCellValueWidget",
            "rowKey": [{"header": "Vehicle #", "text": "1"}, {"header": "Close Date", "text": "10/19/2026"}]})
        self.assertTrue(item["dependsOnData"])
        self.assertIn("Vehicle # = 1, Close Date = 10/19/2026", item["warning"])
        self.assertIn("Close Date = 10/19/2026 is a date literal", item["warning"])

    def test_debug_tooltip_is_not_a_label(self):
        crumb = {"widgetId": "RatingOverridePopup-__crumb__",
                 "label": "See PolicyChangeWizard.pcf StackopenForEditInit: PolicyChangeWizard"}
        self.assertEqual(pr.item_label(crumb), "Return to previous page")
        self.assertEqual(pr.item_label({"widgetId": "P-Override", "label": "See P.pcf", "text": "Override"}), "Override")


VEHICLE_DV = DRIVERS.replace("PersonalAuto_AssignDriversDV", "PersonalAuto_VehicleDV")
GARAGE = VEHICLE_DV + "-PAGarageLocationInput"
OVERRIDE = VEHICLE_DV + "-OverrideddressValidation_IC"
VEHICLES_SCREEN = "PolicyChangeWizard-LOBWizardStepGroup-LineWizardStepSet-PAVehiclesScreen"
QUOTE = VEHICLES_SCREEN + "-JobWizardToolbarButtonSet-QuoteTypeToolbarButtonSet-Quote"
ISSUE = "PolicyChangeWizard-PolicyChangeWizard_QuoteScreen-JobWizardToolbarButtonSet-BindPolicyChange"
STAT = VEHICLE_DV + "-StatTerritoryCode"
RATING = VEHICLE_DV + "-RatingTerritoryCodesLV-0-Code"


def value_widget(widget_id, label, inner):
    return (f'<div id="{widget_id}_Input" class="gw-InputWidget"><div class="gw-label">{label}</div>'
            f'<div class="gw-value"><div id="{widget_id}" class="gw-TextValueWidget gw-ValueWidget gw-readonly">'
            f'<div class="gw-vw--value">{inner}</div><div class="gw-vw--children"><span>Edit</span></div>'
            f'</div></div></div>')


class GarageLocationRunTest(unittest.TestCase):
    """Issues #30 and #31: a policy-change recording that changes the garage location."""

    def plan(self, steps, files=None, project=None):
        return pr.build_plan({"steps": steps}, CSSIDS, (files or {}).get, project)

    def test_picker_menu_icon_and_item_are_one_menu_item(self):
        plan = self.plan([{"seq": 12, "app": "PolicyCenter", "title": "Vehicles", "actions": [
            {"type": "click", "widgetId": GARAGE + "MenuIcon", "kind": "MenuIconWidget", "text": ""},
            {"type": "click", "widgetId": GARAGE + "-NewGarageLocation", "kind": "PickerMenuItemWidget",
             "text": "New Location"}]}])
        item, = step(plan, 12)["actions"]
        self.assertEqual((item["rule"], item["getter"], item["java"]),
                         ("menuItem", f'WidgetMenuItem.get("{GARAGE}MenuIcon", getContext()).get("New Location")',
                          ".click()"))
        self.assertIn("menuOpener", item)
        self.assertIn("com.ankrpt.centertest.guidewire.widget.WidgetMenuItem", plan["imports"])
        self.assertFalse(any(r["widgetId"].startswith(GARAGE) for r in plan["review"] if r["rule"] == "raw"))

    def test_picker_item_in_the_next_step_still_folds_the_icon(self):
        plan = self.plan([
            {"seq": 12, "app": "PolicyCenter", "title": "Vehicles", "actions": [
                {"type": "click", "widgetId": GARAGE + "MenuIcon", "kind": "MenuIconWidget"}]},
            {"seq": 13, "app": "PolicyCenter", "title": "Vehicles", "actions": [
                {"type": "click", "widgetId": GARAGE + "-NewGarageLocation", "kind": "PickerMenuItemWidget",
                 "text": "New Location"}]}])
        self.assertEqual([s["seq"] for s in plan["steps"]], [13])  # nothing left at seq 12
        self.assertEqual(step(plan, 13)["actions"][0]["rule"], "menuItem")

    def test_radio_option_suffix_is_dropped_for_the_getter(self):
        plan = self.plan([{"seq": 18, "app": "PolicyCenter", "title": "Vehicles", "actions": [
            {"type": "change", "widgetId": OVERRIDE + "_0", "kind": "input", "inputType": "radio",
             "name": OVERRIDE, "value": "true", "display": "Yes"}]}])
        item, = step(plan, 18)["actions"]
        self.assertEqual((item["widgetId"], item["resolution"], item["radioOption"]), (OVERRIDE, "resolved", OVERRIDE + "_0"))
        self.assertTrue(item["getter"].endswith(".getOverrideddressValidation_IC()"))
        self.assertEqual(item["java"], '.set("true")')

    def test_raw_radio_is_a_radio_input(self):
        boolean = pr.translate(CSSIDS, "pc", {"type": "change", "widgetId": "X-Y-Flag_0", "inputType": "radio",
                                              "kind": "input", "value": "false"})
        self.assertEqual((boolean["widget"], boolean["getter"]),
                         ("WidgetBooleanRadioInput", 'WidgetBooleanRadioInput.get("X-Y-Flag", getContext())'))
        ranged = pr.translate(CSSIDS, "pc", {"type": "change", "widgetId": "X-Y-Kind_1", "inputType": "radio",
                                             "kind": "input", "value": "owned", "display": "Owned"})
        self.assertEqual((ranged["widget"], ranged["java"]), ("WidgetRangeRadioInput", '.set("Owned")'))

    def test_wizard_toolbar_quote_and_issue(self):
        quote = pr.resolve(CSSIDS, "pc", {"widgetId": QUOTE, "kind": "ToolbarButtonWidget", "text": "Quote"})
        self.assertEqual((quote["rule"], quote["getter"], quote["wizardAction"]),
                         ("wizardButton", "new PolicyChangeWizardPage(getContext()).getWizardButtons().getQuote()", "quote"))
        issue = pr.resolve(CSSIDS, "pc", {"widgetId": ISSUE, "kind": "ToolbarButtonWidget", "text": "Issue Policy"})
        self.assertEqual((issue["getter"], issue["wizardAction"]),
                         ("new PolicyChangeWizardPage(getContext()).getWizardButtons().getIssuePolicy()", "issue"))
        unknown = pr.resolve(CSSIDS, "pc", {"widgetId": ISSUE, "kind": "ToolbarButtonWidget", "text": "Odd Button"})
        self.assertNotEqual(unknown.get("rule"), "wizardButton")

    def test_quote_points_to_the_base_method(self):
        project = {"transactionBases": {"value": [
            {"class": "AbstractPolicyChange", "wizardFields": ["PolicyChangeWizardPage wizardPage"],
             "wizardActions": {"quote": ["quoteStep"], "issue": ["issueStep"]}},
            {"class": "AbstractSubmission", "wizardFields": ["SubmissionWizardPage wizardPage"],
             "wizardActions": {"quote": ["quote"]}}]}}
        plan = self.plan([{"seq": 9, "app": "PolicyCenter", "title": "Quote", "actions": [
            {"type": "click", "widgetId": QUOTE, "kind": "ToolbarButtonWidget", "text": "Quote"}]}], project=project)
        item = step(plan, 9)["actions"][0]
        self.assertEqual(item["baseMethods"], ["AbstractPolicyChange.quoteStep"])
        self.assertIn("AbstractPolicyChange.quoteStep", next(r["reason"] for r in plan["review"] if r["seq"] == 9))

    def test_calendar_icon_in_the_step_before_its_date_is_dropped(self):
        plan = self.plan([
            {"seq": 3, "app": "PolicyCenter", "title": "Start Policy Change", "actions": [
                {"type": "click", "widgetId": EFFECTIVE + "_dateIcon", "kind": ""}]},
            {"seq": 4, "app": "PolicyCenter", "title": "Start Policy Change", "actions": [
                {"type": "click", "widgetId": EFFECTIVE, "kind": "date", "label": "Effective Date"}],
             "requests": [{"fields": [{"name": EFFECTIVE, "value": "10/20/2026"}]}]}])
        self.assertEqual([s["seq"] for s in plan["steps"]], [4])  # nothing left at seq 3
        date, = step(plan, 4)["actions"]
        self.assertEqual((date["java"], date["source"]), ('.set("10/20/2026")', "request"))
        self.assertFalse(any(r["widgetId"].endswith("_dateIcon") for r in plan["review"]))
        self.assertIn("2 calendar clicks", next(r["reason"] for r in plan["review"] if r["widgetId"] == EFFECTIVE))

    def test_dom_values(self):
        reader = pr.FieldValues()
        reader.feed(value_widget(STAT, "Stat. Territory", '<div class="gw-value-readonly-wrapper">105</div>')
                    + value_widget(GARAGE, "Garaged At", '<select name="g"><option value="1">1: Edmonton</option>'
                                                         '<option value="2" selected>2: Fort McMurray</option></select>')
                    + value_widget(OVERRIDE, "Override", '<div class="gw-RangeRadioValueWidget--input-group">'
                                   '<input type="radio" value="true" aria-label="Yes" checked><span>Yes</span>'
                                   '<input type="radio" value="false" aria-label="No"><span>No</span></div>'))
        self.assertEqual(reader.values(), {STAT: "105", GARAGE: "2: Fort McMurray", OVERRIDE: "Yes"})
        self.assertEqual(reader.labels[STAT], "Stat. Territory")

    def test_note_that_asks_for_a_check_gets_the_recorded_values(self):
        files = {"dom/0019.html": value_widget(STAT, "Stat. Territory", "105") + value_widget(RATING, "Code", "11")}
        plan = self.plan([
            {"seq": 8, "app": "PolicyCenter", "title": "Vehicles", "actions": [click("Edit")],
             "requests": [{"fields": [{"name": STAT, "value": "102"}, {"name": RATING, "value": "5"},
                                      {"name": VEHICLE_DV + "-PostalCode", "value": "T5J"}]}]},
            {"seq": 19, "app": "PolicyCenter", "title": "Policy Change Bound", "dom": "dom/0019.html",
             "actions": [click("Issue Policy")],
             "notes": [{"text": "Confirm address and rating territory codes are updated"}]}], files)
        note, = plan["noteChecks"]
        self.assertEqual(note["seq"], 19)
        stat = next(f for f in note["fields"] if f["widgetId"] == STAT)
        self.assertEqual((stat["values"], stat["changed"], stat["java"], stat["label"]),
                         ([{"seq": 8, "value": "102"}, {"seq": 19, "value": "105"}], True, '.assertEquals("105")',
                          "Stat. Territory"))
        self.assertEqual(note["fields"][0]["widgetId"], RATING)  # rating + territor + code: the best match
        self.assertNotIn(VEHICLE_DV + "-PostalCode", [f["widgetId"] for f in note["fields"]])  # only "code"
        self.assertTrue(plan["notes"][0]["asksCheck"])

    def test_conditional_note_is_flagged(self):
        plan = self.plan([{"seq": 18, "app": "PolicyCenter", "title": "Vehicles", "actions": [], "notes": [
            {"text": "If there's an error in validating address, override and continue"}]}])
        self.assertEqual(plan["notes"], [{"seq": 18, "text": "If there's an error in validating address, override "
                                                             "and continue", "conditional": True}])
        self.assertEqual(plan["noteChecks"], [])

    def test_visibility_check_on_a_field_with_a_value_suggests_a_value_check(self):
        files = {"dom/0019.html": value_widget(GARAGE, "Garaged At", "2: 10 Main St, Fort McMurray, AB")}
        plan = self.plan([
            {"seq": 15, "app": "PolicyCenter", "title": "New Location", "actions": [
                {"type": "change", "widgetId": "NewLocationPopup-AddressLine1", "kind": "text",
                 "label": "Address 1", "value": "10 Main St"}]},
            {"seq": 19, "app": "PolicyCenter", "title": "Vehicles", "dom": "dom/0019.html", "actions": [
                click("OK", "NewLocationPopup-Update", "ToolbarButtonWidget"),
                {"type": "check", "widgetId": GARAGE, "kind": "select", "label": "Garaged At", "assert": "isVisible"}]}],
            files)
        check, = step(plan, 19)["checks"]
        self.assertEqual(check["java"], ".assertVisible(true)")
        self.assertEqual(check["valueSuggested"], {"java": '.assertContains("10 Main St")',
                                                   "shown": "2: 10 Main St, Fort McMurray, AB"})
        self.assertIn("always passes", next(r["reason"] for r in plan["review"] if r["widgetId"] == GARAGE))
        self.assertNotIn("recordedCheck", check)

    def test_next_clicks_that_change_nothing_are_navigation(self):
        next_button = click("Next", "PolicyChangeWizard-Next", "WizardButtonWidget")
        plan = self.plan([
            {"seq": 5, "app": "PolicyCenter", "title": "Policy Info", "actions": [
                {"type": "change", "widgetId": EFFECTIVE, "kind": "date", "value": "10/20/2026"}, dict(next_button)]},
            {"seq": 6, "app": "PolicyCenter", "title": "Drivers", "actions": [dict(next_button)]},
            {"seq": 7, "app": "PolicyCenter", "title": "Vehicles", "actions": [dict(next_button)]},
            {"seq": 8, "app": "PolicyCenter", "title": "Vehicles", "actions": [click("Edit")]}])
        self.assertEqual(plan["navigation"], [{"seqs": [6, 7], "clicks": 2, "from": "Policy Info", "to": "Vehicles"}])
        self.assertTrue(step(plan, 7)["actions"][0]["navigationOnly"])
        self.assertNotIn("navigationOnly", step(plan, 5)["actions"][1])


class SnapshotReaderTest(unittest.TestCase):
    def test_reads_dom_from_folder_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "rec")
            os.makedirs(os.path.join(folder, "dom"))
            with open(os.path.join(folder, "session.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            with open(os.path.join(folder, "dom", "0001.html"), "w", encoding="utf-8") as f:
                f.write("<p>x</p>")
            self.assertEqual(pr.file_reader(folder)("dom/0001.html"), "<p>x</p>")
            self.assertIsNone(pr.file_reader(folder)("../session.json"))
            path = os.path.join(tmp, "rec.zip")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("rec/session.json", "{}")
                z.writestr("rec/dom/0001.html", "<p>z</p>")
            self.assertEqual(pr.file_reader(path)("dom/0001.html"), "<p>z</p>")
            self.assertIsNone(pr.file_reader(path)("dom/0002.html"))


class CommandLineTest(unittest.TestCase):
    SCRIPT = os.path.join(SCRIPTS, "parse_recording.py")

    def run_script(self, *args):
        return subprocess.run([sys.executable, self.SCRIPT, *args], capture_output=True, text=True)

    def test_missing_cssids_dir(self):
        result = self.run_script(os.path.join(RECORDINGS, "real-180418"), "--cssids", "/no/such/dir")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cssids directory not found", result.stderr)

    def test_bad_recording(self):
        result = self.run_script("/no/such/recording", "--cssids", CSSIDS)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a recording", result.stderr)

    def test_project_json_adds_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, out = os.path.join(tmp, "project.json"), os.path.join(tmp, "plan.json")
            with open(project, "w", encoding="utf-8") as f:
                json.dump({"screenHelpers": {"value": {"titles": {"Account Summary": ["SearchForAccountPC.find"]}}}}, f)
            result = self.run_script(os.path.join(RECORDINGS, "real-180418"), "--cssids", CSSIDS,
                                     "--project", project, "--out", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(out, encoding="utf-8") as f:
                summary = step(json.load(f), 3)
            self.assertEqual(summary["helpers"], [{"method": "SearchForAccountPC.find", "matched": "title 'Account Summary'"}])

    def test_writes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan.json")
            result = self.run_script(os.path.join(RECORDINGS, "real-180418"), "--cssids", CSSIDS, "--out", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["test"]["testId"], "tc123")


if __name__ == "__main__":
    unittest.main()
