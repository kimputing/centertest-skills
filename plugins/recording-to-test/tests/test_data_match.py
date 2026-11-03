import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

import data_match as dm  # noqa: E402
import parse_recording as pr  # noqa: E402
from xlsx_fixture import make_xlsx  # noqa: E402


def plan_with(*pairs):
    actions = [{"type": "change", "label": label, "value": value} for label, value in pairs]
    return {"steps": [{"seq": i + 1, "actions": [a]} for i, a in enumerate(actions)]}


def book(path, **sheets):
    return {"path": path, "sheets": {name: {"columns": cols, "codes": [], "rows": 0} for name, cols in sheets.items()},
            "usedBy": []}


class TokensTest(unittest.TestCase):
    def test_tokens_split_camel_and_markers(self):
        self.assertEqual(dm.tokens("#Person.FirstName"), {"person", "first", "name"})

    def test_stopwords_removed(self):
        self.assertEqual(dm.tokens("Date of the Birth"), {"date", "birth"})


class ColumnsTest(unittest.TestCase):
    def test_label_maps_to_column(self):
        found = dm.dc_columns(plan_with(("First name", "Ann")),
                              [book("testdata/A.xlsx", DC=["Code", "#Person.FirstName", "#Person.LastName"])])
        self.assertEqual([(c["seq"], c["workbook"], c["sheet"], c["column"], c["value"]) for c in found],
                         [(1, "testdata/A.xlsx", "DC", "#Person.FirstName", "Ann")])

    def test_redacted_values_skipped(self):
        plan = plan_with(("First name", pr.REDACTED))
        self.assertEqual(dm.dc_columns(plan, [book("a.xlsx", DC=["FirstName"])]), [])

    def test_generic_single_token_does_not_map(self):
        found = dm.dc_columns(plan_with(("Business name", "Acme")), [book("a.xlsx", DC=["Code", "Person.Name"])])
        self.assertEqual(found, [])

    def test_generic_label_alone_maps(self):
        found = dm.dc_columns(plan_with(("Name", "Acme")), [book("a.xlsx", DC=["Code", "Name"])])
        self.assertEqual([c["column"] for c in found], ["Name"])

    def test_best_overlap_wins_and_ties_take_first(self):
        found = dm.dc_columns(plan_with(("Mailing address street", "1 Main")),
                              [book("a.xlsx", DC=["Address", "MailingAddressStreet", "Street"])])
        self.assertEqual([c["column"] for c in found], ["MailingAddressStreet"])
        found = dm.dc_columns(plan_with(("Zip code", "85001")), [book("a.xlsx", DC=["ZipCode", "CodeZip"])])
        self.assertEqual([c["column"] for c in found], ["ZipCode"])

    def test_one_column_per_action_per_workbook(self):
        found = dm.dc_columns(plan_with(("Zip code", "85001")),
                              [book("a.xlsx", DC=["ZipCode"]), book("b.xlsx", Other=["ZipCode"])])
        self.assertEqual([c["workbook"] for c in found], ["a.xlsx", "b.xlsx"])

    def test_no_workbooks_gives_empty_lists(self):
        self.assertEqual(dm.dc_columns(plan_with(("First name", "Ann")), []), [])
        self.assertEqual(dm.data_row_candidates([], "/nowhere"), [])


class RowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def workbook(self, rows, name="DC.xlsx"):
        make_xlsx(os.path.join(self.tmp.name, name), {"DC": rows})
        return name

    def cols(self, name, *pairs):
        return [{"seq": i + 1, "label": c, "value": v, "workbook": name, "sheet": "DC", "column": c, "why": ""}
                for i, (c, v) in enumerate(pairs)]

    def run_rows(self, rows, *pairs):
        name = self.workbook(rows)
        return dm.data_row_candidates(self.cols(name, *pairs), self.tmp.name)

    def test_rows_ranked_by_matches(self):
        found = self.run_rows([["Code", "First", "Last"], ["A", "Ann", "Zed"], ["B", "ann", "Poe"], ["C", "Bo", "Poe"]],
                              ("First", "Ann"), ("Last", "Poe"))
        self.assertEqual([(r["code"], r["matched"], r["total"]) for r in found], [("B", 2, 2), ("A", 1, 2), ("C", 1, 2)])

    def test_zero_matches_excluded_and_top_three(self):
        rows = [["Code", "First"]] + [["R%d" % i, "Ann"] for i in range(5)] + [["X", "Nope"]]
        found = self.run_rows(rows, ("First", "Ann"))
        self.assertEqual(len(found), 3)
        self.assertNotIn("X", [r["code"] for r in found])

    def test_dates_match_across_formats(self):
        found = self.run_rows([["Code", "Eff"], ["A", "2026-10-01"]], ("Eff", "10/01/2026"))
        self.assertEqual([r["code"] for r in found], ["A"])

    def test_date_matches_excel_serial(self):
        # 2026-10-01 is serial 46296 (days since 1899-12-30)
        found = self.run_rows([["Code", "Eff"], ["A", "46296"], ["B", "46296.5"], ["C", "46297"]],
                              ("Eff", "10/01/2026"))
        self.assertEqual([r["code"] for r in found], ["A", "B"])

    def test_numbers_compare_without_separators_or_currency(self):
        found = self.run_rows([["Code", "Limit"], ["A", "500000"], ["B", "1000.0"], ["C", "7"]], ("Limit", "500,000"))
        self.assertEqual([r["code"] for r in found], ["A"])
        found = self.run_rows([["Code", "Limit"], ["B", "1000.0"]], ("Limit", "$1,000"))
        self.assertEqual([r["code"] for r in found], ["B"])

    def test_unreadable_workbook_skipped_and_read_once(self):
        calls = []

        def read(path, sheet=".*", max_rows=None):
            calls.append(path)
            raise OSError("gone")
        cols = self.cols("x.xlsx", ("First", "Ann")) + self.cols("x.xlsx", ("Last", "Poe"))
        self.assertEqual(dm.data_row_candidates(cols, self.tmp.name, read=read), [])
        self.assertEqual(len(calls), 1)


class PlanIntegrationTest(unittest.TestCase):
    CSSIDS = os.path.join(os.path.dirname(__file__), "fixtures", "cssids")
    SESSION = {"steps": [{"seq": 1, "app": "PolicyCenter", "title": "Contact", "actions": [
        {"type": "change", "widgetId": "X-FirstName", "kind": "TextInputWidget", "text": "First name", "value": "Ann"}]}]}

    def test_plan_without_workbooks_has_empty_lists(self):
        plan = pr.build_plan(self.SESSION, self.CSSIDS)
        self.assertEqual((plan["dcColumns"], plan["dataRowCandidates"]), ([], []))

    def test_plan_fills_columns_and_rows_from_project_workbooks(self):
        with tempfile.TemporaryDirectory() as root:
            make_xlsx(os.path.join(root, "DC.xlsx"), {"DC": [["Code", "FirstName"], ["A", "Ann"]]})
            project = {"root": root, "dataWorkbooks": {"value": {"workbooks": [book("DC.xlsx", DC=["Code", "FirstName"])]}}}
            plan = pr.build_plan(self.SESSION, self.CSSIDS, project=project)
        self.assertEqual([c["column"] for c in plan["dcColumns"]], ["FirstName"])
        self.assertEqual([r["code"] for r in plan["dataRowCandidates"]], ["A"])


if __name__ == "__main__":
    unittest.main()
