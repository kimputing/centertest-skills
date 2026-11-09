import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
PLUGINS = os.path.dirname(PLUGIN)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class DataOverviewTest(unittest.TestCase):
    def setUp(self):
        from refcheck_fixture import build_project, make_xlsx
        self.tmp = tempfile.mkdtemp()
        build_project(self.tmp)
        make_xlsx(os.path.join(self.tmp, "testdata", "wc", "WC_PolicyChangeDC.xlsx"), {
            "DataCombination": [["Code", "Disabled", "Multiplier", "#Company"],
                                ["Once", "", "", "Acme"], ["Thrice", "", "3", "Acme"], ["Off", "True", "", "Acme"]]})
        src = os.path.join(self.tmp, "src", "main", "java", "com", "acme")
        os.makedirs(src)
        with open(os.path.join(src, "PolicyChangeTest.java"), "w") as fh:
            fh.write('@CenterTest\npublic class PolicyChangeTest {\n'
                     '@CenterTestCase\n@DataDriven(datasource = "testdata/wc/WC_PolicyChangeDC.xlsx")\npublic void run() {}\n}\n')
        with open(os.path.join(src, "LoginTest.java"), "w") as fh:
            fh.write("@CenterTest\npublic class LoginTest { @CenterTestCase public void run() {} }\n")
        import rules.rule_ddt as rule_ddt
        rule_ddt._USERS_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_scenarios_count_enabled_rows_times_multiplier_plus_plain_tests(self):
        from eir_data import data_overview
        d = data_overview(self.tmp, "src/main/java")
        self.assertEqual((d["scenarios"], d["disabled"], d["data_driven"], d["test_classes"]), (5, 1, 1, 2))
        # This policy-change DC has no @Submission column, so nothing reaches the submission DC.
        self.assertEqual(d["unread"], ["testdata/wc/WC_SubmissionDC.xlsx"])

    def test_suites_and_unchecked_breaks_are_reported_honestly(self):
        from eir_data import data_overview
        res = os.path.join(self.tmp, "src", "main", "resources")
        os.makedirs(res)
        with open(os.path.join(res, "CenterTestSuiteList.json"), "w") as fh:
            fh.write('{"CenterTestSuites": [{"Name": "Smoke", "List": ["LoginTest"]}]}')
        d = data_overview(self.tmp, "src/main/java", results=[])
        self.assertEqual(d["in_no_suite"]["classes"], ["PolicyChangeTest"])
        self.assertEqual((d["in_no_suite"]["count"], d["in_no_suite"]["of"]), (2, 3))  # Once, Thrice (Multiplier not counted)
        self.assertIsNone(d["broken_live"])  # 14003/14004 not run: not "0"
        import eir_report
        html = eir_report._data_panel_html(d)
        self.assertIn("distinct scenarios no suite runs", html)
        self.assertIn("not checked", html)

    def test_unused_codes_agree_with_the_cleanup_report(self):
        from eir_data import data_overview
        d = data_overview(self.tmp, "src/main/java")
        env = {**os.environ, "CENTERTEST_PROJECT_DIR": self.tmp, "HOME": self.tmp, "USERPROFILE": self.tmp}
        run = subprocess.run([sys.executable, os.path.join(PLUGINS, "ddt-tools", "scripts", "xlsx-cleanup-unused.py")],
                             capture_output=True, text=True, env=env, cwd=self.tmp)
        found = re.search(r"Found (\d+) unused", run.stdout)
        self.assertEqual(d["unused_codes"], int(found.group(1)) if found else 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
