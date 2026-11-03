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
import scan_project as sp  # noqa: E402
from xlsx_fixture import make_xlsx  # noqa: E402

TEST_A = '''package com.acme.tests.pc.personalauto.submission;
@CenterTest
public final class PA_SubmissionTest {
  public enum RestartPoints { POLICY }
  @CenterTestCase(testCaseId = "C1")
  @DataDriven(datasource = "testdata/personalauto/PA_SubmissionDC.xlsx")
  public void run(ScenarioContext scenarioContext) {
    var producer = scenarioContext.getInvocationContext("producer");
    PC.loginToPC(producer).execute();
  }
}
'''
TEST_B = '''package com.acme.tests.pc.personalauto.policychange;
@CenterTest
public final class PA_PolicyChangeTest {
  @CenterTestCase()
  public void run(ScenarioContext scenarioContext) {
    var producer = scenarioContext.getInvocationContext("producer");
  }
}
'''
TEST_C = '''package com.acme.tests.pc.homeowners.submission;
@CenterTest
public final class HOP_SubmissionTest {
  @CenterTestCase(testCaseId = "C3")
  public void runFirst(ScenarioContext scenarioContext) {
    var underwriter = scenarioContext.getInvocationContext("underwriter");
  }
  @CenterTestCase()
  public void runSecond(ScenarioContext scenarioContext) { }
}
'''
FACADE = '''package com.acme.reusable;
public interface PC {
  static LoginToPC loginToPC(InvocationContext context) {
    return new LoginToPC(context);
  }
  static CreatePersonAccount createPersonAccount(InvocationContext context,
                                                 SharedData.Person person, SharedData.Address address) {
    return new CreatePersonAccount(context, person, address);
  }
  static SearchForPolicyPC searchForPolicyPC(InvocationContext context) {
    return new SearchForPolicyPC(context);
  }
}
'''
LOGIN_STEP = '''package com.acme.reusable.pc.shared;
import com.ankrpt.centertest.flow.FlowTags;
import com.acme.generated.pages.pc.LoginPage;
@FlowTags("Application.PC")
public class LoginToPC extends BaseScenarioPC {
  public LoginToPC(InvocationContext context) { super(context); }
  public void execute() {
    new LoginPage(getContext()).getSubmit().click();
    waitForPageTitle("My Summary");
  }
}
'''
ACCOUNT_STEP = '''package com.acme.reusable.pc.shared.account;
import com.acme.generated.pages.pc.NewAccountPage;
@FlowTags("Application.PC")
public class CreatePersonAccount extends BaseScenarioPC {
  public void execute() { new NewAccountPage(getContext()).getSearch().click(); waitForPageTitle("Create account"); }
}
'''
SEARCH_STEP = '''package com.acme.reusable.pc.shared;
import com.acme.generated.pages.pc.PolicySearchPage;
import com.acme.generated.pages.pc.inner.QXZK;
@FlowTags("Application.PC")
public class SearchForPolicyPC extends BaseScenarioPC {
  public void execute() { new PolicySearchPage(getContext()).getSearch().click(); waitForPageTitle("Search Policies"); }
}
'''
BUILD = '''plugins { id 'org.springframework.boot' }
springBoot { mainClass = 'com.ankrpt.runner.main.MainRunner' }
bootRun { }
dependencies {
    api "com.acme:acme-generated:${property('acme.generated.version') + "${profileSuffix}"}"
}
'''


def write(root, rel, text=""):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def fake_project(root, source="main"):
    java = f"src/{source}/java/com/acme"
    write(root, "src/main/resources/customer.centertest.properties", "centertest.client.package=com.acme\ngw.version=v10\n")
    write(root, "src/main/resources/profile.local.properties", "centertest.runtime.environment=local\n")
    write(root, "src/main/resources/profile.qa.properties", "")
    write(root, "src/main/resources/runtime_environments.properties", "centertest.user.producer.local=aprples|s3cr3t\n")
    write(root, f"{java}/tests/pc/personalauto/submission/PA_SubmissionTest.java", TEST_A)
    write(root, f"{java}/tests/pc/personalauto/policychange/PA_PolicyChangeTest.java", TEST_B)
    write(root, f"{java}/tests/pc/homeowners/submission/HOP_SubmissionTest.java", TEST_C)
    write(root, f"{java}/reusable/PC.java", FACADE)
    write(root, f"{java}/reusable/pc/shared/LoginToPC.java", LOGIN_STEP)
    write(root, f"{java}/reusable/pc/shared/account/CreatePersonAccount.java", ACCOUNT_STEP)
    write(root, f"{java}/reusable/pc/shared/SearchForPolicyPC.java", SEARCH_STEP)
    write(root, "build.gradle", BUILD)
    write(root, "gradle.properties", "acme.generated.version=1.2\n")
    write(root, "gradlew", "#!/bin/sh\n")


class ProjectTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = self.tmp.name
        self.root = os.path.join(self.parent, "acme-project")
        self.gradle = os.path.join(self.parent, "gradle-home")
        self.m2 = os.path.join(self.parent, "m2-home")

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, **kwargs):
        return sp.scan(self.root, gradle_home=self.gradle, m2_home=self.m2,
                       cache_root=os.path.join(self.parent, "cssids-cache"), **kwargs)


class TestsAndStepsTest(ProjectTestCase):
    def test_package_and_tests_root(self):
        fake_project(self.root)
        result = self.scan()
        self.assertEqual(result["clientPackage"]["value"], "com.acme")
        self.assertEqual(result["testsRoot"]["value"], "src/main/java")

    def test_tests_under_src_test(self):
        fake_project(self.root, source="test")
        self.assertEqual(self.scan()["testsRoot"]["value"], "src/test/java")

    def test_layout_and_lob_prefixes(self):
        fake_project(self.root)
        layout = self.scan()["testLayout"]["value"]
        self.assertEqual(layout["folders"], {"pc/personalauto/submission": 1, "pc/personalauto/policychange": 1,
                                             "pc/homeowners/submission": 1})
        self.assertEqual(layout["lobPrefixes"], {"homeowners": "HOP", "personalauto": "PA"})

    def test_style(self):
        fake_project(self.root)
        style = self.scan()["testStyle"]["value"]
        self.assertEqual(style["methods"], {"run": 2, "runFirst": 1, "runSecond": 1})
        self.assertEqual(style["roles"], {"producer": 2, "underwriter": 1})
        self.assertEqual((style["tests"], style["restartPoints"], style["testCaseId"],
                          style["emptyCenterTestCase"], style["dataDriven"]), (3, 1, 2, 2, 1))

    def test_step_conventions(self):
        fake_project(self.root)
        steps = self.scan()["steps"]["value"]
        self.assertEqual(steps["root"], "src/main/java/com/acme/reusable")
        self.assertEqual(steps["bases"], [{"base": "BaseScenarioPC", "center": "pc",
                                           "flowTags": '@FlowTags("Application.PC")', "withFlowTags": 3, "count": 3}])

    def test_flow_tags_array_form_and_untagged_steps(self):
        fake_project(self.root)
        steps_dir = "src/main/java/com/acme/reusable/pc/shared"
        for name, text in (("LoginToPC", LOGIN_STEP), ("SearchForPolicyPC", SEARCH_STEP)):
            write(self.root, f"{steps_dir}/{name}.java",
                  text.replace('@FlowTags("Application.PC")', '@FlowTags({"Application.PC"})'))
        write(self.root, f"{steps_dir}/Untagged.java", "public class Untagged extends BaseScenarioPC { }\n")
        base = self.scan()["steps"]["value"]["bases"][0]
        self.assertEqual((base["flowTags"], base["withFlowTags"], base["count"]),
                         ('@FlowTags({"Application.PC"})', 3, 4))

    def test_missing_package_is_reported(self):
        fake_project(self.root)
        os.remove(os.path.join(self.root, "src", "main", "resources", "customer.centertest.properties"))
        result = self.scan()
        self.assertIsNone(result["clientPackage"]["value"])
        self.assertIn("centertest.client.package", result["clientPackage"]["reason"])
        self.assertIsNone(result["testLayout"]["value"])

    def test_credentials_are_never_read(self):
        fake_project(self.root)
        self.assertNotIn("s3cr3t", json.dumps(self.scan()))


