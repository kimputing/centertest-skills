import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import coverage  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")

BASE = """package com.x.steps.shared;
import com.x.generated.pages.pc.CreateAccountPage;
public abstract class AbstractNewAccount extends BaseScenarioPC {
  protected CreateAccountPage createAccountPage;
}
"""
PERSON = """package com.x.steps.shared;
public class CreatePersonAccount extends AbstractNewAccount {
  public void execute() {
    var addressContainer = createAccountPage.getGlobalAddressContainer();
    addressContainer.getCity().set(address.getCity());
    createAccountPage.getAddressType().set("Billing");
    newAccountPage.getNewAccountButton().get("Person").click();  // NewAccountPage is a type here
  }
}
"""
GL = """package com.x.steps.gl;
import com.x.generated.pages.pc.SubmissionWizardPage;
public class CreateGLSubmission extends BaseScenarioPC {
  public void execute() {
    var wizardPage = new SubmissionWizardPage(getContext());
    CoverageRoutes.with(new CoverageUtil(getContext())).apply(data.getCoverageList());
    wizardPage.getPolicyInfoStep().getOrganizationType().set(data.getPolicyinfo().getOrganizationtype());
  }
}
"""
BOP = """package com.x.steps.bop;
import com.x.generated.pages.pc.SubmissionWizardPage;
public class CreateBOPSubmission extends BaseScenarioPC {
  public void execute() {
    var wizardPage = new SubmissionWizardPage(getContext());
    wizardPage.getOfferingStep().getOfferingSelection().set("Standard");
  }
}
"""
ORG = """package com.x.steps.shared;
public class PickOrganization extends BaseScenarioPC {
  public void execute() {
    var orgSearchPage = new OrganizationSearchPopup(getContext());
    orgSearchPage.getGlobalContactName().getName().set(organizationName);
  }
}
"""
GENERATED = """package com.x.generated.pages.pc;
public class CreateAccountPage { public Object getPhone() { return null; } }
"""


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def step(seq, *actions, login=False, title="Screen"):
    return {"seq": seq, "waitTitle": title, "login": login, "actions": list(actions)}


def getter_action(getter, label, kind="change", value="x", **extra):
    return dict({"type": kind, "label": label, "getter": getter, "resolution": "resolved", "value": value}, **extra)


class LastCall(unittest.TestCase):
    def test_final_call_of_the_statement(self):
        self.assertEqual(coverage.last_call('a.getCity().set(address.getCity());'), ("set", "address.getCity()"))
        self.assertEqual(coverage.last_call('t.getFirstRow().select().get_CHECKBOX().click();'),
                         ("click", ""))
        self.assertEqual(coverage.last_call('x.set("a(b)"); // note'), ("set", '"a(b)"'))
        self.assertIsNone(coverage.last_call("var c = page.getCity()"))

    def test_status_of_a_line(self):
        self.assertEqual(coverage._set_status('c.getCity().set(address.getCity());'), "data")
        self.assertEqual(coverage._set_status('c.getType().set("Billing");'), "hardcoded")
        self.assertEqual(coverage._set_status('c.getBox().set(true);'), "hardcoded")
        self.assertEqual(coverage._set_status('t.getFirstRow().select().get_CHECKBOX().click();'), "automated")


class ChainOf(unittest.TestCase):
    def test_page_and_getters_up_to_the_row(self):
        page, names = coverage.chain_of('new NewSubmissionPage(getContext()).getInstalledCard()'
                                        '.getProductSelectionTable().getFirstRow().with("a", "b").select()')
        self.assertEqual(page, "NewSubmissionPage")
        self.assertEqual(names, ["getInstalledCard", "getProductSelectionTable"])

    def test_keyed_get_is_dropped(self):
        self.assertEqual(coverage.chain_of('new AccountFile(getContext()).getAction().get("New")')[1],
                         ["getAction"])


