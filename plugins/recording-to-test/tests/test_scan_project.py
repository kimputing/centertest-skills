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
        return sp.scan(self.root, gradle_home=self.gradle, m2_home=self.m2, **kwargs)


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
                                           "flowTags": "Application.PC", "count": 3}])

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


if __name__ == "__main__":
    unittest.main()
