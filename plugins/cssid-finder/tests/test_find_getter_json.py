import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "find_getter.py")
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(HERE)), "recording-to-test", "tests", "fixtures", "cssids")


class FindGetterJsonTest(unittest.TestCase):
    def run_json(self, app, css_id):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "CENTERTEST_CSSIDS_DIR": FIXTURES}
            return subprocess.run([sys.executable, SCRIPT, app, css_id, "--json"], capture_output=True, text=True, env=env)

    def test_a_known_widget(self):
        run = self.run_json("pc", "OrganizationSearchPopup-OrganizationSearchPopupScreen-"
                                  "OrganizationSearchDV-GlobalContactNameInputSet-Name")
        self.assertEqual(run.returncode, 0, run.stderr)
        doc = json.loads(run.stdout)
        self.assertEqual(doc["resolution"], "exact")
        self.assertEqual(doc["getters"], ["new OrganizationSearchPopup(getContext()).getGlobalContactName().getName()"])

    def test_an_unknown_widget_and_app(self):
        run = self.run_json("pc", "No-Such-Widget")
        self.assertEqual((run.returncode, json.loads(run.stdout)["resolution"]), (1, "none"))
        self.assertIn("unknown app", json.loads(self.run_json("xx", "A-B").stdout)["error"])


class WordSearchTest(unittest.TestCase):
    def run_words(self, *args):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "CENTERTEST_CSSIDS_DIR": FIXTURES}
            return subprocess.run([sys.executable, SCRIPT, "pc", "--words", *args], capture_output=True, text=True, env=env)

    def test_the_element_named_by_those_words_first(self):
        run = self.run_words("account status", "--json")
        self.assertEqual(run.returncode, 0, run.stderr)
        doc = json.loads(run.stdout)
        self.assertEqual(doc["matches"][0], {
            "css_id": "AccountFile_Summary-AccountSummaryDashboard-AccountDetailsDetailViewTile-"
                      "AccountDetailsDetailViewTile_DV-AccountStatus",
            "page": "AccountFile_Summary", "getter": "new AccountFile_SummaryPage(getContext()).getAccountStatus()"})

    def test_words_any_case_and_order_then_ids_whose_other_segments_name_them(self):
        doc = json.loads(self.run_words("CITY contact", "--json").stdout)
        self.assertEqual([m["css_id"].split("-")[-1] for m in doc["matches"]], ["ContactCity"])
        # "organization search" names no element: the ids under OrganizationSearch* screens follow
        doc = json.loads(self.run_words("organization search", "--json").stdout)
        self.assertTrue(doc["matches"])
        self.assertTrue(all(m["page"] == "OrganizationSearchPopup" for m in doc["matches"]))

    def test_page_matches_any_segment_of_the_id(self):
        doc = json.loads(self.run_words("override rating", "--page", "ViewQuote", "--json").stdout)
        self.assertEqual([m["css_id"] for m in doc["matches"]],
                         ["PolicyChangeWizard-ViewQuoteScreen-RatingCumulDetailsPanelSet-#-OverrideRating"])
        run = self.run_words("override rating", "--page", "OfferingScreen")
        self.assertEqual(run.returncode, 1)
        self.assertIn("Widgets named 'override rating' on pages matching 'OfferingScreen': 0", run.stdout)


if __name__ == "__main__":
    unittest.main()
