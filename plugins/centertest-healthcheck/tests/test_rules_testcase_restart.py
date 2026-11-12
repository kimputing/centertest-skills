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

HEAD = """package com.acme.tests;
import com.ankrpt.centertest.annotation.CenterTest;
import com.ankrpt.centertest.annotation.CenterTestCase;
import com.ankrpt.centertest.runner.context.ScenarioContext;
"""

FACADE = """package com.acme.reusable;
public interface PC {
    static LoginToPC loginToPC(Object ctx) { return new LoginToPC(ctx); }
    static CreateAccount createAccount(Object ctx) { return new CreateAccount(ctx); }
    static SearchPolicy searchForPolicyPC(Object ctx) { return new SearchPolicy(ctx); }
}
"""

TESTS = {
    # ---- 9012
    "AddVehicleTest": HEAD + """@CenterTest
public final class AddVehicleTest {
    @CenterTestCase(testCaseId = "PC_Auto_AddVehicle")
    public void run(ScenarioContext scenarioContext) { }
}
""",
    "SubstituteVehicleTest": HEAD + """@CenterTest
public final class SubstituteVehicleTest {
    @CenterTestCase(testCaseId = "PC_Auto_AddVehicle")
    public void run(ScenarioContext scenarioContext) { }
}
""",
    "UniqueIdTest": HEAD + """@CenterTest
public final class UniqueIdTest {
    @CenterTestCase(testCaseId = "PC_Auto_Unique")
    public void run(ScenarioContext scenarioContext) { }
}
""",
    "NoIdTest": HEAD + """@CenterTest
public final class NoIdTest {
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) { }
}
""",
    # ---- 9013
    "PrivateRunTest": HEAD + """@CenterTest
public final class PrivateRunTest {
    @CenterTestCase
    void run(ScenarioContext ctx) { }
}
""",
    "NoParamTest": HEAD + """@CenterTest
public final class NoParamTest {
    @CenterTestCase
    public void run() { }
}
""",
    "NoCaseTest": HEAD + """@CenterTest
public final class NoCaseTest {
    public void run(ScenarioContext ctx) { }
}
""",
    "PackageTest": HEAD + """@CenterTest
final class PackageTest {
    @CenterTestCase
    public void run(ScenarioContext ctx) { }
}
""",
    "ArgCtorTest": HEAD + """@CenterTest
public final class ArgCtorTest {
    private final String name;
    public ArgCtorTest(String name) { this.name = name; }
    @CenterTestCase
    public void run(ScenarioContext ctx) { }
}
""",
    "AbstractBaseTest": HEAD + """@CenterTest
public abstract class AbstractBaseTest {
    public void helper(ScenarioContext ctx) { }
}
""",
    "AnyNameTest": HEAD + """@CenterTest
public final class AnyNameTest {
    public AnyNameTest() { }
    @CenterTestCase
    public static void submission(ScenarioContext scenarioContext) { }
    @CenterTestCase
    public void other(Object ctx) { }
}
""",
    # ---- 9014
    "FieldTest": HEAD + """@CenterTest
public final class FieldTest {
    private static final org.slf4j.Logger logger = null;
    private org.slf4j.Logger log2;
    private InvocationContext context;
    private int count;
    private java.util.List<String> names = new java.util.ArrayList<>();
    private String product = "PA";
    private String fromCtor;
    @Autowired private Object injected;
    public FieldTest() { fromCtor = "x"; }
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        context = scenarioContext.getInvocationContext("producer");
        count++;
        names.add(product);
        String fromCtor = "local";
        injected = null;
    }
}
""",
    "CleanFieldTest": HEAD + """@CenterTest
public final class CleanFieldTest {
    private static final String USER = "producer";
    private final String fixed = "x";
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        var producer = scenarioContext.getInvocationContext(USER);
    }
}
""",
    # ---- 16001
    "LoginInBlockTest": HEAD + """import com.acme.reusable.PC;
@CenterTest
public final class LoginInBlockTest {
    private enum RestartPoints {POLICY}
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        var producer = scenarioContext.getInvocationContext("producer");
        if (scenarioContext.restart(RestartPoints.POLICY)) {
            PC.loginToPC(producer).execute();
            PC.createAccount(producer).execute();
            scenarioContext.restartComplete(RestartPoints.POLICY);
        }
        PC.searchForPolicyPC(producer).execute();
    }
}
""",
    "LoginBeforeBlockTest": HEAD + """import com.acme.reusable.PC;
@CenterTest
public final class LoginBeforeBlockTest {
    private enum RestartPoints {POLICY}
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        var producer = scenarioContext.getInvocationContext("producer");
        var su = scenarioContext.getInvocationContext("su");
        if (scenarioContext.restart(RestartPoints.POLICY)) {
            PC.loginToPC(producer).execute();
            PC.createAccount(producer).execute();
            scenarioContext.restartComplete(RestartPoints.POLICY);
        }
        CC.loginToCC(su).execute();
        CC.createClaim(su).execute();
    }
}
""",
    "LoginInElseTest": HEAD + """import com.acme.reusable.PC;
@CenterTest
public final class LoginInElseTest {
    private enum RestartPoints {POLICY}
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        var producer = scenarioContext.getInvocationContext("producer");
        if (scenarioContext.restart(RestartPoints.POLICY)) {
            PC.loginToPC(producer).execute();
            PC.createAccount(producer).execute();
            scenarioContext.restartComplete(RestartPoints.POLICY);
        } else {
            PC.loginToPC(producer).execute();
        }
        PC.searchForPolicyPC(producer).execute();
    }
}
""",
    # ---- 16002 / 16003
    "WrongCompleteTest": HEAD + """@CenterTest
public final class WrongCompleteTest {
    private enum RestartPoints {ACCOUNT, POLICY}
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        if (scenarioContext.restart(RestartPoints.ACCOUNT)) {
            step();
            scenarioContext.restartComplete(RestartPoints.ACCOUNT);
        }
        if (scenarioContext.restart(RestartPoints.POLICY)) {
            step();
            scenarioContext.restartComplete(RestartPoints.ACCOUNT);
        }
    }
    void step() { }
}
""",
    "NeverCompleteTest": HEAD + """@CenterTest
public final class NeverCompleteTest {
    private enum RestartPoints {ACCOUNT, POLICY, UNUSED}
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        if (scenarioContext.restart(RestartPoints.ACCOUNT)) {
            step();
        }
        if (scenarioContext.restart(RestartPoints.POLICY, RestartPolicy.DISABLE_ON_FAILURE)) {
            step();
            scenarioContext.restartComplete(RestartPoints.POLICY);
        }
    }
    void step() { }
}
""",
    "WrapperTest": HEAD + """@CenterTest
public final class WrapperTest {
    private enum RestartPoints {ACCOUNT, POLICY}
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        block(scenarioContext, RestartPoints.ACCOUNT);
        block(scenarioContext, RestartPoints.POLICY);
    }
    void block(ScenarioContext ctx, RestartPoints point) {
        if (ctx.restart(point)) { ctx.restartComplete(point); }
    }
}
""",
    "DeadEnumTest": HEAD + """@CenterTest
public final class DeadEnumTest {
    private enum RestartPoints {ACCOUNT}
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) { }
}
""",
    # ---- 16004
    "LongFlowTest": HEAD + """import com.acme.reusable.PC;
@CenterTest
public final class LongFlowTest {
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        var producer = scenarioContext.getInvocationContext("producer");
        PC.loginToPC(producer).execute();
        PC.createAccount(producer).execute();
        PC.createAccount(producer).execute();
        // PC.createAccount(producer).execute();
        PC.searchForPolicyPC(producer).execute();
    }
}
""",
    "ShortFlowTest": HEAD + """import com.acme.reusable.PC;
@CenterTest
public final class ShortFlowTest {
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
        var producer = scenarioContext.getInvocationContext("producer");
        PC.loginToPC(producer).execute();
        PC.createAccount(producer).execute();
        PC.searchForPolicyPC(producer).execute();
    }
}
""",
}


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class TestcaseRestartRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        cls.tmp = tempfile.mkdtemp()
        tests = os.path.join(cls.tmp, "src", "main", "java", "com", "acme", "tests")
        reusable = os.path.join(cls.tmp, "src", "main", "java", "com", "acme", "reusable")
        os.makedirs(tests)
        os.makedirs(reusable)
        with open(os.path.join(reusable, "PC.java"), "w") as fh:
            fh.write(FACADE)
        for name, code in TESTS.items():
            with open(os.path.join(tests, name + ".java"), "w") as fh:
                fh.write(code)
        files = parse_directory(cls.tmp, "src/main/java", [], [], True, None)
        cls.commits = {LOCAL_COMMIT: files}
        cls.config = SimpleNamespace(repository_dir=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def rows(self, func, config=None):
        return func(self.commits, config or self.config).rows

    def test_9012_shared_test_case_id(self):
        import rules.rule_testcase as rt
        rows = self.rows(rt.shared_test_case_ids)
        self.assertEqual(sorted(r[0] for r in rows), ["AddVehicleTest", "SubstituteVehicleTest"])
        self.assertIn("SubstituteVehicleTest.run", rows[0][3])
        self.assertTrue(rows[0][4].endswith("AddVehicleTest.java:7"), rows[0][4])

    def test_9013_unrunnable_classes(self):
        import rules.rule_testcase as rt
        rows = self.rows(rt.unrunnable_test_classes)
        flagged = sorted(r[0] for r in rows)
        self.assertEqual(flagged, ["ArgCtorTest", "NoCaseTest", "NoParamTest", "PackageTest", "PrivateRunTest"])
        by = {r[0]: r for r in rows}
        self.assertIn("not public", by["PrivateRunTest"][3])
        self.assertIn("no parameters", by["NoParamTest"][3])
        self.assertIn("no @CenterTestCase method", by["NoCaseTest"][3])
        self.assertIn("no no-arg constructor", by["ArgCtorTest"][3])

    def test_9014_mutable_fields(self):
        import rules.rule_testcase as rt
        rows = self.rows(rt.mutable_test_class_fields)
        self.assertEqual(sorted(r[2] for r in rows), [
            "private InvocationContext context;", "private int count;",
            "private java.util.List<String> names = new java.util.ArrayList<>();"])
        self.assertTrue(all(r[0] == "FieldTest" and r[1] == "run" for r in rows))

    def test_16001_login_inside_restart_block(self):
        import rules.rule_restart as rr
        rows = self.rows(rr.login_inside_restart_block)
        self.assertEqual([(r[0], r[2]) for r in rows], [("LoginInBlockTest", "PC.loginToPC(producer).execute();")])
        self.assertTrue(rows[0][4].endswith("LoginInBlockTest.java:13"), rows[0][4])

    def test_16002_restart_without_complete(self):
        import rules.rule_restart as rr
        rows = self.rows(rr.restart_without_complete)
        got = sorted((r[0], r[2]) for r in rows)
        self.assertEqual(got, [("NeverCompleteTest", "if (scenarioContext.restart(RestartPoints.ACCOUNT)) {"),
                               ("WrongCompleteTest", "if (scenarioContext.restart(RestartPoints.POLICY)) {")])
        by = {r[0]: r[3] for r in rows}
        self.assertIn("completed as restartComplete(ACCOUNT)", by["WrongCompleteTest"])
        self.assertIn("no restartComplete(ACCOUNT)", by["NeverCompleteTest"])

    def test_16003_unused_restart_points(self):
        import rules.rule_restart as rr
        rows = self.rows(rr.unused_restart_points)
        self.assertEqual(sorted((r[0], r[1]) for r in rows),
                         [("DeadEnumTest", "RestartPoints.ACCOUNT"), ("NeverCompleteTest", "RestartPoints.UNUSED")])
        self.assertTrue(all(r[4].endswith(".java:7") for r in rows), [r[4] for r in rows])

    def test_16004_long_flow_without_restart(self):
        import rules.rule_restart as rr
        rows = self.rows(rr.long_flow_without_restart)
        self.assertEqual([r[0] for r in rows], ["LongFlowTest"])
        self.assertIn("4 steps", rows[0][3])
        lower = SimpleNamespace(repository_dir=self.tmp, get_threshold=lambda rid, d: 3)
        self.assertEqual(sorted(r[0] for r in self.rows(rr.long_flow_without_restart, lower)),
                         ["LongFlowTest", "ShortFlowTest"])


if __name__ == "__main__":
    unittest.main()
