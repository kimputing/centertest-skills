import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))

import eir_products  # noqa: E402
import eir_report  # noqa: E402

try:
    from refcheck_fixture import make_xlsx  # openpyxl: the reference walk reads it
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

GL = [
    {"codeIdentifier": "GLLiquorCov", "name": "Liquor Liability Endorsement",
     "covTerms": [{"codeIdentifier": "GLLiquorLimit", "name": "Limit"},
                  {"codeIdentifier": "GLLiquorDed", "name": "Deductible"}]},
    {"codeIdentifier": "GLPollutionCov", "name": "Pollution Coverage"},
    {"codeIdentifier": "GLPollutionCov2", "name": "Pollution Coverage"},  # same name on another part
    {"codeIdentifier": "GLCyberCov", "name": "Cyber Suite"},
    {"codeIdentifier": "GLDisabledCov", "name": "Only In A Disabled Row"},
    {"codeIdentifier": "GLMedPay", "name": "Medical Payments",
     "covTerms": [{"codeIdentifier": "GLMedLimit", "name": "Limit"}]},
]


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class ProductCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = os.path.join(self.tmp.name, "proj")
        self.resources = os.path.join(self.tmp.name, "gen", "src", "main", "resources")
        os.makedirs(os.path.join(self.resources, "cssids", "pc"))
        with open(os.path.join(self.resources, "GLLine_coverage_structure.json"), "w") as fh:
            json.dump(GL, fh)
        os.makedirs(os.path.join(root, "testdata", "gl"))
        with open(os.path.join(root, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
            json.dump({"$references": {"testdata/GeneralLiabilityData.xlsx": ["testdata/gl/.*DC\\.xlsx"]}}, fh)
        make_xlsx(os.path.join(root, "testdata", "GeneralLiabilityData.xlsx"), {
            "Coverage": [["Code", "Coverage", "Limit", "#Cyber Suite"],
                         ["c1", "Liquor Liability Endorsement", "100,000", "x"],
                         ["c2", "Only In A Disabled Row", "", ""],
                         ["c3", "GLPollutionCov2", "", ""]]})
        # c1 and c3 are selected by an enabled scenario; c2 only by a disabled one
        make_xlsx(os.path.join(root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {
            "DataCombination": [["Code", "#Coverage", "Disabled"], ["Default", "c1,c3", ""], ["Off", "c2", "true"]]})
        java = os.path.join(root, "src", "main", "java", "com", "x", "Step.java")
        os.makedirs(os.path.dirname(java))
        with open(java, "w") as fh:
            fh.write('class Step { void a() { coverageUtil.setSelected("Medical Payments", true); } }')

    def tearDown(self):
        self.tmp.cleanup()

    def line(self, cssids):
        lines = eir_products.product_coverage(self.root, cssids)
        self.assertEqual([l["line"] for l in lines], ["GLLine"])
        return lines[0]

    def test_coverages_named_in_enabled_rows_by_name_or_code(self):
        gl = self.line(os.path.join(self.resources, "cssids"))  # GW10: the files sit beside cssids/
        self.assertEqual(gl["coverages"], 5)  # Pollution Coverage counted once
        self.assertEqual([c["name"] for c in gl["named"]], ["Liquor Liability Endorsement", "Pollution Coverage"])
        self.assertEqual(gl["unused"], ["Only In A Disabled Row"])  # in a row no enabled scenario reaches
        self.assertEqual(gl["missing"], ["Cyber Suite"])  # a #reference header is not a name

    def test_only_in_java_is_apart(self):
        gl = self.line(self.resources)  # GW9: the resources folder itself
        self.assertEqual(gl["java"], ["Medical Payments"])
        self.assertNotIn("Medical Payments", [c["name"] for c in gl["named"]])

    def test_terms_count_only_under_a_named_coverage(self):
        gl = self.line(self.resources)
        liquor = gl["named"][0]
        self.assertEqual((liquor["terms"], liquor["terms_set"]), (2, ["Limit"]))
        self.assertEqual((gl["terms"], gl["terms_set"]), (2, 1))  # Medical Payments' Limit is not counted

    def test_no_product_model(self):
        self.assertIsNone(eir_products.product_coverage(self.root, None))
        self.assertIsNone(eir_products.product_coverage(self.root, os.path.join(self.root, "testdata")))

    def test_panel_shows_the_shorter_list_and_excel_rows_list_everything(self):
        gl = self.line(self.resources)
        page = eir_report._products_panel_html([gl])
        self.assertIn("2<small> of 5 coverages", page)
        self.assertIn('No scenario selects</div><div class="chips"><span class="chip">Cyber Suite', page)  # the shorter list
        self.assertIn("1 in data rows no scenario reaches</summary>", page)
        self.assertIn("named only in code: check", page)
        rows = eir_products.excel_rows([gl])
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0][:4], ["GLLine", "Liquor Liability Endorsement", "Selected by a scenario", "1/2"])
        self.assertEqual(eir_report._products_panel_html(None), "")

    def test_a_well_covered_line_lists_what_is_missing(self):
        gl = self.line(self.resources)
        gl["missing"] = ["Cyber Suite"]
        self.assertIn("No scenario selects", eir_report._products_panel_html([gl]))


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class OutsideSuitesTest(unittest.TestCase):
    def test_a_coverage_only_a_suite_less_scenario_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = os.path.join(tmp, "gen")
            os.makedirs(res)
            with open(os.path.join(res, "GLLine_coverage_structure.json"), "w") as fh:
                json.dump(GL, fh)
            root = os.path.join(tmp, "proj")
            os.makedirs(os.path.join(root, "testdata", "gl"))
            with open(os.path.join(root, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
                json.dump({"$references": {"testdata/GLData.xlsx": ["testdata/gl/.*DC\\.xlsx"]}}, fh)
            make_xlsx(os.path.join(root, "testdata", "GLData.xlsx"), {"Coverage": [
                ["Code", "Coverage"], ["c1", "Liquor Liability Endorsement"], ["c2", "Cyber Suite"]]})
            make_xlsx(os.path.join(root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {"DataCombination": [
                ["Code", "#Coverage"], ["InSuite", "c1"], ["Seed", "c2"]]})
            src = os.path.join(root, "src", "main", "java", "com", "x")
            os.makedirs(src)
            with open(os.path.join(src, "GL_SubmissionTest.java"), "w") as fh:
                fh.write('@CenterTest public final class GL_SubmissionTest { @CenterTestCase() '
                         '@DataDriven(datasource = "testdata/gl/GL_SubmissionDC.xlsx") public void run() { } }')
            os.makedirs(os.path.join(root, "src", "main", "resources"))
            with open(os.path.join(root, "src", "main", "resources", "CenterTestSuiteList.json"), "w") as fh:
                json.dump({"CenterTestSuites": [{"Name": "Regression", "List": ["GL_SubmissionTest run InSuite"]}]}, fh)
            gl = eir_products.product_coverage(root, res)[0]
            self.assertEqual([c["name"] for c in gl["named"]], ["Cyber Suite", "Liquor Liability Endorsement"])
            self.assertEqual(gl["outside_suites"], ["Cyber Suite"])
            liquor = next(c for c in gl["named"] if c["name"].startswith("Liquor"))
            self.assertEqual(eir_products._tests(liquor), "GL_SubmissionTest (1 row)")
            # a coverage's name in a sheet that is not about coverages (a prior-loss cause) is not a selection
            make_xlsx(os.path.join(root, "testdata", "GLData.xlsx"), {
                "Coverage": [["Code", "Coverage"], ["c1", "Liquor Liability Endorsement"], ["c2", "Cyber Suite"]],
                "PriorLosses": [["Code", "Cause"], ["p1", "Pollution Coverage"]]})
            make_xlsx(os.path.join(root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {"DataCombination": [
                ["Code", "#Coverage", "#PriorLosses"], ["InSuite", "c1", "p1"], ["Seed", "c2", ""]]})
            import eir_uses
            eir_uses._graph_cache.clear()
            gl = eir_products.product_coverage(root, res)[0]
            self.assertNotIn("Pollution Coverage", [c["name"] for c in gl["named"]])
            self.assertIn("Selected only by scenarios no suite runs", eir_report._products_panel_html([gl]))


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class CoverageDeltaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.resources = os.path.join(self.tmp.name, "gen")
        os.makedirs(self.resources)
        with open(os.path.join(self.resources, "GLLine_coverage_structure.json"), "w") as fh:
            json.dump(GL, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def tree(self, name, selected):
        root = os.path.join(self.tmp.name, name)
        os.makedirs(os.path.join(root, "testdata", "gl"))
        with open(os.path.join(root, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
            json.dump({"$references": {"testdata/GLData.xlsx": ["testdata/gl/.*DC\\.xlsx"]}}, fh)
        make_xlsx(os.path.join(root, "testdata", "GLData.xlsx"), {"Coverage": [
            ["Code", "Coverage"], ["c1", "Liquor Liability Endorsement"], ["c2", "Cyber Suite"]]})
        make_xlsx(os.path.join(root, "testdata", "gl", "GL_SubmissionDC.xlsx"),
                  {"DataCombination": [["Code", "#Coverage"], ["Default", selected]]})
        return root

    def test_lost_and_gained_per_line(self):
        from eir_review import coverage_delta, render_markdown
        delta = coverage_delta(self.tree("base", "c1"), self.tree("head", "c2"), self.resources)
        self.assertEqual(delta, [{"line": "GLLine", "gained": ["Cyber Suite"], "lost": ["Liquor Liability Endorsement"]}])
        self.assertEqual(coverage_delta(self.tree("b2", "c1"), self.tree("h2", "c1"), self.resources), [])
        meta = {"base_name": "main", "head_name": "b", "base_short": "1", "head_short": "2", "base_files": 1,
                "head_files": 1, "ruleset": "x", "rerun": [], "data": [], "suites": [], "coverage": delta}
        md = render_markdown([], meta)
        self.assertIn("**No scenario selects these any more** (1):\n- GLLine: Liquor Liability Endorsement", md)
        self.assertIn("Newly selected (1): GLLine: Cyber Suite", md)


TERMS = [
    {"codeIdentifier": "GLLiquorCov", "name": "Liquor Liability Endorsement",
     "covTerms": [{"codeIdentifier": "GLLiquorLimit", "name": "Limit",
                   "covTermChoices": [{"codeIdentifier": "z1", "name": "$500,000"},
                                      {"codeIdentifier": "z2", "name": "$1,000,000"},
                                      {"codeIdentifier": "z3", "name": "$2,000,000"}]},
                  {"codeIdentifier": "GLLiquorDed", "name": "Deductible",
                   "covTermChoices": [{"codeIdentifier": "z4", "name": "No Deductible"},
                                      {"codeIdentifier": "z5", "name": "500"}]}]},
    {"codeIdentifier": "GLMedPay", "name": "Medical Payments",
     "covTerms": [{"codeIdentifier": "GLMedLimit", "name": "Limit",
                   "covTermChoices": [{"codeIdentifier": "z6", "name": "5,000"}]}]},
]


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class TermOptions(unittest.TestCase):
    """Which options of a coverage's option terms the scenarios set, and values that are not an option."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = os.path.join(self.tmp.name, "proj")
        self.resources = os.path.join(self.tmp.name, "gen", "src", "main", "resources")
        os.makedirs(os.path.join(self.resources, "cssids", "pc"))
        with open(os.path.join(self.resources, "GLLine_coverage_structure.json"), "w") as fh:
            json.dump(TERMS, fh)
        os.makedirs(os.path.join(root, "testdata", "gl"))
        with open(os.path.join(root, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
            json.dump({"$references": {"testdata/GLData.xlsx": ["testdata/gl/.*DC\\.xlsx"]}}, fh)
        make_xlsx(os.path.join(root, "testdata", "GLData.xlsx"), {
            "Coverage": [["Code", "Coverage", "CovTerm", "CovtermValue"],
                         ["lim", "Liquor Liability Endorsement", "Limit", "1,000,000"],  # "$1,000,000"
                         ["ded", "Liquor Liability Endorsement", "Deductible", "No Deductible, 500"],  # a list
                         ["odd", "Liquor Liability Endorsement", "Limit", "750,000"],  # not an option
                         ["med", "Medical Payments", "Limit", "9,999"]],  # only a disabled row reaches it
            # an API payload's shape: its values are not dropdown labels, so it is not compared
            "CovTerm": [["Code", "Name", "PatternCode", "ChosenTerm"], ["api", "Limit", "GLLiquorLimit", "1000"]]})
        make_xlsx(os.path.join(root, "testdata", "gl", "GL_SubmissionDC.xlsx"), {
            "DataCombination": [["Code", "#Coverage", "#CovTerm", "Disabled"],
                                ["Default", "lim,ded", "api", ""], ["Odd", "odd", "", ""], ["Off", "med", "", "true"]]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_options_chosen_and_values_that_are_not_an_option(self):
        gl = eir_products.product_coverage(self.root, self.resources)[0]
        liquor = next(c for c in gl["named"] if c["name"] == "Liquor Liability Endorsement")
        self.assertEqual(liquor["options"], [
            {"term": "Deductible", "options": ["No Deductible", "500"], "chosen": ["No Deductible", "500"],
             "not_offered": []},
            {"term": "Limit", "options": ["$500,000", "$1,000,000", "$2,000,000"], "chosen": ["$1,000,000"],
             "not_offered": ["750,000"]}])
        self.assertNotIn("Medical Payments", [c["name"] for c in gl["named"]])
        self.assertEqual((gl["option_terms"], gl["options_chosen"], gl["options_total"]), (2, 3, 5))
        self.assertEqual([(n["coverage"], n["term"], n["value"]) for n in gl["not_offered"]],
                         [("Liquor Liability Endorsement", "Limit", "750,000")])

    def test_shown_in_terminal_panel_and_excel(self):
        import contextlib
        import io
        lines = eir_products.product_coverage(self.root, self.resources)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_products.print_products(lines)
        self.assertIn("options 3/5 of 2 option terms", out.getvalue())
        self.assertIn("Liquor Liability Endorsement / Limit = 750,000   (options: $500,000, $1,000,000, $2,000,000)",
                      out.getvalue())
        html = eir_report._products_panel_html(lines)
        self.assertIn("2 option terms set, 3 of their 5 options used", html)
        self.assertIn("Term values that are not an option in the product model", html)
        row = next(r for r in eir_products.excel_rows(lines) if r[1] == "Liquor Liability Endorsement")
        self.assertEqual(row[6], "Deductible: No Deductible, 500 (2 of 2); "
                                 "Limit: $1,000,000, 750,000 NOT AN OPTION (1 of 3)")


if __name__ == "__main__":
    unittest.main()
