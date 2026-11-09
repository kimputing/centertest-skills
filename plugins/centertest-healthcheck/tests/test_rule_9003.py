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

TESTS = {
    # Loads a row by code: needs no @DataDriven (the 38 false alarms on a real suite were all this).
    "ByCodeTest": """@CenterTest
public final class ByCodeTest {
    @CenterTestCase()
    public void run(ScenarioContext scenarioContext) {
        var data = DDTHelper.getWorkerscompWC_ClaimDC("CA-Claim");
    }
}""",
    # Reads the scenario's row but nothing makes the test data-driven: cannot run.
    "NoDataTest": """@CenterTest
public final class NoDataTest {
    @CenterTestCase()
    public void run(ScenarioContext ctx) {
        var data = DDTHelper.getWorkerscompWC_ClaimDC(ctx);
    }
}""",
    "DataDrivenTest": """@CenterTest
public final class DataDrivenTest {
    @CenterTestCase()
    @DataDriven(datasource = "testdata/WC_ClaimDC.xlsx")
    public void run(ScenarioContext scenarioContext) {
        var data = DDTHelper.getWorkerscompWC_ClaimDC(scenarioContext);
    }
}""",
}


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class Rule9003Test(unittest.TestCase):
    def test_only_a_scenario_data_read_without_datadriven_is_reported(self):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        import rules.rule_centertest as rc
        tmp = tempfile.mkdtemp()
        try:
            folder = os.path.join(tmp, "src", "main", "java", "com", "acme", "tests")
            os.makedirs(folder)
            for name, body in TESTS.items():
                with open(os.path.join(folder, name + ".java"), "w") as fh:
                    fh.write("package com.acme.tests;\n\n" + body + "\n")
            files = parse_directory(tmp, "src/main/java", [], [], True, None)
            result = rc.data_driven_patterns({LOCAL_COMMIT: files}, SimpleNamespace(repository_dir=tmp))
            self.assertEqual([(r[0].split(".")[-1], r[1]) for r in result.rows], [("NoDataTest", "run")])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
