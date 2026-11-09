import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from eir_reach import ASSERTION, CodeIndex

try:
    import javalang  # noqa: F401
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False

CODE = {
    "BC": """public final class BC {
    public static AssertDisbursement assertDisbursement(Ctx c) { return new AssertDisbursement(c); }
    public static CreateAccount createAccount(Ctx c) { return new CreateAccount(c); }
}""",
    "AssertDisbursement": """public class AssertDisbursement extends BaseStep {
    public void execute() { var page = new DisbursementPage(getContext()); page.getAmount().assertEquals("10"); }
}""",
    "CreateAccount": """public class CreateAccount extends BaseStep {
    public void execute() { var page = new AccountPage(getContext()); page.getName().setValue("x"); }
}""",
    "Checker": """public class Checker {
    public void check(String v) { if (!"ok".equals(v)) { throw new EnvironmentalException("not ok"); } }
}""",
    "BaseStep": "public abstract class BaseStep { }",
    "VerifiedTest": """@CenterTest
public final class VerifiedTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { BC.assertDisbursement(c).execute(); }
}""",
    "ClicksOnlyTest": """@CenterTest
public final class ClicksOnlyTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { BC.createAccount(c).execute(); }
}""",
    "HelperFieldTest": """@CenterTest
public final class HelperFieldTest {
    private final Checker checker = new Checker();
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { BC.createAccount(c).execute(); checker.check(v); }
}""",
    "ClockToolTest": """@CenterTest
public final class ClockToolTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) { Ansible.moveClock(3); }
}""",
}


class ReachTest(unittest.TestCase):
    def setUp(self):
        self.index = CodeIndex(CODE)

    def test_a_facade_lends_only_the_called_method(self):
        self.assertEqual(self.index.assertions_reached("VerifiedTest"), 1)
        self.assertEqual(self.index.assertions_reached("ClicksOnlyTest"), 0)

    def test_a_helper_held_in_a_field_counts(self):
        self.assertEqual(self.index.assertions_reached("HelperFieldTest"), 1)

    def test_guard_throws_count_but_rethrows_and_argument_checks_do_not(self):
        self.assertTrue(ASSERTION.search('throw new EnvironmentalException("Funds Tracking is off");'))
        self.assertFalse(ASSERTION.search("throw new RuntimeException(e.getMessage(), e);"))
        self.assertFalse(ASSERTION.search('throw new IllegalArgumentException("Neither person nor company");'))


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class Rule9010Test(unittest.TestCase):
    def test_only_screen_driving_tests_without_checks_are_reported(self):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        import rules.rule_centertest as rc
        tmp = tempfile.mkdtemp()
        try:
            folder = os.path.join(tmp, "src", "main", "java", "com", "acme")
            os.makedirs(folder)
            for name, body in CODE.items():
                with open(os.path.join(folder, name + ".java"), "w") as fh:
                    fh.write("package com.acme;\n\n" + body + "\n")
            files = parse_directory(tmp, "src/main/java", [], [], True, None)
            result = rc.tests_that_verify_nothing({LOCAL_COMMIT: files},
                                                  SimpleNamespace(repository_dir=tmp, source_root="src/main/java"))
            self.assertEqual([(r[0].split(".")[-1], r[1]) for r in result.rows], [("ClicksOnlyTest", "run")])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
