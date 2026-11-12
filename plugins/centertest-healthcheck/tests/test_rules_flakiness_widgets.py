import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

try:
    import javalang  # noqa: F401
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


STEP_HEADER = """package com.acme.steps;
import com.ankrpt.centertest.guidewire.runtime.manager.page.BaseScenarioPC;
import com.ankrpt.centertest.guidewire.widget.*;
import java.util.*;
import java.time.*;
"""

FLAKY = STEP_HEADER + """
public class FlakySteps extends BaseScenarioPC {
  private static final String ORG = "Acme";

  public void execute() { }

  // ---- 19001 ------------------------------------------------------------
  void retryForever() {
    while (true) {
      page.getSearch().click();
      if (page.getResults().getRows().size() > 0) break;
    }
  }
  void retryDoWhile() {
    do {
      page.getSearch().click();
    } while (page.getResults().getRows().isEmpty());
  }
  void retryWithDeadline() {
    var deadline = LocalDateTime.now().plusSeconds(30);
    while (page.getResults().getRows().isEmpty()) {
      page.getSearch().click();
      if (LocalDateTime.now().isAfter(deadline)) throw new IllegalStateException("none");
    }
  }
  void retryWithPause() {
    do {
      page.getSearch().click();
      ImplicitSleep.sleep(500);
    } while (page.getResults().getRows().isEmpty());
  }
  void retryCounted() {
    for (int i = 0; i < 5; i++) { page.getSearch().click(); }
  }

  // ---- 19002 ------------------------------------------------------------
  void branchOnTitle() {
    popup.getWizardButtons().getOK().click();
    if ("Matching Contacts".equals(getPageTitle())) {
      popup.getReturn().click();
    }
  }
  void waitedTitle() {
    popup.getWizardButtons().getOK().click();
    waitForPageTitle("Matching Contacts", "New Account");
    if ("Matching Contacts".equals(getPageTitle())) { popup.getReturn().click(); }
  }
  void nextAtEnd() {
    wizard.getWizardButtons().getNext().click();
  }

  // ---- 19003 ------------------------------------------------------------
  void byName() {
    orgSearchPage.getName().set(ORG);
    orgSearchPage.getSearch().click();
    orgSearchPage.getOrganizationSearchResultsTable().getFirstRow().select().get_Select().click();
  }
  void byVariable() {
    var contactSearchResultsTable = contactSearchPage.getContactSearchResultsTable();
    var row = contactSearchResultsTable.getFirstRow().select();
  }
  void byUniqueKey() {
    accountSearchPage.getAccountNumber().set("123");
    accountSearchPage.getSearch().click();
    var row = accountSearchPage.getAccountSearchResultsTable().getFirstRow().select();
  }
  void filtered() {
    var row = orgSearchPage.getOrganizationSearchResultsTable().getFirstRow().withName(ORG).select();
  }
  void ownTable() {
    vehiclesStep.getPAPersonalVehicleTable().getFirstRow().select().getType().click();
  }

  // ---- 19004 ------------------------------------------------------------
  void randomLicence() {
    var n = new Random().nextInt(10000);
    var m = Math.random();
  }
  void seeded() {
    var n = new Random(42L).nextInt(10000);
  }

  // ---- 19005 ------------------------------------------------------------
  LocalDate effective() {
    var businessDate = GW.LocalDate(getContext());
    return businessDate.plus(Period.between(LocalDate.now(), ddt.getAsDate()));
  }
  void throughVariable() {
    var today = LocalDate.now();
    page.getEffectiveDate().set(today.plusDays(5).toString());
  }
  void timeout() {
    var deadline = LocalDateTime.now().plusSeconds(60);
    while (LocalDateTime.now().isBefore(deadline)) { ImplicitSleep.sleep(100); }
  }
  String uniqueName() {
    return "Acct " + LocalDateTime.now().toString();
  }
}
"""

GENERATOR = """package com.acme.exits;
import java.util.concurrent.ThreadLocalRandom;
public class ValueGeneratorExit implements IValueGeneratorExit {
  public String generate(String key) { return String.valueOf(ThreadLocalRandom.current().nextInt(10)); }
}
"""

