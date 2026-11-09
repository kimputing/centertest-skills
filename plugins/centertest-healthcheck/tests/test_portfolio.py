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


class ProductsColumnTest(unittest.TestCase):
    def test_overall_then_the_biggest_lines(self):
        from eir_portfolio import _products, _products_cell
        lines = [{"line": "GL7Line", "coverages": 432, "named": [{}] * 7},
                 {"line": "CA7Line", "coverages": 568, "named": [{}] * 8},
                 {"line": "IMLine", "coverages": 14, "named": []}]
        self.assertEqual(_products({"products": lines}, lines=2), "15/1014 (1%) · CA7 8/568 · GL7 7/432")
        self.assertIn('<div class="kind">CA7 8/568</div>', _products_cell({"products": lines}))
        self.assertIn("not measured", _products({"products": None}))


class CleanHeadTest(unittest.TestCase):
    def test_only_a_clean_tree_is_its_commit(self):
        import subprocess
        import tempfile
        from eir_portfolio import _clean_head
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, "src"))
            with open(os.path.join(repo, "src", "A.java"), "w") as fh:
                fh.write("class A {}")
            for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "a"]):
                subprocess.run(["git", *cmd], cwd=repo, env=env, check=True, capture_output=True)
            self.assertTrue(_clean_head(repo, "src"))
            with open(os.path.join(repo, "src", "A.java"), "w") as fh:
                fh.write("class A { int x; }")
            self.assertIsNone(_clean_head(repo, "src"))  # uncommitted work: analysed fresh


if __name__ == "__main__":
    unittest.main()