class FacadesAndExemplarsTest(ProjectTestCase):
    def test_context_only_facades_carry_their_step_fingerprint(self):
        fake_project(self.root)
        methods = {m["method"]: m for m in self.scan()["facades"]["value"]}
        login = methods["loginToPC"]
        self.assertTrue(login["contextOnly"])
        self.assertEqual(login["step"], "src/main/java/com/acme/reusable/pc/shared/LoginToPC.java")
        self.assertEqual((login["pages"], login["titles"]), (["LoginPage"], ["My Summary"]))
        self.assertEqual(methods["searchForPolicyPC"]["pages"], ["PolicySearchPage", "QXZK"])

    def test_data_facades_are_not_context_only(self):
        fake_project(self.root)
        account = {m["method"]: m for m in self.scan()["facades"]["value"]}["createPersonAccount"]
        self.assertFalse(account["contextOnly"])
        self.assertEqual(account["params"],
                         "InvocationContext context, SharedData.Person person, SharedData.Address address")
        self.assertNotIn("pages", account)

    def test_exemplars_per_center(self):
        fake_project(self.root)
        picked = self.scan()["exemplars"]["value"]["pc"]
        self.assertTrue(picked["test"].startswith("src/main/java/com/acme/tests/pc/"))
        self.assertTrue(picked["step"].startswith("src/main/java/com/acme/reusable/pc/"))

    def test_no_facades(self):
        fake_project(self.root)
        os.remove(os.path.join(self.root, "src", "main", "java", "com", "acme", "reusable", "PC.java"))
        self.assertIsNone(self.scan()["facades"]["value"])


BASE_STEP = """package com.acme.reusable.pc.personalauto.policychange;
import com.acme.generated.pages.pc.PolicyChangeWizardPage;
import com.acme.generated.pages.pc.UWBlockProgressIssuesPopup;
public abstract class AbstractPolicyChange extends BaseScenarioPC {
  private static final String UW_TITLE = "Risk Approval Details";
  protected final PolicyChangeWizardPage wizardPage;
  private final Misc misc;
  public AbstractPolicyChange(InvocationContext context, Misc misc) {
    super(context);
    this.misc = misc;
    this.wizardPage = new PolicyChangeWizardPage(getContext());
  }
  protected boolean hasReformMode() { return misc != null && misc.isReform(); }
  private static final String LIMIT = "2000000";
  protected void quoteStep() { wizardPage.getWizardButtons().getQuote().click(); }
  protected void next() { wizardPage.getWizardButtons().getNextV9().click(); }
  protected void limits() { coverageUtil.setCoverage("Liability", "Limit", LIMIT); coverageUtil.setCoverage("Collision", "Deductible", "500"); }
  public void addLossClaim(String date) {
    var table = TableSortable.get("SubmissionWizard-LOBWizardStepGroup-PAClaimsInfo-ClaimsInfo_ICLV", getContext());
  }
  protected void issueStep() {
    wizardPage.getIssue().click();
    if (getPageTitle().contains("Issues that block Issuance")) {
      new UWBlockProgressIssuesPopup(getContext()).getApprove().click();
      waitForPageTitle(UW_TITLE);
    }
  }
}
"""
RECORDED_STEP = """package com.acme.reusable.pc.personalauto.policychange;
/**
 * Adds a vehicle. Recorded as 2026-10-01_101010 by the CenterTest Recorder.
 */
public class AddVehiclePolicyChange extends AbstractPolicyChange {
  public AddVehiclePolicyChange(InvocationContext context) { super(context, null); }
  public void execute() { issueStep(); }
}
"""
PLAIN_STEP = """package com.acme.reusable.pc.personalauto.policychange;
public class AaaChangeAddress extends AbstractPolicyChange {
  public AaaChangeAddress(InvocationContext context) { super(context, null); }
  public void execute() { }
}
"""
TEST_FLOW = """package com.acme.tests.pc.personalauto.policychange;
@CenterTest
public final class PA_AddDriverTest {
  public enum RestartPoints { POLICY }
  @CenterTestCase()
  @DataDriven(datasource = "testdata/personalauto/PA_SubmissionDC.xlsx")
  public void run(ScenarioContext scenarioContext) {
    var producer = scenarioContext.getInvocationContext("producer");
    PC.loginToPC(producer).execute();
    new AddVehiclePolicyChange(producer).execute();
    PC.searchForPolicyPC(producer).execute();
  }
}
"""


class ProjectKnowledgeTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        fake_project(self.root)
        java = "src/main/java/com/acme"
        write(self.root, f"{java}/reusable/pc/personalauto/policychange/AbstractPolicyChange.java", BASE_STEP)
        write(self.root, f"{java}/reusable/pc/personalauto/policychange/AddVehiclePolicyChange.java", RECORDED_STEP)
        write(self.root, f"{java}/reusable/pc/personalauto/policychange/AaaChangeAddress.java", PLAIN_STEP)
        write(self.root, f"{java}/tests/pc/personalauto/policychange/PA_AddDriverTest.java", TEST_FLOW)
        write(self.root, f"{java}/reusable/CLAUDE.md", "Every new step gets a facade factory method.\n")
        self.result = self.scan()

    def test_guidance_files(self):
        self.assertEqual(self.result["guidance"]["value"], ["src/main/java/com/acme/reusable/CLAUDE.md"])

    def test_base_reports_which_methods_read_each_argument(self):
        base, = self.result["transactionBases"]["value"]
        self.assertEqual(base["class"], "AbstractPolicyChange")
        self.assertEqual(base["constructors"], [{"params": "InvocationContext context, Misc misc",
                                                 "argUsedBy": {"Misc misc": ["hasReformMode"]}}])
        self.assertEqual(base["wizardFields"], ["PolicyChangeWizardPage wizardPage"])

    def test_base_reports_its_quote_and_issue_methods(self):
        base, = self.result["transactionBases"]["value"]
        self.assertEqual(base["wizardActions"], {"quote": ["quoteStep"], "issue": ["issueStep"]})

    def test_idioms(self):
        found = self.result["idioms"]["value"]
        self.assertEqual(found["wizardButtons"], {"getQuote": 1, "getNextV9": 1})
        self.assertEqual(found["coverageAmounts"], "plain")

    def test_screen_helpers_by_widget_id(self):
        ids = self.result["screenHelpers"]["value"]["ids"]
        self.assertEqual(ids["SubmissionWizard-LOBWizardStepGroup-PAClaimsInfo-ClaimsInfo_ICLV"],
                         ["AbstractPolicyChange.addLossClaim"])

    def test_screen_helpers_by_title_and_page(self):
        helpers = self.result["screenHelpers"]["value"]
        self.assertEqual(helpers["titles"]["Issues that block Issuance"], ["AbstractPolicyChange.issueStep"])
        self.assertEqual(helpers["titles"]["Risk Approval Details"], ["AbstractPolicyChange.issueStep"])
        self.assertEqual(helpers["pages"]["UWBlockProgressIssuesPopup"], ["AbstractPolicyChange.issueStep"])
        self.assertIn("LoginToPC.execute", helpers["pages"]["Login"])

    def test_folders_rank_recorded_steps_first_and_show_test_flows(self):
        folders = self.result["folders"]["value"]
        steps = folders["steps"]["pc/personalauto/policychange"]
        self.assertEqual(steps[0], {"path": "src/main/java/com/acme/reusable/pc/personalauto/policychange/"
                                            "AddVehiclePolicyChange.java",
                                    "extends": "AbstractPolicyChange", "recorded": True})
        flow = next(t for t in folders["tests"]["pc/personalauto/policychange"] if t["path"].endswith("PA_AddDriverTest.java"))
        self.assertEqual(flow["flow"], ["PC.loginToPC", "new AddVehiclePolicyChange", "PC.searchForPolicyPC"])
        self.assertEqual((flow["restartPoints"], flow["dataDriven"]),
                         (True, "testdata/personalauto/PA_SubmissionDC.xlsx"))

    def test_project_without_guidance(self):
        os.remove(os.path.join(self.root, "src", "main", "java", "com", "acme", "reusable", "CLAUDE.md"))
        self.assertIsNone(self.scan()["guidance"]["value"])