WIDGETS = STEP_HEADER + """
public class WidgetSteps extends BaseScenarioPC {
  private static final String SUMMARY = "PolicyFile_Summary-PolicySummaryScreen-Badge";
  private static final String QUICK = "PolicyFile_Summary-PolicySummaryScreen-";
  // TODO no getter for the conviction picker, the live id is used
  private static final String PICKER = "PolicyFile_Summary-PolicySummaryScreen-Picker";
  private static final String POLICY_TYPE = "Commercial Package";
  private static final String PANEL = "#gw-center-panel";
  private static final String SHARED = "SubmissionWizard-LOBWizardStepGroup-LineWizardStepSet-Shared";

  public void execute() { }

  void raw() {
    WidgetLabel.get("PolicyFile_Summary-PolicySummaryScreen-Status", getContext()).assertEquals("Canceled");
    WidgetButton.get(QUICK + "Badge", getContext()).click();
    WidgetButton.get(QUICK + "NoSuchWidget", getContext()).click();
    // TODO no getter: the generated one points at the iterated panel
    WidgetButton.get("PolicyFile_Summary-PolicySummaryScreen-Status", getContext()).click();
    new PolicyFile_SummaryPage(getContext()).getStatus().withCssId("PolicyFile_Summary-PolicySummaryScreen-Status").click();
    WidgetButton.get(PICKER, getContext()).click();
  }

  void selectors() {
    WidgetButton.get("div.gw-Wizard--Title[role=\\"heading\\"]", getContext()).click();
    new TableSortable(PANEL, getContext()).getFirstRow();
    WidgetLabel.get("div.gw-Wizard--Title[role=\\"heading\\"]", getContext()).getValue();
    WidgetToolbarButton.get("SubmissionWizard-LV_tb-[ROW]-Add", getContext()).click();
  }

  void typelists() {
    var findPolicy = fnolWizardPage.getFindPolicyStep();
    findPolicy.getPolicyType().set(POLICY_TYPE);
    findPolicy.getPolicyType().set("Personal Auto");
    findPolicy.getPolicyType().set("Not A Value");
    contactSearchPage.getContactType().set("Person");
    WidgetButton.get(SHARED, getContext()).click();
  }
}
"""

OTHER = STEP_HEADER + """
public class OtherSteps extends BaseScenarioPC {
  public void execute() {
    WidgetButton.get("SubmissionWizard-LOBWizardStepGroup-LineWizardStepSet-Shared", getContext()).click();
    WidgetLabel.get("PolicyFile_Summary-PolicySummaryScreen-Unique-OnlyHere", getContext()).getValue();
  }
}
"""

CSSIDS = """PolicyFile_Summary-PolicySummaryScreen-Badge=new PolicyFile_SummaryPage(getContext()).getBadge()
PolicyFile_Summary-PolicySummaryScreen-Status=new PolicyFile_SummaryPage(getContext()).getStatus()
PolicyFile_Summary-PolicySummaryScreen-Picker=new PolicyFile_SummaryPage(getContext()).getPicker()
"""

FNOL_PAGE = """package com.acme.generated.pages.pc;
public final class FNOLWizardPage extends PcfPage {
public MQ.FindPolicyStep getFindPolicyStep() {return null;}
}
"""

INNER = """package com.acme.generated.pages.pc.inner;
public class MQ {
public class FindPolicyStep{
public WidgetTypeKeyInputPolicyType getPolicyType() {return null;}
}
}
"""

ISO_PAGE = """package com.acme.generated.pages.pc;
public final class ISOPage extends PcfPage {
public WidgetTextInput getPolicyType() {return null;}
public WidgetRangeInput getContactType() {return null;}
}
"""

