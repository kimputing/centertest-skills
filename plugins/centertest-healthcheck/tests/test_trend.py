import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import eir_trend


def commit(repo, name, date):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(name)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", name], cwd=repo, check=True, env=env)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


class MonthlyCommitsTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)

    def tearDown(self):
        shutil.rmtree(self.repo)

    def test_last_commit_of_each_month_oldest_first(self):
        commit(self.repo, "a", "2026-04-02T10:00:00")
        april_last = commit(self.repo, "b", "2026-04-28T10:00:00")
        commit(self.repo, "c", "2026-06-01T10:00:00")
        june_last = commit(self.repo, "d", "2026-06-20T10:00:00")
        got = eir_trend.monthly_commits(self.repo, 6)
        self.assertEqual([(m, sha) for m, sha, _ in got], [("2026-04", april_last), ("2026-06", june_last)])
        self.assertEqual([m for m, _, _ in eir_trend.monthly_commits(self.repo, 1)], ["2026-06"])


class RenderTest(unittest.TestCase):
    def test_axis_tops_cover_the_data_at_thirds(self):
        self.assertEqual([eir_trend._nice_max(v) for v in (0, 4, 7, 137)], [3, 6, 9, 150])

    def test_page_has_one_chart_per_measure_and_the_table(self):
        points = [{"month": "2026-04", "sha": "47360e9b", "date": "", "score": 59, "blockers": 7, "dormant": 0,
                   "tests": 81, "cases": 83, "findings": 398, "files": 290, "not_checked": []},
                  {"month": "2026-09", "sha": "53f01821", "date": "", "score": 59, "blockers": 3, "dormant": 26,
                   "tests": 125, "cases": 137, "findings": 684, "files": 421, "not_checked": ["15005"]}]
        html = eir_trend.render_html(points, "client")
        self.assertEqual(html.count('<figure class="chart">'), 3)
        self.assertIn("trust blockers 7 → 3, test cases 83 → 137", html)
        self.assertIn("2026-09 (53f01821): 3", html)  # hover tooltip
        self.assertIn("not counted: 15005", html)


class CoveragesSeriesTest(unittest.TestCase):
    def test_a_product_model_adds_a_chart_and_a_column(self):
        from eir_trend import render_html
        base = {"score": 59, "blockers": 1, "dormant": 0, "tests": 3, "cases": 3, "findings": 4, "files": 9,
                "not_checked": [], "sha": "abc"}
        points = [dict(base, month="2026-10", coverages=74), dict(base, month="2026-11", coverages=68)]
        page = render_html(points, "portage")
        self.assertIn("Product coverages selected", page)
        self.assertIn("coverages selected 74 → 68", page)
        without = render_html([dict(base, month="2026-11", coverages=None)], "x")
        self.assertNotIn("Product coverages selected", without)


    def test_flows_and_jurisdictions_get_a_chart_each(self):
        from eir_trend import render_html
        base = {"score": 59, "blockers": 1, "dormant": 0, "tests": 3, "cases": 3, "findings": 4, "files": 9,
                "not_checked": [], "sha": "abc", "coverages": None}
        points = [dict(base, month="2026-10", flows=9, jurisdictions=3), dict(base, month="2026-11", flows=48, jurisdictions=8)]
        page = render_html(points, "portage")
        self.assertIn("<figcaption>Flows that run</figcaption>", page)
        self.assertIn("<figcaption>Jurisdictions</figcaption>", page)
        self.assertIn("flows that run 9 → 48, jurisdictions 3 → 8", page)
        page = render_html([dict(base, month="2026-11", flows=None, jurisdictions=None)], "x")
        self.assertNotIn("<figcaption>Jurisdictions</figcaption>", page)

    def test_flows_count_every_test_method_that_runs(self):
        import tempfile
        from eir_trend import _flows
        with tempfile.TemporaryDirectory() as root:
            src = os.path.join(root, "src", "main", "java", "x")
            os.makedirs(src)
            with open(os.path.join(src, "ATest.java"), "w") as fh:
                fh.write("@CenterTest public final class ATest { @CenterTestCase() public void run(ScenarioContext s) { } }")
            self.assertEqual(_flows(root, "src"), 1)  # no DataCombination: it runs once


if __name__ == "__main__":
    unittest.main()