def make_jar(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, text in entries.items():
            z.writestr(name, text)


LOGIN_CSSIDS = {"cssids/pc/Login.properties": "Login-LoginScreen-LoginDV-submit=new LoginPage(getContext()).getSubmit()\n"}


class CssidsSourceTest(ProjectTestCase):
    def cache_jar(self, version, entries=LOGIN_CSSIDS):
        path = os.path.join(self.gradle, "caches", "modules-2", "files-2.1", "com.acme", "acme-generated",
                            version, "0a1b2c", f"acme-generated-{version}.jar")
        make_jar(path, entries)
        return path

    def test_jar_at_declared_version(self):
        fake_project(self.root)
        jar = self.cache_jar("1.2")
        cssids = self.scan()["cssids"]
        self.assertTrue(os.path.isfile(os.path.join(cssids["value"], "cssids", "pc", "Login.properties")))
        self.assertIn(jar, cssids["evidence"])

    def test_jar_with_version_suffix(self):
        fake_project(self.root)
        self.cache_jar("1.2-SNAPSHOT")
        self.assertIsNotNone(self.scan()["cssids"]["value"])

    def test_jar_without_cssids_falls_through_to_checkout(self):
        fake_project(self.root)
        self.cache_jar("1.2", {"com/acme/Foo.class": "x"})
        write(self.parent, "acme-generated/src/main/resources/cssids/pc/Login.properties", "k=v\n")
        self.assertEqual(self.scan()["cssids"]["value"],
                         os.path.join(self.parent, "acme-generated", "src", "main", "resources"))

    def test_ambiguous_siblings_are_not_guessed(self):
        fake_project(self.root)
        write(self.parent, "acme-generated/src/main/resources/cssids/pc/A.properties", "k=v\n")
        write(self.parent, "other-generated/src/main/resources/cssids/pc/B.properties", "k=v\n")
        cssids = self.scan()["cssids"]
        self.assertIsNone(cssids["value"])
        self.assertIn("--cssids", cssids["reason"])

    def test_checkout_named_in_build_gradle_wins(self):
        fake_project(self.root)
        with open(os.path.join(self.root, "build.gradle"), "a", encoding="utf-8") as f:
            f.write("includeBuild { dir = '../acme-generated' }\n")
        write(self.parent, "acme-generated/src/main/resources/cssids/pc/A.properties", "k=v\n")
        write(self.parent, "other-generated/src/main/resources/cssids/pc/B.properties", "k=v\n")
        self.assertEqual(self.scan()["cssids"]["value"],
                         os.path.join(self.parent, "acme-generated", "src", "main", "resources"))

    def test_guidewire9_jar_with_root_cssids_files(self):
        fake_project(self.root)
        self.cache_jar("1.2", {"pc.cssids": '{"cssId": "Login:LoginScreen:LoginDV:submit"}\n', "com/acme/Foo.class": "x"})
        cssids = self.scan()["cssids"]["value"]
        self.assertTrue(os.path.isfile(os.path.join(cssids, "pc.cssids")))
        self.assertFalse(os.path.exists(os.path.join(cssids, "com")))

    def test_extracted_cssids_are_reused_across_scans(self):
        fake_project(self.root)
        self.cache_jar("1.2")
        first, second = self.scan()["cssids"]["value"], self.scan()["cssids"]["value"]
        self.assertEqual(first, second)
        self.assertEqual(len(os.listdir(os.path.join(self.parent, "cssids-cache"))), 1)

    def test_override(self):
        fake_project(self.root)
        self.assertEqual(self.scan(cssids=self.parent)["cssids"],
                         {"value": os.path.abspath(self.parent), "evidence": "--cssids"})


class BuildAndCommandLineTest(ProjectTestCase):
    def test_build_info(self):
        fake_project(self.root)
        build = self.scan()["build"]["value"]
        self.assertEqual(build["compile"], "./gradlew compileJava")
        self.assertEqual(build["run"],
                         './gradlew bootRun --args="--spring.profiles.active={profile} --centerTest={testClass}"')
        self.assertEqual(build["profiles"], ["local", "qa"])

    def test_run_command_from_the_properties_bootrun_reads(self):
        fake_project(self.root)
        write(self.root, "build.gradle", BUILD.replace("bootRun { }", '''bootRun {
    if (project.hasProperty('centerTest')) {
        args = ["--centerTest=${project.centerTest}"]
    }
    if (project.hasProperty('profile')) {
        jvmArgs = ["-Dcentertest.profile=${project.profile}"]
    }
    if (project.hasProperty("restart")) { jvmArgs = ["-Dcentertest.execution.mode=Restart"] }
}'''))
        build = self.scan()["build"]["value"]
        self.assertEqual(build["run"], "./gradlew bootRun -Pprofile={profile} -PcenterTest={testClass}")
        self.assertEqual(build["bootRunProperties"], ["centerTest", "profile", "restart"])

    def test_no_run_command_when_bootrun_reads_no_test_property(self):
        fake_project(self.root)
        write(self.root, "build.gradle", BUILD.replace("bootRun { }", '''bootRun {
    def profile = project.findProperty("profile")
    if (project.hasProperty("filter")) {
        args = ["--spring.profiles.active=${profile}", "--filter=${project.findProperty("filter")}"]
    }
}'''))
        build = self.scan()["build"]["value"]
        self.assertIsNone(build["run"])
        self.assertEqual(build["bootRunProperties"], ["filter", "profile"])

    def test_guidewire_version(self):
        fake_project(self.root)
        self.assertEqual(self.scan()["guidewireVersion"]["value"], "v10")

    def test_command_line(self):
        fake_project(self.root)
        out = os.path.join(self.parent, "project.json")
        result = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scan_project.py"), self.root,
                                 "--cssids", self.parent, "--out", out], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["clientPackage"]["value"], "com.acme")

    def test_command_line_missing_root(self):
        result = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scan_project.py"), "/no/such/project"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("project root not found", result.stderr)


