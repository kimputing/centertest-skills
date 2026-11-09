import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))

import eir_cover  # noqa: E402

try:
    from refcheck_fixture import make_xlsx  # openpyxl: the reference walk reads it
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

TYPELIST = """public class TC_Jurisdiction extends TypeCode {
public static TC_Jurisdiction AZ() { return new TC_Jurisdiction("AZ", "Arizona", false); }
public static TC_Jurisdiction TX() { return new TC_Jurisdiction("TX", "Texas", false); }
}
"""
MODEL = [{"codeIdentifier": "GLLiquor", "name": "Liquor Liability"},
         {"codeIdentifier": "GLPollution", "name": "Pollution"},
         {"codeIdentifier": "GLNever", "name": "Never Selected"}]


def test_class(name, datasource):
    return f"""package com.x.tests;
@CenterTest
public final class {name} {{
    @CenterTestCase()
    @DataDriven(datasource = "{datasource}")
    public void run(ScenarioContext scenarioContext) {{ }}
}}"""


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class CoveringSuite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = os.path.join(self.tmp.name, "proj")
        main = os.path.join(self.tmp.name, "gen", "src", "main")
        self.cssids = os.path.join(main, "resources", "cssids")
        os.makedirs(os.path.join(self.cssids, "pc"))
        with open(os.path.join(main, "resources", "GLLine_coverage_structure.json"), "w") as fh:
            json.dump(MODEL, fh)
        typelist = os.path.join(main, "java", "com", "x", "generated", "typelist", "pc")
        os.makedirs(typelist)
        with open(os.path.join(typelist, "TC_Jurisdiction.java"), "w") as fh:
            fh.write(TYPELIST)
        os.makedirs(os.path.join(root, "testdata", "gl"))
        with open(os.path.join(root, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
            json.dump({"$references": {"testdata/GLData.xlsx": ["testdata/gl/.*DC\\.xlsx"]}}, fh)
        make_xlsx(os.path.join(root, "testdata", "GLData.xlsx"), {
            "Coverage": [["Code", "Coverage"], ["liq", "Liquor Liability"], ["pol", "Pollution"]],
            "Address": [["Code", "State"], ["phx", "AZ"], ["aus", "Texas"]]})
        make_xlsx(os.path.join(root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "#Coverage", "#Address", "Disabled"],
            ["A", "liq", "phx", ""], ["B", "pol", "phx", ""], ["C", "liq,pol", "aus", ""],
            ["Off", "liq", "aus", "true"]]})
        make_xlsx(os.path.join(root, "testdata", "gl", "GL_RenewalDC.xlsx"), {"DataCombination": [
            ["Code", "Description"], ["R1", "plain renewal"]]})
        src = os.path.join(root, "src", "main", "java", "com", "x", "tests")
        os.makedirs(src)
        for name, ds in (("GL_SubmissionTest", "testdata/gl/GL_SubmissionDC.xlsx"),
                         ("GL_RenewalTest", "testdata/gl/GL_RenewalDC.xlsx")):
            with open(os.path.join(src, name + ".java"), "w") as fh:
                fh.write(test_class(name, ds))

    def tearDown(self):
        self.tmp.cleanup()

    def test_breadth_items_are_tests_coverages_and_jurisdictions_the_full_run_reaches(self):
        scenarios, every = eir_cover.breadth_items(self.root, "src", self.cssids)
        self.assertEqual(every, {("test", "GL_SubmissionTest.run"), ("test", "GL_RenewalTest.run"),
                                 ("coverage", "GLLine", "Liquor Liability"), ("coverage", "GLLine", "Pollution"),
                                 ("jurisdiction", "GL", "AZ"), ("jurisdiction", "GL", "TX")})
        self.assertNotIn(("GL_SubmissionTest", "run", "Off"), scenarios)  # disabled: never runs

    def test_greedy_picks_the_widest_scenario_first_then_fills_the_gaps(self):
        report = eir_cover.cover_report(self.root, "src", self.cssids)
        # C adds a flow, both coverages and TX; then R1 (the renewal flow) and A (AZ) tie at one: name order
        self.assertEqual([p["scenario"] for p in report["picks"]],
                         [["GL_SubmissionTest", "run", "C"], ["GL_RenewalTest", "run", "R1"],
                          ["GL_SubmissionTest", "run", "A"]])
        self.assertEqual((report["scenarios"], report["of"]), (3, 4))
        self.assertEqual(report["items"], {"test": 2, "coverage": 2, "jurisdiction": 2})
        # A and C of the three rows that run: compact writes "every row but B" (the disabled one never runs)
        self.assertEqual(sorted(report["entries"]), ["GL_RenewalTest", "GL_SubmissionTest run (?!(?:B)$).*"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_cover.print_cover(report, "Cover-Breadth", "CMD")
        self.assertIn("COVERING SUITE: 3 of 4 scenarios keep the breadth of the full run: 2 test methods, "
                      "2 product coverages, 2 line/jurisdiction pairs", out.getvalue())
        self.assertIn("GL_SubmissionTest C: 1 test; 2 coverages (GLLine Liquor Liability, GLLine Pollution); "
                      "1 jurisdiction (GL TX)", out.getvalue())
        self.assertIn('"Name": "Cover-Breadth"', out.getvalue())

    def write_suites(self, *suites):
        resources = os.path.join(self.root, "src", "main", "resources")
        os.makedirs(resources, exist_ok=True)
        with open(os.path.join(resources, "CenterTestSuiteList.json"), "w") as fh:
            json.dump({"CenterTestSuites": [{"Name": n, "List": entries} for n, entries in suites]}, fh)

    def test_what_a_suite_misses_and_the_fewest_scenarios_to_add(self):
        self.write_suites(("Smoke", ["GL_SubmissionTest run A"]))
        report = eir_cover.cover_report(self.root, "src", self.cssids, "smoke")  # suite names: any case
        # A runs the submission flow, Liquor and AZ: missing the renewal flow, Pollution and TX
        self.assertEqual(report["missing"], {"test": 1, "coverage": 1, "jurisdiction": 1})
        self.assertEqual([p["scenario"] for p in report["picks"]],
                         [["GL_SubmissionTest", "run", "C"], ["GL_RenewalTest", "run", "R1"]])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_cover.print_cover(report, "Cover-Smoke", None)
        self.assertIn("MISSES 1 test methods, 1 product coverages, 1 line/jurisdiction pairs", out.getvalue())
        self.assertIn("Adding 2 scenario(s) closes it:", out.getvalue())

    def test_measured_against_another_suite_the_suites_own_reach_counts(self):
        self.write_suites(("Smoke", ["GL_SubmissionTest run C"]), ("Regression", ["GL_SubmissionTest run (A|B)"]))
        report = eir_cover.cover_report(self.root, "src", self.cssids, "Smoke", of="Regression")
        # Regression's breadth: the submission flow, both coverages, AZ; C (not in it) still covers all but AZ
        self.assertEqual(report["items"], {"test": 1, "coverage": 2, "jurisdiction": 1})
        self.assertEqual(report["misses"], [("jurisdiction", "GL", "AZ")])
        self.assertEqual([p["scenario"] for p in report["picks"]], [["GL_SubmissionTest", "run", "A"]])
        self.assertEqual(eir_cover.cover_report(self.root, "src", self.cssids, "Nope"),
                         {"error": "no suite named 'Nope' in CenterTestSuiteList.json"})

    def test_each_suites_share_of_the_full_run(self):
        import eir_report
        self.write_suites(("Smoke", ["GL_SubmissionTest run A"]), ("All", ["GL_.*"]), ("Empty", ["Nothing.*"]))
        rows = eir_cover.suite_breadth(self.root, "src", self.cssids)
        self.assertEqual(rows[0], {"suite": "(full run)", "scenarios": 4, "test": 2, "coverage": 2, "jurisdiction": 2,
                                   "no_suite": [], "any_suite": {"test": 2, "coverage": 2, "jurisdiction": 2}})
        self.assertEqual(rows[1], {"suite": "Smoke", "scenarios": 1, "test": 1, "coverage": 1, "jurisdiction": 1})
        self.assertEqual(rows[2]["scenarios"], 4)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_cover.print_suite_breadth(rows)
        self.assertIn("Smoke                                  1 scen.  flows  50%  coverages  50%  jurisdictions  50%",
                      out.getvalue())
        self.assertIn("Run nothing (1): Empty", out.getvalue())
        html = eir_report._suites_panel_html(rows)
        self.assertIn('<td class="num" title="1 of 2"><span class="share"><i style="width:50%"></i></span>50%</td>', html)
        self.assertIn("Run nothing (1): Empty", html)
        self.assertEqual(eir_cover.suite_breadth_rows(rows)[1], ["Smoke", 1, 1, 0.5, 1, 0.5, 1, 0.5])
        self.assertEqual(rows[0]["no_suite"], [])  # "All" runs everything

    def test_what_no_suite_reaches(self):
        import eir_report
        self.write_suites(("Smoke", ["GL_SubmissionTest run A"]))
        rows = eir_cover.suite_breadth(self.root, "src", self.cssids)
        self.assertEqual(rows[0]["no_suite"], [("coverage", "GLLine", "Pollution"), ("jurisdiction", "GL", "TX"),
                                               ("test", "GL_RenewalTest.run")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_cover.print_suite_breadth(rows)
        self.assertIn("In no suite: 1 flow(s) (GL_RenewalTest.run), 2 coverage or line/jurisdiction item(s)", out.getvalue())
        html = eir_report._suites_panel_html(rows)
        self.assertIn("3 reached by no suite: they run only when everything runs", html)
        self.assertIn('<span class="chip warn">GL_RenewalTest.run</span>', html)
        os.remove(os.path.join(self.root, "src", "main", "resources", "CenterTestSuiteList.json"))
        self.assertIsNone(eir_cover.suite_breadth(self.root, "src", self.cssids))

    def test_scenario_says_what_only_it_reaches(self):
        from eir_uses import print_scenario, scenario_report
        only_c = scenario_report(self.root, "src", "GL_SubmissionTest", "C", self.cssids)["only_here"]
        self.assertEqual(only_c, [("jurisdiction", "GL", "TX")])  # Liquor and Pollution run in A and B too
        report = scenario_report(self.root, "src", "GL_SubmissionTest", "A", self.cssids)
        self.assertEqual(report["only_here"], [])
        self.assertEqual(scenario_report(self.root, "src", "GL_RenewalTest", "R1", self.cssids)["only_here"],
                         [("test", "GL_RenewalTest.run")])  # the renewal flow's one scenario
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            print_scenario(report)
        self.assertIn("Nothing only this scenario reaches", out.getvalue())

    def test_deep_also_keeps_every_limit_option(self):
        model = [{"codeIdentifier": "GLLiquor", "name": "Liquor Liability",
                  "covTerms": [{"name": "Limit", "covTermChoices": [{"codeIdentifier": "z1", "name": "$1,000"},
                                                                     {"codeIdentifier": "z2", "name": "$2,000"}]}]},
                 {"codeIdentifier": "GLPollution", "name": "Pollution"}]
        with open(os.path.join(os.path.dirname(self.cssids), "GLLine_coverage_structure.json"), "w") as fh:
            json.dump(model, fh)
        make_xlsx(os.path.join(self.root, "testdata", "GLData.xlsx"), {
            "Coverage": [["Code", "Coverage", "CovTerm", "CovtermValue"], ["liq", "Liquor Liability", "Limit", "1,000"],
                         ["liq2", "Liquor Liability", "Limit", "2000"], ["pol", "Pollution", "", ""]],
            "Address": [["Code", "State"], ["phx", "AZ"], ["aus", "Texas"]]})
        make_xlsx(os.path.join(self.root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "#Coverage", "#Address"], ["A", "liq", "phx"], ["B", "liq2", "phx"], ["C", "liq,pol", "aus"]]})
        plain = eir_cover.cover_report(self.root, "src", self.cssids)
        self.assertNotIn(["GL_SubmissionTest", "run", "B"], [p["scenario"] for p in plain["picks"]])
        deep = eir_cover.cover_report(self.root, "src", self.cssids, deep=True)
        self.assertEqual(deep["items"]["option"], 2)  # "2000" is the $2,000 option: only B sets it
        self.assertIn(["GL_SubmissionTest", "run", "B"], [p["scenario"] for p in deep["picks"]])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_cover.print_cover(deep, "Cover-Breadth", None)
        self.assertIn("2 term options", out.getvalue())
        self.assertIn("GLLine Liquor Liability / Limit = $2,000", out.getvalue())

    def test_without_a_generated_project_it_still_covers_every_flow(self):
        report = eir_cover.cover_report(self.root, "src", None)
        self.assertEqual(report["items"], {"test": 2, "coverage": 0, "jurisdiction": 0})
        self.assertEqual(report["scenarios"], 2)


if __name__ == "__main__":
    unittest.main()
