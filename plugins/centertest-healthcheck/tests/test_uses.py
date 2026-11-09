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

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

HIERARCHY = {
    "$references": {"testdata/GLData.xlsx": ["testdata/gl/.*DC\\.xlsx"],
                    "testdata/PAData.xlsx": ["testdata/pa/.*DC\\.xlsx"]},
    "$identifiers": {"GL": ["testdata/gl/.*"], "PA": ["testdata/pa/.*"]},
    "$relationships": {"Submission": {"GL": "testdata/gl/GL_SubmissionDC.xlsx",
                                      "PA": "testdata/pa/PA_SubmissionDC.xlsx"}},
}


def test_class(name, datasource):
    return f"""package com.x.tests;
@CenterTest
public final class {name} {{
    @CenterTestCase()
    @DataDriven(datasource = "{datasource}")
    public void run(ScenarioContext scenarioContext) {{ }}
}}"""


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class UsesTest(unittest.TestCase):
    def setUp(self):
        from refcheck_fixture import make_xlsx
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = self.tmp.name
        td = os.path.join(root, "testdata")
        for d in ("gl", "pa"):
            os.makedirs(os.path.join(td, d))
        with open(os.path.join(td, "DataDrivenHierarchy.json"), "w") as fh:
            json.dump(HIERARCHY, fh)
        make_xlsx(os.path.join(td, "GLData.xlsx"), {
            "Coverage": [["Code", "Coverage"], ["Liquor", "Liquor Liability"], ["Pollution", "Pollution"]],
            "Package": [["Code", "#Coverage"], ["Bar", "Liquor,Pollution"], ["Office", "Pollution"]],
            "Location": [["Code", "City"], ["L1", "Austin"]],
        })
        # PA has a coverage sheet with the same code: a PA row must not count for GL's
        make_xlsx(os.path.join(td, "PAData.xlsx"), {
            "Coverage": [["Code", "Coverage"], ["Liquor", "Collision"]],
        })
        make_xlsx(os.path.join(td, "gl", "GL_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "#Coverage", "#Package", "#Location<>#Coverage", "Disabled"],
            ["Direct", "Liquor", "", "", ""],
            ["ViaPackage", "", "Bar", "", ""],
            ["ViaJoin", "", "", "L1: Liquor", ""],
            ["Plain", "Pollution", "Office", "", ""],
            ["Off", "Liquor", "", "", "true"],
        ]})
        make_xlsx(os.path.join(td, "gl", "GL_PolicyChangeDC.xlsx"), {"DataCombination": [
            ["Code", "@Submission"], ["Change", "Direct"], ["Other", "Plain"],
        ]})
        make_xlsx(os.path.join(td, "pa", "PA_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "#Coverage"], ["Direct", "Liquor"],
        ]})
        make_xlsx(os.path.join(td, "pa", "PA_PolicyChangeDC.xlsx"), {"DataCombination": [
            ["Code", "@Submission"], ["Change", "Direct"],
        ]})
        src = os.path.join(root, "src", "main", "java", "com", "x", "tests")
        os.makedirs(src)
        for name, ds in (("GL_SubmissionTest", "testdata/gl/GL_SubmissionDC.xlsx"),
                         ("GL_PolicyChangeTest", "testdata/gl/GL_PolicyChangeDC.xlsx"),
                         ("PA_SubmissionTest", "testdata/pa/PA_SubmissionDC.xlsx")):
            with open(os.path.join(src, name + ".java"), "w") as fh:
                fh.write(test_class(name, ds))

    def tearDown(self):
        self.tmp.cleanup()

    def test_rows_reached_directly_through_data_rows_joins_and_relationships(self):
        from eir_uses import scenarios_using
        self.assertEqual(scenarios_using(self.root, "liquor liability"), {
            "testdata/gl/GL_SubmissionDC.xlsx": {"Direct", "ViaPackage", "ViaJoin", "Off"},
            "testdata/gl/GL_PolicyChangeDC.xlsx": {"Change"},  # @Submission Direct
        })  # nothing in PA: its "Liquor" code is another workbook's row, its @Submission another DC

    def test_pattern_is_a_whole_cell_regex(self):
        from eir_uses import scenarios_using
        self.assertEqual(scenarios_using(self.root, "Liquor Liab"), {})  # the whole cell, not a prefix
        self.assertIn("testdata/pa/PA_SubmissionDC.xlsx", scenarios_using(self.root, "collision|liquor.*"))

    def test_a_code_matches_its_own_row_reference_cells_do_not(self):
        from eir_uses import scenarios_using
        # "Liquor" is a row code in both GLData and PAData: each line reaches its own row
        self.assertEqual(set(scenarios_using(self.root, "Liquor")), {
            "testdata/gl/GL_SubmissionDC.xlsx", "testdata/gl/GL_PolicyChangeDC.xlsx",
            "testdata/pa/PA_SubmissionDC.xlsx", "testdata/pa/PA_PolicyChangeDC.xlsx"})
        self.assertEqual(scenarios_using(self.root, "L1: Liquor"), {})  # a join cell is not a value

    def test_report_runs_enabled_rows_as_a_suite(self):
        from eir_uses import print_uses, uses_report
        report = uses_report(self.root, "src", "Liquor Liability")
        self.assertEqual(report["entries"], ["GL_PolicyChangeTest run Change",
                                             "GL_SubmissionTest run (?!(?:Plain)$).*"])
        gl = next(w for w in report["workbooks"] if w["dc"].endswith("GL_SubmissionDC.xlsx"))
        self.assertEqual(gl["not_run"], ["Off"])
        self.assertEqual(report["scenarios"], 4)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            print_uses(report, "Uses-Liquor", "CMD")
        self.assertIn('"Name": "Uses-Liquor"', out.getvalue())
        self.assertIn("not run (disabled): Off", out.getvalue())

    def test_several_patterns_keep_the_rows_that_use_all_of_them(self):
        from eir_uses import uses_report
        # ViaPackage's Bar package selects Liquor Liability and Pollution; Direct, Change only Liquor, Plain only Pollution
        report = uses_report(self.root, "src", ["Liquor Liability", "Pollution"])
        self.assertEqual(report["entries"], ["GL_SubmissionTest run ViaPackage"])
        self.assertEqual(report["scenarios"], 1)
        self.assertEqual(report["pattern"], "Liquor Liability & Pollution")
        self.assertEqual(uses_report(self.root, "src", ["Liquor Liability", "Collision"])["scenarios"], 0)

    def test_scenario_tree_through_relationships_and_references(self):
        from eir_uses import print_scenario, scenario_report
        report = scenario_report(self.root, "src", "GL_PolicyChangeTest", "change")  # codes: any case
        self.assertTrue(report["found"])
        self.assertEqual((report["datasource"], report["code"], report["disabled"]),
                         ("testdata/gl/GL_PolicyChangeDC.xlsx", "Change", False))
        self.assertEqual(report["tests"], ["GL_PolicyChangeTest.run"])
        sub = report["tree"]["references"][0]
        self.assertEqual((sub["via"], sub["workbook"], sub["code"]), ("@Submission", "testdata/gl/GL_SubmissionDC.xlsx", "Direct"))
        cov = sub["references"][0]
        self.assertEqual((cov["via"], cov["sheet"], cov["values"]), ("#Coverage", "coverage", {"Coverage": "Liquor Liability"}))
        # by workbook stem too; a join cell and a package reach the same coverage once, then "shown above"
        via_join = scenario_report(self.root, "src", "GL_SubmissionDC", "ViaJoin")["tree"]["references"]
        self.assertEqual([(n["via"], n["code"]) for n in via_join], [("#Location<>#Coverage", "Liquor")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            print_scenario(report)
        self.assertIn("SCENARIO testdata/gl/GL_PolicyChangeDC.xlsx / Change: enabled, 3 data row(s)", out.getvalue())
        self.assertIn("    #Coverage -> GLData.xlsx / coverage / Liquor", out.getvalue())
        self.assertIn("Coverage = Liquor Liability", out.getvalue())

    def test_scenario_not_found_lists_the_codes(self):
        from eir_uses import scenario_report
        report = scenario_report(self.root, "src", "GL_SubmissionTest", "Nope")
        self.assertFalse(report["found"])
        self.assertIn("ViaPackage", report["codes"])

    def test_touches_a_page_or_one_widget(self):
        from eir_uses import touches_report
        step = os.path.join(self.root, "src", "main", "java", "com", "x", "CreateGL.java")
        with open(step, "w") as fh:
            fh.write("""import com.x.generated.pages.pc.SubmissionWizardPage;
public class CreateGL { void go() { var w = new SubmissionWizardPage(getContext()); w.getOfferingStep().click(); } }""")
        test = os.path.join(self.root, "src", "main", "java", "com", "x", "tests", "GL_SubmissionTest.java")
        with open(test) as fh:
            text = fh.read()
        with open(test, "w") as fh:
            fh.write(text.replace("{ }\n}", "{ new CreateGL().go(); }\n}"))
        page = touches_report(self.root, "src", "submissionwizard")
        self.assertEqual([p["page"] for p in page["pages"]], ["SubmissionWizardPage"])
        self.assertEqual(page["tests"], ["GL_SubmissionTest"])
        self.assertEqual(page["entries"], ["GL_SubmissionTest"])
        self.assertEqual(touches_report(self.root, "src", "SubmissionWizardPage.getOfferingStep")["tests"],
                         ["GL_SubmissionTest"])
        self.assertEqual(touches_report(self.root, "src", "SubmissionWizardPage.getQuoteStep")["tests"], [])
        self.assertEqual(touches_report(self.root, "src", "NoSuchPage")["pages"], [])

    def test_a_widget_id_resolves_through_the_generated_cssids(self):
        from eir_uses import widget_targets
        fixtures = os.path.join(PLUGINS, "recording-to-test", "tests", "fixtures", "cssids")
        targets = widget_targets(fixtures, "OrganizationSearchPopup-OrganizationSearchPopupScreen-"
                                           "OrganizationSearchDV-GlobalContactNameInputSet-Name")
        self.assertEqual([(p, g) for p, g, _c in targets], [("OrganizationSearchPopup", "getName")])
        self.assertEqual(widget_targets(fixtures, "No-Such-Widget"), [])
        self.assertEqual(widget_targets(None, "A-B"), [])

    def test_which_suites_run_the_scenarios(self):
        from eir_uses import uses_report
        res = os.path.join(self.root, "src", "main", "resources")
        os.makedirs(res, exist_ok=True)
        with open(os.path.join(res, "CenterTestSuiteList.json"), "w") as fh:
            json.dump({"CenterTestSuites": [{"Name": "Smoke", "List": ["GL_SubmissionTest run Direct"]},
                                            {"Name": "Regression", "List": ["GL_SubmissionTest"]}]}, fh)
        report = uses_report(self.root, "src", "Liquor Liability")
        self.assertEqual(report["in_suites"], {"suites": [("Regression", 3), ("Smoke", 1)], "none": 1})

    def test_a_reference_in_another_case_is_followed(self):
        from refcheck_fixture import make_xlsx
        import eir_uses
        make_xlsx(os.path.join(self.root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {"DataCombination": [
            ["Code", "#Coverage"], ["Upper", "LIQUOR"], ["Plain", "Pollution"]]})
        eir_uses._graph_cache.clear()
        self.assertEqual(eir_uses.scenarios_using(self.root, "Liquor Liability")["testdata/gl/GL_SubmissionDC.xlsx"],
                         {"Upper"})  # the code as written, found through 'LIQUOR' -> 'Liquor'

    def test_nothing_uses_it(self):
        from eir_uses import print_uses, uses_report
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            print_uses(uses_report(self.root, "src", "Earthquake"), "Uses-Earthquake", None)
        self.assertIn("no scenario exercises it", out.getvalue())


if __name__ == "__main__":
    unittest.main()
