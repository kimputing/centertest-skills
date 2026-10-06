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
                         "new TabBar(getContext()).getNewAccount()")

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


if __name__ == "__main__":
    unittest.main()
