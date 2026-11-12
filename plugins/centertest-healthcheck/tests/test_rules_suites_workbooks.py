import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def _test_class(name, methods=("run",)):
    body = "".join(f"  @CenterTestCase\n  public void {m}(ScenarioContext c) {{ }}\n" for m in methods)
    return f"package com.acme;\n@CenterTest\npublic class {name} {{\n{body}}}\n"


class _Project:
    """A temporary CenterTest project: test classes, a suite file, workbooks."""

    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.config = SimpleNamespace(repository_dir=self.root, source_root="src/main/java")

    def java(self, name, methods=("run",)):
        folder = os.path.join(self.root, "src", "main", "java", "com", "acme")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name + ".java"), "w") as fh:
            fh.write(_test_class(name, methods))

    def suites(self, suites):
        folder = os.path.join(self.root, "src", "main", "resources")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "CenterTestSuiteList.json"), "w") as fh:
            fh.write(json.dumps({"CenterTestSuites": suites}, indent=2))

    def xlsx(self, rel, sheets):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for title, rows in sheets.items():
            ws = wb.create_sheet(title)
            for row in rows:
                ws.append(row)
        wb.save(path)

    def close(self):
        shutil.rmtree(self.root)


class SuiteHygieneTest(unittest.TestCase):
    def setUp(self):
        self.p = _Project()
        for name in ("LoginTest", "LogoutTest", "HO_SubmissionTest", "HO_RenewalTest", "PA_SubmissionTest"):
            self.p.java(name, ("run", "other") if name == "LoginTest" else ("run",))

    def tearDown(self):
        self.p.close()

    def test_26001_repeated_and_covered_entries(self):
        import rules.rule_suite_hygiene as r
        self.p.suites([
            {"Name": "Bad", "List": ["LoginTest", "logintest", "LoginTest run", "LogoutTest"]},
            {"Name": "Narrow", "List": ["LoginTest run", "LoginTest"]},
            {"Name": "Parent", "Suites": ["Child"], "List": ["LogoutTest run"]},
            {"Name": "Child", "List": ["LogoutTest"]},
            {"Name": "Good", "List": ["LoginTest run", "LoginTest other", "Gone"]},
        ])
        rows = r.suite_entry_repeated_or_covered({}, self.p.config).rows
        got = [(row[0], row[1], row[3].rsplit(":", 1)[1]) for row in rows]
        self.assertEqual(got, [("Bad", "logintest", "7"), ("Bad", "LoginTest run", "8"),
                               ("Narrow", "LoginTest run", "15"), ("Parent", "LogoutTest run", "25")])
        self.assertIn("repeats entry 'LoginTest' (line 6)", rows[0][2])
        self.assertIn("reported as a failed scenario", rows[1][2])
        self.assertIn("adds nothing", rows[2][2])        # the narrower entry comes first: CenterTest credits it
        self.assertNotIn("failed scenario", rows[2][2])
        self.assertIn("child suite 'Child'", rows[3][2])

    def test_26002_full_run_suite_that_misses_a_sibling(self):
        import rules.rule_suite_hygiene as r
        self.p.suites([
            {"Name": "RegressionSuite", "Suites": ["Login"]},
            {"Name": "PC_Regression", "Suites": ["Login"]},     # qualified: a deliberate part, not compared
            {"Name": "Login", "List": ["LoginTest"]},
            {"Name": "Logout", "List": ["LogoutTest"]},
            {"Name": "LoginAgain", "List": ["LoginTest run"]},  # fully inside the aggregate
            {"Name": "Both", "List": ["LogoutTest", "LoginTest"]},
        ])
        rows = r.aggregate_suite_misses_siblings({}, self.p.config).rows
        # Logout and Both miss the same scenario: the suite missed most completely (Logout) is kept
        self.assertEqual([(row[0], row[1], row[2]) for row in rows], [("RegressionSuite", "Logout", "LogoutTest")])
        self.assertTrue(rows[0][4].endswith("CenterTestSuiteList.json:4"))

    def test_26003_names_that_say_nothing(self):
        import rules.rule_suite_hygiene as r
        self.p.suites([
            {"Name": "Regression1", "List": ["LoginTest"]},
            {"Name": "Regression2", "List": ["LogoutTest"]},
            {"Name": "Regression", "List": ["HO_SubmissionTest", "HO_RenewalTest"]},
            {"Name": "Release2024", "List": ["LoginTest"]},                 # a lone number: a version
            {"Name": "HO_Regression", "List": ["HO_SubmissionTest", "HO_RenewalTest"]},
            {"Name": "FullRegression", "List": ["HO_SubmissionTest", "PA_SubmissionTest"]},
        ])
        rows = r.suite_name_says_nothing({}, self.p.config).rows
        self.assertEqual([row[0] for row in rows], ["Regression1", "Regression2", "Regression"])
        self.assertIn("every test it runs is a HO_ test", rows[2][2])

    def test_26004_cycles(self):
        import rules.rule_suite_hygiene as r
        self.p.suites([
            {"Name": "A", "Suites": ["B"]},
            {"Name": "B", "Suites": ["A"], "List": ["LoginTest"]},
            {"Name": "C", "Suites": ["C"]},
            {"Name": "D", "Suites": ["E", "e"]},   # "e" is not E for CenterTest: no cycle back through it
            {"Name": "E", "Suites": ["d"]},
        ])
        rows = r.suite_includes_itself({}, self.p.config).rows
        self.assertEqual([(row[0], row[1]) for row in rows], [("A", "A -> B -> A"), ("C", "C -> C")])

    def test_no_suite_file(self):
        import rules.rule_suite_hygiene as r
        for fn in (r.suite_entry_repeated_or_covered, r.aggregate_suite_misses_siblings,
                   r.suite_name_says_nothing, r.suite_includes_itself):
            res = fn({}, self.p.config)
            self.assertEqual((res.rows, res.error), ([], None))


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class WorkbookRulesTest(unittest.TestCase):
    def setUp(self):
        self.p = _Project()
        self.p.java("DriverTest")

    def tearDown(self):
        self.p.close()

    def test_27001_header_casing(self):
        import rules.rule_workbooks as r
        self.p.xlsx("testdata/a/A_DC.xlsx", {"DataCombination": [["Code", "Disabled", "Composite Rating"], ["x", "", ""]]})
        self.p.xlsx("testdata/a/B_DC.xlsx", {"DataCombination": [["Code", "Disabled", "CompositeRating"], ["x", "", ""]]})
        self.p.xlsx("testdata/a/C_DC.xlsx", {"DataCombination": [["Code", "disabled"], ["x", ""]]})
        self.p.xlsx("testdata/a/~$C_DC.xlsx", {"DataCombination": [["CODE"], ["x"]]})  # lock file: skipped
        rows = r.header_casing_drift({}, self.p.config).rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Disabled")
        self.assertEqual(rows[0][1], "'Disabled' (2 sheets), 'disabled' (1 sheet)")
        self.assertEqual(rows[0][4], "testdata/a/C_DC.xlsx:1")

    def test_27002_duplicate_codes(self):
        import rules.rule_workbooks as r
        self.p.xlsx("testdata/Data.xlsx", {
            "Dwelling": [["Code", "Type"], ["PE_Default", "Homeowners"], ["Coupe", "a"], ["Coupe(2)", "b"],
                         ["pe_default ", "Condo"]],
            "Notes": [["Name"], ["same"], ["same"]],     # no Code column: not keyed
        })
        rows = r.duplicate_code_in_sheet({}, self.p.config).rows
        self.assertEqual([row[:5] for row in rows], [["testdata/Data.xlsx", "Dwelling", 2, "Code", "PE_Default"]])
        self.assertIn("keeps only the last (row 5), so row 2 is silently ignored", rows[0][5])
        self.assertEqual(rows[0][7], "testdata/Data.xlsx:2")

    def _reference_project(self):
        self.p.xlsx("testdata/Data.xlsx", {"Driver": [["Code", "Name"], ["NS_JohnTeen", "a"], ["Exact", "b"]]})
        self.p.xlsx("testdata/pa/PA_SeedDC.xlsx", {
            "DataCombination": [["Code", "#Driver", "#Driver.Name", "Description"],
                                ["r1", "NS_Johnteen, Exact", "x", "fine "],
                                ["r2", "Missing", "", ""],
                                ["r3", "Exact, ", "", ""],
                                ["r4", " Exact", "a,,b", ""]],
            "References": [["Location"], ["../Data.xlsx"]],
        })

    def test_27003_reference_differs_only_by_case(self):
        import rules.rule_workbooks as r
        self._reference_project()
        rows = r.reference_differs_only_by_case({}, self.p.config).rows
        self.assertEqual([row[:5] for row in rows], [["testdata/pa/PA_SeedDC.xlsx", "DataCombination", 2, "#Driver", "NS_Johnteen"]])
        self.assertIn("names row 'NS_JohnTeen' (Data.xlsx row 2)", rows[0][5])
        self.assertIn("so it resolves", rows[0][5])

    def test_27004_whitespace(self):
        import rules.rule_workbooks as r
        self._reference_project()
        self.p.xlsx("testdata/Cov.xlsx", {"Coverage": [
            ["Code", "Coverage", "CovTerm", "RawText", "#A<>#B"],
            ["c1", "Specified Perils ", "\tDwelling Limit", "SP   2023  SPEEDING", "x:  a,\ny:  b"],
            ["c2", "Liability", "Limit", "ok", ""],
            ["c3", "Bodily Injury", "Per\tPerson", "", ""],
        ]})
        rows = r.whitespace_defects_in_cells({}, self.p.config).rows
        got = [(os.path.basename(row[0]), row[2], row[3]) for row in rows]
        self.assertEqual(got, [("Cov.xlsx", 2, "Coverage"), ("Cov.xlsx", 2, "CovTerm"),
                               ("Cov.xlsx", 4, "Coverage"), ("Cov.xlsx", 4, "CovTerm"),
                               ("PA_SeedDC.xlsx", 4, "#Driver"), ("PA_SeedDC.xlsx", 5, "#Driver")])
        issues = {(os.path.basename(row[0]), row[2], row[3]): row[5] for row in rows}
        self.assertTrue(issues[("Cov.xlsx", 2, "Coverage")].startswith("trailing space: CenterTest trims cells"))
        self.assertTrue(issues[("Cov.xlsx", 2, "CovTerm")].startswith("leading tab"))
        self.assertIn("U+00A0", issues[("Cov.xlsx", 4, "Coverage")])
        self.assertIn("tab reaches the application", issues[("Cov.xlsx", 4, "CovTerm")])
        self.assertTrue(issues[("PA_SeedDC.xlsx", 4, "#Driver")].startswith("has an empty item"))
        self.assertTrue(issues[("PA_SeedDC.xlsx", 5, "#Driver")].startswith("leading space"))
        self.assertEqual(rows[0][4], "'Specified Perils '")


if __name__ == "__main__":
    unittest.main()
