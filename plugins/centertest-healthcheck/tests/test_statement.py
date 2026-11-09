import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import eir_statement  # noqa: E402
import test_cover  # noqa: E402  (its fixture project; the module name, so its tests are not collected twice)

LINES = [{"line": "GLLine", "coverages": 10, "named": [{"name": "Liquor Liability"}, {"name": "Pollution"}],
          "options_chosen": 1, "options_total": 3,
          "not_offered": [{"coverage": "Liquor Liability", "term": "Limit", "value": "750,000"}]},
         {"line": "IMLine", "coverages": 4, "named": [{"name": "Signs"}], "options_total": 0},
         {"line": "CRLine", "coverages": 20, "named": [], "options_total": 0}]  # a line no scenario tests


class StatementRender(unittest.TestCase):
    def test_figures_lines_jurisdictions_suites_and_gaps(self):
        page = eir_statement.render({
            "project": "acme", "commit": "abc123 2026-11-01", "flows": ["A.run", "B.run"], "scenarios": 40,
            "products": LINES, "states": [{"line": "GL", "states": {"AZ": 3, "TX": 1}}],
            "suites": [{"suite": "(full run)", "scenarios": 40, "test": 2, "coverage": 3, "jurisdiction": 2,
                        "no_suite": [("test", "B.run")]},
                       {"suite": "Smoke", "scenarios": 4, "test": 1, "coverage": 2, "jurisdiction": 1}]})
        self.assertIn("What the acme regression covers", page)
        self.assertIn("<b>3 of 34</b><span>product coverages the scenarios select</span>", page)
        self.assertIn("<b>1 of 3</b><span>limit and deductible options set", page)
        self.assertIn("<b>2</b><span>jurisdictions the scenarios run in</span>", page)
        self.assertIn('<td class="n">–</td>', page)  # a line without option terms
        self.assertIn("<td>AZ, TX</td>", page)
        self.assertIn("<td>Smoke</td><td class=\"n\">4</td><td class=\"n\">50%</td>", page)
        # coverages missing on tested lines, apart from lines no scenario tests at all
        self.assertIn("On the 2 line(s) the scenarios test, 11 of 14 coverages are not selected by any scenario.", page)
        self.assertIn("1 line(s) of the product model no scenario tests: CRLine (20 coverages).", page)
        self.assertIn("Liquor Liability / Limit = 750,000", page)
        self.assertIn("1 flow(s) run only in a full regression, in no suite: B.run.", page)

    def test_without_a_product_model_only_what_is_known(self):
        page = eir_statement.render({"project": "x", "commit": "", "flows": ["A.run"], "scenarios": 3,
                                     "products": None, "states": None, "suites": None})
        self.assertNotIn("product coverages the scenarios select", page)
        self.assertNotIn("Known gaps", page)


@unittest.skipUnless(test_cover.HAS_OPENPYXL, "openpyxl not installed")
class StatementOnAProject(unittest.TestCase):
    def setUp(self):
        self.fixture = test_cover.CoveringSuite("test_without_a_generated_project_it_still_covers_every_flow")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_the_page_is_written_beside_the_reports(self):
        root, cssids = self.fixture.root, self.fixture.cssids
        path = eir_statement.write(root, "src", cssids)
        self.assertTrue(path.startswith(os.path.join(root, "healthcheck", "Coverage_Statement_")))
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("<b>2</b><span>flows (test methods) run in a full regression</span>", page)
        self.assertIn("<b>2 of 3</b><span>product coverages the scenarios select</span>", page)


if __name__ == "__main__":
    unittest.main()
