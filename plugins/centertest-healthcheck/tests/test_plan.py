import contextlib
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import eir_plan  # noqa: E402
import test_uses  # noqa: E402  (its fixture project; the module name, so its tests are not collected twice)


class ReleasePlan(unittest.TestCase):
    def setUp(self):
        fx = self.fx = test_uses.UsesTest("test_nothing_uses_it")
        fx.setUp()
        self.addCleanup(fx.tearDown)
        self.path = os.path.join(fx.root, "release.txt")
        with open(self.path, "w") as fh:
            fh.write("# release 26.4\n"
                     "coverage: Liquor Liability   # the GL endorsement\n"
                     "value: Collision\n"
                     "coverage: Liqour Liability\n"
                     "rate the new endorsement\n")

    def test_every_item_answered_and_the_scenarios_together(self):
        report = eir_plan.plan_report(self.fx.root, "src", self.path)
        self.assertEqual([(i["kind"], i["pattern"], i["scenarios"], i["new"]) for i in report["items"]], [
            ("coverage", "Liquor Liability", 4, 4),  # GL Direct, ViaPackage, ViaJoin, and PolicyChange via @Submission
            ("value", "Collision", 1, 1),            # PA Direct, through PA's own coverage sheet
            ("coverage", "Liqour Liability", 0, 0)])  # misspelled: selects nothing
        self.assertEqual(report["scenarios"], 5)
        self.assertEqual(report["not_understood"], ["rate the new endorsement"])
        self.assertIn("PA_SubmissionTest", report["entries"])  # its only row: compact names the whole test
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eir_plan.print_plan(report, eir_plan.plan_name(self.path), "CMD")
        self.assertIn("RELEASE PLAN release.txt: 5 of", out.getvalue())
        self.assertIn("!! 1 item(s) select nothing", out.getvalue())
        self.assertIn("?? not an item (coverage:/value:/page:/widget:): rate the new endorsement", out.getvalue())
        self.assertIn('"Name": "Plan-Release"', out.getvalue())


if __name__ == "__main__":
    unittest.main()
