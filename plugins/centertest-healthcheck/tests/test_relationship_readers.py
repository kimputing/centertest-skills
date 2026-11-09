import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class RelationshipReadersTest(unittest.TestCase):
    """@Rel passes a DC's readers only to the relationship target of its own identifier."""

    def build(self, change_cell):
        from refcheck_fixture import make_xlsx
        root = self.tmp.name
        td = os.path.join(root, "testdata")
        for d in ("wc", "ca"):
            os.makedirs(os.path.join(td, d), exist_ok=True)
        with open(os.path.join(td, "DataDrivenHierarchy.json"), "w") as fh:
            json.dump({"$identifiers": {"WC": ["testdata/wc/.*"], "CA": ["testdata/ca/.*"]},
                       "$relationships": {"Submission": {"WC": "testdata/wc/WC_SubmissionDC.xlsx",
                                                         "CA": "testdata/ca/CA_SubmissionDC.xlsx"}}}, fh)
        for path in ("wc/WC_SubmissionDC.xlsx", "ca/CA_SubmissionDC.xlsx"):
            make_xlsx(os.path.join(td, path), {"DataCombination": [["Code", "State"], ["Default", "AZ"]]})
        make_xlsx(os.path.join(td, "wc", "WC_PolicyChangeDC.xlsx"),
                  {"DataCombination": [["Code", "@Submission"], ["Change", change_cell]]})
        src = os.path.join(root, "src", "main", "java", "com", "x")
        os.makedirs(src, exist_ok=True)
        with open(os.path.join(src, "WC_PolicyChangeTest.java"), "w") as fh:
            fh.write('@CenterTest public final class WC_PolicyChangeTest { @CenterTestCase() '
                     '@DataDriven(datasource = "testdata/wc/WC_PolicyChangeDC.xlsx") public void run() { } }')
        from rules.rule_ddt import _workbook_users
        return _workbook_users(root, "src")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_own_identifier_only(self):
        users = self.build("Default")
        self.assertEqual(users.get("testdata/wc/WC_SubmissionDC.xlsx"), ["WC_PolicyChangeTest"])
        self.assertNotIn("testdata/ca/CA_SubmissionDC.xlsx", users)  # CA is another line's target

    def test_an_explicit_identifier_is_followed(self):
        users = self.build("CA.Default")
        self.assertEqual(users.get("testdata/ca/CA_SubmissionDC.xlsx"), ["WC_PolicyChangeTest"])
        self.assertNotIn("testdata/wc/WC_SubmissionDC.xlsx", users)


if __name__ == "__main__":
    unittest.main()
