import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import eir_since  # noqa: E402
from eir_models import RuleResult  # noqa: E402


def result(rule_id, rows, category="Quality", description="d"):
    return RuleResult(rule_id=rule_id, description=description, category=category,
                      headers=["Class", "Method", "Location"], rows=rows)


class SinceTest(unittest.TestCase):
    def test_first_run_saves_then_the_next_compares(self):
        with tempfile.TemporaryDirectory() as out:
            first = [result("15018", [["A", "run", "A.java:3"]]), result("4001", [["B", "go", "B.java:9"]]),
                     result("0001", [["x", "y", "z"]], category="Statistics")]
            self.assertIsNone(eir_since.since_last(out, eir_since.snapshot(first, 10)))
            second = [result("15018", [["A", "run", "A.java:4"], ["C", "run", "C.java:7"]]),  # A moved: not new
                      result("4001", []), result("0001", [["q", "y", "z"]], category="Statistics")]
            d = eir_since.since_last(out, eir_since.snapshot(second, 10))
        self.assertEqual([(r, t) for r, _ti, _l, t in d["added"]], [("15018", True)])
        self.assertIn("C.java:7", d["added"][0][2])
        self.assertEqual([r for r, *_ in d["fixed"]], ["4001"])
        self.assertEqual(d["blockers"][0] + 1, d["blockers"][1])
        page = eir_since.panel_html(d, lambda x: x)
        self.assertIn("Since your last check", page)
        self.assertIn("Added 1", page)

    def test_flows_and_jurisdictions_that_left_the_run_are_named(self):
        import contextlib
        import io
        states = [{"line": "CA", "states": {"AZ": 3, "NV": 1}}, {"line": "GL", "states": {"AZ": 2}}]
        with tempfile.TemporaryDirectory() as out:
            eir_since.since_last(out, eir_since.snapshot([], 10, states=states, flows=["A.run", "B.run"]))
            fewer = [{"line": "CA", "states": {"AZ": 3}}, {"line": "GL", "states": {"AZ": 2, "TX": 1}}]
            d = eir_since.since_last(out, eir_since.snapshot([], 10, states=fewer, flows=["A.run"]))
        self.assertEqual(d["flows"], (2, 1))
        self.assertEqual(d["jurisdictions"], (2, 2))  # NV left, TX came: distinct states stay 2
        self.assertEqual(d["lost"], [("flow", "B.run"), ("jurisdiction", "CA NV")])
        page = eir_since.panel_html(d, lambda x: x)
        self.assertIn("Left the run 2", page)
        self.assertIn("No longer runs: <code>B.run</code>", page)
        self.assertIn("Line no longer runs in: <code>CA NV</code>", page)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_since.print_since(d)
        self.assertIn("flows that run 2 → 1, jurisdictions 2 (same)", out.getvalue())
        self.assertIn("-- line no longer runs in: CA NV", out.getvalue())

    def test_a_finding_whose_details_changed_is_not_added_and_fixed(self):
        prev = {"findings": {"9010": {"k1": 1}}, "labels": {"9010": {"k1": "T.run (T.java:3)"}}, "titles": {}}
        now = {"findings": {"9010": {"k2": 1}}, "labels": {"9010": {"k2": "T.run (T.java:3)"}}, "titles": {},
               "trust": ["9010"], "score": 1, "blockers": 1, "scenarios": None, "coverages": None}
        d = eir_since.compare(prev, now)
        self.assertEqual((d["added"], d["fixed"]), ([], []))


if __name__ == "__main__":
    unittest.main()
