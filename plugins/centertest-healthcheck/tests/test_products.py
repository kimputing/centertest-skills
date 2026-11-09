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


if __name__ == "__main__":
    unittest.main()