class DataWorkbooksTest(ProjectTestCase):
    DC = "testdata/personalauto/PA_SubmissionDC.xlsx"

    def setUp(self):
        super().setUp()
        fake_project(self.root)
        self.dc = os.path.join(self.root, *self.DC.split("/"))
        os.makedirs(os.path.dirname(self.dc), exist_ok=True)
        make_xlsx(self.dc, {"DataCombination": [["Code", "Driver", "Vehicle"], ["DC1", "D1", "V1"], ["DC2", "D1", "V2"]]})

    def workbooks(self):
        return self.scan()["dataWorkbooks"]

    def test_lists_columns_codes_and_rows(self):
        book = {w["path"]: w for w in self.workbooks()["value"]["workbooks"]}[self.DC]
        self.assertEqual(book["sheets"], {"DataCombination": {"columns": ["Code", "Driver", "Vehicle"],
                                                              "codes": ["DC1", "DC2"], "rows": 2}})

    def test_used_by_from_data_driven(self):
        book = {w["path"]: w for w in self.workbooks()["value"]["workbooks"]}[self.DC]
        self.assertEqual(book["usedBy"], ["src/main/java/com/acme/tests/pc/personalauto/submission/PA_SubmissionTest.java"])

    def test_corrupt_workbook_is_skipped_with_reason(self):
        with open(os.path.join(self.root, "testdata", "bad.xlsx"), "wb") as f:
            f.write(b"not a zip")
        value = self.workbooks()["value"]
        self.assertTrue(value["skipped"][0]["path"].endswith("bad.xlsx"))
        self.assertTrue(value["skipped"][0]["reason"])
        self.assertEqual([w["path"] for w in value["workbooks"]], [self.DC])

    def test_excel_lock_file_ignored(self):
        with open(os.path.join(self.root, "testdata", "personalauto", "~$PA_SubmissionDC.xlsx"), "wb") as f:
            f.write(b"lock")
        value = self.workbooks()["value"]
        self.assertEqual(value["skipped"], [])
        self.assertEqual([w["path"] for w in value["workbooks"]], [self.DC])

    def test_member_read_errors_are_skipped_not_fatal(self):
        import unittest.mock
        import zlib
        bad = os.path.join(self.root, "testdata", "crc.xlsx")
        make_xlsx(bad, {"S": [["Code"], ["X"]]})
        real = sp.xlsx_read.read_workbook

        def flaky(path, *args, **kwargs):
            if path.endswith("crc.xlsx"):
                raise zlib.error("bad data")
            return real(path, *args, **kwargs)

        with unittest.mock.patch.object(sp.xlsx_read, "read_workbook", flaky):
            value = self.workbooks()["value"]
        self.assertEqual([w["path"] for w in value["workbooks"]], [self.DC])
        self.assertTrue(value["skipped"][0]["path"].endswith("crc.xlsx"))

    def test_no_testdata_is_missing(self):
        os.remove(self.dc)
        self.assertIn("reason", self.workbooks())
        self.assertIsNone(self.workbooks()["value"])


