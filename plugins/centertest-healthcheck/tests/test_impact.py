import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from eir_impact import command_for, rerun_suite, suite_command, tests_reaching

PLUGINS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PLUGINS, "suite-builder", "tests"))

SOURCES = {
    # A facade every test uses: only the method that builds the changed step passes the change on.
    "BC": ("BC.java", """public final class BC {
    public static AssertDisbursement assertDisbursement(User u) { return new AssertDisbursement(u); }
    public static CreateAccount createAccount(User u) { return new CreateAccount(u); }
}"""),
    "AssertDisbursement": ("AssertDisbursement.java", "public class AssertDisbursement extends BaseScenarioBC { }"),
    "CreateAccount": ("CreateAccount.java", "public class CreateAccount extends BaseScenarioBC { }"),
    "BaseScenarioBC": ("BaseScenarioBC.java", "public abstract class BaseScenarioBC { }"),
    "DisbursementTest": ("DisbursementTest.java", """@CenterTest
public final class DisbursementTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { BC.assertDisbursement(u).execute(); }
}"""),
    "AccountTest": ("AccountTest.java", """@CenterTest
public final class AccountTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { BC.createAccount(u).execute(); }
}"""),
}


class TestsReachingTest(unittest.TestCase):
    def test_a_facade_passes_on_only_the_methods_that_use_the_change(self):
        self.assertEqual(tests_reaching({"AssertDisbursement"}, SOURCES), {"DisbursementTest": "AssertDisbursement"})

    def test_a_changed_base_class_reaches_every_subclass_user(self):
        self.assertEqual(set(tests_reaching({"BaseScenarioBC"}, SOURCES)), {"DisbursementTest", "AccountTest"})

    def test_every_change_that_reaches_a_test_is_credited(self):
        every = {}
        reached = tests_reaching({"BC", "AssertDisbursement"}, SOURCES, every=every)
        self.assertEqual(reached["DisbursementTest"], "AssertDisbursement")  # sorted: the same every run
        self.assertEqual(every["DisbursementTest"], {"AssertDisbursement", "BC"})

    def test_a_changed_test_reaches_itself(self):
        self.assertEqual(tests_reaching({"AccountTest"}, SOURCES), {"AccountTest": "AccountTest"})


class FacadeReceiverTest(unittest.TestCase):
    SRC = {
        "PC": ("PC.java", "public final class PC { public static CreatePcAccount createAccount(User u) { return new CreatePcAccount(u); } }"),
        "BC": ("BC.java", """public final class BC {
    public static CreateBcAccount createAccount(Ctx c, CA_SubmissionDC data) { return new CreateBcAccount(c, data); }
    public static Login login(User u) { return new Login(u); }
}"""),
        "CreatePcAccount": ("CreatePcAccount.java", "public class CreatePcAccount { }"),
        "CreateBcAccount": ("CreateBcAccount.java", "public class CreateBcAccount { }"),
        "Login": ("Login.java", "public class Login { }"),
        "SmokeTest": ("SmokeTest.java", """@CenterTest
public final class SmokeTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { BC.login(su).execute(); PC.createAccount(p).execute(); }
}"""),
        "BillingTest": ("BillingTest.java", """@CenterTest
public final class BillingTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { BC.createAccount(c, data).execute(); }
}"""),
    }

    def test_a_same_named_method_on_another_facade_is_not_a_call(self):
        # SmokeTest names BC and calls PC.createAccount: that is not BC.createAccount
        self.assertEqual(tests_reaching({"CreateBcAccount"}, self.SRC), {"BillingTest": "CreateBcAccount"})

    def test_a_data_reader_passes_a_change_on_only_through_its_reading_methods(self):
        from eir_impact import _reading_methods
        start = _reading_methods({"BC"}, self.SRC, {"CA_SubmissionDC"})
        self.assertEqual(start, {"BC": {"createAccount"}})  # the DC is a parameter of createAccount
        self.assertEqual(tests_reaching({"BC"}, self.SRC, start), {"BillingTest": "BC"})
        self.assertEqual(set(tests_reaching({"BC"}, self.SRC)), {"BillingTest", "SmokeTest"})  # BC.java changed


