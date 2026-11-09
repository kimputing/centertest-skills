import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "suite-builder", "tests"))

import eir_products  # noqa: E402
import eir_report  # noqa: E402
from xlsx_fixture import make_xlsx  # noqa: E402  (stdlib writer)

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


class ProductCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = os.path.join(self.tmp.name, "proj")
        self.resources = os.path.join(self.tmp.name, "gen", "src", "main", "resources")
        os.makedirs(os.path.join(self.resources, "cssids", "pc"))
        with open(os.path.join(self.resources, "GLLine_coverage_structure.json"), "w") as fh:
            json.dump(GL, fh)
        os.makedirs(os.path.join(root, "testdata"))
        make_xlsx(os.path.join(root, "testdata", "GeneralLiabilityData.xlsx"), {
            "Coverage": [["Code", "Coverage", "Limit", "Disabled", "#Cyber Suite"],
                         ["c1", "Liquor Liability Endorsement", "100,000", "", "x"],
                         ["c2", "Only In A Disabled Row", "", "true", ""],
                         ["c3", "GLPollutionCov2", "", "", ""]]})
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
        self.assertIn("Only In A Disabled Row", gl["missing"])
        self.assertIn("Cyber Suite", gl["missing"])  # a #reference header is not a name

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
        self.assertIn("Named in test data", page)  # 2 named vs 2 not named: the named ones
        self.assertIn("Named only in code: check", page)
        rows = eir_products.excel_rows([gl])
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0][:4], ["GLLine", "Liquor Liability Endorsement", "Named in test data", "1/2"])
        self.assertEqual(eir_report._products_panel_html(None), "")

    def test_a_well_covered_line_lists_what_is_missing(self):
        gl = self.line(self.resources)
        gl["missing"] = ["Cyber Suite"]
        self.assertIn("Not named in any test data", eir_report._products_panel_html([gl]))


if __name__ == "__main__":
    unittest.main()