class ConventionsTest(ProjectTestCase):
    JAVA = "src/main/java/com/acme"

    def setUp(self):
        super().setUp()
        fake_project(self.root)

    def add_step(self, name, body):
        write(self.root, f"{self.JAVA}/reusable/pc/shared/{name}.java", body)

    def add_test(self, name, body):
        write(self.root, f"{self.JAVA}/tests/pc/personalauto/submission/{name}.java",
              "@CenterTest\npublic final class %s {\n%s\n}\n" % (name, body))

    def usage(self):
        return self.scan()["sharedValuesUsage"]["value"]

    def test_counts_setcustom_and_datakey(self):
        self.add_step("Shared", 'class Shared { void f() { data.setCustom("A", 1); data.setCustom("B", 2); x(DataKey.ONE, DataKey.TWO); } }')
        usage = self.usage()
        self.assertEqual((usage["setCustom"], usage["dataKey"]), (2, 2))

    def test_reserved_key_with_setcustom_is_flagged(self):
        self.add_step("Shared", 'class Shared { void f() { data.setCustom("Premium", x); } }')
        misuse = self.usage()["reservedKeyMisuse"]
        self.assertEqual([m["key"] for m in misuse], ["Premium"])
        self.assertTrue(misuse[0]["path"].endswith("reusable/pc/shared/Shared.java"))

    def test_other_setcustom_keys_not_flagged(self):
        self.add_step("Shared", 'class Shared { void f() { data.setCustom("Premiums", x); data.setCustom("Other", x); } }')
        self.assertEqual(self.usage()["reservedKeyMisuse"], [])

    def test_reserved_keys_constant(self):
        self.assertEqual(sp.RESERVED_KEYS, ("PolicyExpirationDate", "UserName", "Password", "Premium"))

    def test_negative_protocol_counts(self):
        self.add_test("PA_NegTest", 'void run() { throw new NegativeTestException("x"); }\n'
                      'void other() { passTestWhen(a); passTestWhen(b); }')
        self.assertEqual(self.scan()["negativeProtocol"]["value"], {"projectException": 1, "framework": 2})

    def test_negative_protocol_missing_without_package(self):
        os.remove(os.path.join(self.root, "src/main/resources/customer.centertest.properties"))
        self.assertIn("reason", self.scan()["negativeProtocol"])

    def suite_file(self, data):
        write(self.root, "src/main/resources/CenterTestSuiteList.json", json.dumps(data))

    REAL = {"CenterTestSuites": [{"Name": "Regression", "Suites": ["PolicyCenter", "ClaimCenter"]},
                                 {"Name": "Submission", "List": ["PA_SubmissionTest", "WC_SubmissionTest run2"]},
                                 {"Name": "Mixed", "Suites": ["Submission"], "List": ["X_Test"]}]}

    def test_suites_listed(self):
        self.suite_file(self.REAL)
        value = self.scan()["suites"]["value"]
        self.assertEqual(value["path"], "src/main/resources/CenterTestSuiteList.json")
        self.assertEqual(value["suites"], {"Regression": {"Suites": ["PolicyCenter", "ClaimCenter"]},
                                           "Submission": {"List": ["PA_SubmissionTest", "WC_SubmissionTest run2"]},
                                           "Mixed": {"Suites": ["Submission"], "List": ["X_Test"]}})

    def test_suite_with_packages_keeps_only_present_keys(self):
        self.suite_file({"CenterTestSuites": [{"Name": "All", "Packages": ["com.acme.tests"], "Other": 1}]})
        self.assertEqual(self.scan()["suites"]["value"]["suites"], {"All": {"Packages": ["com.acme.tests"]}})

    def test_unknown_shape_kept_raw(self):
        self.suite_file({"Smoke": ["a.A"]})
        value = self.scan()["suites"]["value"]
        self.assertEqual((value["suites"], value["raw"]), ({}, {"Smoke": ["a.A"]}))

    def test_no_suite_file_is_missing(self):
        result = self.scan()["suites"]
        self.assertIsNone(result["value"])
        self.assertIn("reason", result)

    def test_invalid_suite_file_is_missing(self):
        write(self.root, "src/main/resources/CenterTestSuiteList.json", "{not json")
        self.assertIn("reason", self.scan()["suites"])


