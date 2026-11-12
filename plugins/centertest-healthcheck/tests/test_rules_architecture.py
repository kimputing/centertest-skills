"""Rules 17001-17009 (Architecture) on a small project tree: each rule flags its BAD fixture and
leaves the GOOD one alone."""

import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

try:
    import javalang  # noqa: F401
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False


ABSTRACT_SUBMISSION = """package com.acme.reusable;

import com.acme.generated.pages.pc.SubmissionWizardPage;
import com.acme.generated.pages.pc.UWBlockPopup;
import com.ankrpt.centertest.runner.context.InvocationContext;

public abstract class AbstractSubmission extends BaseScenarioPC {

  protected SubmissionWizardPage wizardPage;
  protected Misc miscDDT;
  protected Object data;
  private String secret;
  protected static final String NAME = "x";

  protected AbstractSubmission(InvocationContext context) {
    super(context);
    wizardPage = new SubmissionWizardPage(getContext());
  }

  protected void formsStep() {
    wizardPage.getNext().click();
  }

  protected void quoteStep() {
    if (new UWBlockPopup(getContext()).isVisible())
      new UWBlockPopup(getContext()).getReturnToPreviousPage().click();
  }

  protected void openAgain() {
    new SubmissionWizardPage(getContext()).getNext().click();
  }

  protected void reset() {
    wizardPage = new SubmissionWizardPage(getContext());
  }

  protected void asOther(InvocationContext underwriter) {
    new SubmissionWizardPage(underwriter).getNext().click();
  }

  protected void popupOnce() {
    var popup = new UWBlockPopup(getContext());
    if (popup.isVisible()) popup.approve();
  }

  protected void issueAsUnderwriter() {
    var underwriter = getContext().getScenarioContext().getInvocationContext("underwriter").withUserIdentifier("UW");
    PC.loginToPC(underwriter).execute();
    PC.approveUWIssues(underwriter).execute();
  }

  protected void readOtherRole() {
    var producer = getContext().getScenarioContext().getInvocationContext("producer");
    Helper.getData(producer).setCustom("Key", "Value");
  }
}
"""

CREATE_SUBMISSION = """package com.acme.reusable;

import com.acme.generated.pages.pc.SubmissionWizardPage;
import com.ankrpt.centertest.runner.context.InvocationContext;

public class CreateSubmission extends AbstractSubmission {

  protected SubmissionWizardPage wizardPage;
  protected String secret;
  protected String data;
  protected static final String NAME = "y";

  public CreateSubmission(InvocationContext context) {
    super(context);
  }

  @Override
  public void execute() {
    formsStep();
  }

  @Override
  protected void formsStep() {
    super.formsStep();
  }

  @Override
  public void quoteStep() {
    super.quoteStep();
  }

  @Override
  protected void openAgain() {
    super.openAgain();
    log("again");
  }

  @Override
  protected void asOther(InvocationContext other) {
    super.asOther(getContext());
  }
}
"""

GENERAL_UTIL = """package com.acme.util;

import com.ankrpt.centertest.guidewire.widget.WidgetButton;
import com.ankrpt.centertest.runner.context.InvocationContext;

public class GeneralUtil {

  public static void saveDraft(InvocationContext context) {
    var button = WidgetButton.getByLabel("Save Draft", context);
    if (button.isVisible()) button.click();
  }

  public static String suffix(String name) {
    return name + "-1";
  }
}
"""

ASSERT_UTIL = """package com.acme.util;

import com.acme.reusable.CreateSubmission;
import com.acme.generated.pages.pc.SubmissionWizardPage;
import com.ankrpt.centertest.runner.context.InvocationContext;
import com.ankrpt.centertest.widget.AbstractWidget;

public class AssertUtil {

  public static void visible(AbstractWidget widget, boolean shouldBe) {
    widget.assertVisible(shouldBe, "should be visible");
  }

  public static void approve(InvocationContext context) {
    new CreateSubmission(context) {
      @Override
      public void execute() {
        new SubmissionWizardPage(getContext()).getNext().click();
      }
    }.execute();
  }
}
"""