class Classify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = self.tmp.name
        write(root, "src/main/java/com/x/steps/shared/AbstractNewAccount.java", BASE)
        write(root, "src/main/java/com/x/steps/shared/CreatePersonAccount.java", PERSON)
        write(root, "src/main/java/com/x/steps/gl/CreateGLSubmission.java", GL)
        write(root, "src/main/java/com/x/steps/bop/CreateBOPSubmission.java", BOP)
        write(root, "src/main/java/com/x/generated/pages/pc/CreateAccountPage.java", GENERATED)

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, *steps, only=None):
        return coverage.coverage({"steps": list(steps), "recording": {"id": "r1"}}, self.root, only)

    def test_inherited_page_and_data_driven_value(self):
        city = getter_action("new CreateAccountPage(getContext()).getGlobalAddressContainer().getCity()", "City")
        row = self.run_plan(step(1, city))["rows"][0]
        self.assertEqual(row["status"], "data")
        self.assertTrue(row["where"].endswith("CreatePersonAccount.java:5"), row["where"])

    def test_literal_value_is_hardcoded(self):
        kind = getter_action("new CreateAccountPage(getContext()).getAddressType()", "Address Type")
        self.assertEqual(self.run_plan(step(1, kind))["rows"][0]["status"], "hardcoded")

    def test_generated_code_does_not_count(self):
        phone = getter_action("new CreateAccountPage(getContext()).getPhone()", "Phone")
        self.assertEqual(self.run_plan(step(1, phone))["rows"][0]["status"], "missing")

    def test_a_page_the_file_does_not_know_does_not_count(self):
        other = getter_action("new ContactPage(getContext()).getGlobalAddressContainer().getCity()", "City")
        self.assertEqual(self.run_plan(step(1, other))["rows"][0]["status"], "missing")

    def test_entry_picked_by_label(self):
        person = getter_action("new NewAccountPage(getContext()).getNewAccount_Person()", "Person", kind="click")
        row = self.run_plan(step(1, person))["rows"][0]
        self.assertEqual((row["status"], row["why"]), ("automated", "picked by its label"))

    def test_only_limits_the_steps_searched(self):
        offering = getter_action("new SubmissionWizardPage(getContext()).getOfferingStep().getOfferingSelection()",
                                 "Offering Selection")
        self.assertEqual(self.run_plan(step(1, offering))["rows"][0]["status"], "hardcoded")
        self.assertEqual(self.run_plan(step(1, offering), only="/gl/|/shared/")["rows"][0]["status"], "missing")

    def test_coverage_without_a_data_row_is_partial(self):
        cov = {"type": "change", "label": "Occurrence Limit", "page": "SubmissionWizard", "getter": "coverageUtil",
               "rule": "coverage", "coverage": {"coverage": "General Liability", "covterm": "Occurrence Limit"}}
        row = self.run_plan(step(1, cov))["rows"][0]
        self.assertEqual(row["status"], "partial")
        self.assertIn("CreateGLSubmission.java", row["where"])

    def test_navigation_and_login_are_not_counted(self):
        result = self.run_plan(
            step(1, getter_action("new LoginPage(getContext()).getUsername()", "Username"), login=True),
            step(2, getter_action("new SubmissionWizardPage(getContext()).getWizardButtons().getNext()", "Next",
                                  kind="click", rule="wizardButton")),
            step(3, getter_action("new TabBar(getContext()).getAccountTab()", "Account", kind="click", rule="tabBar")))
        self.assertEqual(result["totals"]["skip"], 3)
        self.assertEqual(result["counted"], 0)
        self.assertIsNone(result["percent"])

    def test_percent_counts_partial_as_not_done(self):
        city = getter_action("new CreateAccountPage(getContext()).getGlobalAddressContainer().getCity()", "City")
        phone = getter_action("new CreateAccountPage(getContext()).getPhone()", "Phone")
        result = self.run_plan(step(1, city, phone))
        self.assertEqual((result["handled"], result["counted"], result["percent"]), (1, 2, 50))
        self.assertIn("Missing", coverage.render_html(result))


class EndToEnd(unittest.TestCase):
    def test_real_recording_against_a_small_project(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "src/main/java/com/x/steps/shared/AbstractNewAccount.java", BASE)
            write(root, "src/main/java/com/x/steps/shared/PickOrganization.java", ORG)
            out = os.path.join(root, "report.html")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = coverage.main([os.path.join(FIXTURES, "recordings", "real-174907"),
                                      "--cssids", os.path.join(FIXTURES, "cssids"), "--project", root,
                                      "--html", out])
            self.assertEqual(code, 0)
            self.assertIn("Recording coverage:", buf.getvalue())
            with open(out, encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn("PickOrganization.java:5", page)  # Organization Name, resolved from the fixture cssids

    def test_missing_directories_exit_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(coverage.main(["x", "--cssids", "/nonexistent", "--project", "/nonexistent"]), 2)


if __name__ == "__main__":
    unittest.main()