class ComponentEffectsTest(ProjectTestCase):
    JAVA = "src/main/java/com/acme"

    def setUp(self):
        super().setUp()
        fake_project(self.root)

    def step(self, name, body):
        write(self.root, f"{self.JAVA}/reusable/pc/shared/{name}.java",
              "package com.acme.reusable.pc.shared;\npublic class %s extends BaseScenarioPC {\n  public void execute() {\n%s\n  }\n}\n" % (name, body))

    def effects(self):
        return {e["class"]: e for e in self.scan()["componentEffects"]["value"]}

    def test_payment_then_assert_is_after_commit(self):
        self.step("PayInvoice", "    page.getMakePayment().click();\n    assertEquals(a, b);")
        entry = self.effects()["PayInvoice"]
        self.assertEqual((entry["commits"], entry["afterCommit"]), (["payment"], True))
        self.assertEqual(entry["path"], f"{self.JAVA}/reusable/pc/shared/PayInvoice.java")

    def test_issue_last_is_not_after_commit(self):
        self.step("IssueIt", "    waitForPageTitle(\"Quote\");\n    page.getIssuePolicy().click();")
        entry = self.effects()["IssueIt"]
        self.assertEqual((entry["commits"], entry["afterCommit"]), (["issue"], False))

    def test_class_without_commit_absent(self):
        self.assertNotIn("SearchForPolicyPC", self.effects())

    def test_set_after_commit_counts(self):
        self.step("BindAndSet", "    page.getBindOnly().click();\n    page.getName().set(\"x\");")
        entry = self.effects()["BindAndSet"]
        self.assertEqual((entry["commits"], entry["afterCommit"]), (["bind"], True))

    def test_multiple_kinds_listed(self):
        self.step("CancelAndReinstate", "    page.getCancelNow().click();\n    page.getReinstate().click();")
        self.assertEqual(self.effects()["CancelAndReinstate"]["commits"], ["cancel", "reinstate"])

    def test_commit_patterns_kinds(self):
        self.assertEqual(set(sp.COMMIT_PATTERNS), {"issue", "bind", "payment", "cancel", "reinstate", "rewrite"})

    def test_payment_in_class_name_and_setter_is_not_a_commit(self):
        self.step("CreatePaymentPlan", "    page.getPaymentAmount().set(\"5\");")
        self.assertNotIn("CreatePaymentPlan", self.effects())

    def test_payment_string_literal_and_comment_are_not_commits(self):
        self.step("Note", "    // getMakePayment()\n    log(\"Payment getMakePayment()\");")
        self.assertNotIn("Note", self.effects())

    def test_setter_before_issue_and_nothing_after_is_not_after_commit(self):
        self.step("SetThenIssue", "    page.getName().set(\"x\");\n    page.getIssuePolicy().click();")
        self.assertFalse(self.effects()["SetThenIssue"]["afterCommit"])

    def test_after_commit_uses_last_commit_not_earliest(self):
        self.step("MixedOrder", "    page.getBindOnly().click();\n    waitForPageTitle(\"A\");\n    page.getIssuePolicy().click();")
        entry = self.effects()["MixedOrder"]
        self.assertEqual((entry["commits"], entry["afterCommit"]), (["issue", "bind"], False))

    def test_login_submit_is_not_a_commit(self):
        self.step("Login", "    page.getSubmit().click();\n    waitForPageTitle(\"My Summary\");")
        self.assertNotIn("Login", self.effects())

    def test_constructor_declaration_is_not_a_commit(self):
        write(self.root, f"{self.JAVA}/reusable/pc/shared/ReinstatePolicy.java",
              "package com.acme.reusable.pc.shared;\npublic class ReinstatePolicy extends BaseScenarioPC {\n"
              "  public ReinstatePolicy(InvocationContext ctx) { super(ctx); }\n"
              "  public void execute() {\n    page.getReinstate().click();\n  }\n}\n")
        entry = self.effects()["ReinstatePolicy"]
        self.assertEqual((entry["commits"], entry["afterCommit"]), (["reinstate"], False))

    def test_new_step_instantiation_is_a_commit(self):
        self.step("PayThenCheck", "    new MakePayment(ctx).execute();\n    assertEquals(a, b);")
        entry = self.effects()["PayThenCheck"]
        self.assertEqual((entry["commits"], entry["afterCommit"]), (["payment"], True))

    def test_missing_without_package(self):
        os.remove(os.path.join(self.root, "src/main/resources/customer.centertest.properties"))
        self.assertIn("reason", self.scan()["componentEffects"])


if __name__ == "__main__":
    unittest.main()
