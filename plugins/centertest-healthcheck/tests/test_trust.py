import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from eir_models import RuleResult
import eir_report


def result(rule_id, category="Quality", headers=None, rows=None):
    return RuleResult(rule_id=rule_id, description=f"rule {rule_id}", category=category,
                      headers=headers or [], rows=rows or [])


def clean_trust_run():
    """Every trust rule ran and found nothing (15018 last, so a test can replace it)."""
    return [result(r, "CenterTest") for r in sorted(eir_report.TRUST_RULES) if r != "15018"] + [result("15018")]


class TrustBlockersTest(unittest.TestCase):
    def test_a_check_that_cannot_fail_is_a_blocker(self):
        results = clean_trust_run()
        results[-1] = result("15018", headers=["Class", "Method", "Method Called", "Line"],
                             rows=[["DelinquencyEvent", "validate", "equals", "a.equals(b);"]])
        blockers, not_checked, _ = eir_report.trust_blockers(results)
        self.assertEqual(not_checked, [])
        self.assertEqual([(b["rule_id"], b["count"]) for b in blockers], [("15018", 1)])
        self.assertEqual(blockers[0]["samples"], ["DelinquencyEvent.validate: a.equals(b);"])

    def test_data_findings_read_as_file_row_column_code(self):
        rows = [["testdata/wc/WC_SeedingDC.xlsx", 35, "#Company", "McDEL1", "code not found"]]
        r = result("14003", "CenterTest", ["File", "Row", "Column", "Code", "Issue"], rows)
        blockers, _, _ = eir_report.trust_blockers([r])
        self.assertEqual(blockers[0]["samples"], ["WC_SeedingDC.xlsx row 35: #Company 'McDEL1'"])

    def test_rules_not_run_are_reported_not_passed(self):
        blockers, not_checked, _ = eir_report.trust_blockers([result("5001", "Complexity")])
        self.assertEqual(blockers, [])
        self.assertEqual(sorted(not_checked), sorted(eir_report.TRUST_RULES))
        self.assertTrue({"9003", "9010", "14002", "14003", "14004", "14005", "15005", "15018",
                         "9013", "18001", "18005", "21005"} <= set(not_checked))


class HealthScoreTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out)

    def score(self, results):
        path = eir_report.generate_html(results, self.out, project_name="p", total_files=400)
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        number = int(re.search(r'class="score-number">(\d+)<', html).group(1))
        label = re.search(r'class="score-badge">([^<]+)<', html).group(1)
        return number, label, html

    def test_one_silent_assertion_in_400_files_is_not_healthy(self):
        results = clean_trust_run()
        results[-1] = result("15018", headers=["Class", "Method", "Method Called", "Line"],
                             rows=[["A", "validate", "equals", "x.equals(y);"]])
        number, label, html = self.score(results)
        self.assertLessEqual(number, eir_report.TRUST_SCORE_CAP)
        self.assertEqual(label, "At risk")
        self.assertIn("Can these tests be trusted? Not yet.", html)
        self.assertIn("A.validate: x.equals(y);", html)

    def test_clean_suite_keeps_its_score(self):
        number, label, html = self.score(clean_trust_run())
        self.assertEqual((number, label), (100, "Healthy"))
        self.assertIn("No trust blockers", html)



class VerdictSheetTest(unittest.TestCase):
    def test_the_excel_opens_on_the_verdict(self):
        import openpyxl
        out = tempfile.mkdtemp()
        try:
            results = clean_trust_run()
            results[-1] = result("15018", headers=["Class", "Method", "Method Called", "Line", "Location"],
                                 rows=[["A", "validate", "equals", "x.equals(y);", "src/A.java:7"]])
            path = eir_report.generate_excel(results, out, total_files=400, data=None)
            wb = openpyxl.load_workbook(path, read_only=True)
            self.assertEqual(wb.sheetnames[:2], ["Verdict", "Summary"])
            rows = [tuple(c for c in r if c is not None) for r in wb["Verdict"].iter_rows(values_only=True)]
            wb.close()  # a read-only workbook keeps the file open: Windows cannot delete it
            self.assertIn(("Health score", eir_report.TRUST_SCORE_CAP, "At risk"), rows)
            self.assertIn(("A.validate: x.equals(y);", "src/A.java:7"), rows)
        finally:
            shutil.rmtree(out)


class FixOrderTest(unittest.TestCase):
    def test_tiers_order_by_cost_and_trust_counts_only_live_findings(self):
        data_headers = ["File", "Row", "Column", "Code", "Issue", "Runs in"]
        results = [
            result("15018", headers=["Class", "Method", "Method Called", "Line"], rows=[["A", "v", "equals", "x.equals(y);"]]),
            result("14003", "CenterTest", data_headers, [["f.xlsx", 2, "#C", "X", "code not found", "SomeTest"],
                                                         ["g.xlsx", 3, "#C", "Y", "code not found", "not run: row disabled"]]),
            result("15017", "Quality", ["Class"], [["B"], ["C"]]),
            result("15002", "Quality", ["Class"], [["H"]]),  # a loud failure with a poor message: should fix
            result("5001", "Complexity", ["Class"], [["D"]]),
            result("4001", "Methods", ["Class"], [["E"], ["F"], ["G"]]),
            result("0001", "Statistics", ["Commit"], [["local"]]),
        ]
        tiers = {t["tier"]: (t["count"], [r[0] for r in t["rules"]]) for t in eir_report.fix_order(results)}
        self.assertEqual(tiers, {"trust": (2, ["14003", "15018"]), "high": (2, ["15017"]),
                                 "medium": (2, ["15002", "5001"]), "low": (3, ["4001"])})

if __name__ == "__main__":
    unittest.main()