class InheritedFieldTest(unittest.TestCase):
    SRC = {
        "AbstractSubmission": ("AbstractSubmission.java", """import com.x.generated.pages.pc.SubmissionWizardPage;
public abstract class AbstractSubmission extends BaseScenarioPC {
    protected SubmissionWizardPage wizardPage;
    void open() { this.wizardPage = new SubmissionWizardPage(getContext()); }
}"""),
        "CreatePaSubmission": ("CreatePaSubmission.java", """public class CreatePaSubmission extends AbstractSubmission {
    public void offering() { wizardPage.getOfferingStep().getOfferingSelection().set("Standard"); }
    public void other() { log("no wizard here"); }
}"""),
        "PaTest": ("PaTest.java", """@CenterTest
public final class PaTest {
    @CenterTestCase()
    public void run(ScenarioContext s) { new CreatePaSubmission().offering(); }
}"""),
        "OtherTest": ("OtherTest.java", """@CenterTest
public final class OtherTest {
    @CenterTestCase()
    public void run(ScenarioContext s) { new CreatePaSubmission().other(); }
}"""),
    }

    def test_a_widget_used_through_a_superclass_field_is_reached(self):
        reached = tests_reaching({"SubmissionWizardPage"}, self.SRC, {"SubmissionWizardPage": {"getOfferingStep"}})
        self.assertEqual(set(reached), {"PaTest"})  # other() never uses wizardPage


class StepClosureTest(unittest.TestCase):
    SRC = {
        "CreatePersonAccount": ("CreatePersonAccount.java", """public class CreatePersonAccount extends BaseScenarioPC {
    private CreateAccountPage page = new CreateAccountPage(getContext());
    public void execute() { search(); fillAddress(); }
    private void search() { }
    private void fillAddress() { page.getGlobalAddressContainer().getCity().set(address.getCity()); }
}"""),
        "PC": ("PC.java", """public final class PC {
    public static CreatePersonAccount createPersonAccount(Ctx c) { return new CreatePersonAccount(c); }
    public static Login login(Ctx c) { return new Login(c); }
}"""),
        "AccountTest": ("AccountTest.java", """@CenterTest
public final class AccountTest {
    @CenterTestCase()
    public void run(ScenarioContext s) { PC.createPersonAccount(c).execute(); }
}"""),
        "LoginTest": ("LoginTest.java", """@CenterTest
public final class LoginTest {
    @CenterTestCase()
    public void run(ScenarioContext s) { PC.login(c).execute(); }
}"""),
    }

    def test_a_widget_set_in_a_helper_reaches_the_test_through_execute_and_the_facade(self):
        reached = tests_reaching({"CreateAccountPage"}, self.SRC, {"CreateAccountPage": {"getCity"}})
        self.assertEqual(set(reached), {"AccountTest"})


class CommandTest(unittest.TestCase):
    def test_rows_become_a_code_filter_only_when_the_build_forwards_it(self):
        entry = {"test": "WC_ClaimTest", "codes": ["CA-Claim", "Default"]}
        self.assertEqual(command_for(entry, (True, True)),
                         './gradlew bootRun -PcenterTest="WC_ClaimTest run" -Pfilter="Code=^(CA\\-Claim|Default)$"')
        self.assertIsNone(command_for(entry, (True, False)))
        self.assertEqual(command_for({"test": "X", "codes": []}, (True, False)), './gradlew bootRun -PcenterTest="X run"')


if __name__ == "__main__":
    unittest.main()


class RerunSuiteTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from xlsx_fixture import make_xlsx
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = self.tmp.name
        src = os.path.join(root, "src", "main", "java", "com", "x", "tests")
        os.makedirs(src)
        with open(os.path.join(src, "PolicyTest.java"), "w") as fh:
            fh.write("""package com.x.tests;
@CenterTest
public final class PolicyTest {
    @CenterTestCase()
    @DataDriven(datasource = "testdata/PolicyDC.xlsx")
    public void run(ScenarioContext scenarioContext) { }
}""")
        with open(os.path.join(src, "AccountTest.java"), "w") as fh:
            fh.write("""package com.x.tests;
@CenterTest
public final class AccountTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { }
}""")
        with open(os.path.join(src, "OtherTest.java"), "w") as fh:
            fh.write("""package com.x.tests;
@CenterTest
public final class OtherTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { }
}""")
        os.makedirs(os.path.join(root, "testdata"))
        make_xlsx(os.path.join(root, "testdata", "PolicyDC.xlsx"),
                  {"DataCombination": [["Code", "Disabled"], ["A", ""], ["B", ""], ["C", ""], ["D", ""]]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_entries_run_exactly_the_planned_scenarios(self):
        import suite as suites
        plan = [{"test": "AccountTest", "codes": [], "reasons": []},
                {"test": "PolicyTest", "codes": ["B", "D"], "reasons": []}]
        entries, idle = rerun_suite(self.root, plan, "src")
        self.assertEqual((entries, idle), (["AccountTest", "PolicyTest run (B|D)"], []))
        tests = suites.scan(self.root, "src")
        ran = set()
        for e in entries:
            ran |= set(suites.resolve_entry(e, suites.scenarios_of(tests)))
        self.assertEqual(ran, {("AccountTest", "run", ""), ("PolicyTest", "run", "B"), ("PolicyTest", "run", "D")})

    def test_a_whole_data_driven_test_is_its_class(self):
        self.assertEqual(rerun_suite(self.root, [{"test": "PolicyTest", "codes": [], "reasons": []}], "src"),
                         (["PolicyTest"], []))

    def test_a_test_whose_rows_are_all_disabled_is_named_not_dropped(self):
        from xlsx_fixture import make_xlsx
        make_xlsx(os.path.join(self.root, "testdata", "PolicyDC.xlsx"),
                  {"DataCombination": [["Code", "Disabled"], ["A", "true"], ["B", "true"]]})
        plan = [{"test": "PolicyTest", "codes": [], "reasons": []}, {"test": "AccountTest", "codes": [], "reasons": []}]
        self.assertEqual(rerun_suite(self.root, plan, "src"), (["AccountTest"], ["PolicyTest"]))

    def test_command_follows_what_the_build_forwards(self):
        self.assertEqual(suite_command(self.root, "Rerun-1"), "CENTERTESTFILTERCENTERTESTSUITE=Rerun-1 ./gradlew bootRun")
        with open(os.path.join(self.root, "build.gradle"), "w") as fh:
            fh.write("if (project.hasProperty('suiteFilter')) { args = [\"--suiteFilter=${project.suiteFilter}\"] }")
        self.assertEqual(suite_command(self.root, "Rerun-1"), "./gradlew bootRun -PsuiteFilter=Rerun-1")

    def test_pr_comment_offers_the_suite(self):
        from eir_review import render_markdown
        plan = [{"test": f"T{i}Test", "codes": [], "reasons": ["test changed"]} for i in range(5)]
        meta = {"base_name": "main", "head_name": "b", "base_short": "1", "head_short": "2", "base_files": 1,
                "head_files": 1, "ruleset": "x", "rerun": plan, "forwards": (True, True), "changed": 5,
                "data": [], "suites": [],
                "rerun_suite": {"name": "Rerun-2", "entries": [p["test"] for p in plan],
                                "command": "./gradlew bootRun -PsuiteFilter=Rerun-2"}}
        md = render_markdown([], meta)
        self.assertIn("**All of it in one run**", md)
        self.assertIn('"Name": "Rerun-2"', md)
        self.assertIn("./gradlew bootRun -PsuiteFilter=Rerun-2", md)
        self.assertNotIn("One test at a time", md)  # five commands: the suite replaces them

    def test_a_large_plan_reads_by_cause(self):
        from eir_review import render_markdown
        plan = [{"test": f"T{i:02}Test", "codes": [], "reasons": ["PC.java changed"]} for i in range(9)]
        plan += [{"test": "BillTest", "codes": [], "reasons": ["PC.java changed", "BC.java changed"]},
                 {"test": "OnlyBcTest", "codes": [], "reasons": ["BC.java changed"]},
                 {"test": "RowTest", "codes": ["AZ"], "reasons": ["WC_SubmissionDC.xlsx rows changed"]}]
        meta = {"base_name": "main", "head_name": "b", "base_short": "1", "head_short": "2", "base_files": 1,
                "head_files": 1, "ruleset": "x", "rerun": plan, "forwards": (True, True), "changed": 3,
                "data": [], "suites": []}
        md = render_markdown([], meta)
        self.assertIn("- **PC.java changed** → 10 tests, 9 only through it: T00Test", md)
        self.assertIn("- **BC.java changed** → 2 tests, 1 only through it: BillTest, OnlyBcTest", md)
        self.assertLess(md.index("PC.java changed"), md.index("BC.java changed"))  # biggest first
        self.assertIn("Only some rows:\n- **RowTest** — rows AZ", md)
        self.assertNotIn("- **T00Test**", md)  # not listed test by test


class DataRowsTest(unittest.TestCase):
    """Changed DataCombination rows filter only the test whose own datasource is that workbook."""

    def setUp(self):
        import tempfile
        sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))
        from refcheck_fixture import make_xlsx
        self.tmp = tempfile.TemporaryDirectory()
        self.base, self.head = os.path.join(self.tmp.name, "base"), os.path.join(self.tmp.name, "head")
        for tree, value in ((self.base, "old"), (self.head, "new")):
            src = os.path.join(tree, "src", "main", "java", "com", "x")
            os.makedirs(src)
            files = {
                "SubmissionTest.java": """@CenterTest
public final class SubmissionTest {
    @CenterTestCase()
    @DataDriven(datasource = "testdata/WC_SubmissionDC.xlsx")
    public void run(ScenarioContext scenarioContext) { }
}""",
                "CreateSubmission.java": "public class CreateSubmission { void go(WC_SubmissionDC data) { } }",
                "CancelTest.java": """@CenterTest
public final class CancelTest {
    @CenterTestCase()
    @DataDriven(datasource = "testdata/WC_CancelDC.xlsx")
    public void run(ScenarioContext scenarioContext) { new CreateSubmission().go(d); }
}""",
            }
            for name, text in files.items():
                with open(os.path.join(src, name), "w") as fh:
                    fh.write(text)
            os.makedirs(os.path.join(tree, "testdata"))
            make_xlsx(os.path.join(tree, "testdata", "WC_SubmissionDC.xlsx"),
                      {"DataCombination": [["Code", "State"], ["AZ", value], ["TX", "same"]]})
            make_xlsx(os.path.join(tree, "testdata", "WC_CancelDC.xlsx"),
                      {"DataCombination": [["Code", "Reason"], ["Flat", "x"]]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_rows_for_the_own_datasource_whole_test_otherwise(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl not installed")
        from eir_impact import rerun_plan
        plan = {e["test"]: e["codes"] for e in rerun_plan(self.base, self.head, ["testdata/WC_SubmissionDC.xlsx"], "src")}
        # CancelTest reaches WC_SubmissionDC through a step: "AZ" is not one of its own rows
        self.assertEqual(plan, {"SubmissionTest": ["AZ"], "CancelTest": []})

    def test_a_reference_row_named_in_another_case_reaches_the_dc_row(self):
        from eir_impact import _dc_rows_using
        from refcheck_fixture import make_xlsx
        make_xlsx(os.path.join(self.head, "testdata", "WC_CancelDC.xlsx"),
                  {"DataCombination": [["Code", "#Company"], ["Flat", "ACME"]]})
        self.assertEqual(_dc_rows_using(self.head, {"Company": {"Acme"}}), {"testdata/WC_CancelDC.xlsx": {"Flat"}})

class RunScopeTest(unittest.TestCase):
    def build(self, root, rows, with_account):
        from xlsx_fixture import make_xlsx
        src = os.path.join(root, "src", "main", "java", "com", "x")
        os.makedirs(src)
        with open(os.path.join(src, "PolicyTest.java"), "w") as fh:
            fh.write('@CenterTest public final class PolicyTest { @CenterTestCase() '
                     '@DataDriven(datasource = "testdata/PolicyDC.xlsx") public void run(ScenarioContext s) { } }')
        if with_account:
            with open(os.path.join(src, "AccountTest.java"), "w") as fh:
                fh.write('@CenterTest public final class AccountTest { @CenterTestCase() public void run(ScenarioContext s) { } }')
        os.makedirs(os.path.join(root, "testdata"))
        make_xlsx(os.path.join(root, "testdata", "PolicyDC.xlsx"), {"DataCombination": [["Code", "Disabled"]] + rows})

    def test_removed_switched_off_and_added(self):
        import tempfile
        from eir_review import render_markdown, run_scope
        with tempfile.TemporaryDirectory() as tmp:
            base, head = os.path.join(tmp, "base"), os.path.join(tmp, "head")
            self.build(base, [["A", ""], ["B", ""], ["C", ""]], True)
            self.build(head, [["A", ""], ["B", "true"], ["D", ""]], False)
            scope = run_scope(base, head, "src")
        self.assertEqual((scope["before"], scope["after"]), (4, 2))
        self.assertEqual(scope["removed"], [("AccountTest", "run", ""), ("PolicyTest", "run", "C")])
        self.assertEqual(scope["switched_off"], [("PolicyTest", "run", "B")])
        self.assertEqual(scope["added"], [("PolicyTest", "run", "D")])
        meta = {"base_name": "main", "head_name": "b", "base_short": "1", "head_short": "2", "base_files": 1,
                "head_files": 1, "ruleset": "x", "rerun": [], "data": [], "suites": [], "scope": scope}
        md = render_markdown([], meta)
        self.assertIn("A full run executes 4 → 2 scenarios.", md)
        self.assertIn("**Switched off** (1: the row is disabled): `PolicyTest run B`", md)
        self.assertEqual(scope["flows_stopped"], [{"test": "AccountTest.run", "deleted": True}])
        self.assertIn("**Flows that no longer run** (1): AccountTest.run (test gone: deleted or renamed)", md)

    def test_what_the_run_loses_heads_the_comment(self):
        from eir_json import review_json
        from eir_review import breadth_lost, render_markdown
        meta = {"base_name": "main", "head_name": "b", "base_short": "1", "head_short": "2", "base_files": 1,
                "head_files": 1, "ruleset": "x", "rerun": [], "data": [], "suites": [],
                "scope": {"before": 3, "after": 2, "removed": [], "switched_off": [], "added": [],
                          "flows_stopped": [{"test": "A.run", "deleted": False}]},
                "coverage": [{"line": "GLLine", "lost": ["Pollution", "Liquor"], "gained": [], "not_offered": [],
                              "options_lost": ["Liquor / Limit = $1,000"], "options_gained": []}],
                "states": [{"line": "GL", "lost": ["NV"], "gained": []}]}
        line = "The run loses 1 flow, 2 coverages, 1 limit/deductible option, 1 line/jurisdiction (details below)."
        self.assertEqual(breadth_lost(meta), line)
        md = render_markdown([], meta)
        self.assertLess(md.index(line), md.index("Compared 2 with the merge-base"))  # right under the verdict
        self.assertEqual(review_json([], meta)["breadth_lost"], line)
        self.assertEqual(breadth_lost({"scope": None}), "")

    def test_a_flow_whose_every_row_is_switched_off_stops_running(self):
        import tempfile
        from eir_review import run_scope
        with tempfile.TemporaryDirectory() as tmp:
            base, head = os.path.join(tmp, "base"), os.path.join(tmp, "head")
            self.build(base, [["A", ""], ["B", ""]], True)
            self.build(head, [["A", "true"], ["B", "yes"]], True)
            scope = run_scope(base, head, "src")
        self.assertEqual(scope["flows_stopped"], [{"test": "PolicyTest.run", "deleted": False}])