TC_POLICY_TYPE = """package com.acme.generated.typelist.pc;
public class TC_PolicyType extends com.ankrpt.centertest.guidewire.widget.TypeCode {
public static TC_PolicyType CommercialPackage() { return new TC_PolicyType("CommercialPackage", "Commercial Package", false); }
public static TC_PolicyType PersonalAuto() { return new TC_PolicyType("PersonalAuto", "Personal Auto", false); }
}
"""


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class FlakinessAndWidgetRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        cls.tmp = tempfile.mkdtemp()
        cls.repo = os.path.join(cls.tmp, "proj")
        java = os.path.join("src", "main", "java", "com", "acme")
        _write(cls.repo, os.path.join(java, "steps", "FlakySteps.java"), FLAKY)
        _write(cls.repo, os.path.join(java, "exits", "ValueGeneratorExit.java"), GENERATOR)
        _write(cls.repo, os.path.join(java, "steps", "WidgetSteps.java"), WIDGETS)
        _write(cls.repo, os.path.join(java, "steps", "OtherSteps.java"), OTHER)
        gen = os.path.join(cls.tmp, "proj-generated", "src", "main")
        _write(gen, os.path.join("resources", "cssids", "pc", "PolicyFile_Summary.properties"), CSSIDS)
        gjava = os.path.join("java", "com", "acme", "generated")
        _write(gen, os.path.join(gjava, "pages", "pc", "FNOLWizardPage.java"), FNOL_PAGE)
        _write(gen, os.path.join(gjava, "pages", "pc", "inner", "MQ.java"), INNER)
        _write(gen, os.path.join(gjava, "pages", "pc", "ISOPage.java"), ISO_PAGE)
        _write(gen, os.path.join(gjava, "typelist", "pc", "TC_PolicyType.java"), TC_POLICY_TYPE)
        files = parse_directory(cls.repo, "src/main/java", [], [], True, None)
        cls.commits = {LOCAL_COMMIT: files}
        cls.config = SimpleNamespace(repository_dir=cls.repo, cssids=None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def _run(self, func, config=None):
        return func(self.commits, config or self.config)

    @staticmethod
    def _methods(result):
        return sorted(r[1] for r in result.rows)

    # -- Flakiness ----------------------------------------------------------

    def test_19001_retry_loops_without_pause_or_limit(self):
        import rules.rule_flakiness as rf
        result = self._run(rf.retry_loop_without_pause_or_limit)
        self.assertEqual(self._methods(result), ["retryDoWhile", "retryForever"])
        self.assertTrue(all(r[-1].startswith("src/main/java/com/acme/steps/FlakySteps.java:") for r in result.rows))

    def test_19002_title_read_straight_after_click(self):
        import rules.rule_flakiness as rf
        result = self._run(rf.click_then_unwaited_page_read)
        self.assertEqual(self._methods(result), ["branchOnTitle"])
        self.assertIn("getOK().click()", result.rows[0][2])

    def test_19003_unfiltered_first_search_row(self):
        import rules.rule_flakiness as rf
        result = self._run(rf.first_search_row_unfiltered)
        self.assertEqual(self._methods(result), ["byName", "byVariable"])

    def test_19004_unseeded_random_in_steps_only(self):
        import rules.rule_flakiness as rf
        result = self._run(rf.unseeded_random)
        self.assertEqual(self._methods(result), ["randomLicence", "randomLicence"])
        self.assertFalse(any("ValueGeneratorExit" in r[0] for r in result.rows))

    def test_19005_machine_clock_in_business_dates(self):
        import rules.rule_flakiness as rf
        result = self._run(rf.machine_clock_in_business_dates)
        self.assertEqual(self._methods(result), ["effective", "throughVariable"])

    # -- Widgets ------------------------------------------------------------

    def test_20001_raw_ids_with_a_generated_getter(self):
        import rules.rule_widgets as rw
        result = self._run(rw.raw_id_with_generated_getter)
        self.assertIsNone(result.error)
        got = sorted((r[1], r[2].split("(")[0].strip()) for r in result.rows)
        # SUMMARY constant, the literal Status label, QUICK + "Badge"; not: the unknown id, the TODO'd
        # call and PICKER constant, getStatus().withCssId(its own id)
        self.assertEqual(got, [("field SUMMARY", "private static final String SUMMARY = \"PolicyFile_Summary-PolicySummaryScreen-Badge\";"),
                               ("raw", "WidgetButton.get"), ("raw", "WidgetLabel.get")])
        self.assertTrue(any("getBadge()" in r[3] for r in result.rows))

    def test_20001_needs_the_generated_project(self):
        import rules.rule_widgets as rw
        bare = tempfile.mkdtemp()
        try:
            with mock.patch.dict(os.environ, {"HOME": bare}):
                result = self._run(rw.raw_id_with_generated_getter, SimpleNamespace(repository_dir=bare, cssids=None))
            self.assertEqual(result.error, "needs the generated project (--cssids or <project>-generated)")
            self.assertEqual(result.rows, [])
        finally:
            shutil.rmtree(bare)

    def test_20002_selectors_as_ids_except_on_labels(self):
        import rules.rule_widgets as rw
        result = self._run(rw.selector_as_widget_id)
        got = sorted(r[2].split("(")[0].strip() for r in result.rows)
        self.assertEqual(got, ["WidgetButton.get", "new TableSortable"])

    def test_20003_same_raw_id_in_two_files(self):
        import rules.rule_widgets as rw
        result = self._run(rw.same_raw_id_in_several_files)
        self.assertEqual(len(result.rows), 1)
        self.assertIn("OtherSteps.java", result.rows[0][-1] + result.rows[0][3])
        self.assertIn("2 files", result.rows[0][3])

    def test_20004_typelist_display_text(self):
        import rules.rule_widgets as rw
        result = self._run(rw.typelist_set_by_display_text)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.rows), 2)
        joined = " ".join(r[3] for r in result.rows)
        self.assertIn("TC_PolicyType.CommercialPackage()", joined)
        self.assertIn("TC_PolicyType.PersonalAuto()", joined)
        self.assertNotIn("Person\"", joined)


if __name__ == "__main__":
    unittest.main()
