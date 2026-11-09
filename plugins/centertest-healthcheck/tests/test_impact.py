import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from eir_impact import command_for, tests_reaching

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

    def test_a_changed_test_reaches_itself(self):
        self.assertEqual(tests_reaching({"AccountTest"}, SOURCES), {"AccountTest": "AccountTest"})


class CommandTest(unittest.TestCase):
    def test_rows_become_a_code_filter_only_when_the_build_forwards_it(self):
        entry = {"test": "WC_ClaimTest", "codes": ["CA-Claim", "Default"]}
        self.assertEqual(command_for(entry, (True, True)),
                         './gradlew bootRun -PcenterTest="WC_ClaimTest run" -Pfilter="Code=^(CA\\-Claim|Default)$"')
        self.assertIsNone(command_for(entry, (True, False)))
        self.assertEqual(command_for({"test": "X", "codes": []}, (True, False)), './gradlew bootRun -PcenterTest="X run"')


if __name__ == "__main__":
    unittest.main()