PORTAL_PAGE = """package com.acme.pages.portal;

import com.ankrpt.centertest.guidewire.runtime.PortalPage;
import com.ankrpt.centertest.guidewire.widget.portal.PortalWidgetInput;
import com.ankrpt.centertest.runner.context.InvocationContext;

public class PortalLoginPage extends PortalPage {

  public PortalLoginPage(InvocationContext context) {
    super(context);
  }

  public PortalWidgetInput getUsername() {
    return PortalWidgetInput.getInputNg("$ctrl.username", getInvocationContext());
  }
}
"""

WIP_TEST = """package com.acme.tests;

import com.ankrpt.centertest.annotation.CenterTest;
import com.ankrpt.centertest.annotation.CenterTestCase;
import com.ankrpt.centertest.runner.context.InvocationContext;
import com.ankrpt.centertest.runner.context.ScenarioContext;
import com.acme.generated.pages.pc.SubmissionWizardPage;
import com.acme.reusable.CreateSubmission;
import com.acme.reusable.PC;

@CenterTest
public final class WipTest {

  private InvocationContext context;

  @CenterTestCase
  public void run(ScenarioContext scenarioContext) {
    context = scenarioContext.getInvocationContext("producer");
    PC.loginToPC(context).execute();
    new SubmissionWizardPage(context).getLEFT().getNavigate().getByLabel("Coverages").click();
    new BigOverride(context).execute();
  }

  protected void selectTab() {
    var lineStep = new SubmissionWizardPage(context).getLineStep();
    lineStep.getCoveragesTab().click();
  }

  private class BigOverride extends CreateSubmission {
    BigOverride(InvocationContext context) {
      super(context);
    }

    @Override
    protected void formsStep() {
      super.formsStep();
      new SubmissionWizardPage(getContext()).getFormsStep().getFormsTable().getFirstRow().select();
      wizardPage.getNext().click();
      wizardPage.getNext().click();
      wizardPage.getNext().click();
    }
  }
}
"""

GOOD_TEST = """package com.acme.tests;

import com.ankrpt.centertest.annotation.CenterTest;
import com.ankrpt.centertest.annotation.CenterTestCase;
import com.ankrpt.centertest.runner.context.InvocationContext;
import com.ankrpt.centertest.runner.context.ScenarioContext;
import com.acme.reusable.CreateSubmission;
import com.acme.reusable.PC;

@CenterTest
public final class GoodTest {

  @CenterTestCase
  public void run(ScenarioContext scenarioContext) {
    var producer = scenarioContext.getInvocationContext("producer");
    PC.loginToPC(producer).execute();
    new SmallOverride(producer).execute();
  }

  private class SmallOverride extends CreateSubmission {
    SmallOverride(InvocationContext context) {
      super(context);
    }
  }
}
"""

# 17008 / 17009: three submission tests on the same DC; Copy = Submission + one data line;
# Other runs a different step. All three copy the same driver-list line into a private helper.
DUP_TEMPLATE = """package com.acme.tests;

import com.ankrpt.centertest.annotation.CenterTest;
import com.ankrpt.centertest.annotation.CenterTestCase;
import com.ankrpt.centertest.datadriven.annotation.DataDriven;
import com.ankrpt.centertest.runner.context.ScenarioContext;
import com.acme.reusable.PC;

@CenterTest
public final class {name} {

  private enum RestartPoints {ACCOUNT}

  @CenterTestCase(testCaseId = "{name}")
  @DataDriven(datasource = "testdata/PA_SubmissionDC.xlsx")
  public void run(ScenarioContext scenarioContext) {
    var {var} = DDTHelper.getPA_SubmissionDC(scenarioContext);
{extra}    initialize(scenarioContext, {var}.getTestInfo().getCode(), {var});
    var producer = scenarioContext.getInvocationContext("producer");
    PC.loginToPC(producer).execute();
    if (scenarioContext.restart(RestartPoints.ACCOUNT)) {
      PC.createPersonAccount(producer, {var}.getPerson(), {var}.getAddress()).execute();
      scenarioContext.restartComplete(RestartPoints.ACCOUNT);
    } else {
      PC.searchForAccountPC(producer).execute();
    }
    PC.{step}(producer, {var}).execute();
  }

  private void initialize(ScenarioContext scenarioContext, String code, PA_SubmissionDC {var}) {
    if ({var}.getPerson() != null && !{var}.getVehicle().getDriverList().isEmpty()) {var}.getVehicle().getDriverList().get(0).withPerson({var}.getPerson());
    PersonNameUtil.process(scenarioContext, {var}.getPersonList(), code);
{helper_extra}  }
}
"""


