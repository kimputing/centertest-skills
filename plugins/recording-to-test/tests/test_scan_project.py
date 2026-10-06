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


if __name__ == "__main__":
    unittest.main()
