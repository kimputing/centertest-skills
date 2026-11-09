import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import eir_portfolio


class PortfolioRenderTest(unittest.TestCase):
    def test_every_suite_gets_a_row_and_a_broken_one_says_why(self):
        ok = {"path": "/x/clients/exavalu/CenterTest", "name": eir_portfolio.suite_name("/x/clients/exavalu/CenterTest"),
              "score": 59, "files": 10, "not_checked": [], "changed": "2026-09-02",
              "blockers": [{"rule_id": "9010", "title": "Tests that check nothing", "count": 7}],
              "data": {"scenarios": 859, "broken_live": 25, "unread": ["a", "b", "c"]}, "screens": None}
        broken = {"path": "/x/other", "error": "no Java files under src/main/java"}
        html = eir_portfolio.render_html([ok, broken])
        self.assertIn("exavalu/CenterTest", html)
        self.assertIn("7 × Tests that check nothing", html)
        self.assertIn("not measured (generated cssids/ not found)", html)
        self.assertIn("Not analysed: no Java files under src/main/java", html)
        self.assertIn("1 suites analysed, 1 at risk", html)

    def test_names(self):
        self.assertEqual(eir_portfolio.suite_name("/p/client-portage"), "client-portage")
        self.assertEqual(eir_portfolio.suite_name("/p/exavalu/CenterTest"), "exavalu/CenterTest")


if __name__ == "__main__":
    unittest.main()
