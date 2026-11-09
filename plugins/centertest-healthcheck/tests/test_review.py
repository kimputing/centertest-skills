import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(PLUGIN), "ddt-tools", "tests"))

try:
    import openpyxl  # noqa: F401
    import javalang  # noqa: F401
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from eir_models import RuleResult, Section

CLEAN = """package com.acme.tests;

public class DelinquencyCheck {
    public void validate(String shown, String expected) {
        if (!shown.equals(expected)) {
            throw new AssertionError(shown);
        }
    }
}
"""
SILENT = CLEAN.replace("        if (!shown.equals(expected)) {\n            throw new AssertionError(shown);\n        }\n",
                       "        shown.equals(expected);\n")

READER = """package com.acme.tests;

@CenterTest
public final class PolicyChangeTest {
    @CenterTestCase()
    @DataDriven(datasource = "testdata/wc/WC_PolicyChangeDC.xlsx")
    public void run(ScenarioContext scenarioContext) {
    }
}
"""


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class DiffPairTest(unittest.TestCase):
    def test_a_long_cell_shows_where_it_changed(self):
        from eir_review import _diff_pair
        old = "Waiver Type:Schedule Waiver,Holder:TestCo,Location:Retail - Texas"
        new = "Waiver Type:Schedule Waiver,Holder:TestCo,Location:Retail - California"
        self.assertEqual(_diff_pair(old, new), ("…on:Retail - Texas", "…on:Retail - California"))
        self.assertEqual(_diff_pair("a", "b"), ("a", "b"))


class FindingKeysTest(unittest.TestCase):
    def test_counts_inside_grouped_items_do_not_make_a_new_finding(self):
        from eir_review import finding_keys
        before = RuleResult("4001", "d", "Methods", sections=[Section("Commit local", items=["A.run: 2x — x()"])])
        after = RuleResult("4001", "d", "Methods", sections=[Section("Commit local", items=["A.run: 3x — x()"])])
        self.assertEqual(finding_keys(before), finding_keys(after))

    def test_workbook_row_numbers_do_not_make_a_new_finding(self):
        from eir_review import finding_keys
        headers = ["File", "Row", "Column", "Code", "Issue"]
        a = RuleResult("14003", "d", "CenterTest", headers=headers, rows=[["f.xlsx", 3, "#C", "X", "code not found"]])
        b = RuleResult("14003", "d", "CenterTest", headers=headers, rows=[["f.xlsx", 9, "#C", "X", "code not found"]])
        self.assertEqual(finding_keys(a), finding_keys(b))


@unittest.skipUnless(HAS_DEPS, "openpyxl and javalang required")
class BranchReviewTest(unittest.TestCase):
    def setUp(self):
        from refcheck_fixture import build_project, make_xlsx
        self.repo = tempfile.mkdtemp()
        build_project(self.repo)
        # The base is clean: drop the fixture's broken policy-change rows.
        make_xlsx(os.path.join(self.repo, "testdata", "wc", "WC_PolicyChangeDC.xlsx"),
                  {"DataCombination": [["Code", "@Submission", "#Company"], ["Ok", "Default", "Acme"]]})
        java = os.path.join(self.repo, "src", "main", "java", "com", "acme", "tests")
        os.makedirs(java)
        self.java_file = os.path.join(java, "DelinquencyCheck.java")
        with open(self.java_file, "w") as fh:
            fh.write(CLEAN)
        with open(os.path.join(java, "PolicyChangeTest.java"), "w") as fh:
            fh.write(READER)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        git(self.repo, "checkout", "-q", "-b", "feature")
        with open(self.java_file, "w") as fh:
            fh.write(SILENT)
        make_xlsx(os.path.join(self.repo, "testdata", "wc", "WC_PolicyChangeDC.xlsx"),
                  {"DataCombination": [["Code", "@Submission", "#Company"], ["Ok", "Default", "Acme"],
                                       ["New", "Default", "Ghost"]]})
        git(self.repo, "commit", "-q", "-am", "feature")
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.repo)
        shutil.rmtree(self.out)

    def review(self, base, head):
        cmd = [sys.executable, os.path.join(PLUGIN, "scripts", "eir_analyzer.py"), "--path", self.repo,
               "--rules", "14002,14003,14004,15005,15018", "--review", base, head]
        env = {**os.environ, "HOME": self.out}  # keep ~/.centertest out of the user's home
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def test_branch_that_adds_blockers_is_sent_back(self):
        run = self.review("main", "feature")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("Changes requested: this branch introduces 2 trust blockers", run.stdout)
        md_dir = os.path.join(self.repo, "healthcheck")
        with open(os.path.join(md_dir, sorted(f for f in os.listdir(md_dir) if f.endswith(".md"))[0]), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("DelinquencyCheck.validate (src/main/java/com/acme/tests/DelinquencyCheck.java:5): shown.equals(expected);", md)
        self.assertIn("WC_PolicyChangeDC.xlsx row 3: #Company 'Ghost' (in PolicyChangeTest)", md)
        self.assertIn("- `WC_PolicyChangeDC.xlsx › DataCombination`: added **New**", md)
        # The changed row, not the whole workbook, is what to rerun.
        self.assertIn("**PolicyChangeTest** — rows New (WC_PolicyChangeDC.xlsx rows changed)", md)

    def test_suite_changes_say_what_the_run_gains_and_what_adds_nothing(self):
        res = os.path.join(self.repo, "src", "main", "resources")
        os.makedirs(res)
        path = os.path.join(res, "CenterTestSuiteList.json")
        with open(path, "w") as fh:
            fh.write('{"CenterTestSuites": [{"Name": "Smoke", "List": ["DelinquencyCheck"]}]}')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "suite")
        with open(path, "w") as fh:
            fh.write('{"CenterTestSuites": [{"Name": "Smoke", "List": ["DelinquencyCheck", "PolicyChangeTest", '
                     '"PolicyChangeTest run", "GhostTest"]}]}')
        git(self.repo, "commit", "-q", "-am", "suite edit")
        run = self.review("HEAD~1", "HEAD")
        self.assertIn("## suite Smoke: 0 -> 2 scenarios, 1 entry adds nothing, 1 match no test", run.stdout)
        md_dir = os.path.join(self.repo, "healthcheck")
        with open(os.path.join(md_dir, sorted(f for f in os.listdir(md_dir) if f.endswith(".md"))[-1]), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("`PolicyChangeTest run` adds nothing", md)
        self.assertIn("`GhostTest` matches no test", md)

    def test_the_fix_reads_as_fixed_not_new(self):
        from refcheck_fixture import make_xlsx
        with open(self.java_file, "w") as fh:
            fh.write(CLEAN)
        make_xlsx(os.path.join(self.repo, "testdata", "wc", "WC_PolicyChangeDC.xlsx"),
                  {"DataCombination": [["Code", "@Submission", "#Company"], ["Ok", "Default", "Acme"]]})
        git(self.repo, "commit", "-q", "-am", "fix")
        run = self.review("feature~1", "feature")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Clean: no new findings; 2 fixed.", run.stdout)


if __name__ == "__main__":
    unittest.main()