def _dup(name, var="dataDC", extra="", step="createPersonalAutoSubmission", helper_extra=""):
    return (DUP_TEMPLATE.replace("{name}", name).replace("{var}", var).replace("{extra}", extra)
            .replace("{step}", step).replace("{helper_extra}", helper_extra))


SHARED_TWICE = "    {v}.getVehicle().withVin({v}.getDatacombination().getDataField(\"#vehicle.vin\").getValue());\n"

FILES = {
    "reusable/AbstractSubmission.java": ABSTRACT_SUBMISSION,
    "reusable/CreateSubmission.java": CREATE_SUBMISSION,
    "util/GeneralUtil.java": GENERAL_UTIL,
    "util/AssertUtil.java": ASSERT_UTIL,
    "pages/portal/PortalLoginPage.java": PORTAL_PAGE,
    "tests/WipTest.java": WIP_TEST,
    "tests/GoodTest.java": GOOD_TEST,
    "tests/PA_SubmissionTest.java": _dup("PA_SubmissionTest", helper_extra=SHARED_TWICE.format(v="dataDC")),
    "tests/TC_UI_003Test.java": _dup("TC_UI_003Test", var="data",
                                     extra="    data.getVehicle().withVin(\"1HGCM82633A004352\");\n",
                                     helper_extra=SHARED_TWICE.format(v="data")),
    "tests/PA_EditSubmissionTest.java": _dup("PA_EditSubmissionTest", step="editPersonalAutoSubmission"),
}


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class ArchitectureRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        cls.tmp = tempfile.mkdtemp()
        base = os.path.join(cls.tmp, "src", "main", "java", "com", "acme")
        for rel, text in FILES.items():
            path = os.path.join(base, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)
        files = parse_directory(cls.tmp, "src/main/java", [], [], True, None)
        cls.commits = {LOCAL_COMMIT: files}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_rule(self, fn, **thresholds):
        config = SimpleNamespace(repository_dir=self.tmp)
        if thresholds:
            config.get_threshold = lambda rid, default: thresholds.get(rid, default)
        result = fn(self.commits, config)
        self.assertIsNone(result.error)
        self.assertEqual(result.category, "Architecture")
        return result

    def test_17001_test_drives_widgets(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.test_drives_widgets).rows
        # run() and selectTab() of WipTest; the inner step override (BigOverride) is 17002's, GoodTest is clean
        self.assertEqual([(r[0], r[1]) for r in rows], [("WipTest", "run"), ("WipTest", "selectTab")])
        self.assertIn("new SubmissionWizardPage", rows[0][2])
        self.assertTrue(rows[0][4].endswith("tests/WipTest.java:20"), rows[0][4])
        self.assertIn("2 UI lines", rows[1][3])

    def test_17002_large_step_override(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.large_step_override_in_test, **{"17002": 10}).rows
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [("WipTest.BigOverride", "CreateSubmission", 14)])
        self.assertTrue(rows[0][4].endswith("tests/WipTest.java:29"), rows[0][4])
        # default threshold (40 lines): nothing in the fixture is that long
        self.assertEqual(self.run_rule(ra.large_step_override_in_test).rows, [])

    def test_17003_widget_access_outside_steps(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.widget_access_outside_steps).rows
        # GeneralUtil.saveDraft only: not the assertion helper that receives a widget, not the anonymous
        # step inside AssertUtil.approve, not the portal page object, not steps or tests
        self.assertEqual([(r[0], r[1]) for r in rows], [("GeneralUtil", "saveDraft")])
        self.assertIn("WidgetButton.getByLabel", rows[0][3])

    def test_17004_override_only_calls_super(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.override_only_calls_super).rows
        # formsStep only: quoteStep widens protected -> public, openAgain adds a line, asOther passes other args;
        # WipTest.BigOverride.formsStep does more than call super
        self.assertEqual([(r[0], r[1]) for r in rows], [("CreateSubmission", "formsStep")])

    def test_17005_field_redeclared(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.field_redeclared_in_subclass).rows
        # wizardPage (same type, visible in the parent); not secret (private in the parent), data (narrower
        # type), NAME (static)
        self.assertEqual([(r[0], r[1]) for r in rows], [("CreateSubmission", "wizardPage")])
        self.assertIn("AbstractSubmission", rows[0][3])
        self.assertTrue(rows[0][4].endswith("reusable/CreateSubmission.java:8"), rows[0][4])

    def test_17006_page_recreated(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.page_recreated_in_step).rows
        found = sorted((r[0], r[1]) for r in rows)
        # quoteStep builds the popup twice, openAgain ignores the wizardPage field, BigOverride (a step in a
        # test) does the same; reset() (assigns the field), asOther() (other context), popupOnce() are fine
        self.assertEqual(found, [("AbstractSubmission", "openAgain"), ("AbstractSubmission", "quoteStep"),
                                 ("WipTest.BigOverride", "formsStep")])
        quote = next(r for r in rows if r[1] == "quoteStep")
        self.assertIn("again in the same method", quote[3])
        self.assertTrue(quote[4].endswith("reusable/AbstractSubmission.java:26"), quote[4])

    def test_17007_step_logs_in_as_other_user(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.step_logs_in_as_other_user).rows
        # issueAsUnderwriter only: readOtherRole fetches a context but never logs in; tests are not steps
        self.assertEqual([(r[0], r[1]) for r in rows], [("AbstractSubmission", "issueAsUnderwriter")])
        self.assertIn('"underwriter"', rows[0][3])
        self.assertTrue(rows[0][4].endswith("reusable/AbstractSubmission.java:47"), rows[0][4])

    def test_17008_near_duplicate_tests(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.near_duplicate_tests).rows
        # TC_UI_003Test = PA_SubmissionTest + one data line (other variable name); PA_EditSubmissionTest runs a
        # different step, so it is a different flow
        self.assertEqual([(r[0], r[1]) for r in rows], [("PA_SubmissionTest", "TC_UI_003Test")])
        self.assertGreaterEqual(int(rows[0][2].rstrip("%")), 80)
        self.assertEqual(self.run_rule(ra.near_duplicate_tests, **{"17008": 100}).rows, [])

    def test_17009_same_helper_line(self):
        import rules.rule_architecture as ra
        rows = self.run_rule(ra.same_helper_line_in_many_tests).rows
        # the driver-list line is in all three tests (variable names differ); the withVin line only in two;
        # PersonNameUtil.process(...) is a single plain call (not worth a utility of its own)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("getDriverList().isEmpty()", rows[0][2])
        self.assertEqual(rows[0][3], 3)
        self.assertEqual(rows[0][0], "PA_EditSubmissionTest")
        two = self.run_rule(ra.same_helper_line_in_many_tests, **{"17009": 2}).rows
        self.assertEqual(sorted(r[3] for r in two), [2, 3])


if __name__ == "__main__":
    unittest.main()
