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
        self.assertIn("COVERING SUITE: 3 of 4 scenarios keep the full run's breadth: 2 test methods, "
                      "2 product coverages, 2 line/jurisdiction pairs", out.getvalue())
        self.assertIn("GL_SubmissionTest C: 1 test; 2 coverages (GLLine Liquor Liability, GLLine Pollution); "
                      "1 jurisdiction (GL TX)", out.getvalue())
        self.assertIn('"Name": "Cover-Breadth"', out.getvalue())

    def test_without_a_generated_project_it_still_covers_every_flow(self):
        report = eir_cover.cover_report(self.root, "src", None)
        self.assertEqual(report["items"], {"test": 2, "coverage": 0, "jurisdiction": 0})
        self.assertEqual(report["scenarios"], 2)


if __name__ == "__main__":
    unittest.main()
