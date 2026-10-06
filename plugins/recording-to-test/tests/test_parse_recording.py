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
                                           ".getLineWizardStepSetGLLineStep().getAdditionalCoveragesCard().getAdd()")

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
        self.assertIn("MessagesUtil.getErrorMessages(getContext())).isEmpty()",
                      pr.message_check_java({"assert": "noErrorMessages"}))

    def test_actions(self):
        self.assertEqual(pr.action_java({"type": "click"}), ".click()")
        self.assertEqual(pr.action_java({"type": "change", "value": "su"}), '.set("su")')
        self.assertEqual(pr.action_java({"type": "change", "value": "1000", "display": "1,000"}), '.set("1,000")')
        self.assertEqual(pr.action_java({"type": "change", "value": True}), ".set(true)")
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
        self.assertEqual(self.plan["notes"], ["before the first step"])
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
        self.assertEqual(reasons[(5, "")]["reason"], "unknown application")

    def test_soft_message_check_is_flagged(self):
        message = step(self.plan, 3)["checks"][3]
        self.assertEqual(message["java"], 'MessagesUtil.assertMessageContaining(getContext(), "Quote");')
        self.assertIn("no soft variant", message["warning"])

    def test_app_switch_links_check_to_unique_value(self):
        billing = step(self.plan, 4)
        self.assertEqual((billing["app"], billing["appSwitch"]), ("bc", True))
        self.assertEqual(billing["checks"][0]["uniqueFrom"], {"seq": 2, "label": "Name"})
        self.assertEqual(self.plan["apps"], ["pc", "bc"])


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

    def test_writes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan.json")
            result = self.run_script(os.path.join(RECORDINGS, "real-180418"), "--cssids", CSSIDS, "--out", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["test"]["testId"], "tc123")


if __name__ == "__main__":
    unittest.main()
