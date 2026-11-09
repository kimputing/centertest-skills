import filecmp
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))


class Rule14005Test(unittest.TestCase):
    def test_entries_that_match_no_test_and_missing_child_suites(self):
        import rules.rule_suites as rs
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "src", "main", "java", "com", "acme")
            os.makedirs(src)
            with open(os.path.join(src, "LoginTest.java"), "w") as fh:
                fh.write("@CenterTest\npublic class LoginTest {\n  @CenterTestCase\n  public void run(ScenarioContext c) { }\n}\n")
            res = os.path.join(tmp, "src", "main", "resources")
            os.makedirs(res)
            doc = {"CenterTestSuites": [{"Name": "Smoke", "List": ["logintest RUN", "LoginTest renamedMethod"]},
                                        {"Name": "All", "Suites": ["Smoke", "Gone"]}]}
            with open(os.path.join(res, "CenterTestSuiteList.json"), "w") as fh:
                fh.write(json.dumps(doc, indent=2))
            rows = rs.suite_entries_that_run_nothing({}, SimpleNamespace(repository_dir=tmp, source_root="src/main/java")).rows
            self.assertEqual([(r[0], r[1], r[3]) for r in rows],
                             [("Smoke", "LoginTest renamedMethod", "src/main/resources/CenterTestSuiteList.json:7"),
                              ("All", "Gone", "src/main/resources/CenterTestSuiteList.json:14")])
        finally:
            shutil.rmtree(tmp)


class Rule9011Test(unittest.TestCase):
    def test_a_data_driven_test_with_no_enabled_rows(self):
        import rules.rule_suites as rs
        sys.path.insert(0, os.path.join(os.path.dirname(PLUGIN), "suite-builder", "tests"))
        from xlsx_fixture import make_xlsx
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "src", "main", "java", "a")
            os.makedirs(src)
            with open(os.path.join(src, "ParkedTest.java"), "w") as fh:
                fh.write('@CenterTest\npublic class ParkedTest {\n  @CenterTestCase\n'
                         '  @DataDriven(datasource = "testdata/ParkedDC.xlsx")\n  public void run(ScenarioContext c) { }\n}\n')
            os.makedirs(os.path.join(tmp, "testdata"))
            make_xlsx(os.path.join(tmp, "testdata", "ParkedDC.xlsx"), {"DataCombination": [["Code", "Disabled"], ["a", "True"]]})
            rows = rs.tests_with_no_enabled_rows({}, SimpleNamespace(repository_dir=tmp, source_root="src/main/java")).rows
            self.assertEqual(rows, [["ParkedTest", "run", "every row of ParkedDC.xlsx is disabled: the test runs nothing"]])
        finally:
            shutil.rmtree(tmp)


class VendoredSuiteEngineTest(unittest.TestCase):
    def test_vendored_copies_match_suite_builder(self):
        for name in ("suite.py", "xlsx_read.py"):
            self.assertTrue(
                filecmp.cmp(os.path.join(PLUGIN, "scripts", name),
                            os.path.join(os.path.dirname(PLUGIN), "suite-builder", "scripts", name), shallow=False),
                f"plugins/centertest-healthcheck/scripts/{name} must be an unchanged copy of "
                f"plugins/suite-builder/scripts/{name}; copy it again with cp")


if __name__ == "__main__":
    unittest.main()
